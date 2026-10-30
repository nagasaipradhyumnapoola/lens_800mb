#pragma once
// Thin operating-system layer for the portable core (Windows, Linux, macOS, Android, iOS): shared libraries and durable
// new files. Everything else in the core is standard C++. Key storage lives in adapters/<os>/key_store.cpp.
#include <cstdint>
#include <filesystem>
#include <optional>
#include <string>
#include <vector>
namespace lens::platform {
std::filesystem::path executable_dir();  // folder of the running executable (sibling workers live there)
inline std::filesystem::path sibling(const char* name) {  // a worker next to this executable: "lens-sherpa" -> lens-sherpa(.exe)
#ifdef _WIN32
    return executable_dir()/(std::string(name)+".exe");
#else
    return executable_dir()/name;
#endif
}
// Runs `exe` without arguments or a console window, feeds `input` on stdin and returns its stdout and stderr
// (at most 4 MiB); nullopt when it cannot start. Killed after 300 s.
std::optional<std::string> run_child(const std::filesystem::path& exe,const std::string& input,int& exit_code);
std::vector<char> base64_decode(const std::string& text);  // standard alphabet, whitespace ignored; throws Error("base64_invalid")
std::string base64_encode(const std::string& bytes);
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
std::uint64_t peak_memory_bytes();  // this process's peak resident set (Windows: peak working set)
}
