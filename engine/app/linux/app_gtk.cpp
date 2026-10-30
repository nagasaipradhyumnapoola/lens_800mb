// lens-app for Linux (docs/LENS_V1_SPEC.md §16, §18): a GTK 4 window hosting the same UI as Windows (engine/app/ui) in
// WebKitGTK 6. The page talks only to the local lens-agent through this host: messages {"id","request"} posted to the
// "lens" script handler are relayed to the agent's user-only Unix socket (agent/os.hpp) and answered by calling
// window.chrome.webview._deliver({"id","response"}) — a shim gives the page the WebView2 API it already uses. The page
// can load nothing but the bundled UI (lens://app/); any other navigation is refused, and only the microphone may be
// granted (push-to-talk questions). If the agent is not running it is started.
// --self-test: loads the UI, runs window.lensSelfTest(), prints its JSON result and exits (tests use a virtual display).
#include "../agent_client.hpp"
#include <gtk/gtk.h>
#include <webkit/webkit.h>
#include <nlohmann/json.hpp>
#include <chrono>
#include <fstream>
#include <iostream>
#include <mutex>
#include <sstream>
#include <thread>

namespace fs=std::filesystem;
using json=nlohmann::json;
namespace os=lens::agent::os;

namespace {
struct App {
    std::string pipe;bool self_test=false;int exit_code=0;GMainLoop* loop=nullptr;WebKitWebView* view=nullptr;
    std::unique_ptr<lens::app::AgentClient> agent;
};
App app;

const char* SHIM=R"JS(
(() => {
  const listeners = [];
  window.chrome = window.chrome || {};
  window.chrome.webview = {
    addEventListener(type, f) { if (type === 'message') listeners.push(f); },
    postMessage(s) { window.webkit.messageHandlers.lens.postMessage(s); },
    _deliver(data) { for (const f of listeners) f({ data }); }
  };
})();
)JS";

void deliver(json message) {  // main thread: hand a reply to the page
    const auto script="window.chrome.webview._deliver("+message.dump()+");";
    webkit_web_view_evaluate_javascript(app.view,script.c_str(),-1,nullptr,nullptr,nullptr,nullptr,nullptr);
}

void on_message(WebKitUserContentManager*,JSCValue* value,gpointer) {
    char* text=jsc_value_to_string(value);const auto msg=json::parse(text?text:"",nullptr,false);g_free(text);
    if(!msg.is_object())return;
    if(msg.contains("selftest")) {
        std::cout<<msg["selftest"].dump()<<std::endl;app.exit_code=msg["selftest"].value("ok",false)?0:1;
        if(app.self_test)g_main_loop_quit(app.loop);
        return;
    }
    if(!msg.contains("id"))return;
    const auto id=msg["id"];
    if(msg.contains("host")){deliver({{"id",id},{"response",{{"ok",false},{"error","host_request_unsupported"}}}});return;}  // file picker: not yet
    if(!msg.contains("request")||!msg["request"].is_object())return;
    std::thread([id,request=msg["request"]] {
        auto* reply=new json{{"id",id},{"response",app.agent->ask(request)}};
        g_idle_add([](gpointer p)->gboolean{std::unique_ptr<json> r(static_cast<json*>(p));deliver(*r);return G_SOURCE_REMOVE;},reply);
    }).detach();
}

// lens://app/<file>: the bundled UI only, from <executable folder>/ui.
void serve_ui(WebKitURISchemeRequest* request,gpointer) {
    const std::string path=webkit_uri_scheme_request_get_path(request);
    const auto ui=lens::platform::executable_dir()/"ui";const auto file=(ui/fs::path(path).relative_path()).lexically_normal();
    const auto rel=file.lexically_relative(ui);
    std::ifstream f(file,std::ios::binary);
    if(rel.empty()||rel.native().rfind("..",0)==0||!f) {
        GError* e=g_error_new_literal(g_quark_from_static_string("lens"),404,"not found");webkit_uri_scheme_request_finish_error(request,e);g_error_free(e);return;
    }
    std::ostringstream s;s<<f.rdbuf();const auto data=s.str();
    const auto ext=file.extension().string();
    const char* mime=ext==".html"?"text/html":ext==".js"?"text/javascript":ext==".css"?"text/css":ext==".svg"?"image/svg+xml":"application/octet-stream";
    GBytes* bytes=g_bytes_new(data.data(),data.size());GInputStream* stream=g_memory_input_stream_new_from_bytes(bytes);
    webkit_uri_scheme_request_finish(request,stream,static_cast<gint64>(data.size()),mime);
    g_object_unref(stream);g_bytes_unref(bytes);
}

gboolean on_policy(WebKitWebView*,WebKitPolicyDecision* decision,WebKitPolicyDecisionType type,gpointer) {
    if(type==WEBKIT_POLICY_DECISION_TYPE_NAVIGATION_ACTION||type==WEBKIT_POLICY_DECISION_TYPE_NEW_WINDOW_ACTION) {
        auto* action=webkit_navigation_policy_decision_get_navigation_action(WEBKIT_NAVIGATION_POLICY_DECISION(decision));
        const std::string uri=webkit_uri_request_get_uri(webkit_navigation_action_get_request(action));
        if(type==WEBKIT_POLICY_DECISION_TYPE_NEW_WINDOW_ACTION||uri.rfind("lens://app/",0)!=0){webkit_policy_decision_ignore(decision);return TRUE;}
    }
    return FALSE;
}

gboolean on_permission(WebKitWebView*,WebKitPermissionRequest* request,gpointer) {
    if(WEBKIT_IS_USER_MEDIA_PERMISSION_REQUEST(request)&&
       webkit_user_media_permission_is_for_audio_device(WEBKIT_USER_MEDIA_PERMISSION_REQUEST(request))&&
       !webkit_user_media_permission_is_for_video_device(WEBKIT_USER_MEDIA_PERMISSION_REQUEST(request)))webkit_permission_request_allow(request);
    else webkit_permission_request_deny(request);
    return TRUE;
}

void on_load(WebKitWebView* view,WebKitLoadEvent event,gpointer) {
    if(event==WEBKIT_LOAD_FINISHED&&app.self_test)
        webkit_web_view_evaluate_javascript(view,"window.lensSelfTest();",-1,nullptr,nullptr,nullptr,nullptr,nullptr);
}
}

int main(int argc,char** argv) {
    for(int i=1;i<argc;++i) {
        const std::string a=argv[i];
        if(a=="--pipe-name"&&i+1<argc)app.pipe=argv[++i];
        else if(a=="--self-test")app.self_test=true;
        else {std::cerr<<"usage: lens-app [--pipe-name <name>] [--self-test]\n";return 2;}
    }
    if(app.pipe.empty())app.pipe="lens-agent-"+os::user_name();
    app.agent=std::make_unique<lens::app::AgentClient>(app.pipe);
    gtk_init();
    auto* context=webkit_web_context_get_default();
    webkit_web_context_register_uri_scheme(context,"lens",serve_ui,nullptr,nullptr);
    webkit_security_manager_register_uri_scheme_as_secure(webkit_web_context_get_security_manager(context),"lens");
    auto* content=webkit_user_content_manager_new();
    webkit_user_content_manager_add_script(content,webkit_user_script_new(SHIM,WEBKIT_USER_CONTENT_INJECT_TOP_FRAME,
        WEBKIT_USER_SCRIPT_INJECT_AT_DOCUMENT_START,nullptr,nullptr));
    webkit_user_content_manager_register_script_message_handler(content,"lens",nullptr);
    g_signal_connect(content,"script-message-received::lens",G_CALLBACK(on_message),nullptr);
    app.view=WEBKIT_WEB_VIEW(g_object_new(WEBKIT_TYPE_WEB_VIEW,"user-content-manager",content,nullptr));
    auto* settings=webkit_web_view_get_settings(app.view);
    webkit_settings_set_enable_developer_extras(settings,FALSE);webkit_settings_set_enable_media_stream(settings,TRUE);
    g_signal_connect(app.view,"decide-policy",G_CALLBACK(on_policy),nullptr);
    g_signal_connect(app.view,"permission-request",G_CALLBACK(on_permission),nullptr);
    g_signal_connect(app.view,"load-changed",G_CALLBACK(on_load),nullptr);
    app.loop=g_main_loop_new(nullptr,FALSE);
    GtkWidget* window=gtk_window_new();gtk_window_set_title(GTK_WINDOW(window),"Lens");
    gtk_window_set_default_size(GTK_WINDOW(window),1180,780);gtk_window_set_child(GTK_WINDOW(window),GTK_WIDGET(app.view));
    g_signal_connect_swapped(window,"close-request",G_CALLBACK(+[](GMainLoop* l){g_main_loop_quit(l);return FALSE;}),app.loop);
    gtk_window_present(GTK_WINDOW(window));  // tests run it on a virtual display (Xvfb), never the user's screen
    webkit_web_view_load_uri(app.view,"lens://app/index.html");
    if(app.self_test)g_timeout_add_seconds(120,[](gpointer)->gboolean{std::cout<<R"({"ok":false,"error":"self_test_timeout"})"<<std::endl;app.exit_code=1;g_main_loop_quit(app.loop);return G_SOURCE_REMOVE;},nullptr);
    g_main_loop_run(app.loop);
    return app.exit_code;
}
