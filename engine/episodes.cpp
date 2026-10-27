#include "episodes.hpp"
#include "sql.hpp"
#include <openssl/evp.h>
#include <iomanip>
#include <sstream>
#include <vector>

namespace lens {
using json=nlohmann::json;
using namespace sql;
namespace {
std::string episode_id(const std::string& first_source) {
    unsigned char out[EVP_MAX_MD_SIZE]{};size_t n{};
    if(!EVP_Q_digest(nullptr,"SHA256",nullptr,first_source.data(),first_source.size(),out,&n))throw Error("hash_failed");
    std::ostringstream s;s<<"ep-";for(size_t i=0;i<12;++i)s<<std::hex<<std::setfill('0')<<std::setw(2)<<static_cast<unsigned>(out[i]);return s.str();
}
std::string title_of(const std::string& locator){return locator.rfind("window:",0)==0?locator.substr(7):locator;}

json row(Statement& s) {
    return {{"id",s.text(0)},{"device",s.text(1)},{"application",s.text(2)},{"title",s.text(3)},{"started_at",s.text(4)},
            {"ended_at",s.text(5)},{"duration_seconds",sqlite3_column_int64(s.p,7)-sqlite3_column_int64(s.p,6)},
            {"observation_count",sqlite3_column_int64(s.p,8)},{"first_source_id",s.text(9)},{"last_source_id",s.text(10)}};
}
const char* episode_columns="SELECT id,device,application,title,started_at,ended_at,start_seconds,end_seconds,observation_count,first_source_id,last_source_id FROM episodes ";
}

json consolidate_episodes(sqlite3* db,const json& j) {
    const long long gap=j.value("gap_seconds",600LL);
    if(gap<10||gap>86400)throw Error("invalid_request");
    Transaction tx(db);
    exec(db,"DELETE FROM episode_members; DELETE FROM episodes;");
    struct Current {std::string device,app,locator,first,last,started,ended;long long start=0,end=0,count=0;std::vector<std::string> members;};
    Current cur;size_t episodes=0,members=0;
    Statement ins(db,"INSERT INTO episodes(id,device,application,locator,title,started_at,ended_at,start_seconds,end_seconds,observation_count,first_source_id,last_source_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?);");
    Statement mem(db,"INSERT INTO episode_members(episode_id,source_id) VALUES(?,?);");
    auto flush=[&] {
        if(!cur.count)return;
        const auto id=episode_id(cur.first);
        sqlite3_reset(ins.p);ins.text(1,id);ins.text(2,cur.device);ins.text(3,cur.app);ins.text(4,cur.locator);ins.text(5,title_of(cur.locator));
        ins.text(6,cur.started);ins.text(7,cur.ended);check(sqlite3_bind_int64(ins.p,8,cur.start));check(sqlite3_bind_int64(ins.p,9,cur.end));
        check(sqlite3_bind_int64(ins.p,10,cur.count));ins.text(11,cur.first);ins.text(12,cur.last);ins.step();
        for(const auto& m:cur.members){sqlite3_reset(mem.p);mem.text(1,id);mem.text(2,m);mem.step();}
        ++episodes;members+=cur.members.size();cur=Current{};
    };
    Statement s(db,"SELECT o.id,o.device,m.source_application,m.source_locator,m.event_key,m.event_seconds FROM observations o "
                   "JOIN source_metadata m ON m.source_id=o.id WHERE m.event_seconds IS NOT NULL "
                   "ORDER BY o.device,m.source_application,m.source_locator,m.event_seconds,o.id;");
    while(s.step()==SQLITE_ROW) {
        const auto id=s.text(0),device=s.text(1),app=s.text(2),locator=s.text(3),when=s.text(4);const long long t=sqlite3_column_int64(s.p,5);
        if(cur.count&&(device!=cur.device||app!=cur.app||locator!=cur.locator||t-cur.end>gap))flush();
        if(!cur.count){cur.device=device;cur.app=app;cur.locator=locator;cur.first=id;cur.started=when;cur.start=t;}
        cur.last=id;cur.ended=when;cur.end=t;++cur.count;cur.members.push_back(id);
    }
    flush();tx.commit();
    return {{"ok",true},{"episodes",episodes},{"members",members},{"gap_seconds",gap}};
}

json list_episodes(sqlite3* db,const json& j) {
    const int limit=j.value("limit",25);if(limit<1||limit>200)throw Error("invalid_limit");
    std::string where="WHERE 1=1";std::vector<std::string> values;
    if(j.contains("start")){where+=" AND end_seconds>=?";values.push_back(std::to_string(epoch(required(j,"start",64))));}
    if(j.contains("end")){where+=" AND start_seconds<?";values.push_back(std::to_string(epoch(required(j,"end",64))));}
    if(j.contains("application")){where+=" AND application=?";values.push_back(required(j,"application",256));}
    Statement s(db,(std::string(episode_columns)+where+" ORDER BY start_seconds DESC,id LIMIT "+std::to_string(limit)+";").c_str());
    for(size_t i=0;i<values.size();++i)s.text(static_cast<int>(i+1),values[i]);
    json out=json::array();while(s.step()==SQLITE_ROW)out.push_back(row(s));
    return {{"ok",true},{"episodes",out},{"not_found",out.empty()}};
}

json episode_of(sqlite3* db,const std::string& source_id) {
    Statement s(db,(std::string(episode_columns)+"WHERE id=(SELECT episode_id FROM episode_members WHERE source_id=?);").c_str());
    s.text(1,source_id);
    if(s.step()==SQLITE_ROW)return row(s);
    return nullptr;
}

json episode_context(sqlite3* db,const json& j) {
    const auto source_id=required(j,"source_id");
    const auto ep=episode_of(db,source_id);
    if(ep.is_null())return {{"ok",true},{"not_found",true},{"episode",nullptr}};
    auto neighbour=[&](const char* cmp,const char* order) {
        Statement s(db,(std::string(episode_columns)+"WHERE device=? AND start_seconds"+cmp+"(SELECT start_seconds FROM episodes WHERE id=?) AND id<>? ORDER BY start_seconds "+order+",id LIMIT 1;").c_str());
        s.text(1,ep.at("device").get<std::string>());s.text(2,ep.at("id").get<std::string>());s.text(3,ep.at("id").get<std::string>());
        return s.step()==SQLITE_ROW?row(s):json(nullptr);
    };
    return {{"ok",true},{"not_found",false},{"episode",ep},{"previous",neighbour("<=","DESC")},{"next",neighbour(">=","ASC")}};
}
}
