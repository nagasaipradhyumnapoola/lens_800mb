#include "platform.hpp"
#include "input.hpp"
#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <thread>
#ifdef _WIN32
#include <windows.h>
#include <psapi.h>  // K32GetProcessMemoryInfo (kernel32)
#else
#include <dlfcn.h>
#include <fcntl.h>
#include <signal.h>
#include <spawn.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <unistd.h>
#ifdef __APPLE__
#include <mach-o/dyld.h>
#endif
extern char** environ;
#endif
namespace lens::platform {
namespace {
constexpr char B64[]="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
constexpr size_t MAX_CHILD_OUTPUT=4*1024*1024;
}
std::vector<char> base64_decode(const std::string& text) {
    std::vector<char> out;out.reserve(text.size()*3/4);unsigned buffer=0;int bits=0;bool padded=false;
    for(const char c:text) {
        if(c==' '||c=='\n'||c=='\r'||c=='\t')continue;
        if(c=='='){padded=true;continue;}
        const char* p=c?std::strchr(B64,c):nullptr;if(!p||padded)throw Error("base64_invalid");
        buffer=(buffer<<6)|static_cast<unsigned>(p-B64);bits+=6;
        if(bits>=8){bits-=8;out.push_back(static_cast<char>((buffer>>bits)&0xFF));}
    }
    return out;
}
std::string base64_encode(const std::string& bytes) {
    std::string out;out.reserve((bytes.size()+2)/3*4);
    for(size_t i=0;i<bytes.size();i+=3) {
        const unsigned b0=static_cast<unsigned char>(bytes[i]),b1=i+1<bytes.size()?static_cast<unsigned char>(bytes[i+1]):0,b2=i+2<bytes.size()?static_cast<unsigned char>(bytes[i+2]):0;
        const unsigned v=(b0<<16)|(b1<<8)|b2;
        out+=B64[(v>>18)&63];out+=B64[(v>>12)&63];out+=i+1<bytes.size()?B64[(v>>6)&63]:'=';out+=i+2<bytes.size()?B64[v&63]:'=';
    }
    return out;
}
#ifdef _WIN32
std::filesystem::path executable_dir() {
    std::wstring self(32768,L'\0');self.resize(GetModuleFileNameW(nullptr,self.data(),static_cast<DWORD>(self.size())));
    return std::filesystem::path(self).parent_path();
}
std::optional<std::string> run_child(const std::filesystem::path& exe,const std::string& input,int& exit_code) {
    SECURITY_ATTRIBUTES sa{sizeof sa,nullptr,TRUE};HANDLE in_r{},in_w{},out_r{},out_w{};
    if(!CreatePipe(&in_r,&in_w,&sa,0))return std::nullopt;
    if(!CreatePipe(&out_r,&out_w,&sa,0)){CloseHandle(in_r);CloseHandle(in_w);return std::nullopt;}
    SetHandleInformation(in_w,HANDLE_FLAG_INHERIT,0);SetHandleInformation(out_r,HANDLE_FLAG_INHERIT,0);
    STARTUPINFOW si{};si.cb=sizeof si;si.dwFlags=STARTF_USESTDHANDLES;si.hStdInput=in_r;si.hStdOutput=out_w;si.hStdError=out_w;
    PROCESS_INFORMATION pi{};std::wstring cmd=L"\""+exe.wstring()+L"\"";
    const bool started=CreateProcessW(exe.c_str(),cmd.data(),nullptr,nullptr,TRUE,CREATE_NO_WINDOW,nullptr,nullptr,&si,&pi);
    CloseHandle(in_r);CloseHandle(out_w);
    if(!started){CloseHandle(in_w);CloseHandle(out_r);return std::nullopt;}
    std::thread writer([&] {
        size_t at=0;
        while(at<input.size()){DWORD n=0;if(!WriteFile(in_w,input.data()+at,static_cast<DWORD>(std::min<size_t>(input.size()-at,65536)),&n,nullptr))break;at+=n;}
        CloseHandle(in_w);
    });
    std::string out;char buf[65536];DWORD n=0;
    while(ReadFile(out_r,buf,sizeof buf,&n,nullptr)&&n){out.append(buf,n);if(out.size()>MAX_CHILD_OUTPUT)break;}
    writer.join();CloseHandle(out_r);
    if(WaitForSingleObject(pi.hProcess,300000)!=WAIT_OBJECT_0)TerminateProcess(pi.hProcess,1);
    DWORD code=1;GetExitCodeProcess(pi.hProcess,&code);CloseHandle(pi.hProcess);CloseHandle(pi.hThread);exit_code=static_cast<int>(code);
    return out;
}
void* open_library(const std::filesystem::path& path) {
    const auto full=std::filesystem::absolute(path).make_preferred();  // fully qualified, or the DLL_LOAD_DIR flag is ignored
    return LoadLibraryExW(full.c_str(),nullptr,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
}
void* library_symbol(void* library,const char* name){return reinterpret_cast<void*>(GetProcAddress(static_cast<HMODULE>(library),name));}
void close_library(void* library){if(library)FreeLibrary(static_cast<HMODULE>(library));}
NewFile::NewFile(const std::filesystem::path& path):path_(path) {
    const HANDLE h=CreateFileW(path.c_str(),GENERIC_WRITE,0,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);
    if(h==INVALID_HANDLE_VALUE){ok_=false;}else handle_=h;
}
bool NewFile::write(const std::string& data) {
    DWORD n=0;ok_=ok_&&handle_&&WriteFile(handle_,data.data(),static_cast<DWORD>(data.size()),&n,nullptr)&&n==data.size();return ok_;
}
bool NewFile::commit() {
    if(!handle_)return false;
    ok_=ok_&&FlushFileBuffers(handle_);CloseHandle(handle_);handle_=nullptr;
    if(!ok_){std::error_code ec;std::filesystem::remove(path_,ec);}
    return ok_;
}
NewFile::~NewFile(){if(handle_){CloseHandle(handle_);std::error_code ec;std::filesystem::remove(path_,ec);}}
bool replace_file(const std::filesystem::path& from,const std::filesystem::path& to) {
    return MoveFileExW(from.c_str(),to.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH)!=0;
}
std::string environment(const char* name) {
    char* value=nullptr;size_t n=0;std::string out;
    if(_dupenv_s(&value,&n,name)==0&&value)out=value;
    free(value);return out;
}
std::uint64_t peak_memory_bytes() {
    PROCESS_MEMORY_COUNTERS pmc{};return GetProcessMemoryInfo(GetCurrentProcess(),&pmc,sizeof pmc)?pmc.PeakWorkingSetSize:0;
}
#else
std::filesystem::path executable_dir() {
#ifdef __APPLE__
    char buf[4096];uint32_t n=sizeof buf;if(_NSGetExecutablePath(buf,&n)==0)return std::filesystem::canonical(buf).parent_path();
#else
    std::error_code ec;const auto self=std::filesystem::read_symlink("/proc/self/exe",ec);if(!ec)return self.parent_path();
#endif
    return std::filesystem::current_path();
}
std::optional<std::string> run_child(const std::filesystem::path& exe,const std::string& input,int& exit_code) {
    int in[2],out[2];
    if(::pipe(in)!=0)return std::nullopt;
    if(::pipe(out)!=0){::close(in[0]);::close(in[1]);return std::nullopt;}
    posix_spawn_file_actions_t fa;posix_spawn_file_actions_init(&fa);
    posix_spawn_file_actions_adddup2(&fa,in[0],0);posix_spawn_file_actions_adddup2(&fa,out[1],1);posix_spawn_file_actions_adddup2(&fa,out[1],2);
    for(int fd:{in[0],in[1],out[0],out[1]})posix_spawn_file_actions_addclose(&fa,fd);
    const std::string path=exe.string();char* argv[]={const_cast<char*>(path.c_str()),nullptr};pid_t pid=0;
    const int rc=posix_spawn(&pid,path.c_str(),&fa,nullptr,argv,environ);posix_spawn_file_actions_destroy(&fa);
    ::close(in[0]);::close(out[1]);
    if(rc!=0){::close(in[1]);::close(out[0]);return std::nullopt;}
    std::thread writer([&] {
        signal(SIGPIPE,SIG_IGN);size_t at=0;  // a child that exits early must not kill the engine
        while(at<input.size()){const auto n=::write(in[1],input.data()+at,std::min<size_t>(input.size()-at,65536));if(n<=0)break;at+=static_cast<size_t>(n);}
        ::close(in[1]);
    });
    std::string result;char buf[65536];
    for(ssize_t n;(n=::read(out[0],buf,sizeof buf))>0;){result.append(buf,static_cast<size_t>(n));if(result.size()>MAX_CHILD_OUTPUT)break;}
    writer.join();::close(out[0]);
    int status=0;const auto until=std::chrono::steady_clock::now()+std::chrono::seconds(300);
    while(::waitpid(pid,&status,WNOHANG)==0) {
        if(std::chrono::steady_clock::now()>until){::kill(pid,SIGKILL);::waitpid(pid,&status,0);break;}
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    exit_code=WIFEXITED(status)?WEXITSTATUS(status):1;
    return result;
}
void* open_library(const std::filesystem::path& path){return dlopen(path.c_str(),RTLD_NOW|RTLD_LOCAL);}
void* library_symbol(void* library,const char* name){return dlsym(library,name);}
void close_library(void* library){if(library)dlclose(library);}
NewFile::NewFile(const std::filesystem::path& path):path_(path) {
    fd_=::open(path.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC,0600);  // owner-only: exports and backups hold personal data
    if(fd_<0){ok_=false;}
}
bool NewFile::write(const std::string& data) {
    size_t off=0;
    while(ok_&&fd_>=0&&off<data.size()){const auto n=::write(fd_,data.data()+off,data.size()-off);if(n<=0)ok_=false;else off+=static_cast<size_t>(n);}
    return ok_&&fd_>=0;
}
bool NewFile::commit() {
    if(fd_<0)return false;
    ok_=ok_&&::fsync(fd_)==0;::close(fd_);fd_=-1;
    if(!ok_){std::error_code ec;std::filesystem::remove(path_,ec);}
    return ok_;
}
NewFile::~NewFile(){if(fd_>=0){::close(fd_);std::error_code ec;std::filesystem::remove(path_,ec);}}
bool replace_file(const std::filesystem::path& from,const std::filesystem::path& to) {
    if(::rename(from.c_str(),to.c_str())!=0)return false;
    const int dir=::open(to.parent_path().empty()?".":to.parent_path().c_str(),O_RDONLY|O_DIRECTORY|O_CLOEXEC);  // persist the rename
    if(dir>=0){::fsync(dir);::close(dir);}
    return true;
}
std::string environment(const char* name){const char* v=std::getenv(name);return v?v:"";}  // NOLINT(concurrency-mt-unsafe)
std::uint64_t peak_memory_bytes() {
    rusage u{};if(getrusage(RUSAGE_SELF,&u)!=0)return 0;
#ifdef __APPLE__
    return static_cast<std::uint64_t>(u.ru_maxrss);  // bytes on Apple platforms
#else
    return static_cast<std::uint64_t>(u.ru_maxrss)*1024;  // kilobytes on Linux and Android
#endif
}
#endif
void write_new_file(const std::filesystem::path& path,const std::string& data) {
    NewFile f(path);if(!f.write(data)||!f.commit())throw Error("file_write_failed");
}
}
