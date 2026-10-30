#pragma once
// Safe cross-device actions (docs/LENS_V1_SPEC.md §14; Milestone 13).
// A fixed, typed capability registry: each capability names its target device, side effects, parameters (validated
// here) and whether the user must confirm it on the laptop. Requests from devices or models only ever create a
// pending action; nothing executes until the user approves it in the Lens app, and approval cannot arrive over the
// network (lens-mesh does not forward it). A request not decided within the expiry (default 10 minutes) expires and can
// no longer be approved: an approval is always a fresh decision about a request the user has just seen. Every
// transition is reported to the caller for the audit memory.
#include <nlohmann/json.hpp>
#include <chrono>
#include <map>
#include <mutex>
#include <string>

namespace lens::agent {
class Actions {
public:
    Actions(bool test_capabilities,std::chrono::seconds expiry):test_(test_capabilities),expiry_(expiry) {}
    nlohmann::json capabilities() const;
    nlohmann::json request(const nlohmann::json& req);            // -> pending action or validation error
    nlohmann::json pending();
    nlohmann::json status(const std::string& id);
    nlohmann::json decide(const std::string& id,bool approve);    // executes on approval; returns final state
private:
    nlohmann::json execute(const std::string& capability,const nlohmann::json& params);
    void expire_locked();  // pending requests older than expiry_ become "expired"
    bool test_;std::chrono::seconds expiry_;std::mutex lock_;std::map<std::string,nlohmann::json> actions_;
    std::map<std::string,std::chrono::steady_clock::time_point> requested_;
};
}
