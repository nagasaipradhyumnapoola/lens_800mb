// POSIX --serve OCR worker for screen_capture.hpp (Linux, macOS): a child process with pipes (posix_spawn), a poll
// timeout that kills a stuck worker, and the worker's CPU time (/proc/<pid>/stat on Linux, proc_pid_rusage on macOS).
#include "screen_capture.hpp"
#include <cerrno>
#include <chrono>
#include <fcntl.h>
#include <fstream>
#include <poll.h>
#include <signal.h>
#include <spawn.h>
#include <sstream>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>
#ifdef __APPLE__
#include <libproc.h>
#include <mach/mach_time.h>
#endif
extern char** environ;

namespace lens::observe {
namespace {
unsigned long long proc_cpu_ms(pid_t pid) {  // user + system time of a live child
#ifdef __APPLE__
    rusage_info_v2 r{};if(proc_pid_rusage(pid,RUSAGE_INFO_V2,reinterpret_cast<rusage_info_t*>(&r))!=0)return 0;
    mach_timebase_info_data_t tb{};mach_timebase_info(&tb);  // ri_*_time are in Mach absolute-time units
    return (r.ri_user_time+r.ri_system_time)*tb.numer/tb.denom/1000000;
#else
    std::ifstream f("/proc/"+std::to_string(pid)+"/stat");std::string stat;std::getline(f,stat);
    const auto close=stat.rfind(')');if(close==std::string::npos)return 0;
    std::istringstream in(stat.substr(close+2));std::string field;unsigned long long ut=0,st=0;
    for(int i=3;i<=15&&in>>field;++i){if(i==14)ut=std::stoull(field);if(i==15)st=std::stoull(field);}
    return (ut+st)*1000/static_cast<unsigned long long>(sysconf(_SC_CLK_TCK));
#endif
}
}

bool ServeWorker::start() {
    int in[2],out[2];
    if(::pipe(in)!=0)return false;
    if(::pipe(out)!=0){::close(in[0]);::close(in[1]);return false;}
    for(int fd:{in[1],out[0]})::fcntl(fd,F_SETFD,FD_CLOEXEC);
    posix_spawn_file_actions_t fa;posix_spawn_file_actions_init(&fa);
    posix_spawn_file_actions_adddup2(&fa,in[0],0);posix_spawn_file_actions_adddup2(&fa,out[1],1);
    posix_spawn_file_actions_addopen(&fa,2,"/dev/null",O_WRONLY,0);
    for(int fd:{in[0],out[1]})posix_spawn_file_actions_addclose(&fa,fd);
    const std::string exe=exe_.string();char serve[]="--serve";char* argv[]={const_cast<char*>(exe.c_str()),serve,nullptr};
    pid_t pid=0;const int rc=posix_spawn(&pid,exe.c_str(),&fa,nullptr,argv,environ);posix_spawn_file_actions_destroy(&fa);
    ::close(in[0]);::close(out[1]);
    if(rc!=0){::close(in[1]);::close(out[0]);return false;}
    signal(SIGPIPE,SIG_IGN);
    process_=static_cast<std::uintptr_t>(pid);in_=static_cast<std::uintptr_t>(in[1]);out_=static_cast<std::uintptr_t>(out[0]);buffer_.clear();return true;
}

void ServeWorker::stop() {
    if(!process_)return;
    const auto pid=static_cast<pid_t>(process_);
    ::close(static_cast<int>(in_));in_=0;  // EOF: the worker finishes and exits
    finished_cpu_ms_=cpu_ms();
    int status=0;const auto until=std::chrono::steady_clock::now()+std::chrono::seconds(5);
    while(::waitpid(pid,&status,WNOHANG)==0) {
        if(std::chrono::steady_clock::now()>until){::kill(pid,SIGKILL);::waitpid(pid,&status,0);break;}
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    ::close(static_cast<int>(out_));out_=process_=0;buffer_.clear();
}

unsigned long long ServeWorker::cpu_ms() const {
    return process_?finished_cpu_ms_+proc_cpu_ms(static_cast<pid_t>(process_)):finished_cpu_ms_;
}

std::optional<std::string> ServeWorker::request(const std::string& line,unsigned timeout_ms) {
    if(!process_&&!start())return std::nullopt;
    last_used_=tick_ms();
    const std::string payload=line+"\n";size_t at=0;
    while(at<payload.size()) {
        const auto n=::write(static_cast<int>(in_),payload.data()+at,payload.size()-at);
        if(n<0&&errno==EINTR)continue;
        if(n<=0){stop();return std::nullopt;}
        at+=static_cast<size_t>(n);
    }
    const auto until=std::chrono::steady_clock::now()+std::chrono::milliseconds(timeout_ms);
    while(true) {
        const auto pos=buffer_.find('\n');
        if(pos!=std::string::npos){auto r=buffer_.substr(0,pos);buffer_.erase(0,pos+1);last_used_=tick_ms();return r;}
        const auto left=std::chrono::duration_cast<std::chrono::milliseconds>(until-std::chrono::steady_clock::now()).count();
        if(left<=0){::kill(static_cast<pid_t>(process_),SIGKILL);stop();return std::nullopt;}  // stuck: the next request starts a new worker
        pollfd p{static_cast<int>(out_),POLLIN,0};const int ready=::poll(&p,1,static_cast<int>(left));
        if(ready<0&&errno==EINTR)continue;
        if(ready<=0)continue;
        char buf[65536];const auto n=::read(static_cast<int>(out_),buf,sizeof buf);
        if(n<=0){stop();return std::nullopt;}
        buffer_.append(buf,static_cast<size_t>(n));
    }
}
}
