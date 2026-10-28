#include "screen_capture.hpp"
#include <wincrypt.h>
#include <algorithm>
#include <cstring>
#include <thread>

namespace lens::observe {
Frame capture_window(HWND window) {
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

std::optional<Rect> changed_region(const Frame& a,const Frame& b) {
    if(a.w!=b.w||a.h!=b.h||a.bgr.empty())return Rect{0,0,b.w,b.h};
    constexpr int tile=32;int x0=b.w,y0=b.h,x1=-1,y1=-1;
    for(int ty=0;ty<b.h;ty+=tile)for(int tx=0;tx<b.w;tx+=tile) {
        const int tw=std::min(tile,b.w-tx),th=std::min(tile,b.h-ty);bool diff=false;
        for(int y=ty;y<ty+th&&!diff;++y)diff=std::memcmp(&a.bgr[(static_cast<size_t>(y)*a.w+tx)*3],&b.bgr[(static_cast<size_t>(y)*b.w+tx)*3],static_cast<size_t>(tw)*3)!=0;
        if(diff){x0=std::min(x0,tx);y0=std::min(y0,ty);x1=std::max(x1,tx+tw);y1=std::max(y1,ty+th);}
    }
    if(x1<0)return std::nullopt;
    return Rect{x0,y0,x1-x0,y1-y0};
}

std::string bmp_base64(const Frame& f) {
    const int stride=(f.w*3+3)&~3;const DWORD image=static_cast<DWORD>(stride)*f.h;
    BITMAPFILEHEADER fh{};BITMAPINFOHEADER ih{};
    fh.bfType=0x4D42;fh.bfOffBits=sizeof fh+sizeof ih;fh.bfSize=fh.bfOffBits+image;
    ih.biSize=sizeof ih;ih.biWidth=f.w;ih.biHeight=-f.h;ih.biPlanes=1;ih.biBitCount=24;ih.biCompression=BI_RGB;ih.biSizeImage=image;
    std::vector<BYTE> file(fh.bfSize,0);std::memcpy(file.data(),&fh,sizeof fh);std::memcpy(file.data()+sizeof fh,&ih,sizeof ih);
    for(int y=0;y<f.h;++y)std::memcpy(file.data()+fh.bfOffBits+static_cast<size_t>(y)*stride,&f.bgr[static_cast<size_t>(y)*f.w*3],static_cast<size_t>(f.w)*3);
    DWORD n=0;CryptBinaryToStringA(file.data(),static_cast<DWORD>(file.size()),CRYPT_STRING_BASE64|CRYPT_STRING_NOCRLF,nullptr,&n);
    std::string out(n,'\0');CryptBinaryToStringA(file.data(),static_cast<DWORD>(file.size()),CRYPT_STRING_BASE64|CRYPT_STRING_NOCRLF,out.data(),&n);
    out.resize(n);return out;
}

std::optional<std::string> run_worker(const std::wstring& exe,const std::string& input,DWORD timeout_ms) {
    SECURITY_ATTRIBUTES sa{sizeof sa,nullptr,TRUE};HANDLE in_r{},in_w{},out_r{},out_w{};
    if(!CreatePipe(&in_r,&in_w,&sa,0))return std::nullopt;
    if(!CreatePipe(&out_r,&out_w,&sa,0)){CloseHandle(in_r);CloseHandle(in_w);return std::nullopt;}
    SetHandleInformation(in_w,HANDLE_FLAG_INHERIT,0);SetHandleInformation(out_r,HANDLE_FLAG_INHERIT,0);
    HANDLE null=CreateFileW(L"NUL",GENERIC_WRITE,FILE_SHARE_WRITE,&sa,OPEN_EXISTING,0,nullptr);
    STARTUPINFOW si{};si.cb=sizeof si;si.dwFlags=STARTF_USESTDHANDLES;si.hStdInput=in_r;si.hStdOutput=out_w;si.hStdError=null;
    PROCESS_INFORMATION pi{};std::wstring cmd=L"\""+exe+L"\"";
    const BOOL ok=CreateProcessW(exe.c_str(),cmd.data(),nullptr,nullptr,TRUE,DETACHED_PROCESS,nullptr,nullptr,&si,&pi);
    CloseHandle(in_r);CloseHandle(out_w);if(null!=INVALID_HANDLE_VALUE)CloseHandle(null);
    if(!ok){CloseHandle(in_w);CloseHandle(out_r);return std::nullopt;}
    std::thread writer([&]{DWORD n=0;WriteFile(in_w,input.data(),static_cast<DWORD>(input.size()),&n,nullptr);WriteFile(in_w,"\n",1,&n,nullptr);CloseHandle(in_w);});
    std::string out;std::thread reader([&]{char buf[65536];DWORD n=0;while(ReadFile(out_r,buf,sizeof buf,&n,nullptr)&&n)out.append(buf,n);});
    const bool finished=WaitForSingleObject(pi.hProcess,timeout_ms)==WAIT_OBJECT_0;
    if(!finished)TerminateProcess(pi.hProcess,1);
    writer.join();reader.join();CloseHandle(out_r);
    DWORD code=1;GetExitCodeProcess(pi.hProcess,&code);CloseHandle(pi.hThread);CloseHandle(pi.hProcess);
    if(!finished||code!=0)return std::nullopt;
    return out;
}

bool ServeWorker::start() {
    SECURITY_ATTRIBUTES sa{sizeof sa,nullptr,TRUE};HANDLE in_r{},out_w{};
    if(!CreatePipe(&in_r,&in_,&sa,0))return false;
    if(!CreatePipe(&out_,&out_w,&sa,0)){CloseHandle(in_r);CloseHandle(in_);in_=nullptr;return false;}
    SetHandleInformation(in_,HANDLE_FLAG_INHERIT,0);SetHandleInformation(out_,HANDLE_FLAG_INHERIT,0);
    HANDLE null=CreateFileW(L"NUL",GENERIC_WRITE,FILE_SHARE_WRITE,&sa,OPEN_EXISTING,0,nullptr);
    STARTUPINFOW si{};si.cb=sizeof si;si.dwFlags=STARTF_USESTDHANDLES;si.hStdInput=in_r;si.hStdOutput=out_w;si.hStdError=null;
    PROCESS_INFORMATION pi{};std::wstring cmd=L"\""+exe_+L"\" --serve";
    const BOOL ok=CreateProcessW(exe_.c_str(),cmd.data(),nullptr,nullptr,TRUE,DETACHED_PROCESS,nullptr,nullptr,&si,&pi);
    CloseHandle(in_r);CloseHandle(out_w);if(null!=INVALID_HANDLE_VALUE)CloseHandle(null);
    if(!ok){CloseHandle(in_);CloseHandle(out_);in_=out_=nullptr;return false;}
    CloseHandle(pi.hThread);process_=pi.hProcess;buffer_.clear();return true;
}

void ServeWorker::stop() {
    if(!process_)return;
    CloseHandle(in_);in_=nullptr;  // EOF: the worker finishes and exits
    if(WaitForSingleObject(process_,5000)!=WAIT_OBJECT_0)TerminateProcess(process_,1);
    finished_cpu_ms_=cpu_ms();
    CloseHandle(out_);CloseHandle(process_);out_=process_=nullptr;buffer_.clear();
}

unsigned long long ServeWorker::cpu_ms() const {
    FILETIME c,e,k,u;
    if(!process_||!GetProcessTimes(process_,&c,&e,&k,&u))return finished_cpu_ms_;
    auto v=[](const FILETIME& f){return (static_cast<unsigned long long>(f.dwHighDateTime)<<32)|f.dwLowDateTime;};
    return finished_cpu_ms_+(v(k)+v(u))/10000;
}

std::optional<std::string> ServeWorker::request(const std::string& line,DWORD timeout_ms) {
    if(!process_&&!start())return std::nullopt;
    last_used_=GetTickCount64();
    DWORD n=0;std::string payload=line+"\n";
    if(!WriteFile(in_,payload.data(),static_cast<DWORD>(payload.size()),&n,nullptr)){stop();return std::nullopt;}
    // Watchdog: a stuck worker is terminated, which also unblocks the read below.
    HANDLE done=CreateEventW(nullptr,TRUE,FALSE,nullptr);HANDLE process=process_;bool timed_out=false;
    std::thread watchdog([&]{if(WaitForSingleObject(done,timeout_ms)==WAIT_TIMEOUT){timed_out=true;TerminateProcess(process,1);}});
    std::optional<std::string> result;
    while(true) {
        const auto pos=buffer_.find('\n');
        if(pos!=std::string::npos){result=buffer_.substr(0,pos);buffer_.erase(0,pos+1);break;}
        char buf[65536];
        if(!ReadFile(out_,buf,sizeof buf,&n,nullptr)||!n)break;
        buffer_.append(buf,n);
    }
    SetEvent(done);watchdog.join();CloseHandle(done);
    if(!result||timed_out){stop();return std::nullopt;}
    last_used_=GetTickCount64();return result;
}
}
