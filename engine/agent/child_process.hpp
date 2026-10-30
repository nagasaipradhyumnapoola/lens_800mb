#pragma once
// A child process with piped stdin/stdout (JSON lines) and stderr discarded or forwarded. No console window.
// Paths and arguments are native strings (UTF-16 on Windows, UTF-8 elsewhere).
#ifdef _WIN32
#include <windows.h>
#else
#include <sys/types.h>
#endif
#include <atomic>
#include <filesystem>
#include <functional>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>

namespace lens::agent {
using native=std::filesystem::path::string_type;
class Child {
public:
    ~Child(){stop();}
    // Starts `exe args...`. on_line, when given, receives every stdout line on a reader thread; otherwise lines are
    // read synchronously with request().
    bool start(const native& exe,const std::vector<native>& args,std::function<void(const std::string&)> on_line={});
    bool running() const;
    bool send(const std::string& line);                       // writes line + "\n"
    std::optional<std::string> request(const std::string& line); // send, then read one stdout line (synchronous mode)
    void close_input();                                        // EOF on the child's stdin
    void stop(unsigned grace_ms=5000);                         // EOF, wait, terminate if needed
    unsigned long pid() const {return pid_;}
private:
    bool read_some(std::string& into);                         // false at EOF or on error
#ifdef _WIN32
    HANDLE process_=nullptr,in_=nullptr,out_=nullptr;
#else
    pid_t process_=0;int in_=-1,out_=-1;mutable std::atomic<bool> exited_=false;
#endif
    unsigned long pid_=0;std::thread reader_;std::string buffer_;std::mutex write_;
};
}
