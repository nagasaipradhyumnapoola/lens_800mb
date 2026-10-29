#include "platform.hpp"
#include "input.hpp"
#ifdef _WIN32
#include <windows.h>
#else
#include <dlfcn.h>
#include <fcntl.h>
#include <unistd.h>
#endif
namespace lens::platform {
#ifdef _WIN32
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
#else
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
#endif
void write_new_file(const std::filesystem::path& path,const std::string& data) {
    NewFile f(path);if(!f.write(data)||!f.commit())throw Error("file_write_failed");
}
}
