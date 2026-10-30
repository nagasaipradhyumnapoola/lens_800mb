#pragma once
// The Linux and macOS app hosts' link to lens-agent: one connection to the agent's user-only endpoint, one request at a
// time (the agent answers in order), reconnecting — and starting the agent, detached, when it is not running.
#include "../agent/os.hpp"
#include "../platform.hpp"
#include <nlohmann/json.hpp>
#include <chrono>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>
#include <fcntl.h>
#include <spawn.h>
extern char** environ;

namespace lens::app {
class AgentClient {
public:
    explicit AgentClient(std::string pipe):pipe_(std::move(pipe)){}
    nlohmann::json ask(const nlohmann::json& request) {
        std::lock_guard g(lock_);
        for(int attempt=0;attempt<2;++attempt) {
            if(!c_)c_=agent::os::connect(pipe_);
            if(!c_) {
                start_agent();
                for(int i=0;i<150&&!c_;++i){std::this_thread::sleep_for(std::chrono::milliseconds(100));c_=agent::os::connect(pipe_);}
                if(!c_)return {{"ok",false},{"error","agent_unavailable"}};
            }
            if(c_->write(request.dump()+"\n")) {
                size_t pos;
                while((pos=buf_.find('\n'))==std::string::npos)if(!c_->read_some(buf_))break;
                if((pos=buf_.find('\n'))!=std::string::npos){auto line=buf_.substr(0,pos);buf_.erase(0,pos+1);return nlohmann::json::parse(line,nullptr,false);}
            }
            c_.reset();buf_.clear();  // the agent went away: reconnect (or start it) once
        }
        return {{"ok",false},{"error","agent_unavailable"}};
    }
private:
    void start_agent() {  // detached, in its own session: it outlives the window (closing the app frees only the app)
        const auto agent=platform::sibling("lens-agent").string();
        std::vector<char*> argv{const_cast<char*>(agent.c_str()),const_cast<char*>("--pipe-name"),const_cast<char*>(pipe_.c_str()),nullptr};
        posix_spawn_file_actions_t fa;posix_spawn_file_actions_init(&fa);
        for(int fd=0;fd<3;++fd)posix_spawn_file_actions_addopen(&fa,fd,"/dev/null",fd?O_WRONLY:O_RDONLY,0);
        posix_spawnattr_t attr;posix_spawnattr_init(&attr);posix_spawnattr_setflags(&attr,POSIX_SPAWN_SETSID);
        pid_t pid=0;posix_spawn(&pid,agent.c_str(),&fa,&attr,argv.data(),environ);
        posix_spawn_file_actions_destroy(&fa);posix_spawnattr_destroy(&attr);
    }
    std::string pipe_;std::mutex lock_;std::unique_ptr<agent::os::Connection> c_;std::string buf_;
};
}
