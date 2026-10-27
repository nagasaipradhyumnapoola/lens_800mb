#include "user_memory.hpp"
#include "sql.hpp"
#include "temporal.hpp"
#include <openssl/evp.h>
#include <algorithm>
#include <cctype>
#include <chrono>
#include <iomanip>
#include <map>
#include <set>
#include <sstream>

namespace lens {
using json=nlohmann::json;
using namespace sql;
namespace {
std::string now_iso(){return iso_utc(std::chrono::floor<std::chrono::seconds>(std::chrono::system_clock::now()));}
std::string sha_hex(const std::string& text,std::size_t bytes=32) {
    unsigned char out[EVP_MAX_MD_SIZE]{};size_t n{};
    if(!EVP_Q_digest(nullptr,"SHA256",nullptr,text.data(),text.size(),out,&n))throw Error("hash_failed");
    std::ostringstream s;for(size_t i=0;i<std::min(n,bytes);++i)s<<std::hex<<std::setfill('0')<<std::setw(2)<<static_cast<unsigned>(out[i]);return s.str();
}
// Feedback applies to the same question however it is spaced or cased; only this hash is stored.
std::string query_key(const std::string& q) {
    std::string n;bool space=false;
    for(char c:q){const auto u=static_cast<unsigned char>(c);if(u<0x80&&std::isspace(u)){space=!n.empty();continue;}
        if(space){n+=' ';space=false;}n+=static_cast<char>(u<0x80?std::tolower(u):u);}
    return sha_hex(n);
}
bool source_exists(sqlite3* db,const std::string& id){Statement s(db,"SELECT 1 FROM observations WHERE id=?;");s.text(1,id);return s.step()==SQLITE_ROW;}
json brief_entity(sqlite3* db,const std::string& id) {
    if(id.empty())return nullptr;
    Statement s(db,"SELECT id,type,name FROM entities WHERE id=?;");s.text(1,id);
    return s.step()==SQLITE_ROW?json{{"id",s.text(0)},{"type",s.text(1)},{"name",s.text(2)}}:json(nullptr);
}
std::size_t char_floor(const std::string& s,std::size_t i){i=std::min(i,s.size());while(i>0&&i<s.size()&&(static_cast<unsigned char>(s[i])&0xC0)==0x80)--i;return i;}
json user_fact_row(sqlite3* db,Statement& s) {  // id,type,predicate,subject_id,value,value_seconds,statement,created_at,supersedes,supersedes_sources
    json value_date=nullptr;
    if(sqlite3_column_type(s.p,5)!=SQLITE_NULL)value_date=iso_utc(std::chrono::sys_seconds{std::chrono::seconds{sqlite3_column_int64(s.p,5)}}).substr(0,10);
    json superseded_sources=json::array();try{superseded_sources=json::parse(s.text(9));}catch(...){}
    return {{"id",s.text(0)},{"type",s.text(1)},{"predicate",s.text(2)},{"subject",brief_entity(db,s.text(3))},{"object_entity",nullptr},
            {"value",s.text(4).empty()?json(nullptr):json(s.text(4))},{"value_date",value_date},{"statement",s.text(6)},{"status","user_stated"},
            {"user_status",nullptr},{"certain",true},{"subject_basis","user"},{"sources",json::array()},{"source_count",0},{"object",s.text(6)},
            {"first_seen",s.text(7)},{"last_seen",s.text(7)},{"derived",false},
            {"provenance",{{"kind","user_correction"},{"created_at",s.text(7)},{"supersedes",s.text(8).empty()?json(nullptr):json(s.text(8))},
                           {"supersedes_sources",superseded_sources}}}};
}
const char* user_fact_columns="SELECT id,type,predicate,subject_id,value,value_seconds,statement,created_at,coalesce(supersedes,''),supersedes_sources FROM user_facts ";
}  // namespace

json user_memory_op(sqlite3* db,const std::string& op,const json& j) {
    if(op=="pin") {
        const auto id=required(j,"source_id");if(!source_exists(db,id))throw Error("source_not_found");
        const auto note=j.contains("note")?validated_string(j.at("note").get<std::string>(),500,true):std::string();
        Statement s(db,"INSERT OR REPLACE INTO pins(source_id,pinned_at,note) VALUES(?,?,?);");s.text(1,id);s.text(2,now_iso());s.text(3,note);s.step();
        return {{"ok",true},{"pinned",id}};
    }
    if(op=="unpin") {
        Statement s(db,"DELETE FROM pins WHERE source_id=?;");s.text(1,required(j,"source_id"));s.step();return {{"ok",true},{"unpinned",sqlite3_changes(db)}};
    }
    if(op=="pins") {
        const int limit=j.contains("limit")?j.at("limit").get<int>():50;if(limit<1||limit>500)throw Error("invalid_limit");
        Statement s(db,("SELECT p.source_id,p.pinned_at,p.note,o.captured_at,m.source_application,lens_text(o.text,o.text_codec,o.text_zstd) FROM pins p "
                        "JOIN observations o ON o.id=p.source_id JOIN source_metadata m ON m.source_id=o.id ORDER BY p.pinned_at DESC,p.source_id LIMIT "+std::to_string(limit)+";").c_str());
        json out=json::array();
        while(s.step()==SQLITE_ROW){const auto t=s.text(5);out.push_back({{"source_id",s.text(0)},{"pinned_at",s.text(1)},{"note",s.text(2)},{"timestamp",s.text(3)},
            {"source_application",s.text(4)},{"excerpt",t.substr(0,char_floor(t,200))}});}
        return {{"ok",true},{"pins",out},{"not_found",out.empty()}};
    }
    if(op=="feedback") {
        const auto q=required(j,"query",1024),id=required(j,"source_id");if(!source_exists(db,id))throw Error("source_not_found");
        if(!j.contains("relevant")||!j["relevant"].is_boolean())throw Error("invalid_request");
        Statement s(db,"INSERT OR REPLACE INTO recall_feedback(query_key,source_id,signal,at) VALUES(?,?,?,?);");
        s.text(1,query_key(q));s.text(2,id);check(sqlite3_bind_int(s.p,3,j["relevant"].get<bool>()?1:-1));s.text(4,now_iso());s.step();
        return {{"ok",true},{"source_id",id},{"signal",j["relevant"].get<bool>()?1:-1}};
    }
    if(op=="correct_fact") {
        const auto fact_id=required(j,"fact_id",64);const auto action=j.contains("action")?required(j,"action",16):std::string("correct");
        if(action!="correct"&&action!="reject"&&action!="confirm")throw Error("invalid_request");
        std::string type,predicate,subject,value;
        {Statement f(db,"SELECT type,predicate,coalesce(subject_id,''),value FROM facts WHERE id=?;");f.text(1,fact_id);
         if(f.step()!=SQLITE_ROW)throw Error("fact_not_found");type=f.text(0);predicate=f.text(1);subject=f.text(2);value=f.text(3);}
        Transaction tx(db);const auto at=now_iso();json user_fact=nullptr;
        if(action=="correct") {
            const auto statement=required(j,"statement",2000);
            if(j.contains("value"))value=validated_string(j.at("value").get<std::string>(),256,true);
            json seconds=nullptr;
            if(type=="deadline"||type=="meeting") {  // a corrected date must be a date
                if(value.size()!=10)throw Error("invalid_value");seconds=epoch(value+"T00:00:00Z");
            }
            json sources=json::array();
            {Statement s(db,"SELECT source_id FROM fact_sources WHERE fact_id=? ORDER BY source_id;");s.text(1,fact_id);while(s.step()==SQLITE_ROW)sources.push_back(s.text(0));}
            const auto id="uf-"+sha_hex(fact_id+"|"+value+"|"+statement+"|"+at,12);
            Statement ins(db,"INSERT INTO user_facts(id,type,predicate,subject_id,value,value_seconds,statement,created_at,supersedes,supersedes_sources) VALUES(?,?,?,?,?,?,?,?,?,?);");
            ins.text(1,id);ins.text(2,type);ins.text(3,predicate);if(subject.empty())check(sqlite3_bind_null(ins.p,4));else ins.text(4,subject);
            ins.text(5,value);if(seconds.is_null())check(sqlite3_bind_null(ins.p,6));else check(sqlite3_bind_int64(ins.p,6,seconds.get<long long>()));
            ins.text(7,statement);ins.text(8,at);ins.text(9,fact_id);ins.text(10,sources.dump());ins.step();
            Statement st(db,"INSERT OR REPLACE INTO fact_status(fact_id,status,user_fact_id,at) VALUES(?,'superseded',?,?);");st.text(1,fact_id);st.text(2,id);st.text(3,at);st.step();
            Statement row(db,(std::string(user_fact_columns)+"WHERE id=?;").c_str());row.text(1,id);row.step();user_fact=user_fact_row(db,row);
        } else {
            Statement st(db,"INSERT OR REPLACE INTO fact_status(fact_id,status,user_fact_id,at) VALUES(?,?,NULL,?);");
            st.text(1,fact_id);st.text(2,action=="reject"?"rejected":"confirmed");st.text(3,at);st.step();
        }
        tx.commit();
        return {{"ok",true},{"fact_id",fact_id},{"status",action=="correct"?"superseded":action=="reject"?"rejected":"confirmed"},{"user_fact",user_fact}};
    }
    throw Error("unsupported_operation");
}

json user_facts_for(sqlite3* db,const std::vector<std::string>& entity_ids,const std::string& type) {
    std::string where="WHERE 1=1";std::vector<std::string> values;
    if(!entity_ids.empty()){std::string in;for(const auto& id:entity_ids){in+=in.empty()?"?":",?";values.push_back(id);}where+=" AND subject_id IN ("+in+")";}
    if(!type.empty()){where+=" AND type=?";values.push_back(type);}
    Statement s(db,(std::string(user_fact_columns)+where+" ORDER BY created_at DESC,id LIMIT 100;").c_str());
    for(std::size_t i=0;i<values.size();++i)s.text(static_cast<int>(i+1),values[i]);
    json out=json::array();while(s.step()==SQLITE_ROW)out.push_back(user_fact_row(db,s));return out;
}

void annotate_facts(sqlite3* db,json& facts) {
    Statement st(db,"SELECT status,coalesce(user_fact_id,''),at FROM fact_status WHERE fact_id=?;");
    for(auto& f:facts) {
        if(!f.contains("id")||f["status"]=="user_stated")continue;
        sqlite3_reset(st.p);st.text(1,f["id"].get<std::string>());
        if(st.step()==SQLITE_ROW){f["user_status"]=st.text(0);f["superseded_by"]=st.text(1).empty()?json(nullptr):json(st.text(1));f["user_status_at"]=st.text(2);}
        else{f["user_status"]=nullptr;f["superseded_by"]=nullptr;}
    }
    // L6 latest vs superseded: among facts of one kind about one subject (a deadline of Orion, its budget), the most
    // recently evidenced one is current; corrected or rejected facts are never current.
    std::map<std::string,std::pair<std::string,std::size_t>> latest;
    auto group=[](const json& f)->std::string{
        const auto type=f.value("type",std::string());
        if((type!="deadline"&&type!="meeting"&&type!="amount")||!f["subject"].is_object())return {};
        return type+"|"+f.value("predicate",std::string())+"|"+f["subject"].value("id",std::string());
    };
    auto inactive=[](const json& f){const auto s=f.value("user_status",json(nullptr));return s=="superseded"||s=="rejected";};
    for(std::size_t i=0;i<facts.size();++i) {
        const auto& f=facts[i];const auto g=group(f);if(g.empty()||inactive(f))continue;
        const auto when=f["last_seen"].is_string()?f["last_seen"].get<std::string>():std::string();
        auto it=latest.find(g);if(it==latest.end()||when>it->second.first)latest[g]={when,i};
    }
    for(std::size_t i=0;i<facts.size();++i) {
        auto& f=facts[i];const auto g=group(f);
        if(inactive(f)){f["current"]=false;continue;}
        if(g.empty()){f["current"]=true;continue;}
        const auto w=latest[g].second;f["current"]=w==i;
        if(w!=i)f["superseded_by_later"]=facts[w]["id"];
    }
}

void apply_user_signals(sqlite3* db,const std::string& question,json& result,bool enabled) {
    if(!result.contains("results")||!result["results"].is_array())return;
    const auto key=query_key(question);
    Statement pin(db,"SELECT 1 FROM pins WHERE source_id=?;");Statement fb(db,"SELECT signal FROM recall_feedback WHERE query_key=? AND source_id=?;");
    auto& results=result["results"];std::vector<std::pair<int,json>> ranked;
    for(auto& r:results) {
        if(!r.contains("source")||!r["source"].contains("id")){ranked.emplace_back(2,r);continue;}
        const auto sid=r["source"]["id"].get<std::string>();
        sqlite3_reset(pin.p);pin.text(1,sid);const bool pinned=pin.step()==SQLITE_ROW;
        sqlite3_reset(fb.p);fb.text(1,key);fb.text(2,sid);const int signal=fb.step()==SQLITE_ROW?sqlite3_column_int(fb.p,0):0;
        r["pinned"]=pinned;r["feedback"]=signal;
        ranked.emplace_back(signal>0?0:signal<0?3:pinned?1:2,r);
    }
    bool reordered=false;
    if(enabled) {
        std::stable_sort(ranked.begin(),ranked.end(),[](const auto& a,const auto& b){return a.first<b.first;});
        json out=json::array();for(auto& [rank,r]:ranked)out.push_back(std::move(r));
        reordered=out!=results;results=std::move(out);
    }
    result["user_signals_applied"]=reordered;
}
}
