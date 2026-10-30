#pragma once
// Operating-system services of lens-agent: the per-user data folder, one agent per user, the local endpoint that only
// the current user can open, the memory of the agent's process tree, and file hashes. Windows: a named pipe with a
// user-only DACL that rejects remote clients. Elsewhere: a Unix domain socket in a folder only the user can enter
// (0700, owner checked), every peer's user id checked on connect.
#include <nlohmann/json.hpp>
#include <filesystem>
#include <memory>
#include <string>

namespace lens::agent::os {
std::filesystem::path default_data_dir();  // Windows %LOCALAPPDATA%\Lens; Linux $XDG_DATA_HOME/lens; macOS ~/Library/Application Support/Lens
std::string user_name();
std::string sha256_file(const std::filesystem::path& p);  // lower-case hex; empty when unreadable
std::string sha256(const std::string& data);
void random_bytes(unsigned char* out,size_t n);  // the OS's cryptographic generator; aborts if it is unavailable
bool open_url(const std::string& url);           // default browser; the caller has validated the URL
nlohmann::json process_tree();  // [{name,pid,working_set,private}] for this process and every descendant

class SingleInstance {  // held for the life of the object; acquired() false when another agent holds `name`
public:
    explicit SingleInstance(const std::string& name);
    ~SingleInstance();
    SingleInstance(const SingleInstance&)=delete;SingleInstance& operator=(const SingleInstance&)=delete;
    bool acquired() const {return acquired_;}
private:
    bool acquired_=false;
#ifdef _WIN32
    void* handle_=nullptr;
#else
    int fd_=-1;
#endif
};

class Connection {  // one client; read/write block; cancel() from another thread unblocks them
public:
    virtual ~Connection()=default;
    virtual bool read_some(std::string& into)=0;  // false at end or on error
    virtual bool write(const std::string& data)=0;
    virtual void cancel()=0;
};

// A client connection to the agent's endpoint `name` (the app, CLI tools); nullptr when no agent is listening.
std::unique_ptr<Connection> connect(const std::string& name);

class Server {
public:
    Server();~Server();
    Server(const Server&)=delete;Server& operator=(const Server&)=delete;
    bool listen(const std::string& name);       // false when the endpoint cannot be created safely
    std::unique_ptr<Connection> accept();       // nullptr after interrupt() or on error
    void interrupt();                           // wakes a blocked accept (shutdown)
    std::string address() const {return address_;}
    std::string error() const {return error_;}
private:
    struct State;std::unique_ptr<State> s_;std::string address_,error_;
};
}
