// Linux side of os_window.hpp: windows are AT-SPI frames on the accessibility bus (the same tree screen readers use);
// the process is /proc/<pid>/comm. The frame registry keeps a reference to every frame handed out as a Window.
#include "os_window.hpp"
#include "atspi_registry.hpp"
#include "../platform.hpp"
#include <atspi/atspi.h>
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <ctime>
#include <fstream>
#include <map>
#include <mutex>
#include <sys/resource.h>
#include <unistd.h>

namespace lens::observe {
namespace {
std::mutex registry_lock;std::map<Window,AtspiAccessible*> frames;  // id -> referenced frame
Window remember(AtspiAccessible* frame) {
    std::lock_guard g(registry_lock);const auto id=reinterpret_cast<Window>(frame);
    if(!frames.count(id)) {
        if(frames.size()>=64){g_object_unref(frames.begin()->second);frames.erase(frames.begin());}
        frames[id]=static_cast<AtspiAccessible*>(g_object_ref(frame));
    }
    return id;
}
bool has_state(AtspiAccessible* a,AtspiStateType s) {
    AtspiStateSet* set=atspi_accessible_get_state_set(a);if(!set)return false;
    const bool r=atspi_state_set_contains(set,s);g_object_unref(set);return r;
}
std::wstring process_name(long pid) {
    std::ifstream f("/proc/"+std::to_string(pid)+"/comm");std::string name;std::getline(f,name);
    std::wstring w=wide(name);std::transform(w.begin(),w.end(),w.begin(),[](wchar_t c){return c>=L'A'&&c<=L'Z'?static_cast<wchar_t>(c+32):c;});return w;
}
WindowInfo info(AtspiAccessible* app,AtspiAccessible* frame) {
    GError* e=nullptr;const long pid=static_cast<long>(atspi_accessible_get_process_id(app,&e));if(e)g_clear_error(&e);
    gchar* name=atspi_accessible_get_name(frame,&e);if(e)g_clear_error(&e);
    WindowInfo w{remember(frame),wide(name?name:""),process_name(pid),pid};g_free(name);return w;
}
// Calls `pick(app, frame)` for every top-level frame until it returns true.
template<class F>std::optional<WindowInfo> find_frame(F pick) {
    AtspiAccessible* desktop=atspi_get_desktop(0);if(!desktop)return std::nullopt;
    GError* e=nullptr;const int apps=atspi_accessible_get_child_count(desktop,&e);if(e)g_clear_error(&e);
    std::optional<WindowInfo> found;
    for(int i=0;i<apps&&!found;++i) {
        AtspiAccessible* app=atspi_accessible_get_child_at_index(desktop,i,&e);if(e)g_clear_error(&e);if(!app)continue;
        const int n=atspi_accessible_get_child_count(app,&e);if(e)g_clear_error(&e);
        for(int k=0;k<n&&!found;++k) {
            AtspiAccessible* frame=atspi_accessible_get_child_at_index(app,k,&e);if(e)g_clear_error(&e);if(!frame)continue;
            if(pick(app,frame))found=info(app,frame);
            g_object_unref(frame);
        }
        g_object_unref(app);
    }
    g_object_unref(desktop);return found;
}
}
AtspiAccessible* atspi_frame(Window id) {  // referenced by the registry; the caller must not unref it
    std::lock_guard g(registry_lock);const auto it=frames.find(id);return it==frames.end()?nullptr:it->second;
}
bool init_thread() {
    static const bool ok=[]{const int r=atspi_init();if(r<0)return false;atspi_set_timeout(800,4000);return true;}();  // a hung app never blocks the observer for long
    return ok;
}
void uninit_thread() {}
void lower_priority(){(void)!nice(10);}
std::optional<WindowInfo> foreground_window() {
    return find_frame([](AtspiAccessible*,AtspiAccessible* f){return has_state(f,ATSPI_STATE_ACTIVE);});
}
std::optional<WindowInfo> window_for_pid(long pid) {
    return find_frame([pid](AtspiAccessible* app,AtspiAccessible* f){
        GError* e=nullptr;const long p=static_cast<long>(atspi_accessible_get_process_id(app,&e));if(e)g_clear_error(&e);
        return p==pid&&has_state(f,ATSPI_STATE_SHOWING);});
}
std::string os_privacy_block(Window id) {
    AtspiAccessible* f=atspi_frame(id);
    if(!f||!has_state(f,ATSPI_STATE_SHOWING)||has_state(f,ATSPI_STATE_ICONIFIED))return "not_visible";
    return {};  // X11 and Wayland have no capture-protection flag
}
long current_pid(){return static_cast<long>(getpid());}
unsigned long long process_cpu_ms() {
    rusage u{};if(getrusage(RUSAGE_SELF,&u)!=0)return 0;
    return static_cast<unsigned long long>(u.ru_utime.tv_sec+u.ru_stime.tv_sec)*1000+static_cast<unsigned long long>(u.ru_utime.tv_usec+u.ru_stime.tv_usec)/1000;
}
unsigned long long thread_cpu_ms() {
    timespec t{};if(clock_gettime(CLOCK_THREAD_CPUTIME_ID,&t)!=0)return 0;
    return static_cast<unsigned long long>(t.tv_sec)*1000+static_cast<unsigned long long>(t.tv_nsec)/1000000;
}
unsigned long long tick_ms() {
    return static_cast<unsigned long long>(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch()).count());
}
std::string utc_now() {
    const auto now=std::chrono::system_clock::now();const std::time_t t=std::chrono::system_clock::to_time_t(now);
    const int ms=static_cast<int>(std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count()%1000);
    std::tm u{};gmtime_r(&t,&u);char buf[40];
    std::snprintf(buf,sizeof buf,"%04d-%02d-%02dT%02d:%02d:%02d.%03dZ",u.tm_year+1900,u.tm_mon+1,u.tm_mday,u.tm_hour,u.tm_min,u.tm_sec,ms);return buf;
}
std::string utf8(const std::wstring& w) {  // wchar_t is UTF-32 here
    std::string s;
    for(wchar_t wc:w) {
        auto c=static_cast<char32_t>(wc);if(c>0x10FFFF||(c>=0xD800&&c<=0xDFFF))c=0xFFFD;
        if(c<0x80)s+=static_cast<char>(c);
        else if(c<0x800){s+=static_cast<char>(0xC0|(c>>6));s+=static_cast<char>(0x80|(c&0x3F));}
        else if(c<0x10000){s+=static_cast<char>(0xE0|(c>>12));s+=static_cast<char>(0x80|((c>>6)&0x3F));s+=static_cast<char>(0x80|(c&0x3F));}
        else {s+=static_cast<char>(0xF0|(c>>18));s+=static_cast<char>(0x80|((c>>12)&0x3F));s+=static_cast<char>(0x80|((c>>6)&0x3F));s+=static_cast<char>(0x80|(c&0x3F));}
    }
    return s;
}
std::wstring wide(const std::string& s) {  // invalid sequences become U+FFFD
    std::wstring w;size_t i=0;
    while(i<s.size()) {
        const auto c=static_cast<unsigned char>(s[i]);size_t n=0;char32_t v=c;
        if(c>=0x80) {
            if((c&0xE0)==0xC0){n=1;v=c&0x1F;}else if((c&0xF0)==0xE0){n=2;v=c&0x0F;}else if((c&0xF8)==0xF0){n=3;v=c&0x07;}
            else {w+=L'�';++i;continue;}
        }
        bool ok=i+n<s.size();
        for(size_t k=1;ok&&k<=n;++k){const auto b=static_cast<unsigned char>(s[i+k]);ok=(b&0xC0)==0x80;v=(v<<6)|(b&0x3F);}
        if(!ok){w+=L'�';++i;continue;}
        w+=static_cast<wchar_t>(v);i+=n+1;
    }
    return w;
}
std::filesystem::path worker_path(const char* name){return lens::platform::sibling(name);}
}
