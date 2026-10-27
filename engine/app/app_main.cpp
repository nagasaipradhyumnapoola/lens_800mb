// lens-app: the Lens Windows app (docs/LENS_V1_SPEC.md §16). A native window hosting the UI (engine/app/ui) in
// WebView2. The UI talks only to the local lens-agent through this host: page messages {"id","request"} are relayed
// to the agent's user-only named pipe and answered with {"id","response"}. The page can load nothing but the bundled
// UI (virtual host https://lens.local/); any other navigation is cancelled. If the agent is not running it is started.
// --self-test: never shows the window; loads the UI, runs window.lensSelfTest() and prints its JSON result, with
// host_ready_ms (process start to result). --self-test-hold <ms> keeps the hidden window alive afterwards (RAM measurement).
// {"id","host":"pick_file"} from the page opens the native file dialog (Import) and answers with the chosen path.
// --background: makes sure the agent runs (starting it with its tray icon) and exits without a window or WebView2; the
// per-user autostart entry uses this, so signing in starts only the agent. --tray-hidden passes the agent's test mode.
// Opening Lens while its window exists brings that window forward instead of starting a second app.
#include <windows.h>
#include <dwmapi.h>
#include <shlobj.h>
#include <shobjidl.h>
#include <wrl.h>
#include <wrl/event.h>
#include "WebView2.h"
#include <nlohmann/json.hpp>
#include <filesystem>
#include <iostream>
#include <mutex>
#include <string>
#include <thread>

using Microsoft::WRL::Callback;using Microsoft::WRL::ComPtr;
using json=nlohmann::json;
namespace fs=std::filesystem;

namespace {
constexpr UINT WM_LENS_REPLY=WM_APP+10;
std::wstring pipe_name,data_dir_arg,root_arg,agent_tray=L"--tray";bool self_test=false,background=false;
HWND window=nullptr;ComPtr<ICoreWebView2Controller> controller;ComPtr<ICoreWebView2> webview;
std::mutex pipe_lock;HANDLE pipe=INVALID_HANDLE_VALUE;std::string pipe_buffer;int exit_code=0;DWORD self_test_hold=0;

std::string utf8(const std::wstring& w) {
    if(w.empty())return {};
    const int n=WideCharToMultiByte(CP_UTF8,0,w.data(),static_cast<int>(w.size()),nullptr,0,nullptr,nullptr);
    std::string s(n,'\0');WideCharToMultiByte(CP_UTF8,0,w.data(),static_cast<int>(w.size()),s.data(),n,nullptr,nullptr);return s;
}
std::wstring wide(const std::string& s) {
    const int n=MultiByteToWideChar(CP_UTF8,0,s.data(),static_cast<int>(s.size()),nullptr,0);
    std::wstring w(n,L'\0');MultiByteToWideChar(CP_UTF8,0,s.data(),static_cast<int>(s.size()),w.data(),n);return w;
}
void out(const json& j){const auto t=j.dump()+"\n";DWORD n=0;WriteFile(GetStdHandle(STD_OUTPUT_HANDLE),t.data(),static_cast<DWORD>(t.size()),&n,nullptr);}  // inherited stdout (GUI app)
fs::path exe_dir(){std::wstring s(32768,L'\0');s.resize(GetModuleFileNameW(nullptr,s.data(),32768));return fs::path(s).parent_path();}

bool connect_agent() {
    const std::wstring path=L"\\\\.\\pipe\\"+pipe_name;
    for(int attempt=0;attempt<300;++attempt) {  // up to 30 s: the agent verifies model hashes at start
        pipe=CreateFileW(path.c_str(),GENERIC_READ|GENERIC_WRITE,0,nullptr,OPEN_EXISTING,0,nullptr);
        if(pipe!=INVALID_HANDLE_VALUE)return true;
        if(attempt==0) {  // not running: start the agent (detached, no console)
            std::wstring cmd=L"\""+(exe_dir()/L"lens-agent.exe").wstring()+L"\" --pipe-name \""+pipe_name+L"\"";
            if(!self_test)cmd+=L" "+agent_tray;  // the resident tray icon belongs to the agent, not to this window
            if(!data_dir_arg.empty())cmd+=L" --data-dir \""+data_dir_arg+L"\"";
            if(!root_arg.empty())cmd+=L" --root \""+root_arg+L"\"";
            STARTUPINFOW si{};si.cb=sizeof si;PROCESS_INFORMATION pi{};
            if(CreateProcessW(nullptr,cmd.data(),nullptr,nullptr,FALSE,DETACHED_PROCESS,nullptr,nullptr,&si,&pi)){CloseHandle(pi.hThread);CloseHandle(pi.hProcess);}
        }
        Sleep(100);
    }
    return false;
}

json ask_agent(const json& request) {
    std::lock_guard g(pipe_lock);
    if(pipe==INVALID_HANDLE_VALUE&&!connect_agent())return {{"ok",false},{"error","agent_unavailable"}};
    const auto line=request.dump()+"\n";DWORD n=0;
    if(!WriteFile(pipe,line.data(),static_cast<DWORD>(line.size()),&n,nullptr)){CloseHandle(pipe);pipe=INVALID_HANDLE_VALUE;return {{"ok",false},{"error","agent_unavailable"}};}
    while(true) {
        const auto pos=pipe_buffer.find('\n');
        if(pos!=std::string::npos){auto out=pipe_buffer.substr(0,pos);pipe_buffer.erase(0,pos+1);return json::parse(out,nullptr,false);}
        char buf[65536];
        if(!ReadFile(pipe,buf,sizeof buf,&n,nullptr)||!n){CloseHandle(pipe);pipe=INVALID_HANDLE_VALUE;pipe_buffer.clear();return {{"ok",false},{"error","agent_unavailable"}};}
        pipe_buffer.append(buf,n);
    }
}

void on_message(const std::wstring& raw) {
    const auto msg=json::parse(utf8(raw),nullptr,false);
    if(!msg.is_object())return;
    if(msg.contains("selftest")) {
        auto result=msg["selftest"];FILETIME created,exited,kernel,user,now;GetSystemTimeAsFileTime(&now);
        if(GetProcessTimes(GetCurrentProcess(),&created,&exited,&kernel,&user)) {
            const auto t=[](const FILETIME& f){return (static_cast<unsigned long long>(f.dwHighDateTime)<<32)|f.dwLowDateTime;};
            result["host_ready_ms"]=(t(now)-t(created))/10000;
        }
        KillTimer(window,1);out(result);exit_code=result.value("ok",false)?0:1;
        if(self_test_hold)SetTimer(window,2,self_test_hold,[](HWND w,UINT,UINT_PTR,DWORD){DestroyWindow(w);});
        else PostMessageW(window,WM_CLOSE,0,0);
        return;
    }
    if(msg.value("host",std::string())=="pick_file"&&msg.contains("id")) {  // Import: the user chooses a file; only its path goes to the page
        json response={{"ok",false},{"error","cancelled"}};
        ComPtr<IFileOpenDialog> dialog;
        if(self_test)response["error"]="unavailable_in_self_test";
        else if(SUCCEEDED(CoCreateInstance(CLSID_FileOpenDialog,nullptr,CLSCTX_INPROC_SERVER,IID_PPV_ARGS(&dialog)))) {
            const COMDLG_FILTERSPEC types[]={{L"Chat exports and notes (*.txt;*.jsonl)",L"*.txt;*.jsonl"},{L"All files",L"*.*"}};
            dialog->SetFileTypes(2,types);dialog->SetTitle(L"Choose a file to import into Lens");
            DWORD opts=0;dialog->GetOptions(&opts);dialog->SetOptions(opts|FOS_FORCEFILESYSTEM|FOS_FILEMUSTEXIST);
            ComPtr<IShellItem> item;PWSTR path=nullptr;
            if(SUCCEEDED(dialog->Show(window))&&SUCCEEDED(dialog->GetResult(&item))&&SUCCEEDED(item->GetDisplayName(SIGDN_FILESYSPATH,&path))) {
                response={{"ok",true},{"path",utf8(path)},{"name",utf8(fs::path(path).filename().wstring())}};CoTaskMemFree(path);
            }
        }
        if(webview)webview->PostWebMessageAsJson(wide(json{{"id",msg["id"]},{"response",response}}.dump()).c_str());
        return;
    }
    if(!msg.contains("id")||!msg.contains("request")||!msg["request"].is_object())return;
    std::thread([msg]{  // pipe I/O off the UI thread; the reply is posted back to it
        const json reply={{"id",msg["id"]},{"response",ask_agent(msg["request"])}};
        auto* text=new std::wstring(wide(reply.dump()));
        if(!PostMessageW(window,WM_LENS_REPLY,0,reinterpret_cast<LPARAM>(text)))delete text;
    }).detach();
}

void create_webview() {
    wchar_t* local=nullptr;fs::path user_data;
    if(SUCCEEDED(SHGetKnownFolderPath(FOLDERID_LocalAppData,0,nullptr,&local))){user_data=fs::path(local)/L"Lens"/L"WebView2";CoTaskMemFree(local);}
    if(self_test){wchar_t tmp[MAX_PATH];GetTempPathW(MAX_PATH,tmp);user_data=fs::path(tmp)/(L"lens-app-selftest-"+std::to_wstring(GetCurrentProcessId()));}
    CreateCoreWebView2EnvironmentWithOptions(nullptr,user_data.c_str(),nullptr,Callback<ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler>(
        [](HRESULT hr,ICoreWebView2Environment* env)->HRESULT {
            if(FAILED(hr)||!env){out({{"ok",false},{"error","webview2_unavailable"}});exit_code=2;PostMessageW(window,WM_CLOSE,0,0);return S_OK;}
            return env->CreateCoreWebView2Controller(window,Callback<ICoreWebView2CreateCoreWebView2ControllerCompletedHandler>(
                [](HRESULT hr2,ICoreWebView2Controller* c)->HRESULT {
                    if(FAILED(hr2)||!c){exit_code=2;PostMessageW(window,WM_CLOSE,0,0);return S_OK;}
                    controller=c;controller->get_CoreWebView2(&webview);
                    COREWEBVIEW2_COLOR dark{255,17,18,20};ComPtr<ICoreWebView2Controller2> c2;if(SUCCEEDED(controller.As(&c2)))c2->put_DefaultBackgroundColor(dark);
                    ComPtr<ICoreWebView2Settings> settings;webview->get_Settings(&settings);
                    settings->put_AreDefaultContextMenusEnabled(FALSE);settings->put_IsStatusBarEnabled(FALSE);settings->put_AreDevToolsEnabled(FALSE);
                    settings->put_IsZoomControlEnabled(FALSE);
                    ComPtr<ICoreWebView2_3> wv3;
                    if(SUCCEEDED(webview.As(&wv3)))wv3->SetVirtualHostNameToFolderMapping(L"lens.local",(exe_dir()/L"ui").c_str(),COREWEBVIEW2_HOST_RESOURCE_ACCESS_KIND_DENY_CORS);
                    EventRegistrationToken t{};
                    webview->add_NavigationStarting(Callback<ICoreWebView2NavigationStartingEventHandler>([](ICoreWebView2*,ICoreWebView2NavigationStartingEventArgs* a)->HRESULT{
                        LPWSTR uri=nullptr;a->get_Uri(&uri);const std::wstring u=uri?uri:L"";CoTaskMemFree(uri);
                        if(u.rfind(L"https://lens.local/",0)!=0)a->put_Cancel(TRUE);  // the UI never leaves its bundle
                        return S_OK;}).Get(),&t);
                    webview->add_NewWindowRequested(Callback<ICoreWebView2NewWindowRequestedEventHandler>([](ICoreWebView2*,ICoreWebView2NewWindowRequestedEventArgs* a)->HRESULT{
                        a->put_Handled(TRUE);return S_OK;}).Get(),&t);
                    webview->add_WebMessageReceived(Callback<ICoreWebView2WebMessageReceivedEventHandler>([](ICoreWebView2*,ICoreWebView2WebMessageReceivedEventArgs* a)->HRESULT{
                        LPWSTR s=nullptr;if(SUCCEEDED(a->TryGetWebMessageAsString(&s))&&s){on_message(s);CoTaskMemFree(s);}return S_OK;}).Get(),&t);
                    if(self_test)webview->add_NavigationCompleted(Callback<ICoreWebView2NavigationCompletedEventHandler>([](ICoreWebView2* w,ICoreWebView2NavigationCompletedEventArgs*)->HRESULT{
                        w->ExecuteScript(L"window.lensSelfTest && window.lensSelfTest()",nullptr);return S_OK;}).Get(),&t);
                    RECT r;GetClientRect(window,&r);controller->put_Bounds(r);
                    webview->Navigate(L"https://lens.local/index.html");
                    return S_OK;}).Get());
        }).Get());
}

LRESULT CALLBACK proc(HWND w,UINT m,WPARAM wp,LPARAM lp) {
    switch(m) {
    case WM_SIZE:if(controller){RECT r;GetClientRect(w,&r);controller->put_Bounds(r);}return 0;
    case WM_LENS_REPLY:{auto* text=reinterpret_cast<std::wstring*>(lp);if(webview)webview->PostWebMessageAsJson(text->c_str());delete text;return 0;}
    case WM_DESTROY:PostQuitMessage(0);return 0;
    }
    return DefWindowProcW(w,m,wp,lp);
}
}

int WINAPI wWinMain(HINSTANCE inst,HINSTANCE,LPWSTR,int show) {
    int argc=0;LPWSTR* argv=CommandLineToArgvW(GetCommandLineW(),&argc);
    for(int i=1;i<argc;++i) {
        const std::wstring a=argv[i];auto next=[&]{return i+1<argc?std::wstring(argv[++i]):std::wstring();};
        if(a==L"--self-test")self_test=true;else if(a==L"--background")background=true;
        else if(a==L"--self-test-hold")self_test_hold=static_cast<DWORD>(std::wcstoul(next().c_str(),nullptr,10));
        else if(a==L"--tray-hidden")agent_tray=L"--tray-hidden";else if(a==L"--pipe-name")pipe_name=next();
        else if(a==L"--data-dir")data_dir_arg=next();else if(a==L"--root")root_arg=next();
    }
    LocalFree(argv);
    if(pipe_name.empty()){wchar_t user[256];DWORD n=256;GetUserNameW(user,&n);pipe_name=L"lens-agent-"+std::wstring(user);}
    if(background){const bool up=connect_agent();if(pipe!=INVALID_HANDLE_VALUE)CloseHandle(pipe);return up?0:1;}
    if(!self_test)if(HWND open=FindWindowW(L"LensApp",nullptr);open&&IsWindowVisible(open)) {  // user asked to open Lens again
        if(IsIconic(open))ShowWindow(open,SW_RESTORE);SetForegroundWindow(open);return 0;
    }
    CoInitializeEx(nullptr,COINIT_APARTMENTTHREADED);
    WNDCLASSW wc{};wc.lpfnWndProc=proc;wc.hInstance=inst;wc.lpszClassName=L"LensApp";wc.hCursor=LoadCursorW(nullptr,IDC_ARROW);
    wc.hbrBackground=CreateSolidBrush(RGB(17,18,20));wc.hIcon=LoadIconW(nullptr,IDI_APPLICATION);RegisterClassW(&wc);
    window=CreateWindowExW(0,wc.lpszClassName,L"Lens",WS_OVERLAPPEDWINDOW,CW_USEDEFAULT,CW_USEDEFAULT,1240,820,nullptr,nullptr,inst,nullptr);
    BOOL dark=TRUE;DwmSetWindowAttribute(window,20/*DWMWA_USE_IMMERSIVE_DARK_MODE*/,&dark,sizeof dark);
    if(!self_test){ShowWindow(window,show);UpdateWindow(window);}  // self-test never shows anything on screen
    else SetTimer(window,1,60000,[](HWND w,UINT,UINT_PTR,DWORD){exit_code=3;out({{"ok",false},{"error","self_test_timeout"}});DestroyWindow(w);});
    create_webview();
    MSG msg;while(GetMessageW(&msg,nullptr,0,0)>0){TranslateMessage(&msg);DispatchMessageW(&msg);}
    controller.Reset();webview.Reset();
    if(pipe!=INVALID_HANDLE_VALUE)CloseHandle(pipe);
    CoUninitialize();
    return exit_code;
}
