// Windows side of screen_capture.hpp: PrintWindow capture and the --serve worker process (CreateProcess, pipes).
#include "screen_capture.hpp"
#include <windows.h>
#include <algorithm>
#include <cstring>
#include <thread>

namespace lens::observe {
namespace {
HANDLE H(std::uintptr_t h){return reinterpret_cast<HANDLE>(h);}
std::uintptr_t U(HANDLE h){return reinterpret_cast<std::uintptr_t>(h);}
}
Frame capture_window(Window id) {
    HWND window=reinterpret_cast<HWND>(id);
    RECT r{};if(!GetWindowRect(window,&r))return {};
    const int w=r.right-r.left,h=r.bottom-r.top;
    if(w<8||h<8||static_cast<long long>(w)*h>16000000)return {};
    HDC screen=GetDC(nullptr);HDC dc=CreateCompatibleDC(screen);
    BITMAPINFO bi{};bi.bmiHeader.biSize=sizeof bi.bmiHeader;bi.bmiHeader.biWidth=w;bi.bmiHeader.biHeight=-h;
    bi.bmiHeader.biPlanes=1;bi.bmiHeader.biBitCount=32;bi.bmiHeader.biCompression=BI_RGB;
    void* bits=nullptr;HBITMAP bmp=CreateDIBSection(screen,&bi,DIB_RGB_COLORS,&bits,nullptr,0);
    Frame f;
    if(bmp&&bits) {
        auto old=SelectObject(dc,bmp);
        auto grab=[&](UINT flags){std::memset(bits,0,static_cast<size_t>(w)*h*4);return PrintWindow(window,dc,flags)!=FALSE;};
        const auto* px=static_cast<const unsigned char*>(bits);
        auto blank=[&]{for(size_t i=4;i<static_cast<size_t>(w)*h*4;i+=4)if(std::memcmp(px,px+i,3))return false;return true;};
        if(!grab(PW_RENDERFULLCONTENT)||blank()){if(!grab(0)||blank()){SelectObject(dc,old);DeleteObject(bmp);DeleteDC(dc);ReleaseDC(nullptr,screen);return {};}}
        f.w=w;f.h=h;f.bgr.resize(static_cast<size_t>(w)*h*3);
        for(size_t i=0,n=static_cast<size_t>(w)*h;i<n;++i)std::memcpy(&f.bgr[i*3],px+i*4,3);
        SelectObject(dc,old);
    }
    if(bmp)DeleteObject(bmp);DeleteDC(dc);ReleaseDC(nullptr,screen);
    return f;
}

bool ServeWorker::start() {
    SECURITY_ATTRIBUTES sa{sizeof sa,nullptr,TRUE};HANDLE in_r{},in_w{},out_r{},out_w{};
    if(!CreatePipe(&in_r,&in_w,&sa,0))return false;
    if(!CreatePipe(&out_r,&out_w,&sa,0)){CloseHandle(in_r);CloseHandle(in_w);return false;}
    SetHandleInformation(in_w,HANDLE_FLAG_INHERIT,0);SetHandleInformation(out_r,HANDLE_FLAG_INHERIT,0);
    HANDLE null=CreateFileW(L"NUL",GENERIC_WRITE,FILE_SHARE_WRITE,&sa,OPEN_EXISTING,0,nullptr);
    STARTUPINFOW si{};si.cb=sizeof si;si.dwFlags=STARTF_USESTDHANDLES;si.hStdInput=in_r;si.hStdOutput=out_w;si.hStdError=null;
    PROCESS_INFORMATION pi{};std::wstring cmd=L"\""+exe_.wstring()+L"\" --serve";
    const BOOL ok=CreateProcessW(exe_.c_str(),cmd.data(),nullptr,nullptr,TRUE,DETACHED_PROCESS,nullptr,nullptr,&si,&pi);
    CloseHandle(in_r);CloseHandle(out_w);if(null!=INVALID_HANDLE_VALUE)CloseHandle(null);
    if(!ok){CloseHandle(in_w);CloseHandle(out_r);return false;}
    CloseHandle(pi.hThread);process_=U(pi.hProcess);in_=U(in_w);out_=U(out_r);buffer_.clear();return true;
}

void ServeWorker::stop() {
    if(!process_)return;
    CloseHandle(H(in_));in_=0;  // EOF: the worker finishes and exits
    if(WaitForSingleObject(H(process_),5000)!=WAIT_OBJECT_0)TerminateProcess(H(process_),1);
    finished_cpu_ms_=cpu_ms();
    CloseHandle(H(out_));CloseHandle(H(process_));out_=process_=0;buffer_.clear();
}

unsigned long long ServeWorker::cpu_ms() const {
    FILETIME c,e,k,u;
    if(!process_||!GetProcessTimes(H(process_),&c,&e,&k,&u))return finished_cpu_ms_;
    auto v=[](const FILETIME& f){return (static_cast<unsigned long long>(f.dwHighDateTime)<<32)|f.dwLowDateTime;};
    return finished_cpu_ms_+(v(k)+v(u))/10000;
}

std::optional<std::string> ServeWorker::request(const std::string& line,unsigned timeout_ms) {
    if(!process_&&!start())return std::nullopt;
    last_used_=GetTickCount64();
    DWORD n=0;std::string payload=line+"\n";
    if(!WriteFile(H(in_),payload.data(),static_cast<DWORD>(payload.size()),&n,nullptr)){stop();return std::nullopt;}
    // Watchdog: a stuck worker is terminated, which also unblocks the read below.
    HANDLE done=CreateEventW(nullptr,TRUE,FALSE,nullptr);HANDLE process=H(process_);bool timed_out=false;
    std::thread watchdog([&]{if(WaitForSingleObject(done,timeout_ms)==WAIT_TIMEOUT){timed_out=true;TerminateProcess(process,1);}});
    std::optional<std::string> result;
    while(true) {
        const auto pos=buffer_.find('\n');
        if(pos!=std::string::npos){result=buffer_.substr(0,pos);buffer_.erase(0,pos+1);break;}
        char buf[65536];
        if(!ReadFile(H(out_),buf,sizeof buf,&n,nullptr)||!n)break;
        buffer_.append(buf,n);
    }
    SetEvent(done);watchdog.join();CloseHandle(done);
    if(!result||timed_out){stop();return std::nullopt;}
    last_used_=GetTickCount64();return result;
}
}
