#pragma once
#include "input.hpp"
#include <sqlcipher/sqlite3.h>
#include <nlohmann/json.hpp>
#include <chrono>
#include <iomanip>
#include <regex>
#include <sstream>
#include <string>
namespace lens::sql {
inline void check(int code){if(code!=SQLITE_OK&&code!=SQLITE_DONE&&code!=SQLITE_ROW)throw Error("database_operation_failed");}
inline void exec(sqlite3* db,const char* text){check(sqlite3_exec(db,text,nullptr,nullptr,nullptr));}
struct Statement {
    sqlite3_stmt* p{};
    Statement(sqlite3* db,const char* text){check(sqlite3_prepare_v2(db,text,-1,&p,nullptr));}
    ~Statement(){sqlite3_finalize(p);}
    Statement(const Statement&)=delete;
    void text(int i,const std::string& s){check(sqlite3_bind_text(p,i,s.data(),static_cast<int>(s.size()),SQLITE_TRANSIENT));}
    std::string text(int i)const{auto s=sqlite3_column_text(p,i);return s?reinterpret_cast<const char*>(s):"";}
    int step(){int r=sqlite3_step(p);check(r);return r;}
};
struct Transaction {
    sqlite3* db;bool own,done=false;
    explicit Transaction(sqlite3* value):db(value),own(sqlite3_get_autocommit(value)!=0){if(own)exec(db,"BEGIN IMMEDIATE;");}
    ~Transaction(){if(own&&!done)sqlite3_exec(db,"ROLLBACK;",nullptr,nullptr,nullptr);}
    void commit(){if(own)exec(db,"COMMIT;");done=true;}
};
inline std::string required(const nlohmann::json& j,const char* name,size_t max=1024){
    if(!j.contains(name)||!j[name].is_string())throw Error("invalid_request");
    return validated_string(j[name].get<std::string>(),max);
}
inline std::string optional(const nlohmann::json& j,const char* name,size_t max=1024){
    if(!j.contains(name))return "";
    return validated_string(j.at(name).get<std::string>(),max,true);
}
struct Instant {std::chrono::sys_seconds whole;std::string fraction;};
inline Instant parse_time(const std::string& value){
    static const std::regex iso(R"(^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$)");
    std::smatch m;if(!std::regex_match(value,m,iso))throw Error("invalid_timestamp");
    const auto number=[&](int n){return std::stoi(m[n].str());};
    using namespace std::chrono;
    year_month_day date{year{number(1)},month{static_cast<unsigned>(number(2))},day{static_cast<unsigned>(number(3))}};
    if(!date.ok()||number(4)>23||number(5)>59||number(6)>59)throw Error("invalid_timestamp");
    const auto zone=m[8].str();int offset=0;
    if(zone!="Z"){
        int h=std::stoi(zone.substr(1,2)),min=std::stoi(zone.substr(4,2));
        if(h>14||min>59||(h==14&&min))throw Error("invalid_timestamp");
        offset=(h*60+min)*(zone[0]=='-'?-1:1);
    }
    auto fraction=m[7].str();fraction.resize(9,'0');
    return {sys_days{date}+hours{number(4)}+minutes{number(5)}+seconds{number(6)}-minutes{offset},fraction};
}
inline std::int64_t epoch(const std::string& value){return parse_time(value).whole.time_since_epoch().count();}
inline std::string instant(const std::string& value){
    using namespace std::chrono;const auto parsed=parse_time(value);const auto day=floor<days>(parsed.whole);
    const year_month_day date{day};const hh_mm_ss time{parsed.whole-day};
    if(static_cast<int>(date.year())<1||static_cast<int>(date.year())>9999)throw Error("invalid_timestamp");
    std::ostringstream out;out<<std::setfill('0')<<std::setw(4)<<static_cast<int>(date.year())<<'-'<<std::setw(2)
        <<static_cast<unsigned>(date.month())<<'-'<<std::setw(2)<<static_cast<unsigned>(date.day())<<'T'
        <<std::setw(2)<<time.hours().count()<<':'<<std::setw(2)<<time.minutes().count()<<':'<<std::setw(2)<<time.seconds().count()
        <<'.'<<parsed.fraction<<'Z';return out.str();
}
inline nlohmann::json source(Statement& s){
    using json=nlohmann::json;
    return {{"id",s.text(0)},{"text",s.text(1)},{"language",s.text(2)},{"timestamp",s.text(3)},
        {"device",s.text(4)},{"kind",s.text(5)},{"provenance",s.text(6)},{"sha256",s.text(7)},
        {"confidence",sqlite3_column_double(s.p,8)},
        {"original_timestamp",sqlite3_column_type(s.p,9)==SQLITE_NULL?json(nullptr):json(s.text(9))},
        {"observed_at",s.text(10)},{"timezone",s.text(11)},{"source_application",s.text(12)},
        {"source_locator",s.text(13)},{"consent_context",json::parse(s.text(14))},
        {"metadata",json::parse(s.text(15))},{"model_version",s.text(16)},{"version",1}};
}
// Observation text is read through lens_text() (schema v6 compression, engine/text_codec.hpp).
inline const std::string columns="SELECT o.id,lens_text(o.text,o.text_codec,o.text_zstd),o.language,o.captured_at,o.device,o.kind,o.provenance,o.sha256,o.confidence,m.original_timestamp,m.observed_at,m.timezone,m.source_application,m.source_locator,m.consent_context,m.metadata,m.model_version ";
// Before schema v6 (used only by older migrations).
inline const std::string legacy_columns="SELECT o.id,o.text,o.language,o.captured_at,o.device,o.kind,o.provenance,o.sha256,o.confidence,m.original_timestamp,m.observed_at,m.timezone,m.source_application,m.source_locator,m.consent_context,m.metadata,m.model_version ";
inline const std::string tables=" FROM observations o JOIN source_metadata m ON m.source_id=o.id ";
}
