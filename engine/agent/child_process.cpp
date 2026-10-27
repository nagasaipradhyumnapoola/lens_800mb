#include "child_process.hpp"

namespace lens::agent {
bool Child::start(const std::wstring& exe,const std::vector<std::wstring>& args,std::function<void(const std::string&)> on_line) {
    SECURITY_ATTRIBUTES sa{sizeof sa,nullptr,TRUE};HANDLE in_r{},out_w{};
    if(!CreatePipe(&in_r,&in_,&sa,0))return false;
    if(!CreatePipe(&out_,&out_w,&sa,0)){CloseHandle(in_r);CloseHandle(in_);in_=nullptr;return false;}
    SetHandleInformation(in_,HANDLE_FLAG_INHERIT,0);SetHandleInformation(out_,HANDLE_FLAG_INHERIT,0);
    HANDLE null=CreateFileW(L"NUL",GENERIC_WRITE,FILE_SHARE_WRITE,&sa,OPEN_EXISTING,0,nullptr);
    STARTUPINFOW si{};si.cb=sizeof si;si.dwFlags=STARTF_USESTDHANDLES;si.hStdInput=in_r;si.hStdOutput=out_w;si.hStdError=null;
    std::wstring cmd=L"\""+exe+L"\"";for(const auto& a:args){cmd+=L" \"";cmd+=a;cmd+=L"\"";}
    PROCESS_INFORMATION pi{};
    const BOOL ok=CreateProcessW(exe.c_str(),cmd.data(),nullptr,nullptr,TRUE,DETACHED_PROCESS,nullptr,nullptr,&si,&pi);
    CloseHandle(in_r);CloseHandle(out_w);if(null!=INVALID_HANDLE_VALUE)CloseHandle(null);
    if(!ok){CloseHandle(in_);CloseHandle(out_);in_=out_=nullptr;return false;}
    CloseHandle(pi.hThread);process_=pi.hProcess;pid_=pi.dwProcessId;
    if(on_line)reader_=std::thread([this,on_line]{
        std::string pending;char buf[65536];DWORD n=0;
        while(ReadFile(out_,buf,sizeof buf,&n,nullptr)&&n) {
            pending.append(buf,n);size_t pos;
            while((pos=pending.find('\n'))!=std::string::npos){auto line=pending.substr(0,pos);pending.erase(0,pos+1);if(!line.empty()&&line.back()=='\r')line.pop_back();on_line(line);}
        }
    });
    return true;
}

bool Child::send(const std::string& line) {
    std::lock_guard g(write_);if(!in_)return false;
    const std::string payload=line+"\n";DWORD n=0;
    return WriteFile(in_,payload.data(),static_cast<DWORD>(payload.size()),&n,nullptr)&&n==payload.size();
}

std::optional<std::string> Child::request(const std::string& line) {
    if(!send(line))return std::nullopt;
    while(true) {
        const auto pos=buffer_.find('\n');
        if(pos!=std::string::npos){auto out=buffer_.substr(0,pos);buffer_.erase(0,pos+1);if(!out.empty()&&out.back()=='\r')out.pop_back();return out;}
        char buf[65536];DWORD n=0;
        if(!ReadFile(out_,buf,sizeof buf,&n,nullptr)||!n)return std::nullopt;
        buffer_.append(buf,n);
    }
}

void Child::close_input(){std::lock_guard g(write_);if(in_){CloseHandle(in_);in_=nullptr;}}

void Child::stop(DWORD grace_ms) {
    if(!process_)return;
    close_input();
    if(WaitForSingleObject(process_,grace_ms)!=WAIT_OBJECT_0)TerminateProcess(process_,1);
    if(reader_.joinable())reader_.join();
    if(out_){CloseHandle(out_);out_=nullptr;}
    CloseHandle(process_);process_=nullptr;pid_=0;buffer_.clear();
}
}
