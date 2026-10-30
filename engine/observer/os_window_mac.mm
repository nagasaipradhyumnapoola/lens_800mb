// macOS side of os_window.hpp: windows are Accessibility (AX) window elements of the frontmost or followed application.
// Reading them needs the user's Accessibility permission (System Settings > Privacy & Security > Accessibility);
// without it init_thread() fails and the observer refuses to start. The registry retains every window handed out.
#import <AppKit/AppKit.h>
#import <ApplicationServices/ApplicationServices.h>
#include "os_window.hpp"
#include "ax_registry.hpp"
#include "../platform.hpp"
#include <libproc.h>
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <ctime>
#include <map>
#include <mutex>
#include <sys/resource.h>
#include <unistd.h>

namespace lens::observe {
namespace {
std::mutex registry_lock;std::map<Window,AXUIElementRef> windows;
Window remember(AXUIElementRef w) {
    std::lock_guard g(registry_lock);const auto id=reinterpret_cast<Window>(w);
    if(!windows.count(id)) {
        if(windows.size()>=64){CFRelease(windows.begin()->second);windows.erase(windows.begin());}
        windows[id]=static_cast<AXUIElementRef>(CFRetain(w));
    }
    return id;
}
std::wstring process_name(pid_t pid) {
    char name[PROC_PIDPATHINFO_MAXSIZE]{};proc_name(pid,name,sizeof name);
    std::wstring w=wide(name);std::transform(w.begin(),w.end(),w.begin(),[](wchar_t c){return c>=L'A'&&c<=L'Z'?static_cast<wchar_t>(c+32):c;});return w;
}
std::optional<WindowInfo> window_of(pid_t pid,CFStringRef which) {
    AXUIElementRef app=AXUIElementCreateApplication(pid);if(!app)return std::nullopt;
    CFTypeRef w=nullptr;std::optional<WindowInfo> out;
    if(AXUIElementCopyAttributeValue(app,which,&w)==kAXErrorSuccess&&w&&CFGetTypeID(w)==AXUIElementGetTypeID()) {
        CFTypeRef t=nullptr;std::string title;
        if(AXUIElementCopyAttributeValue(static_cast<AXUIElementRef>(w),kAXTitleAttribute,&t)==kAXErrorSuccess&&t&&CFGetTypeID(t)==CFStringGetTypeID())
            title=[(__bridge NSString*)t UTF8String]?:"";
        if(t)CFRelease(t);
        out=WindowInfo{remember(static_cast<AXUIElementRef>(w)),wide(title),process_name(pid),static_cast<long>(pid)};
    }
    if(w)CFRelease(w);CFRelease(app);return out;
}
}
AXUIElementRef ax_window(Window id) {
    std::lock_guard g(registry_lock);const auto it=windows.find(id);return it==windows.end()?nullptr:it->second;
}
bool init_thread(){return AXIsProcessTrusted();}  // the user granted Accessibility access to Lens
void uninit_thread() {}
void lower_priority(){(void)!nice(10);}
std::optional<WindowInfo> foreground_window() {
    NSRunningApplication* front=[[NSWorkspace sharedWorkspace] frontmostApplication];if(!front)return std::nullopt;
    return window_of(front.processIdentifier,kAXFocusedWindowAttribute);
}
std::optional<WindowInfo> window_for_pid(long pid){return window_of(static_cast<pid_t>(pid),kAXMainWindowAttribute);}
std::string os_privacy_block(Window id) {
    AXUIElementRef w=ax_window(id);if(!w)return "not_visible";
    CFTypeRef m=nullptr;bool minimised=false;
    if(AXUIElementCopyAttributeValue(w,kAXMinimizedAttribute,&m)==kAXErrorSuccess&&m&&CFGetTypeID(m)==CFBooleanGetTypeID())minimised=CFBooleanGetValue(static_cast<CFBooleanRef>(m));
    if(m)CFRelease(m);
    return minimised?"not_visible":"";
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
std::string utf8(const std::wstring& w) {  // wchar_t is UTF-32 on Apple platforms
    NSString* s=[[NSString alloc] initWithBytes:w.data() length:w.size()*sizeof(wchar_t) encoding:NSUTF32LittleEndianStringEncoding];
    const char* c=[s UTF8String];return c?c:"";
}
std::wstring wide(const std::string& s) {
    NSString* n=[[NSString alloc] initWithBytes:s.data() length:s.size() encoding:NSUTF8StringEncoding];
    if(!n)n=[[NSString alloc] initWithBytes:s.data() length:s.size() encoding:NSISOLatin1StringEncoding];
    NSData* d=[n dataUsingEncoding:NSUTF32LittleEndianStringEncoding];
    return std::wstring(static_cast<const wchar_t*>(d.bytes),d.length/sizeof(wchar_t));
}
std::filesystem::path worker_path(const char* name){return lens::platform::sibling(name);}
}
