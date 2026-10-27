#pragma once
// A child process with piped stdin/stdout (JSON lines) and stderr discarded or forwarded. No console window.
#include <windows.h>
#include <functional>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>

namespace lens::agent {
class Child {
public:
    ~Child(){stop();}
    // Starts `exe args...`. on_line, when given, receives every stdout line on a reader thread; otherwise lines are
    // read synchronously with request().
    bool start(const std::wstring& exe,const std::vector<std::wstring>& args,std::function<void(const std::string&)> on_line={});
    bool running() const {return process_!=nullptr&&WaitForSingleObject(process_,0)==WAIT_TIMEOUT;}
    bool send(const std::string& line);                       // writes line + "\n"
    std::optional<std::string> request(const std::string& line); // send, then read one stdout line (synchronous mode)
    void close_input();                                        // EOF on the child's stdin
    void stop(DWORD grace_ms=5000);                            // EOF, wait, terminate if needed
    DWORD pid() const {return pid_;}
private:
    HANDLE process_=nullptr,in_=nullptr,out_=nullptr;DWORD pid_=0;std::thread reader_;std::string buffer_;std::mutex write_;
};
}
