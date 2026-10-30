#include "child_process.hpp"
#ifndef _WIN32
#include <cerrno>
#include <chrono>
#include <fcntl.h>
#include <signal.h>
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>
extern char** environ;
#endif

namespace lens::agent {
#ifdef _WIN32
bool Child::start(const native& exe,const std::vector<native>& args,std::function<void(const std::string&)> on_line) {
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
#else
bool Child::start(const native& exe,const std::vector<native>& args,std::function<void(const std::string&)> on_line) {
    int in[2],out[2];
    if(::pipe(in)!=0)return false;
    if(::pipe(out)!=0){::close(in[0]);::close(in[1]);return false;}
    for(int fd:{in[1],out[0]})::fcntl(fd,F_SETFD,FD_CLOEXEC);  // the parent's ends never leak into other children
    posix_spawn_file_actions_t fa;posix_spawn_file_actions_init(&fa);
    posix_spawn_file_actions_adddup2(&fa,in[0],0);posix_spawn_file_actions_adddup2(&fa,out[1],1);
    posix_spawn_file_actions_addopen(&fa,2,"/dev/null",O_WRONLY,0);
    for(int fd:{in[0],out[1]})posix_spawn_file_actions_addclose(&fa,fd);
    std::vector<char*> argv{const_cast<char*>(exe.c_str())};for(const auto& a:args)argv.push_back(const_cast<char*>(a.c_str()));argv.push_back(nullptr);
    pid_t pid=0;const int rc=posix_spawn(&pid,exe.c_str(),&fa,nullptr,argv.data(),environ);posix_spawn_file_actions_destroy(&fa);
    ::close(in[0]);::close(out[1]);
    if(rc!=0){::close(in[1]);::close(out[0]);return false;}
    signal(SIGPIPE,SIG_IGN);  // writing to a child that exited must fail, not end the agent
    process_=pid;pid_=static_cast<unsigned long>(pid);in_=in[1];out_=out[0];exited_=false;
#endif
    if(on_line)reader_=std::thread([this,on_line]{
        std::string pending;
        while(read_some(pending)) {
            size_t pos;
            while((pos=pending.find('\n'))!=std::string::npos){auto line=pending.substr(0,pos);pending.erase(0,pos+1);if(!line.empty()&&line.back()=='\r')line.pop_back();on_line(line);}
        }
    });
    return true;
}

std::optional<std::string> Child::request(const std::string& line) {
    if(!send(line))return std::nullopt;
    while(true) {
        const auto pos=buffer_.find('\n');
        if(pos!=std::string::npos){auto out=buffer_.substr(0,pos);buffer_.erase(0,pos+1);if(!out.empty()&&out.back()=='\r')out.pop_back();return out;}
        if(!read_some(buffer_))return std::nullopt;
    }
}

#ifdef _WIN32
bool Child::running() const {return process_!=nullptr&&WaitForSingleObject(process_,0)==WAIT_TIMEOUT;}

bool Child::read_some(std::string& into) {
    char buf[65536];DWORD n=0;
    if(!ReadFile(out_,buf,sizeof buf,&n,nullptr)||!n)return false;
    into.append(buf,n);return true;
}

bool Child::send(const std::string& line) {
    std::lock_guard g(write_);if(!in_)return false;
    const std::string payload=line+"\n";DWORD n=0;
    return WriteFile(in_,payload.data(),static_cast<DWORD>(payload.size()),&n,nullptr)&&n==payload.size();
}

void Child::close_input(){std::lock_guard g(write_);if(in_){CloseHandle(in_);in_=nullptr;}}

void Child::stop(unsigned grace_ms) {
    if(!process_)return;
    close_input();
    if(WaitForSingleObject(process_,grace_ms)!=WAIT_OBJECT_0)TerminateProcess(process_,1);
    if(reader_.joinable())reader_.join();
    if(out_){CloseHandle(out_);out_=nullptr;}
    CloseHandle(process_);process_=nullptr;pid_=0;buffer_.clear();
}
#else
bool Child::running() const {
    if(!process_||exited_)return false;
    int status=0;const auto r=::waitpid(process_,&status,WNOHANG);  // reaped here; stop() then skips the wait
    if(r==process_||(r<0&&errno==ECHILD))exited_=true;
    return !exited_;
}

bool Child::read_some(std::string& into) {
    char buf[65536];
    while(true) {
        const auto n=::read(out_,buf,sizeof buf);
        if(n>0){into.append(buf,static_cast<size_t>(n));return true;}
        if(n<0&&errno==EINTR)continue;
        return false;
    }
}

bool Child::send(const std::string& line) {
    std::lock_guard g(write_);if(in_<0)return false;
    const std::string payload=line+"\n";size_t at=0;
    while(at<payload.size()) {
        const auto n=::write(in_,payload.data()+at,payload.size()-at);
        if(n<0&&errno==EINTR)continue;
        if(n<=0)return false;
        at+=static_cast<size_t>(n);
    }
    return true;
}

void Child::close_input(){std::lock_guard g(write_);if(in_>=0){::close(in_);in_=-1;}}

void Child::stop(unsigned grace_ms) {
    if(!process_)return;
    close_input();
    int status=0;const auto until=std::chrono::steady_clock::now()+std::chrono::milliseconds(grace_ms);
    while(!exited_) {
        const auto r=::waitpid(process_,&status,WNOHANG);if(r==process_||(r<0&&errno==ECHILD)){exited_=true;break;}
        if(std::chrono::steady_clock::now()>until){::kill(process_,SIGKILL);::waitpid(process_,&status,0);exited_=true;break;}
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    if(reader_.joinable())reader_.join();
    if(out_>=0){::close(out_);out_=-1;}
    process_=0;pid_=0;buffer_.clear();
}
#endif
}
