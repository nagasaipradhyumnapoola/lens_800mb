#include "actions.hpp"
#include "os.hpp"
#include <chrono>
#include <ctime>
#include <regex>

namespace lens::agent {
using json=nlohmann::json;
namespace {
std::string random_id() {
    unsigned char b[12];os::random_bytes(b,sizeof b);
    static const char* h="0123456789abcdef";std::string s="act-";for(unsigned char c:b){s+=h[c>>4];s+=h[c&15];}return s;
}
std::string now_iso() {  // UTC with milliseconds
    const auto now=std::chrono::system_clock::now();const std::time_t t=std::chrono::system_clock::to_time_t(now);
    const auto ms=std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count()%1000;std::tm u{};
#ifdef _WIN32
    gmtime_s(&u,&t);
#else
    gmtime_r(&t,&u);
#endif
    char b[40];std::strftime(b,sizeof b,"%Y-%m-%dT%H:%M:%S",&u);char out[48];snprintf(out,sizeof out,"%s.%03dZ",b,static_cast<int>(ms));return out;
}

// Only absolute https URLs without credentials, control characters or whitespace.
bool safe_url(const std::string& u) {
    static const std::regex ok(R"(^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[^\s"<>\\^`{|}]*)?$)");
    return u.size()<=2048&&std::regex_match(u,ok)&&u.find('@')==std::string::npos;
}
}

json Actions::capabilities() const {
    json caps=json::array({
        {{"id","laptop.open_url"},{"device","laptop"},{"side_effects","opens a web page in the default browser"},{"confirmation","required"},
         {"parameters",{{"url","absolute https URL, no credentials"}}}},
        {{"id","laptop.remember"},{"device","laptop"},{"side_effects","adds a memory"},{"confirmation","required"},
         {"parameters",{{"text","1-20000 characters"}}}}});
    if(test_)caps.push_back({{"id","test.echo"},{"device","laptop"},{"side_effects","none (test only)"},{"confirmation","required"},{"parameters",{{"message","text"}}}});
    return {{"ok",true},{"capabilities",caps}};
}

json Actions::request(const json& req) {
    const auto cap=req.value("capability",std::string());const auto params=req.value("params",json::object());
    const auto by=req.value("requested_by",std::string("unknown")).substr(0,64);
    if(!params.is_object())return {{"ok",false},{"error","invalid_parameters"}};
    if(cap=="laptop.open_url"){if(!params.contains("url")||!params["url"].is_string()||!safe_url(params["url"]))return {{"ok",false},{"error","invalid_parameters"}};}
    else if(cap=="laptop.remember"){if(!params.contains("text")||!params["text"].is_string()||params["text"].get<std::string>().empty()||params["text"].get<std::string>().size()>20000)return {{"ok",false},{"error","invalid_parameters"}};}
    else if(cap=="test.echo"&&test_){if(!params.contains("message")||!params["message"].is_string())return {{"ok",false},{"error","invalid_parameters"}};}
    else return {{"ok",false},{"error","unknown_capability"}};
    std::lock_guard g(lock_);
    size_t open=0;for(const auto& [_,a]:actions_)if(a["status"]=="pending_confirmation")++open;
    if(open>=20)return {{"ok",false},{"error","too_many_pending_actions"}};
    const auto id=random_id();
    actions_[id]={{"id",id},{"capability",cap},{"params",params},{"requested_by",by},{"status","pending_confirmation"},{"requested_utc",now_iso()}};
    return {{"ok",true},{"action",actions_[id]}};
}

json Actions::pending() {
    std::lock_guard g(lock_);json out=json::array();
    for(const auto& [_,a]:actions_)if(a["status"]=="pending_confirmation")out.push_back(a);
    return {{"ok",true},{"actions",out}};
}

json Actions::status(const std::string& id) {
    std::lock_guard g(lock_);const auto it=actions_.find(id);
    if(it==actions_.end())return {{"ok",false},{"error","unknown_action"}};
    return {{"ok",true},{"action",it->second}};
}

json Actions::decide(const std::string& id,bool approve) {
    json action;
    {std::lock_guard g(lock_);const auto it=actions_.find(id);
     if(it==actions_.end())return {{"ok",false},{"error","unknown_action"}};
     if(it->second["status"]!="pending_confirmation")return {{"ok",false},{"error","already_decided"},{"action",it->second}};
     if(!approve){it->second["status"]="denied";it->second["decided_utc"]=now_iso();return {{"ok",true},{"action",it->second}};}
     it->second["status"]="executing";it->second["decided_utc"]=now_iso();action=it->second;}
    const auto result=execute(action["capability"],action["params"]);
    std::lock_guard g(lock_);auto& a=actions_[id];
    a["status"]=result.value("ok",false)?"executed":"failed";a["result"]=result;a["finished_utc"]=now_iso();
    return {{"ok",true},{"action",a}};
}

json Actions::execute(const std::string& cap,const json& params) {
    if(cap=="test.echo")return {{"ok",true},{"verified",true},{"echo",params["message"]}};
    if(cap=="laptop.open_url") {
        const auto url=params["url"].get<std::string>();if(!safe_url(url))return {{"ok",false},{"error","invalid_parameters"}};
        const bool ok=os::open_url(url);
        return {{"ok",ok},{"verified",ok}};
    }
    if(cap=="laptop.remember")return {{"ok",true},{"memory",{{"text",params["text"]}}}};  // the agent stores it (needs the engine)
    return {{"ok",false},{"error","unknown_capability"}};
}
}
