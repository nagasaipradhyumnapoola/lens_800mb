#pragma once
// Thin operating-system layer for the portable core (Windows, Linux, macOS, Android, iOS): shared libraries and durable
// new files. Everything else in the core is standard C++. Key storage lives in adapters/<os>/key_store.cpp.
#include <filesystem>
#include <string>
namespace lens::platform {
// nullptr on failure. Windows resolves the library's own dependencies from its folder first (never System32's copy).
void* open_library(const std::filesystem::path& path);
void* library_symbol(void* library,const char* name);
void close_library(void* library);

// A file that must not exist yet (refuses to overwrite), written and flushed to the device before commit() returns.
// Destroyed without a successful commit(), the partial file is removed.
class NewFile {
public:
    explicit NewFile(const std::filesystem::path& path);
    ~NewFile();
    NewFile(const NewFile&)=delete;NewFile& operator=(const NewFile&)=delete;
    bool write(const std::string& data);
    bool commit();
private:
    std::filesystem::path path_;void* handle_=nullptr;int fd_=-1;bool ok_=true;
};
void write_new_file(const std::filesystem::path& path,const std::string& data);  // throws Error("file_write_failed")
// Atomically replaces `to` with `from` (same volume), durable when it returns; false when `to` is in use.
bool replace_file(const std::filesystem::path& from,const std::filesystem::path& to);
std::string environment(const char* name);  // empty when unset
}
