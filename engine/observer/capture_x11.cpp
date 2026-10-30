// Linux side of screen_capture.hpp: the frame's on-screen area read from the X server (X11 or Xwayland; a native
// Wayland session gives no screen access without the desktop portal, so capture returns an empty frame there), and the
// --serve OCR worker as a child process with pipes (posix_spawn, poll timeout, CPU from /proc/<pid>/stat).
#include "screen_capture.hpp"
#include "atspi_registry.hpp"
#include "../platform.hpp"
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <algorithm>
#include <cerrno>
#include <chrono>
#include <fcntl.h>
#include <fstream>
#include <mutex>
#include <poll.h>
#include <signal.h>
#include <spawn.h>
#include <sstream>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>
extern char** environ;

namespace lens::observe {
Frame capture_window(Window id) {
    AtspiAccessible* frame=atspi_frame(id);if(!frame)return {};
    AtspiComponent* c=atspi_accessible_get_component_iface(frame);if(!c)return {};
    GError* e=nullptr;AtspiRect* r=atspi_component_get_extents(c,ATSPI_COORD_TYPE_SCREEN,&e);if(e)g_clear_error(&e);g_object_unref(c);
    if(!r)return {};
    int x=r->x,y=r->y,w=r->width,h=r->height;g_free(r);
    static std::mutex lock;static Display* display=nullptr;std::lock_guard g(lock);
    if(!display)display=XOpenDisplay(nullptr);
    if(!display)return {};
    const int sw=DisplayWidth(display,DefaultScreen(display)),sh=DisplayHeight(display,DefaultScreen(display));
    if(x<0){w+=x;x=0;}if(y<0){h+=y;y=0;}w=std::min(w,sw-x);h=std::min(h,sh-y);  // the visible part of the frame
    if(w<8||h<8||static_cast<long long>(w)*h>16000000)return {};
    XImage* img=XGetImage(display,DefaultRootWindow(display),x,y,static_cast<unsigned>(w),static_cast<unsigned>(h),AllPlanes,ZPixmap);
    if(!img)return {};
    Frame f;f.w=w;f.h=h;f.bgr.resize(static_cast<size_t>(w)*h*3);
    const bool direct=img->bits_per_pixel==32&&img->red_mask==0xFF0000&&img->green_mask==0xFF00&&img->blue_mask==0xFF&&img->byte_order==LSBFirst;
    for(int yy=0;yy<h;++yy)for(int xx=0;xx<w;++xx) {
        unsigned char* out=&f.bgr[(static_cast<size_t>(yy)*w+xx)*3];
        if(direct){const auto* p=reinterpret_cast<const unsigned char*>(img->data)+static_cast<size_t>(yy)*img->bytes_per_line+static_cast<size_t>(xx)*4;out[0]=p[0];out[1]=p[1];out[2]=p[2];}
        else {
            const unsigned long px=XGetPixel(img,xx,yy);
            auto chan=[&](unsigned long mask){if(!mask)return static_cast<unsigned char>(0);int s=0;while(!((mask>>s)&1))++s;const unsigned long m=mask>>s;return static_cast<unsigned char>(((px&mask)>>s)*255/m);};
            out[0]=chan(img->blue_mask);out[1]=chan(img->green_mask);out[2]=chan(img->red_mask);
        }
    }
    XDestroyImage(img);
    bool blank=true;for(size_t i=3;i<f.bgr.size()&&blank;i+=3)blank=f.bgr[i]==f.bgr[0]&&f.bgr[i+1]==f.bgr[1]&&f.bgr[i+2]==f.bgr[2];
    return blank?Frame{}:f;
}

namespace {
unsigned long long proc_cpu_ms(pid_t pid) {  // utime + stime of a live child
    std::ifstream f("/proc/"+std::to_string(pid)+"/stat");std::string stat;std::getline(f,stat);
    const auto close=stat.rfind(')');if(close==std::string::npos)return 0;
    std::istringstream in(stat.substr(close+2));std::string field;unsigned long long ut=0,st=0;
    for(int i=3;i<=15&&in>>field;++i){if(i==14)ut=std::stoull(field);if(i==15)st=std::stoull(field);}
    return (ut+st)*1000/static_cast<unsigned long long>(sysconf(_SC_CLK_TCK));
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
