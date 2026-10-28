#include "lifecycle.hpp"
#include "memory_layers.hpp"
#include "sql.hpp"
#include "temporal.hpp"
#include "../adapters/windows/key_store.hpp"
#include <windows.h>
#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <chrono>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <set>
#include <sstream>

namespace lens {
using json=nlohmann::json;
using namespace sql;
namespace {
constexpr std::size_t max_scope_ids=1000;
std::string now_iso(){return iso_utc(std::chrono::floor<std::chrono::seconds>(std::chrono::system_clock::now()));}
std::string hex(const unsigned char* p,std::size_t n){std::ostringstream s;for(std::size_t i=0;i<n;++i)s<<std::hex<<std::setfill('0')<<std::setw(2)<<static_cast<unsigned>(p[i]);return s.str();}
std::string file_sha256(const std::filesystem::path& path) {
    std::ifstream in(path,std::ios::binary);if(!in)throw Error("file_unavailable");
    std::unique_ptr<EVP_MD_CTX,decltype(&EVP_MD_CTX_free)> ctx(EVP_MD_CTX_new(),EVP_MD_CTX_free);
    if(!ctx||!EVP_DigestInit_ex(ctx.get(),EVP_sha256(),nullptr))throw Error("hash_failed");
    std::vector<char> buf(1<<16);
    while(in){in.read(buf.data(),static_cast<std::streamsize>(buf.size()));if(in.gcount()>0&&!EVP_DigestUpdate(ctx.get(),buf.data(),static_cast<size_t>(in.gcount())))throw Error("hash_failed");}
    unsigned char out[EVP_MAX_MD_SIZE];unsigned n=0;if(!EVP_DigestFinal_ex(ctx.get(),out,&n))throw Error("hash_failed");
    return hex(out,n);
}
// A path the user chose for a new file: absolute, not yet existing, in an existing directory.
std::filesystem::path new_file(const json& j,const char* name) {
    const auto path=utf8_path(required(j,name,4096));
    std::error_code ec;
    if(!path.is_absolute()||std::filesystem::exists(path,ec)||!std::filesystem::is_directory(path.parent_path(),ec))throw Error("invalid_path");
    return path;
}
std::filesystem::path existing_file(const json& j,const char* name) {
    const auto path=utf8_path(required(j,name,4096));std::error_code ec;
    if(!path.is_absolute()||!std::filesystem::is_regular_file(path,ec))throw Error("invalid_path");
    return path;
}
std::filesystem::path with_suffix(std::filesystem::path p,const wchar_t* suffix){p+=suffix;return p;}
void write_new_file(const std::filesystem::path& path,const std::string& data) {
    HANDLE f=CreateFileW(path.c_str(),GENERIC_WRITE,0,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);
    if(f==INVALID_HANDLE_VALUE)throw Error("file_write_failed");
    DWORD written=0;const bool ok=WriteFile(f,data.data(),static_cast<DWORD>(data.size()),&written,nullptr)&&written==data.size()&&FlushFileBuffers(f);
    CloseHandle(f);if(!ok){std::error_code ec;std::filesystem::remove(path,ec);throw Error("file_write_failed");}
}
void remove_quietly(const std::filesystem::path& p){std::error_code ec;std::filesystem::remove(p,ec);}
void remove_database_files(const std::filesystem::path& p) {
    for(const wchar_t* s:{L"",L"-journal",L"-wal",L"-shm"})remove_quietly(with_suffix(p,s));
}
// ATTACH with a key: the 32 key bytes are bound as a blob, exactly as the main database is keyed (sqlite3_key), or the
// user's passphrase as text (SQLCipher derives the page key with its KDF).
void attach(sqlite3* db,const std::filesystem::path& path,const char* alias,const void* key,int key_size,bool text_key) {
    const auto u8=path.u8string();
    Statement s(db,(std::string("ATTACH DATABASE ? AS ")+alias+" KEY ?;").c_str());
    check(sqlite3_bind_text(s.p,1,reinterpret_cast<const char*>(u8.c_str()),static_cast<int>(u8.size()),SQLITE_TRANSIENT));
    if(text_key)check(sqlite3_bind_text(s.p,2,static_cast<const char*>(key),key_size,SQLITE_TRANSIENT));
    else check(sqlite3_bind_blob(s.p,2,key,key_size,SQLITE_TRANSIENT));
    s.step();
}
void detach(sqlite3* db,const char* alias){sqlite3_exec(db,(std::string("DETACH DATABASE ")+alias+";").c_str(),nullptr,nullptr,nullptr);}
int user_version(sqlite3* db,const char* alias) {
    Statement s(db,(std::string("PRAGMA ")+alias+".user_version;").c_str());
    if(s.step()!=SQLITE_ROW)throw Error("backup_key_invalid");return sqlite3_column_int(s.p,0);
}
// HMAC of every page (SQLCipher) and SQLite's structural check; any failure means the file is not a sound backup.
void verify(sqlite3* db,const char* alias,const char* failure) {
    try {
        {Statement c(db,(std::string("PRAGMA ")+alias+".cipher_integrity_check;").c_str());if(c.step()==SQLITE_ROW)throw Error(failure);}
        Statement i(db,(std::string("PRAGMA ")+alias+".integrity_check;").c_str());
        if(i.step()!=SQLITE_ROW||i.text(0)!="ok")throw Error(failure);
    } catch(const Error& e){if(std::string(e.what())=="database_operation_failed")throw Error(failure);throw;}
}
long long count_sources(sqlite3* db,const char* alias) {
    Statement s(db,(std::string("SELECT count(*) FROM ")+alias+".observations;").c_str());s.step();return sqlite3_column_int64(s.p,0);
}
}  // namespace

void fault_point(const char* name) {
    char value[64]{};const DWORD n=GetEnvironmentVariableA("LENS_FAULT_INJECTION",value,sizeof value);
    if(n>0&&n<sizeof value&&std::string(value)==name)std::_Exit(3);  // simulated crash: no cleanup, no unwinding
}
bool database_opens_with(const std::filesystem::path& path,const std::array<std::uint8_t,32>& key) {
    sqlite3* db=nullptr;const auto u8=path.u8string();
    bool ok=sqlite3_open_v2(reinterpret_cast<const char*>(u8.c_str()),&db,SQLITE_OPEN_READWRITE,nullptr)==SQLITE_OK&&
            sqlite3_key(db,key.data(),static_cast<int>(key.size()))==SQLITE_OK&&
            sqlite3_exec(db,"SELECT count(*) FROM sqlite_master;",nullptr,nullptr,nullptr)==SQLITE_OK;
    sqlite3_close_v2(db);return ok;
}
void replace_file(const std::filesystem::path& from,const std::filesystem::path& to) {
    if(!MoveFileExW(from.c_str(),to.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH))throw Error("database_in_use");
}
void export_encrypted(sqlite3* db,const std::filesystem::path& target,const std::array<std::uint8_t,32>& key,const char* alias) {
    attach(db,target,alias,key.data(),static_cast<int>(key.size()),false);
    try {
        Statement e(db,(std::string("SELECT sqlcipher_export('")+alias+"');").c_str());e.step();
        exec(db,(std::string("PRAGMA ")+alias+".user_version="+std::to_string(user_version(db,"main"))+";").c_str());
        verify(db,alias,"export_verification_failed");
        if(count_sources(db,alias)!=count_sources(db,"main"))throw Error("export_verification_failed");
    } catch(...){detach(db,alias);throw;}
    detach(db,alias);
}

void create_lifecycle_schema(sqlite3* db) {
    exec(db,R"sql(
CREATE TABLE IF NOT EXISTS pins(source_id TEXT PRIMARY KEY REFERENCES observations(id) ON DELETE CASCADE,pinned_at TEXT NOT NULL,note TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS recall_feedback(query_key TEXT NOT NULL,source_id TEXT NOT NULL REFERENCES observations(id) ON DELETE CASCADE,
 signal INTEGER NOT NULL CHECK(signal IN(-1,1)),at TEXT NOT NULL,PRIMARY KEY(query_key,source_id));
CREATE INDEX IF NOT EXISTS recall_feedback_source ON recall_feedback(source_id);
CREATE TABLE IF NOT EXISTS user_facts(id TEXT PRIMARY KEY,type TEXT NOT NULL,predicate TEXT NOT NULL,
 subject_id TEXT REFERENCES entities(id) ON DELETE SET NULL,value TEXT NOT NULL,value_seconds INTEGER,statement TEXT NOT NULL,
 created_at TEXT NOT NULL,supersedes TEXT,supersedes_sources TEXT NOT NULL DEFAULT '[]');
CREATE INDEX IF NOT EXISTS user_fact_subject ON user_facts(subject_id);
CREATE TABLE IF NOT EXISTS fact_status(fact_id TEXT PRIMARY KEY REFERENCES facts(id) ON DELETE CASCADE,
 status TEXT NOT NULL CHECK(status IN('superseded','rejected','confirmed')),user_fact_id TEXT REFERENCES user_facts(id) ON DELETE SET NULL,at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS retention_rules(id INTEGER PRIMARY KEY,kind TEXT,application TEXT,
 max_age_days INTEGER NOT NULL CHECK(max_age_days BETWEEN 1 AND 36500),created_at TEXT NOT NULL);
INSERT OR REPLACE INTO schema_migrations VALUES(9,strftime('%Y-%m-%dT%H:%M:%fZ','now'));
PRAGMA user_version=9;)sql");
}

std::vector<std::string> select_sources(sqlite3* db,const json& scope) {
    static const std::set<std::string> allowed={"all","source_ids","application","kind","start","end","import"};
    if(!scope.is_object()||scope.empty())throw Error("invalid_scope");
    for(const auto& [k,v]:scope.items())if(!allowed.contains(k))throw Error("invalid_scope");
    std::string where=" WHERE 1=1";std::vector<std::string> values;
    if(scope.contains("all")) {
        if(scope.size()!=1||!scope["all"].is_boolean()||!scope["all"].get<bool>())throw Error("invalid_scope");
    }
    if(scope.contains("source_ids")) {
        const auto& ids=scope["source_ids"];if(!ids.is_array()||ids.empty()||ids.size()>max_scope_ids)throw Error("invalid_scope");
        std::string in;for(const auto& id:ids){if(!id.is_string())throw Error("invalid_scope");values.push_back(validated_string(id.get<std::string>(),1024));in+=in.empty()?"?":",?";}
        where+=" AND o.id IN ("+in+")";
    }
    if(scope.contains("application")){where+=" AND m.source_application=?";values.push_back(required(scope,"application",1024));}
    if(scope.contains("kind")){where+=" AND o.kind=?";values.push_back(required(scope,"kind",64));}
    if(scope.contains("start")){where+=" AND m.event_seconds>=?";values.push_back(std::to_string(epoch(required(scope,"start",64))));}
    if(scope.contains("end")){where+=" AND m.event_seconds<?";values.push_back(std::to_string(epoch(required(scope,"end",64))));}
    if(scope.contains("import")) {
        const auto sha=required(scope,"import",64);
        if(sha.size()!=64||sha.find_first_not_of("0123456789abcdef")!=std::string::npos)throw Error("invalid_scope");
        where+=" AND m.source_locator LIKE ?";values.push_back("sha256:"+sha+"#%");
    }
    Statement s(db,("SELECT o.id FROM observations o JOIN source_metadata m ON m.source_id=o.id"+where+" ORDER BY m.event_seconds,o.id;").c_str());
    for(std::size_t i=0;i<values.size();++i)s.text(static_cast<int>(i+1),values[i]);
    std::vector<std::string> ids;while(s.step()==SQLITE_ROW)ids.push_back(s.text(0));
    return ids;
}

long long purge_sources(sqlite3* db,const std::vector<std::string>& ids) {
    if(ids.empty())return 0;
    exec(db,"CREATE TEMP TABLE IF NOT EXISTS purge_ids(id TEXT PRIMARY KEY); CREATE TEMP TABLE IF NOT EXISTS purge_episodes(id TEXT PRIMARY KEY);"
            "DELETE FROM temp.purge_ids; DELETE FROM temp.purge_episodes;");
    {Statement ins(db,"INSERT OR IGNORE INTO temp.purge_ids(id) VALUES(?);");for(const auto& id:ids){sqlite3_reset(ins.p);ins.text(1,id);ins.step();}}
    std::set<std::string> touched;
    {Statement t(db,"SELECT DISTINCT entity_id FROM entity_mentions WHERE source_id IN (SELECT id FROM temp.purge_ids);");while(t.step()==SQLITE_ROW)touched.insert(t.text(0));}
    exec(db,"INSERT OR IGNORE INTO temp.purge_episodes SELECT DISTINCT episode_id FROM episode_members WHERE source_id IN (SELECT id FROM temp.purge_ids);");
    exec(db,"DELETE FROM observations WHERE id IN (SELECT id FROM temp.purge_ids);");
    const long long deleted=sqlite3_changes(db);
    refresh_after_delete(db,touched);
    // Episodes keep only what remains: emptied episodes go, the others are re-bounded by their remaining members.
    exec(db,R"sql(
DELETE FROM episodes WHERE id IN (SELECT id FROM temp.purge_episodes) AND NOT EXISTS(SELECT 1 FROM episode_members WHERE episode_id=episodes.id);
UPDATE episodes SET
 observation_count=(SELECT count(*) FROM episode_members WHERE episode_id=episodes.id),
 first_source_id=(SELECT em.source_id FROM episode_members em JOIN source_metadata m ON m.source_id=em.source_id WHERE em.episode_id=episodes.id ORDER BY m.event_seconds,em.source_id LIMIT 1),
 last_source_id=(SELECT em.source_id FROM episode_members em JOIN source_metadata m ON m.source_id=em.source_id WHERE em.episode_id=episodes.id ORDER BY m.event_seconds DESC,em.source_id DESC LIMIT 1),
 start_seconds=(SELECT min(m.event_seconds) FROM episode_members em JOIN source_metadata m ON m.source_id=em.source_id WHERE em.episode_id=episodes.id),
 end_seconds=(SELECT max(m.event_seconds) FROM episode_members em JOIN source_metadata m ON m.source_id=em.source_id WHERE em.episode_id=episodes.id),
 started_at=(SELECT m.event_key FROM episode_members em JOIN source_metadata m ON m.source_id=em.source_id WHERE em.episode_id=episodes.id ORDER BY m.event_seconds,em.source_id LIMIT 1),
 ended_at=(SELECT m.event_key FROM episode_members em JOIN source_metadata m ON m.source_id=em.source_id WHERE em.episode_id=episodes.id ORDER BY m.event_seconds DESC,em.source_id DESC LIMIT 1)
 WHERE id IN (SELECT id FROM temp.purge_episodes);
DELETE FROM temp.purge_ids; DELETE FROM temp.purge_episodes;
)sql");
    // FTS5 keeps deleted terms in old segments until they are merged; merging rewrites them away (secure_delete zeroes
    // the freed pages). With no sources left, user corrections and trained dictionaries (built from text) go too.
    exec(db,"INSERT INTO memory_fts(memory_fts) VALUES('optimize');");
    {Statement left(db,"SELECT count(*) FROM observations;");left.step();
     if(!sqlite3_column_int64(left.p,0))exec(db,"DELETE FROM fact_status; DELETE FROM user_facts; DELETE FROM text_dictionaries; DELETE FROM episodes;");}
    return deleted;
}

void checkpoint(sqlite3* db,bool vacuum) {
    if(!sqlite3_get_autocommit(db))return;  // inside a client transaction: the commit will carry it
    if(vacuum)exec(db,"VACUUM;");
    exec(db,"PRAGMA wal_checkpoint(TRUNCATE);");
}

json list_imports(sqlite3* db,const json& j) {
    const int limit=j.contains("limit")?j.at("limit").get<int>():50;if(limit<1||limit>500)throw Error("invalid_limit");
    Statement s(db,("SELECT substr(m.source_locator,8,64) sha,count(*),min(m.event_seconds),max(m.event_seconds),min(o.provenance) FROM source_metadata m "
                    "JOIN observations o ON o.id=m.source_id WHERE m.source_locator LIKE 'sha256:%#record=%' GROUP BY sha ORDER BY max(m.event_seconds) DESC LIMIT "+
                    std::to_string(limit)+";").c_str());
    json out=json::array();
    while(s.step()==SQLITE_ROW) {
        std::string format;try{const auto p=json::parse(s.text(4));if(p.is_object()&&p.contains("format")&&p["format"].is_string())format=p["format"].get<std::string>();}catch(...){}
        auto when=[&](int c){return sqlite3_column_type(s.p,c)==SQLITE_NULL?json(nullptr):json(iso_utc(std::chrono::sys_seconds{std::chrono::seconds{sqlite3_column_int64(s.p,c)}}));};
        out.push_back({{"export_sha256",s.text(0)},{"format",format},{"sources",sqlite3_column_int64(s.p,1)},{"first_timestamp",when(2)},{"last_timestamp",when(3)}});
    }
    return {{"ok",true},{"imports",out},{"not_found",out.empty()}};
}

json export_sources(sqlite3* db,const json& j) {
    if(!j.value("consent",false))throw Error("consent_required");
    const auto path=new_file(j,"path");
    const auto ids=select_sources(db,j.contains("scope")?j.at("scope"):json{{"all",true}});
    // The user asked for their own data in a portable form: this file is plaintext by design (reported back).
    HANDLE f=CreateFileW(path.c_str(),GENERIC_WRITE,0,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);
    if(f==INVALID_HANDLE_VALUE)throw Error("file_write_failed");
    bool ok=true;std::size_t bytes=0;
    auto put=[&](const std::string& line){DWORD w=0;const auto data=line+"\n";ok=ok&&WriteFile(f,data.data(),static_cast<DWORD>(data.size()),&w,nullptr)&&w==data.size();bytes+=data.size();};
    try {
        put(json{{"format","lens-history"},{"version",1}}.dump());
        Statement s(db,(columns+tables+"WHERE o.id=?;").c_str());
        for(const auto& id:ids) {
            sqlite3_reset(s.p);s.text(1,id);if(s.step()!=SQLITE_ROW)continue;
            auto src=source(s);json row;
            for(const char* k:{"id","text","language","timestamp","original_timestamp","observed_at","timezone","device","kind","source_application",
                               "source_locator","provenance","consent_context","metadata","confidence"})row[k]=src[k];
            if(!src["model_version"].get<std::string>().empty())row["model_version"]=src["model_version"];
            put(row.dump());
        }
    } catch(...){CloseHandle(f);remove_quietly(path);throw;}
    ok=ok&&FlushFileBuffers(f);CloseHandle(f);
    if(!ok){remove_quietly(path);throw Error("file_write_failed");}
    return {{"ok",true},{"exported",ids.size()},{"bytes",bytes},{"sha256",file_sha256(path)},{"format","lens-history/1"},{"plaintext",true},
            {"warning","plaintext_export_written"}};
}

json backup_database(sqlite3* db,const json& j) {
    if(!sqlite3_get_autocommit(db))throw Error("transaction_open");
    const auto path=new_file(j,"path");const auto key_path=with_suffix(path,L".key"),manifest_path=with_suffix(path,L".manifest.json");
    std::error_code ec;if(std::filesystem::exists(key_path,ec)||std::filesystem::exists(manifest_path,ec))throw Error("invalid_path");
    const bool passphrase_mode=j.contains("passphrase");
    std::string passphrase;if(passphrase_mode){passphrase=required(j,"passphrase",1024);if(passphrase.size()<12)throw Error("weak_passphrase");}
    std::array<std::uint8_t,32> key{};
    try {
        if(!passphrase_mode)key=create_key_file(key_path);
        if(passphrase_mode)attach(db,path,"lens_backup",passphrase.data(),static_cast<int>(passphrase.size()),true);
        else attach(db,path,"lens_backup",key.data(),static_cast<int>(key.size()),false);
        OPENSSL_cleanse(passphrase.data(),passphrase.size());OPENSSL_cleanse(key.data(),key.size());
        try {
            Statement e(db,"SELECT sqlcipher_export('lens_backup');");e.step();
            exec(db,("PRAGMA lens_backup.user_version="+std::to_string(user_version(db,"main"))+";").c_str());
            verify(db,"lens_backup","backup_verification_failed");
            if(count_sources(db,"lens_backup")!=count_sources(db,"main"))throw Error("backup_verification_failed");
        } catch(...){detach(db,"lens_backup");throw;}
        const auto sources=count_sources(db,"lens_backup");detach(db,"lens_backup");
        const json manifest={{"format","lens-backup"},{"version",1},{"created_at",now_iso()},{"schema_version",user_version(db,"main")},
            {"key_mode",passphrase_mode?"passphrase":"dpapi_current_user"},{"source_count",sources},{"sha256",file_sha256(path)},
            {"bytes",std::filesystem::file_size(path)},{"cipher","sqlcipher"}};
        write_new_file(manifest_path,manifest.dump(2));
        return {{"ok",true},{"backup",manifest},{"key_file",passphrase_mode?json(nullptr):json(reinterpret_cast<const char*>(key_path.u8string().c_str()))}};
    } catch(...) {
        OPENSSL_cleanse(passphrase.data(),passphrase.size());OPENSSL_cleanse(key.data(),key.size());
        remove_database_files(path);remove_quietly(key_path);remove_quietly(manifest_path);throw;
    }
}

json restore_database(sqlite3* db,const json& j) {
    if(!sqlite3_get_autocommit(db))throw Error("transaction_open");
    const auto backup=existing_file(j,"backup_path");const auto target=new_file(j,"target_path");const auto target_key=with_suffix(target,L".key");
    const auto staging=with_suffix(target,L".restoring"),staging_key=with_suffix(staging,L".key");
    std::error_code ec;if(std::filesystem::exists(target_key,ec))throw Error("invalid_path");
    json manifest;
    try{const auto bytes=read_file(with_suffix(backup,L".manifest.json"),65536);manifest=json::parse(std::string(bytes.begin(),bytes.end()));}
    catch(...){throw Error("backup_manifest_invalid");}
    if(!manifest.is_object()||manifest.value("format",std::string())!="lens-backup"||manifest.value("version",0)!=1||!manifest.contains("sha256"))throw Error("backup_manifest_invalid");
    // The file must be exactly what was written: a truncated or altered backup is refused before it is opened.
    if(manifest["sha256"]!=file_sha256(backup))throw Error("backup_integrity_failed");
    if(manifest.value("schema_version",0)>schema_version)throw Error("schema_too_new");
    const auto mode=manifest.value("key_mode",std::string());
    std::array<std::uint8_t,32> key{};std::string passphrase;
    if(mode=="passphrase")passphrase=required(j,"passphrase",1024);
    else if(mode=="dpapi_current_user")key=unwrap_key_file(with_suffix(backup,L".key"));
    else throw Error("backup_manifest_invalid");
    bool src_attached=false;
    try {
        try {  // SQLCipher reads the first page while attaching: a wrong key fails here
            if(mode=="passphrase")attach(db,backup,"lens_restore_src",passphrase.data(),static_cast<int>(passphrase.size()),true);
            else attach(db,backup,"lens_restore_src",key.data(),static_cast<int>(key.size()),false);
        } catch(const Error&){throw Error("backup_key_invalid");}
        src_attached=true;OPENSSL_cleanse(passphrase.data(),passphrase.size());OPENSSL_cleanse(key.data(),key.size());
        try{user_version(db,"lens_restore_src");}catch(...){throw Error("backup_key_invalid");}
        verify(db,"lens_restore_src","backup_integrity_failed");
        const auto expected=count_sources(db,"lens_restore_src");
        if(manifest.contains("source_count")&&manifest["source_count"]!=expected)throw Error("backup_integrity_failed");
        // Crash safety: the copy is built and verified under <target>.restoring, then moved into place (database first,
        // key second; a database whose key move was interrupted gets it on its next open, engine/store.cpp).
        remove_database_files(staging);remove_quietly(staging_key);  // leftovers of an interrupted restore to this target
        auto new_key=create_key_file(staging_key);
        attach(db,staging,"lens_restore_dst",new_key.data(),static_cast<int>(new_key.size()),false);OPENSSL_cleanse(new_key.data(),new_key.size());
        try {
            Statement e(db,"SELECT sqlcipher_export('lens_restore_dst','lens_restore_src');");e.step();
            exec(db,("PRAGMA lens_restore_dst.user_version="+std::to_string(user_version(db,"lens_restore_src"))+";").c_str());
            verify(db,"lens_restore_dst","restore_verification_failed");
            if(count_sources(db,"lens_restore_dst")!=expected)throw Error("restore_verification_failed");
        } catch(...){detach(db,"lens_restore_dst");throw;}
        detach(db,"lens_restore_dst");detach(db,"lens_restore_src");src_attached=false;
        fault_point("restore_after_export");
        replace_file(staging,target);
        fault_point("restore_after_db_swap");
        replace_file(staging_key,target_key);
        return {{"ok",true},{"restored_sources",expected},{"schema_version",manifest.value("schema_version",0)},{"verified",true}};
    } catch(...) {
        OPENSSL_cleanse(passphrase.data(),passphrase.size());OPENSSL_cleanse(key.data(),key.size());
        if(src_attached)detach(db,"lens_restore_src");
        remove_database_files(staging);remove_quietly(staging_key);throw;
    }
}

json retention_op(sqlite3* db,const std::string& op,const json& j) {
    if(op=="retention_set") {
        const long long days=j.at("max_age_days").get<long long>();if(days<1||days>36500)throw Error("invalid_retention");
        Statement s(db,"INSERT INTO retention_rules(kind,application,max_age_days,created_at) VALUES(?,?,?,?);");
        if(j.contains("kind"))s.text(1,required(j,"kind",64));else check(sqlite3_bind_null(s.p,1));
        if(j.contains("application"))s.text(2,required(j,"application",1024));else check(sqlite3_bind_null(s.p,2));
        check(sqlite3_bind_int64(s.p,3,days));s.text(4,now_iso());s.step();
        return {{"ok",true},{"id",sqlite3_last_insert_rowid(db)}};
    }
    if(op=="retention_remove") {
        Statement s(db,"DELETE FROM retention_rules WHERE id=?;");check(sqlite3_bind_int64(s.p,1,j.at("id").get<long long>()));s.step();
        return {{"ok",true},{"removed",sqlite3_changes(db)}};
    }
    json rules=json::array();
    Statement s(db,"SELECT id,kind,application,max_age_days,created_at FROM retention_rules ORDER BY id;");
    while(s.step()==SQLITE_ROW)rules.push_back({{"id",sqlite3_column_int64(s.p,0)},{"kind",sqlite3_column_type(s.p,1)==SQLITE_NULL?json(nullptr):json(s.text(1))},
        {"application",sqlite3_column_type(s.p,2)==SQLITE_NULL?json(nullptr):json(s.text(2))},{"max_age_days",sqlite3_column_int64(s.p,3)},{"created_at",s.text(4)}});
    return {{"ok",true},{"rules",rules}};
}

json apply_retention(sqlite3* db) {
    const long long now=std::chrono::duration_cast<std::chrono::seconds>(std::chrono::system_clock::now().time_since_epoch()).count();
    struct Rule {long long id,days;json kind,app;};std::vector<Rule> rules;
    {Statement s(db,"SELECT id,max_age_days,kind,application FROM retention_rules ORDER BY id;");
     while(s.step()==SQLITE_ROW)rules.push_back({sqlite3_column_int64(s.p,0),sqlite3_column_int64(s.p,1),
         sqlite3_column_type(s.p,2)==SQLITE_NULL?json(nullptr):json(s.text(2)),sqlite3_column_type(s.p,3)==SQLITE_NULL?json(nullptr):json(s.text(3))});}
    long long total=0;json applied=json::array();
    for(const auto& r:rules) {
        std::string sql="SELECT o.id FROM observations o JOIN source_metadata m ON m.source_id=o.id WHERE m.event_seconds<? AND NOT EXISTS(SELECT 1 FROM pins p WHERE p.source_id=o.id)";
        if(!r.kind.is_null())sql+=" AND o.kind=?";if(!r.app.is_null())sql+=" AND m.source_application=?";
        Statement s(db,(sql+";").c_str());check(sqlite3_bind_int64(s.p,1,now-r.days*86400));int k=2;
        if(!r.kind.is_null())s.text(k++,r.kind.get<std::string>());if(!r.app.is_null())s.text(k++,r.app.get<std::string>());
        std::vector<std::string> ids;while(s.step()==SQLITE_ROW)ids.push_back(s.text(0));
        const auto n=purge_sources(db,ids);total+=n;applied.push_back({{"rule",r.id},{"deleted",n}});
    }
    return {{"deleted",total},{"rules",applied}};
}
}
