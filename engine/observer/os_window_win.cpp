#include "os_window.hpp"
#include "../platform.hpp"
#include <windows.h>
#include <dwmapi.h>
#include <algorithm>
#include <cstdio>
#include <cwctype>

namespace lens::observe {
namespace {
std::wstring lower(std::wstring s){std::transform(s.begin(),s.end(),s.begin(),[](wchar_t c){return static_cast<wchar_t>(towlower(c));});return s;}
std::wstring window_title(HWND w){wchar_t buf[512]{};InternalGetWindowText(w,buf,512);return buf;}
std::wstring process_name(DWORD pid) {
    HANDLE p=OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,FALSE,pid);if(!p)return {};
    wchar_t path[MAX_PATH]{};DWORD size=MAX_PATH;std::wstring name;
    if(QueryFullProcessImageNameW(p,0,path,&size)){name=path;name=name.substr(name.find_last_of(L"\\/")+1);}
    CloseHandle(p);return lower(name);
}
WindowInfo info(HWND w) {
    DWORD pid=0;GetWindowThreadProcessId(w,&pid);
    return {reinterpret_cast<Window>(w),window_title(w),process_name(pid),static_cast<long>(pid)};
}
struct FindPid{DWORD pid;HWND found=nullptr;};
BOOL CALLBACK find_pid_window(HWND w,LPARAM p) {
    auto& f=*reinterpret_cast<FindPid*>(p);DWORD pid=0;GetWindowThreadProcessId(w,&pid);
    if(pid==f.pid&&IsWindowVisible(w)&&!GetWindow(w,GW_OWNER)){f.found=w;return FALSE;}return TRUE;
}
unsigned long long ms_of(const FILETIME& k,const FILETIME& u) {
    auto v=[](const FILETIME& f){return (static_cast<unsigned long long>(f.dwHighDateTime)<<32)|f.dwLowDateTime;};
    return (v(k)+v(u))/10000;
}
}
bool init_thread(){return SUCCEEDED(CoInitializeEx(nullptr,COINIT_MULTITHREADED));}
void uninit_thread(){CoUninitialize();}
void lower_priority(){SetPriorityClass(GetCurrentProcess(),BELOW_NORMAL_PRIORITY_CLASS);}
std::optional<WindowInfo> foreground_window(){HWND w=GetForegroundWindow();if(!w)return std::nullopt;return info(w);}
std::optional<WindowInfo> window_for_pid(long pid) {
    FindPid f{static_cast<DWORD>(pid)};EnumWindows(find_pid_window,reinterpret_cast<LPARAM>(&f));
    if(!f.found)return std::nullopt;return info(f.found);
}
std::string os_privacy_block(Window id) {
    HWND w=reinterpret_cast<HWND>(id);
    if(!w||!IsWindowVisible(w)||IsIconic(w))return "not_visible";
    BOOL cloaked=FALSE;if(SUCCEEDED(DwmGetWindowAttribute(w,DWMWA_CLOAKED,&cloaked,sizeof cloaked))&&cloaked)return "not_visible";
    DWORD affinity=WDA_NONE;if(GetWindowDisplayAffinity(w,&affinity)&&affinity!=WDA_NONE)return "capture_protected";
    return {};
}
long current_pid(){return static_cast<long>(GetCurrentProcessId());}
unsigned long long process_cpu_ms(){FILETIME c,e,k,u;return GetProcessTimes(GetCurrentProcess(),&c,&e,&k,&u)?ms_of(k,u):0;}
unsigned long long thread_cpu_ms(){FILETIME c,e,k,u;return GetThreadTimes(GetCurrentThread(),&c,&e,&k,&u)?ms_of(k,u):0;}
unsigned long long tick_ms(){return GetTickCount64();}
std::string utc_now() {
    SYSTEMTIME t;GetSystemTime(&t);char buf[40];
    std::snprintf(buf,sizeof buf,"%04u-%02u-%02uT%02u:%02u:%02u.%03uZ",t.wYear,t.wMonth,t.wDay,t.wHour,t.wMinute,t.wSecond,t.wMilliseconds);return buf;
}
std::string utf8(const std::wstring& w) {
    if(w.empty())return {};
    const int n=WideCharToMultiByte(CP_UTF8,0,w.data(),static_cast<int>(w.size()),nullptr,0,nullptr,nullptr);
    std::string s(n,'\0');WideCharToMultiByte(CP_UTF8,0,w.data(),static_cast<int>(w.size()),s.data(),n,nullptr,nullptr);return s;
}
std::wstring wide(const std::string& s) {
    const int n=MultiByteToWideChar(CP_UTF8,0,s.data(),static_cast<int>(s.size()),nullptr,0);
    std::wstring w(n,L'\0');MultiByteToWideChar(CP_UTF8,0,s.data(),static_cast<int>(s.size()),w.data(),n);return w;
}
std::filesystem::path worker_path(const char* name){return lens::platform::sibling(name);}
}
