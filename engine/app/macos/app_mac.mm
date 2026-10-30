// lens-app for macOS (docs/LENS_V1_SPEC.md §16, §18): a Cocoa window hosting the same UI as Windows and Linux
// (engine/app/ui) in WKWebView. The page talks only to the local lens-agent through this host: messages {"id","request"}
// posted to the "lens" script handler are relayed to the agent's user-only Unix socket and answered by calling
// window.chrome.webview._deliver({"id","response"}) — a shim gives the page the WebView2 API it already uses. The page
// can load nothing but the bundled UI (lens://app/); any other navigation is refused, and only the microphone may be
// granted (push-to-talk questions). If the agent is not running it is started.
// --self-test: loads the UI, runs window.lensSelfTest(), prints its JSON result and exits.
#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>
#include "../agent_client.hpp"
#include <fstream>
#include <iostream>
#include <sstream>

namespace fs=std::filesystem;
using json=nlohmann::json;

namespace {
std::unique_ptr<lens::app::AgentClient> agent;bool self_test=false;int exit_code=0;
NSString* SHIM=@"(() => { const listeners = []; window.chrome = window.chrome || {}; window.chrome.webview = {"
                 " addEventListener(type, f) { if (type === 'message') listeners.push(f); },"
                 " postMessage(s) { window.webkit.messageHandlers.lens.postMessage(s); },"
                 " _deliver(data) { for (const f of listeners) f({ data }); } }; })();";
NSString* ns(const std::string& s){return [[NSString alloc] initWithBytes:s.data() length:s.size() encoding:NSUTF8StringEncoding];}
}

// lens://app/<file>: the bundled UI only, from <executable folder>/ui.
@interface LensScheme:NSObject<WKURLSchemeHandler>
@end
@implementation LensScheme
- (void)webView:(WKWebView*)view startURLSchemeTask:(id<WKURLSchemeTask>)task {
    const std::string path=task.request.URL.path.UTF8String?task.request.URL.path.UTF8String:"";
    const auto ui=lens::platform::executable_dir()/"ui";const auto file=(ui/fs::path(path).relative_path()).lexically_normal();
    const auto rel=file.lexically_relative(ui);std::ifstream f(file,std::ios::binary);
    if(rel.empty()||rel.native().rfind("..",0)==0||!f){[task didFailWithError:[NSError errorWithDomain:@"lens" code:404 userInfo:nil]];return;}
    std::ostringstream s;s<<f.rdbuf();const auto data=s.str();const auto ext=file.extension().string();
    NSString* mime=ext==".html"?@"text/html":ext==".js"?@"text/javascript":ext==".css"?@"text/css":ext==".svg"?@"image/svg+xml":@"application/octet-stream";
    [task didReceiveResponse:[[NSURLResponse alloc] initWithURL:task.request.URL MIMEType:mime expectedContentLength:static_cast<NSInteger>(data.size()) textEncodingName:@"utf-8"]];
    [task didReceiveData:[NSData dataWithBytes:data.data() length:data.size()]];[task didFinish];
}
- (void)webView:(WKWebView*)view stopURLSchemeTask:(id<WKURLSchemeTask>)task {}
@end

@interface LensHost:NSObject<NSApplicationDelegate,WKScriptMessageHandler,WKNavigationDelegate,WKUIDelegate,NSWindowDelegate>
@property(strong) NSWindow* window;@property(strong) WKWebView* view;
@end
@implementation LensHost
- (void)deliver:(const json&)message {  // main thread: hand a reply to the page
    [self.view evaluateJavaScript:ns("window.chrome.webview._deliver("+message.dump()+");") completionHandler:nil];
}
- (void)userContentController:(WKUserContentController*)controller didReceiveScriptMessage:(WKScriptMessage*)message {
    if(![message.body isKindOfClass:[NSString class]])return;
    const auto msg=json::parse(std::string([(NSString*)message.body UTF8String]),nullptr,false);if(!msg.is_object())return;
    if(msg.contains("selftest")){std::cout<<msg["selftest"].dump()<<std::endl;exit_code=msg["selftest"].value("ok",false)?0:1;if(self_test)[NSApp terminate:nil];return;}
    if(!msg.contains("id"))return;
    const auto id=msg["id"];
    if(msg.contains("host")){[self deliver:json{{"id",id},{"response",{{"ok",false},{"error","host_request_unsupported"}}}}];return;}  // file picker: not yet
    if(!msg.contains("request")||!msg["request"].is_object())return;
    const json request=msg["request"];
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{
        const json reply={{"id",id},{"response",agent->ask(request)}};
        dispatch_async(dispatch_get_main_queue(),^{[self deliver:reply];});
    });
}
- (void)webView:(WKWebView*)view decidePolicyForNavigationAction:(WKNavigationAction*)action decisionHandler:(void(^)(WKNavigationActionPolicy))decide {
    const bool ours=[action.request.URL.absoluteString hasPrefix:@"lens://app/"]&&action.targetFrame!=nil;
    decide(ours?WKNavigationActionPolicyAllow:WKNavigationActionPolicyCancel);
}
- (void)webView:(WKWebView*)view requestMediaCapturePermissionForOrigin:(WKSecurityOrigin*)origin initiatedByFrame:(WKFrameInfo*)frame
           type:(WKMediaCaptureType)type decisionHandler:(void(^)(WKPermissionDecision))decide API_AVAILABLE(macos(12.0)) {
    decide([origin.protocol isEqualToString:@"lens"]&&type==WKMediaCaptureTypeMicrophone?WKPermissionDecisionGrant:WKPermissionDecisionDeny);
}
- (void)webView:(WKWebView*)view didFinishNavigation:(WKNavigation*)navigation {
    if(self_test)[view evaluateJavaScript:@"window.lensSelfTest();" completionHandler:nil];
}
- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication*)app {return YES;}
- (void)applicationDidFinishLaunching:(NSNotification*)note {
    WKWebViewConfiguration* config=[WKWebViewConfiguration new];
    [config setURLSchemeHandler:[LensScheme new] forURLScheme:@"lens"];
    [config.userContentController addUserScript:[[WKUserScript alloc] initWithSource:SHIM injectionTime:WKUserScriptInjectionTimeAtDocumentStart forMainFrameOnly:YES]];
    [config.userContentController addScriptMessageHandler:self name:@"lens"];
    self.window=[[NSWindow alloc] initWithContentRect:NSMakeRect(0,0,1180,780)
        styleMask:NSWindowStyleMaskTitled|NSWindowStyleMaskClosable|NSWindowStyleMaskResizable|NSWindowStyleMaskMiniaturizable backing:NSBackingStoreBuffered defer:NO];
    self.window.title=@"Lens";self.window.delegate=self;
    self.view=[[WKWebView alloc] initWithFrame:self.window.contentView.bounds configuration:config];
    self.view.navigationDelegate=self;self.view.UIDelegate=self;self.view.autoresizingMask=NSViewWidthSizable|NSViewHeightSizable;
    [self.window.contentView addSubview:self.view];[self.window center];
    if(!self_test){[self.window makeKeyAndOrderFront:nil];[NSApp activateIgnoringOtherApps:YES];}
    [self.view loadRequest:[NSURLRequest requestWithURL:[NSURL URLWithString:@"lens://app/index.html"]]];
    if(self_test)dispatch_after(dispatch_time(DISPATCH_TIME_NOW,120*NSEC_PER_SEC),dispatch_get_main_queue(),^{
        std::cout<<R"({"ok":false,"error":"self_test_timeout"})"<<std::endl;exit_code=1;[NSApp terminate:nil];});
}
- (void)applicationWillTerminate:(NSNotification*)note {std::cout.flush();_exit(exit_code);}
@end

int main(int argc,const char** argv) {
    std::string pipe;
    for(int i=1;i<argc;++i) {
        const std::string a=argv[i];
        if(a=="--pipe-name"&&i+1<argc)pipe=argv[++i];
        else if(a=="--self-test")self_test=true;
        else {std::cerr<<"usage: lens-app [--pipe-name <name>] [--self-test]\n";return 2;}
    }
    if(pipe.empty())pipe="lens-agent-"+lens::agent::os::user_name();
    agent=std::make_unique<lens::app::AgentClient>(pipe);
    @autoreleasepool {
        NSApplication* app=[NSApplication sharedApplication];
        [app setActivationPolicy:self_test?NSApplicationActivationPolicyProhibited:NSApplicationActivationPolicyRegular];
        LensHost* host=[LensHost new];app.delegate=host;[app run];
    }
    return exit_code;
}
