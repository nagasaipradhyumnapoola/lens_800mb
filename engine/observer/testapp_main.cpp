// lens-observer-testapp: a synthetic window for observer tests (never a user window).
// Shows a title, a static label, a multi-line edit box and a password box. stdin commands (UTF-8 lines):
//   set <text>   replace the edit box text (or the painted text)      title <text>   replace the window title
// --paint <text>: draw the text with GDI only, no accessible controls (exercises the observer's OCR fallback).
//   protect      SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)      quit
// Prints "ready" on stdout once the window is shown. Tests always pass --invisible.
#include <windows.h>
#include <iostream>
#include <string>
#include <thread>

namespace {
HWND window=nullptr,edit=nullptr;
std::wstring wide(const std::string& s) {
    const int n=MultiByteToWideChar(CP_UTF8,0,s.data(),static_cast<int>(s.size()),nullptr,0);
    std::wstring w(n,L'\0');MultiByteToWideChar(CP_UTF8,0,s.data(),static_cast<int>(s.size()),w.data(),n);return w;
}
std::wstring painted;  // --paint: text drawn with GDI only (no accessible controls), to exercise the OCR fallback
void paint(HDC dc,HWND w) {
    RECT r;GetClientRect(w,&r);FillRect(dc,&r,reinterpret_cast<HBRUSH>(GetStockObject(WHITE_BRUSH)));
    HFONT font=CreateFontW(-28,0,0,0,FW_NORMAL,0,0,0,DEFAULT_CHARSET,0,0,CLEARTYPE_QUALITY,0,L"Segoe UI");
    auto old=SelectObject(dc,font);SetBkMode(dc,TRANSPARENT);SetTextColor(dc,RGB(20,20,20));
    RECT t{30,40,r.right-30,r.bottom-30};DrawTextW(dc,painted.c_str(),-1,&t,DT_LEFT|DT_TOP|DT_WORDBREAK);
    SelectObject(dc,old);DeleteObject(font);
}
LRESULT CALLBACK proc(HWND w,UINT m,WPARAM wp,LPARAM lp) {
    if(m==WM_DESTROY){PostQuitMessage(0);return 0;}
    if(!painted.empty()&&m==WM_PAINT){PAINTSTRUCT ps;HDC dc=BeginPaint(w,&ps);paint(dc,w);EndPaint(w,&ps);return 0;}
    if(!painted.empty()&&m==WM_PRINTCLIENT){paint(reinterpret_cast<HDC>(wp),w);return 0;}
    if(!painted.empty()&&m==WM_APP+2){InvalidateRect(w,nullptr,TRUE);return 0;}
    if(m==WM_APP+1){SetWindowDisplayAffinity(w,WDA_EXCLUDEFROMCAPTURE);return 0;}
    return DefWindowProcW(w,m,wp,lp);
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
    window=CreateWindowExW(ex,wc.lpszClassName,title.c_str(),WS_OVERLAPPEDWINDOW,80,80,640,360,nullptr,nullptr,wc.hInstance,nullptr);
    if(invisible)SetLayeredWindowAttributes(window,0,0,LWA_ALPHA);
    if(painted.empty()) {
        CreateWindowExW(0,L"STATIC",label.c_str(),WS_CHILD|WS_VISIBLE,10,10,600,24,window,nullptr,wc.hInstance,nullptr);
        edit=CreateWindowExW(WS_EX_CLIENTEDGE,L"EDIT",body.c_str(),WS_CHILD|WS_VISIBLE|ES_MULTILINE|ES_AUTOVSCROLL,10,40,600,180,window,nullptr,wc.hInstance,nullptr);
        CreateWindowExW(WS_EX_CLIENTEDGE,L"EDIT",secret.c_str(),WS_CHILD|WS_VISIBLE|ES_PASSWORD,10,230,300,24,window,nullptr,wc.hInstance,nullptr);
    }
    ShowWindow(window,SW_SHOWNOACTIVATE);UpdateWindow(window);
    std::cout<<"ready"<<std::endl;
    std::thread([] {
        std::string line;
        while(std::getline(std::cin,line)) {
            if(!line.empty()&&line.back()=='\r')line.pop_back();
            if(line.rfind("set ",0)==0) {
                if(edit)SetWindowTextW(edit,wide(line.substr(4)).c_str());
                else{painted=wide(line.substr(4));SendMessageW(window,WM_APP+2,0,0);}
            }
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
