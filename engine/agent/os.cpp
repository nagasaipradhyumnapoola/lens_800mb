#include "os.hpp"
#include "../platform.hpp"
#include <algorithm>
#include <atomic>
#include <fstream>
#include <map>
#include <vector>
#ifdef _WIN32
#include <windows.h>
#include <bcrypt.h>
#include <sddl.h>
#include <shlobj.h>
#include <tlhelp32.h>
#include <psapi.h>
#include <shellapi.h>
#else
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <poll.h>
#include <pwd.h>
#include <spawn.h>
#include <sys/wait.h>
#include <sys/file.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>
#include <openssl/evp.h>
#include <sys/random.h>  // getentropy (Linux, Android, Apple)
extern char** environ;
#ifdef __APPLE__
#include <libproc.h>
#include <sys/resource.h>
#endif
#endif

namespace fs=std::filesystem;
using json=nlohmann::json;
namespace lens::agent::os {
namespace {
std::string hex(const unsigned char* d,size_t n) {
    static const char* h="0123456789abcdef";std::string out;for(size_t i=0;i<n;++i){out+=h[d[i]>>4];out+=h[d[i]&15];}return out;
}
std::string u8(const fs::path& p){const auto s=p.u8string();return {s.begin(),s.end()};}
}

#ifdef _WIN32
namespace {
std::string utf8(const std::wstring& w) {
    if(w.empty())return {};
    const int n=WideCharToMultiByte(CP_UTF8,0,w.data(),static_cast<int>(w.size()),nullptr,0,nullptr,nullptr);
    std::string s(n,'\0');WideCharToMultiByte(CP_UTF8,0,w.data(),static_cast<int>(w.size()),s.data(),n,nullptr,nullptr);return s;
}
// Security descriptor: full access for the current user only (plus SYSTEM); remote clients are rejected separately.
bool user_only_security(SECURITY_ATTRIBUTES& sa) {
    HANDLE token=nullptr;if(!OpenProcessToken(GetCurrentProcess(),TOKEN_QUERY,&token))return false;
    DWORD n=0;GetTokenInformation(token,TokenUser,nullptr,0,&n);std::vector<BYTE> buf(n);
    if(!GetTokenInformation(token,TokenUser,buf.data(),n,&n)){CloseHandle(token);return false;}CloseHandle(token);
    LPWSTR sid=nullptr;if(!ConvertSidToStringSidW(reinterpret_cast<TOKEN_USER*>(buf.data())->User.Sid,&sid))return false;
    const std::wstring sddl=L"D:P(A;;GA;;;"+std::wstring(sid)+L")(A;;GA;;;SY)";LocalFree(sid);
    PSECURITY_DESCRIPTOR sd=nullptr;
    if(!ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl.c_str(),SDDL_REVISION_1,&sd,nullptr))return false;
    sa.nLength=sizeof sa;sa.lpSecurityDescriptor=sd;sa.bInheritHandle=FALSE;return true;
}
}
fs::path default_data_dir() {
    wchar_t* local=nullptr;fs::path out;
    if(SUCCEEDED(SHGetKnownFolderPath(FOLDERID_LocalAppData,0,nullptr,&local)))out=fs::path(local)/L"Lens";
    CoTaskMemFree(local);return out;
}
std::string user_name(){wchar_t user[256];DWORD n=256;return GetUserNameW(user,&n)?utf8(user):std::string("user");}
std::string sha256_file(const fs::path& p) {
    std::ifstream f(p,std::ios::binary);if(!f)return {};
    BCRYPT_ALG_HANDLE alg=nullptr;BCRYPT_HASH_HANDLE h=nullptr;unsigned char d[32]{};
    BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,nullptr,0);BCryptCreateHash(alg,&h,nullptr,0,nullptr,0,0);
    std::vector<char> buf(1<<20);
    while(f){f.read(buf.data(),buf.size());const auto n=f.gcount();if(n>0)BCryptHashData(h,reinterpret_cast<PUCHAR>(buf.data()),static_cast<ULONG>(n),0);}
    BCryptFinishHash(h,d,32,0);BCryptDestroyHash(h);BCryptCloseAlgorithmProvider(alg,0);return hex(d,32);
}
std::string sha256(const std::string& data) {
    BCRYPT_ALG_HANDLE alg=nullptr;BCRYPT_HASH_HANDLE h=nullptr;unsigned char d[32]{};
    BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,nullptr,0);BCryptCreateHash(alg,&h,nullptr,0,nullptr,0,0);
    BCryptHashData(h,reinterpret_cast<PUCHAR>(const_cast<char*>(data.data())),static_cast<ULONG>(data.size()),0);
    BCryptFinishHash(h,d,32,0);BCryptDestroyHash(h);BCryptCloseAlgorithmProvider(alg,0);return hex(d,32);
}
void random_bytes(unsigned char* out,size_t n) {
    if(BCryptGenRandom(nullptr,out,static_cast<ULONG>(n),BCRYPT_USE_SYSTEM_PREFERRED_RNG)!=0)std::abort();
}
bool open_url(const std::string& url) {
    const auto w=fs::path(std::u8string(url.begin(),url.end())).wstring();
    return reinterpret_cast<INT_PTR>(ShellExecuteW(nullptr,L"open",w.c_str(),nullptr,nullptr,SW_SHOWNORMAL))>32;
}
json process_tree() {
    json out=json::array();HANDLE snap=CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS,0);if(snap==INVALID_HANDLE_VALUE)return out;
    std::vector<PROCESSENTRY32W> all;PROCESSENTRY32W e{};e.dwSize=sizeof e;
    if(Process32FirstW(snap,&e))do all.push_back(e);while(Process32NextW(snap,&e));
    CloseHandle(snap);
    std::vector<DWORD> tree{GetCurrentProcessId()};
    for(size_t i=0;i<tree.size();++i)for(const auto& p:all)
        if(p.th32ParentProcessID==tree[i]&&std::find(tree.begin(),tree.end(),p.th32ProcessID)==tree.end())tree.push_back(p.th32ProcessID);
    for(const DWORD pid:tree) {
        std::wstring name;for(const auto& p:all)if(p.th32ProcessID==pid)name=p.szExeFile;
        HANDLE h=OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,FALSE,pid);if(!h)continue;
        PROCESS_MEMORY_COUNTERS_EX m{};m.cb=sizeof m;
        if(GetProcessMemoryInfo(h,reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&m),sizeof m))
            out.push_back({{"name",utf8(name)},{"pid",pid},{"working_set",m.WorkingSetSize},{"private",m.PrivateUsage}});
        CloseHandle(h);
    }
    return out;
}
SingleInstance::SingleInstance(const std::string& name) {
    handle_=CreateMutexW(nullptr,TRUE,(L"Local\\"+fs::path(std::u8string(name.begin(),name.end())).wstring()).c_str());
    acquired_=handle_&&GetLastError()!=ERROR_ALREADY_EXISTS;
}
SingleInstance::~SingleInstance(){if(handle_){if(acquired_)ReleaseMutex(handle_);CloseHandle(handle_);}}

namespace {
class PipeConnection:public Connection {
public:
    explicit PipeConnection(HANDLE p):pipe_(p){}
    ~PipeConnection() override {FlushFileBuffers(pipe_);DisconnectNamedPipe(pipe_);CloseHandle(pipe_);}
    bool read_some(std::string& into) override {
        char buf[65536];DWORD n=0;
        thread_=GetCurrentThreadId();busy_=true;
        const bool ok=!cancelled_&&ReadFile(pipe_,buf,sizeof buf,&n,nullptr)&&n;
        busy_=false;if(ok)into.append(buf,n);return ok;
    }
    bool write(const std::string& data) override {
        DWORD n=0;return WriteFile(pipe_,data.data(),static_cast<DWORD>(data.size()),&n,nullptr)&&n==data.size();
    }
    void cancel() override {  // a blocked synchronous ReadFile is cancelled on its own thread
        cancelled_=true;
        for(int i=0;i<250&&busy_;++i) {
            if(HANDLE t=OpenThread(THREAD_TERMINATE,FALSE,thread_)){CancelSynchronousIo(t);CloseHandle(t);}
            Sleep(20);
        }
    }
private:
    HANDLE pipe_;std::atomic<DWORD> thread_=0;std::atomic<bool> busy_=false,cancelled_=false;
};
}
struct Server::State {SECURITY_ATTRIBUTES sa{};std::wstring path;std::atomic<bool> stopping=false;};
Server::Server():s_(std::make_unique<State>()){}
Server::~Server(){if(s_->sa.lpSecurityDescriptor)LocalFree(s_->sa.lpSecurityDescriptor);}
bool Server::listen(const std::string& name) {
    if(!user_only_security(s_->sa)){error_="security_descriptor_failed";return false;}
    s_->path=L"\\\\.\\pipe\\"+fs::path(std::u8string(name.begin(),name.end())).wstring();address_=utf8(s_->path);return true;
}
std::unique_ptr<Connection> Server::accept() {
    while(!s_->stopping) {
        HANDLE pipe=CreateNamedPipeW(s_->path.c_str(),PIPE_ACCESS_DUPLEX,PIPE_TYPE_BYTE|PIPE_READMODE_BYTE|PIPE_WAIT|PIPE_REJECT_REMOTE_CLIENTS,
                                     PIPE_UNLIMITED_INSTANCES,1<<16,1<<16,0,&s_->sa);
        if(pipe==INVALID_HANDLE_VALUE){error_="pipe_failed:"+std::to_string(GetLastError());return nullptr;}
        const BOOL connected=ConnectNamedPipe(pipe,nullptr)?TRUE:(GetLastError()==ERROR_PIPE_CONNECTED);
        if(!connected||s_->stopping){CloseHandle(pipe);continue;}
        return std::make_unique<PipeConnection>(pipe);
    }
    return nullptr;
}
void Server::interrupt() {  // a connect of our own wakes ConnectNamedPipe
    s_->stopping=true;
    HANDLE poke=CreateFileW(s_->path.c_str(),GENERIC_READ|GENERIC_WRITE,0,nullptr,OPEN_EXISTING,0,nullptr);if(poke!=INVALID_HANDLE_VALUE)CloseHandle(poke);
}
#else
namespace {
fs::path home(){const auto h=lens::platform::environment("HOME");if(!h.empty())return h;const passwd* p=getpwuid(getuid());return p?fs::path(p->pw_dir):fs::path("/tmp");}
// Folder for the socket and lock: created 0700 and refused unless owned by this user with no group/other access.
fs::path runtime_dir(std::string& error) {
    fs::path dir;
    if(const auto e=lens::platform::environment("LENS_RUNTIME_DIR");!e.empty())dir=e;
    else if(const auto x=lens::platform::environment("XDG_RUNTIME_DIR");!x.empty())dir=fs::path(x)/"lens";
    else dir=fs::path("/tmp")/("lens-"+std::to_string(getuid()));
    ::mkdir(dir.c_str(),0700);
    struct stat st{};
    if(::lstat(dir.c_str(),&st)!=0||!S_ISDIR(st.st_mode)||st.st_uid!=getuid()||(st.st_mode&077)){error="runtime_dir_unsafe";return {};}
    return dir;
}
bool same_user(int fd) {
#if defined(__APPLE__)
    uid_t uid=0;gid_t gid=0;return getpeereid(fd,&uid,&gid)==0&&uid==getuid();
#else
    ucred c{};socklen_t n=sizeof c;return getsockopt(fd,SOL_SOCKET,SO_PEERCRED,&c,&n)==0&&c.uid==getuid();
#endif
}
class SocketConnection:public Connection {
public:
    explicit SocketConnection(int fd):fd_(fd){}
    ~SocketConnection() override {::close(fd_);}
    bool read_some(std::string& into) override {
        char buf[65536];
        while(true){const auto n=::read(fd_,buf,sizeof buf);if(n>0){into.append(buf,static_cast<size_t>(n));return true;}if(n<0&&errno==EINTR)continue;return false;}
    }
    bool write(const std::string& data) override {
        size_t at=0;
        while(at<data.size()) {
            const auto n=::send(fd_,data.data()+at,data.size()-at,MSG_NOSIGNAL_FLAG);
            if(n<0&&errno==EINTR)continue;
            if(n<=0)return false;
            at+=static_cast<size_t>(n);
        }
        return true;
    }
    void cancel() override {::shutdown(fd_,SHUT_RDWR);}  // a blocked read returns 0
private:
#ifdef MSG_NOSIGNAL
    static constexpr int MSG_NOSIGNAL_FLAG=MSG_NOSIGNAL;
#else
    static constexpr int MSG_NOSIGNAL_FLAG=0;  // Apple: SO_NOSIGPIPE is set on the socket instead
#endif
    int fd_;
};
}
fs::path default_data_dir() {
    if(const auto e=lens::platform::environment("LENS_DATA_DIR");!e.empty())return e;
#ifdef __APPLE__
    return home()/"Library"/"Application Support"/"Lens";
#else
    if(const auto x=lens::platform::environment("XDG_DATA_HOME");!x.empty())return fs::path(x)/"lens";
    return home()/".local"/"share"/"lens";
#endif
}
std::string user_name(){const passwd* p=getpwuid(getuid());return p&&p->pw_name?p->pw_name:std::to_string(getuid());}
std::string sha256_file(const fs::path& p) {
    std::ifstream f(p,std::ios::binary);if(!f)return {};
    EVP_MD_CTX* ctx=EVP_MD_CTX_new();if(!ctx)return {};
    EVP_DigestInit_ex(ctx,EVP_sha256(),nullptr);std::vector<char> buf(1<<20);
    while(f){f.read(buf.data(),buf.size());const auto n=f.gcount();if(n>0)EVP_DigestUpdate(ctx,buf.data(),static_cast<size_t>(n));}
    unsigned char d[32]{};unsigned int n=0;EVP_DigestFinal_ex(ctx,d,&n);EVP_MD_CTX_free(ctx);return hex(d,32);
}
std::string sha256(const std::string& data) {
    unsigned char d[32]{};unsigned int n=0;
    if(!EVP_Digest(data.data(),data.size(),d,&n,EVP_sha256(),nullptr))return {};
    return hex(d,32);
}
void random_bytes(unsigned char* out,size_t n) {
    while(n) {  // getentropy: at most 256 bytes per call (Linux glibc 2.25+, macOS, Android API 28+)
        const size_t k=std::min<size_t>(n,256);if(::getentropy(out,k)!=0)std::abort();out+=k;n-=k;
    }
}
bool open_url(const std::string& url) {
#ifdef __APPLE__
    const char* opener="/usr/bin/open";
#else
    const char* opener="xdg-open";
#endif
    char* argv[]={const_cast<char*>(opener),const_cast<char*>(url.c_str()),nullptr};pid_t pid=0;
    if(posix_spawnp(&pid,opener,nullptr,nullptr,argv,environ)!=0)return false;
    int status=0;::waitpid(pid,&status,0);return WIFEXITED(status)&&WEXITSTATUS(status)==0;
}
json process_tree() {
    json out=json::array();std::map<long,long> parent;std::map<long,std::string> names;
#ifdef __APPLE__
    std::vector<pid_t> pids(4096);const int n=proc_listallpids(pids.data(),static_cast<int>(pids.size()*sizeof(pid_t)));
    for(int i=0;i<n;++i){proc_bsdinfo b{};if(proc_pidinfo(pids[i],PROC_PIDTBSDINFO,0,&b,sizeof b)==sizeof b){parent[pids[i]]=b.pbi_ppid;names[pids[i]]=b.pbi_name[0]?b.pbi_name:b.pbi_comm;}}
#else
    std::error_code ec;
    for(const auto& e:fs::directory_iterator("/proc",ec)) {
        const auto pid_s=e.path().filename().string();if(pid_s.empty()||!std::all_of(pid_s.begin(),pid_s.end(),[](char c){return c>='0'&&c<='9';}))continue;
        std::ifstream f(e.path()/"stat");std::string stat;std::getline(f,stat);
        const auto open=stat.find('('),close=stat.rfind(')');if(open==std::string::npos||close==std::string::npos||close+4>stat.size())continue;
        names[std::stol(pid_s)]=stat.substr(open+1,close-open-1);
        try{parent[std::stol(pid_s)]=std::stol(stat.substr(close+4));}catch(...){}  // ") S ppid ..."
    }
#endif
    std::vector<long> tree{static_cast<long>(getpid())};
    for(size_t i=0;i<tree.size();++i)for(const auto& [pid,pp]:parent)
        if(pp==tree[i]&&std::find(tree.begin(),tree.end(),pid)==tree.end())tree.push_back(pid);
    for(const long pid:tree) {
        unsigned long long ws=0,pv=0;
#ifdef __APPLE__
        rusage_info_v2 r{};if(proc_pid_rusage(static_cast<pid_t>(pid),RUSAGE_INFO_V2,reinterpret_cast<rusage_info_t*>(&r))!=0)continue;
        ws=r.ri_resident_size;pv=r.ri_phys_footprint;
#else
        const auto dir=fs::path("/proc")/std::to_string(pid);std::ifstream status(dir/"status");if(!status)continue;
        auto kb=[](const std::string& line){unsigned long long v=0;for(char c:line)if(c>='0'&&c<='9')v=v*10+static_cast<unsigned long long>(c-'0');return v*1024;};
        unsigned long long anon=0;
        for(std::string line;std::getline(status,line);){if(line.rfind("VmRSS:",0)==0)ws=kb(line);else if(line.rfind("RssAnon:",0)==0)anon=kb(line);}
        std::ifstream rollup(dir/"smaps_rollup");bool have=false;  // private = Private_Clean + Private_Dirty (Linux 4.14+)
        for(std::string line;std::getline(rollup,line);)if(line.rfind("Private_",0)==0){pv+=kb(line);have=true;}
        if(!have)pv=anon;
#endif
        out.push_back({{"name",names[pid]},{"pid",pid},{"working_set",ws},{"private",pv}});
    }
    return out;
}
SingleInstance::SingleInstance(const std::string& name) {
    std::string error;const auto dir=runtime_dir(error);if(dir.empty())return;
    fd_=::open((dir/(name+".lock")).c_str(),O_RDWR|O_CREAT|O_CLOEXEC,0600);
    acquired_=fd_>=0&&::flock(fd_,LOCK_EX|LOCK_NB)==0;
}
SingleInstance::~SingleInstance(){if(fd_>=0)::close(fd_);}

struct Server::State {int fd=-1,wake[2]{-1,-1};std::atomic<bool> stopping=false;fs::path path;};
Server::Server():s_(std::make_unique<State>()){}
Server::~Server() {
    if(s_->fd>=0){::close(s_->fd);std::error_code ec;fs::remove(s_->path,ec);}
    for(int fd:s_->wake)if(fd>=0)::close(fd);
}
bool Server::listen(const std::string& name) {
    const auto dir=runtime_dir(error_);if(dir.empty())return false;
    s_->path=dir/(name+".sock");address_=u8(s_->path);
    sockaddr_un addr{};addr.sun_family=AF_UNIX;
    if(s_->path.native().size()>=sizeof addr.sun_path){error_="socket_path_too_long";return false;}
    std::memcpy(addr.sun_path,s_->path.c_str(),s_->path.native().size()+1);
    ::unlink(s_->path.c_str());  // a stale socket from a previous run (one agent per user: SingleInstance is already held)
    s_->fd=::socket(AF_UNIX,SOCK_STREAM,0);if(s_->fd<0){error_="socket_failed";return false;}
    ::fcntl(s_->fd,F_SETFD,FD_CLOEXEC);
    const mode_t old=::umask(0177);  // the socket file is created 0600
    const bool bound=::bind(s_->fd,reinterpret_cast<sockaddr*>(&addr),sizeof addr)==0;::umask(old);
    if(!bound||::listen(s_->fd,16)!=0||::pipe(s_->wake)!=0){error_="listen_failed";return false;}
    return true;
}
std::unique_ptr<Connection> Server::accept() {
    while(!s_->stopping) {
        pollfd p[2]{{s_->fd,POLLIN,0},{s_->wake[0],POLLIN,0}};
        if(::poll(p,2,-1)<0){if(errno==EINTR)continue;error_="poll_failed";return nullptr;}
        if(s_->stopping||(p[1].revents&POLLIN))return nullptr;
        if(!(p[0].revents&POLLIN))continue;
        const int c=::accept(s_->fd,nullptr,nullptr);if(c<0)continue;
        ::fcntl(c,F_SETFD,FD_CLOEXEC);
#ifdef SO_NOSIGPIPE
        const int one=1;::setsockopt(c,SOL_SOCKET,SO_NOSIGPIPE,&one,sizeof one);
#endif
        if(!same_user(c)){::close(c);continue;}  // another user's process: refused before any request is read
        return std::make_unique<SocketConnection>(c);
    }
    return nullptr;
}
void Server::interrupt(){s_->stopping=true;if(s_->wake[1]>=0){const char b=1;(void)!::write(s_->wake[1],&b,1);}}
#endif
}
