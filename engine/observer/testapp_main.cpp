// lens-observer-testapp: a synthetic window for observer tests (never a user window).
// Shows a title, a static label, a multi-line edit box and a password box. stdin commands (UTF-8 lines; "\n" in the
// text means a line break):
//   set <text>      replace the edit box text (or the painted text)   title <text>   replace the window title
//   append <text>   add a line to the end of the edit box and scroll to it (streaming text)
//   fill <n> <p>    replace the edit box text with n lines "<p> <i>" and scroll to the last one (long scroll-back)
//   offscreen <t>   add a static label positioned outside the window's visible area (off-screen element)
//   panel <n> <p>   add a clipping child panel holding n labels "<p> <i>", scrolled so only the last few are visible
//                   (element-based scroll-back like a chat app: the hidden labels still exist in the UIA tree)
//   protect         SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)  quit
// --paint <text>: draw the text with GDI only, no accessible controls (exercises the observer's OCR fallback).
// Prints "ready" on stdout once the window is shown and "ok" after each command. Tests always pass --invisible.
#include <windows.h>
#include <functional>
#include <iostream>
#include <string>
#include <thread>

namespace {
HWND window=nullptr,edit=nullptr;
std::wstring wide(const std::string& s) {
    const int n=MultiByteToWideChar(CP_UTF8,0,s.data(),static_cast<int>(s.size()),nullptr,0);
    std::wstring w(n,L'\0');MultiByteToWideChar(CP_UTF8,0,s.data(),static_cast<int>(s.size()),w.data(),n);return w;
}
std::wstring lines(std::wstring s) {  // the two characters \n become a Windows line break
    for(size_t p=0;(p=s.find(L"\\n",p))!=std::wstring::npos;p+=2)s.replace(p,2,L"\r\n");
    return s;
}
std::wstring painted;  // --paint: text drawn with GDI only (no accessible controls), to exercise the OCR fallback
void paint(HDC dc,HWND w) {
    RECT r;GetClientRect(w,&r);FillRect(dc,&r,reinterpret_cast<HBRUSH>(GetStockObject(WHITE_BRUSH)));
    HFONT font=CreateFontW(-28,0,0,0,FW_NORMAL,0,0,0,DEFAULT_CHARSET,0,0,CLEARTYPE_QUALITY,0,L"Segoe UI");
    auto old=SelectObject(dc,font);SetBkMode(dc,TRANSPARENT);SetTextColor(dc,RGB(20,20,20));
    RECT t{30,40,r.right-30,r.bottom-30};DrawTextW(dc,painted.c_str(),-1,&t,DT_LEFT|DT_TOP|DT_WORDBREAK);
    SelectObject(dc,old);DeleteObject(font);
}
void scroll_to_end() {
    const auto n=GetWindowTextLengthW(edit);SendMessageW(edit,EM_SETSEL,n,n);SendMessageW(edit,EM_SCROLLCARET,0,0);
}
LRESULT CALLBACK proc(HWND w,UINT m,WPARAM wp,LPARAM lp) {
    if(m==WM_DESTROY){PostQuitMessage(0);return 0;}
    if(!painted.empty()&&m==WM_PAINT){PAINTSTRUCT ps;HDC dc=BeginPaint(w,&ps);paint(dc,w);EndPaint(w,&ps);return 0;}
    if(!painted.empty()&&m==WM_PRINTCLIENT){paint(reinterpret_cast<HDC>(wp),w);return 0;}
    if(!painted.empty()&&m==WM_APP+2){InvalidateRect(w,nullptr,TRUE);return 0;}
    if(m==WM_APP+1){SetWindowDisplayAffinity(w,WDA_EXCLUDEFROMCAPTURE);return 0;}
    if(m==WM_APP+3){(*reinterpret_cast<std::function<void()>*>(lp))();return 0;}  // run a command on the window thread
    return DefWindowProcW(w,m,wp,lp);
}
void on_window_thread(std::function<void()> f){SendMessageW(window,WM_APP+3,0,reinterpret_cast<LPARAM>(&f));}
std::pair<int,std::wstring> count_and_prefix(const std::string& args) {
    const auto space=args.find(' ');
    return {std::stoi(args.substr(0,space)),space==std::string::npos?L"Synthetic line":wide(args.substr(space+1))};
}
}

int wmain(int argc,wchar_t** argv) {
    // --invisible (first argument): fully transparent (alpha 0), click-through, never activated, no taskbar button.
    // The window stays on screen for UI Automation, but tests never show anything to, or take input from, the user.
    bool invisible=false;
    if(argc>1&&std::wstring(argv[1])==L"--invisible"){invisible=true;++argv;--argc;}
    if(argc>2&&std::wstring(argv[1])==L"--paint"){painted=argv[2];argv+=2;argc-=2;}
    const std::wstring title=argc>1?argv[1]:L"Lens observer test window";
    const std::wstring label=argc>2?argv[2]:L"Synthetic label for the Lens observer test";
    const std::wstring body=argc>3?argv[3]:L"Synthetic note: the quarterly review moved to Thursday.";
    const std::wstring secret=argc>4?argv[4]:L"synthetic-password-do-not-capture";
    WNDCLASSW wc{};wc.lpfnWndProc=proc;wc.hInstance=GetModuleHandleW(nullptr);wc.lpszClassName=L"LensObserverTestApp";
    wc.hbrBackground=reinterpret_cast<HBRUSH>(COLOR_WINDOW+1);RegisterClassW(&wc);
    const DWORD ex=invisible?WS_EX_LAYERED|WS_EX_TRANSPARENT|WS_EX_TOOLWINDOW|WS_EX_NOACTIVATE:0;
    window=CreateWindowExW(ex,wc.lpszClassName,title.c_str(),WS_OVERLAPPEDWINDOW|WS_CLIPCHILDREN,80,80,640,360,nullptr,nullptr,wc.hInstance,nullptr);
    if(invisible)SetLayeredWindowAttributes(window,0,0,LWA_ALPHA);
    if(painted.empty()) {
        CreateWindowExW(0,L"STATIC",label.c_str(),WS_CHILD|WS_VISIBLE,10,10,600,24,window,nullptr,wc.hInstance,nullptr);
        edit=CreateWindowExW(WS_EX_CLIENTEDGE,L"EDIT",lines(body).c_str(),WS_CHILD|WS_VISIBLE|WS_VSCROLL|ES_MULTILINE|ES_AUTOVSCROLL,
                             10,40,600,180,window,nullptr,wc.hInstance,nullptr);
        CreateWindowExW(WS_EX_CLIENTEDGE,L"EDIT",secret.c_str(),WS_CHILD|WS_VISIBLE|ES_PASSWORD,10,230,300,24,window,nullptr,wc.hInstance,nullptr);
    }
    ShowWindow(window,SW_SHOWNOACTIVATE);UpdateWindow(window);
    std::cout<<"ready"<<std::endl;
    std::thread([&wc] {
        std::string line;
        while(std::getline(std::cin,line)) {
            if(!line.empty()&&line.back()=='\r')line.pop_back();
            if(line.rfind("set ",0)==0) {
                if(edit)on_window_thread([&]{SetWindowTextW(edit,lines(wide(line.substr(4))).c_str());});
                else{painted=wide(line.substr(4));SendMessageW(window,WM_APP+2,0,0);}
            }
            else if(line.rfind("append ",0)==0&&edit)
                on_window_thread([&]{scroll_to_end();const auto add=L"\r\n"+lines(wide(line.substr(7)));
                                     SendMessageW(edit,EM_REPLACESEL,FALSE,reinterpret_cast<LPARAM>(add.c_str()));scroll_to_end();});
            else if(line.rfind("fill ",0)==0&&edit)
                on_window_thread([&]{const auto [n,prefix]=count_and_prefix(line.substr(5));std::wstring all;
                                     for(int i=1;i<=n;++i)all+=(i>1?L"\r\n":L"")+prefix+L" "+std::to_wstring(i);
                                     SetWindowTextW(edit,all.c_str());scroll_to_end();});
            else if(line.rfind("offscreen ",0)==0)
                on_window_thread([&]{CreateWindowExW(0,L"STATIC",wide(line.substr(10)).c_str(),WS_CHILD|WS_VISIBLE,10,1400,600,24,window,nullptr,wc.hInstance,nullptr);});
            else if(line.rfind("panel ",0)==0)
                on_window_thread([&]{
                    const auto [n,prefix]=count_and_prefix(line.substr(6));
                    // A 60 px clipping panel; label i sits at 20*(i-n)+40, so only the last three are inside it.
                    HWND panel=CreateWindowExW(0,L"STATIC",L"",WS_CHILD|WS_VISIBLE|WS_CLIPCHILDREN,320,230,290,60,window,nullptr,wc.hInstance,nullptr);
                    for(int i=1;i<=n;++i)
                        CreateWindowExW(0,L"STATIC",(prefix+L" "+std::to_wstring(i)).c_str(),WS_CHILD|WS_VISIBLE,0,20*(i-n)+40,280,20,panel,nullptr,wc.hInstance,nullptr);
                });
            else if(line.rfind("title ",0)==0)SetWindowTextW(window,wide(line.substr(6)).c_str());
            else if(line=="protect")SendMessageW(window,WM_APP+1,0,0);
            else if(line=="quit")break;
            std::cout<<"ok"<<std::endl;
        }
        PostMessageW(window,WM_CLOSE,0,0);
    }).detach();
    MSG msg;while(GetMessageW(&msg,nullptr,0,0)>0){TranslateMessage(&msg);DispatchMessageW(&msg);}
    return 0;
}
