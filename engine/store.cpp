#include "store.hpp"
#include "input.hpp"
#include "sql.hpp"
#include "memory_query.hpp"
#include "retrieval.hpp"
#include "text_codec.hpp"
#include "episodes.hpp"
#include "memory_layers.hpp"
#include "lifecycle.hpp"
#include "user_memory.hpp"
#include "../adapters/windows/key_store.hpp"
#include <sqlcipher/sqlite3.h>
#include <openssl/evp.h>
#include <openssl/crypto.h>
#include <cmath>
#include <iomanip>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>

namespace lens {
using json=nlohmann::json;
using namespace sql;
namespace {
// Support logit threshold of the answerability head (set from the dev harness; see docs/VERIFICATION.md).
constexpr double default_min_support=0.0;
std::string hash(const std::string& text) {
    unsigned char out[EVP_MAX_MD_SIZE]{};size_t n{};
    if(!EVP_Q_digest(nullptr,"SHA256",nullptr,text.data(),text.size(),out,&n))throw Error("hash_failed");
    std::ostringstream s;for(size_t i=0;i<n;++i)s<<std::hex<<std::setfill('0')<<std::setw(2)<<static_cast<unsigned>(out[i]);return s.str();
}
std::string canonical_source_hash(const json& value){
    json normalized;
    for(const char* name:{"text","language","timestamp","device","kind","provenance","confidence",
        "original_timestamp","timezone","source_application","source_locator","consent_context","metadata","model_version"})normalized[name]=value.at(name);
    return hash(normalized.dump());
}
}

Store::Store(const std::filesystem::path& path,EmbedderConfig embedding,RerankerConfig reranking,RerankerConfig verification):codec_(std::make_unique<TextCodec>()),path_(path),embedding_(std::move(embedding)),reranking_(std::move(reranking)),verification_(std::move(verification)) {
    open();
}
namespace {
std::filesystem::path suffixed(std::filesystem::path p,const wchar_t* s){p+=s;return p;}
// Key rotation writes <db>.next and <db>.key.next, swaps the database, then the key. Whatever point a crash
// interrupted, exactly one of the two keys opens the database file; the other files are leftovers.
void recover_rotation(const std::filesystem::path& db) {
    const auto key_path=suffixed(db,L".key"),next_key=suffixed(key_path,L".next"),next_db=suffixed(db,L".next");
    std::error_code ec;
    if(!std::filesystem::exists(next_key,ec)){if(std::filesystem::exists(next_db,ec))std::filesystem::remove(next_db,ec);return;}
    if(std::filesystem::exists(next_db,ec)){  // the swap never happened: the old database and key are intact
        for(const wchar_t* x:{L"",L"-journal",L"-wal",L"-shm"})std::filesystem::remove(suffixed(next_db,x),ec);
        std::filesystem::remove(next_key,ec);return;
    }
    bool current=false;try{auto k=unwrap_key_file(key_path);current=database_opens_with(db,k);OPENSSL_cleanse(k.data(),k.size());}catch(const Error&){}
    if(current){std::filesystem::remove(next_key,ec);return;}
    auto k=unwrap_key_file(next_key);const bool next=database_opens_with(db,k);OPENSSL_cleanse(k.data(),k.size());
    if(!next)throw Error("key_unavailable");
    replace_file(next_key,key_path);  // the database was swapped; finish by promoting its key
}
}
// A restore moves the verified database into place, then its key; a crash between the two leaves the key staged.
void recover_restore(const std::filesystem::path& db) {
    const auto key_path=suffixed(db,L".key"),staged_key=suffixed(db,L".restoring.key");std::error_code ec;
    if(std::filesystem::exists(key_path,ec)||!std::filesystem::exists(staged_key,ec)||!std::filesystem::exists(db,ec))return;
    auto k=unwrap_key_file(staged_key);const bool ok=database_opens_with(db,k);OPENSSL_cleanse(k.data(),k.size());
    if(!ok)throw Error("key_unavailable");
    replace_file(staged_key,key_path);
}
void Store::open() {
    const auto& path=path_;
    recover_rotation(path);
    recover_restore(path);
    const bool exists=std::filesystem::exists(path);
    auto key_path=path;key_path+=L".key";
    auto key=load_or_create_key(key_path,exists);
    try {
        const auto u8=path.u8string();
        check(sqlite3_open_v2(reinterpret_cast<const char*>(u8.c_str()),&db_,SQLITE_OPEN_READWRITE|SQLITE_OPEN_CREATE,nullptr));
        check(sqlite3_busy_timeout(db_,5000));
        check(sqlite3_key(db_,key.data(),static_cast<int>(key.size())));
        OPENSSL_cleanse(key.data(),key.size());
        {Statement cipher(db_,"PRAGMA cipher_version;");
        if(cipher.step()!=SQLITE_ROW||cipher.text(0).empty())throw Error("encryption_unavailable");}
        exec(db_,"PRAGMA foreign_keys=ON; PRAGMA temp_store=MEMORY; PRAGMA secure_delete=ON; PRAGMA cipher_memory_security=ON;");
        exec(db_,"PRAGMA journal_mode=WAL;");
        codec_->register_sql(db_);  // lens_text() is used by schema v6 triggers, the FTS view and all text reads
        Transaction migration(db_);int v;
        {Statement version(db_,"PRAGMA user_version;");if(version.step()!=SQLITE_ROW)throw Error("schema_unavailable");v=sqlite3_column_int(version.p,0);}
        if(v>schema_version)throw Error("schema_too_new");
        if(v==0) {
            exec(db_,R"sql(
CREATE TABLE observations(id TEXT PRIMARY KEY,text TEXT NOT NULL,language TEXT NOT NULL,captured_at TEXT NOT NULL,
device TEXT NOT NULL,kind TEXT NOT NULL,provenance TEXT NOT NULL,sha256 TEXT NOT NULL UNIQUE,confidence REAL NOT NULL CHECK(confidence>=0 AND confidence<=1));
CREATE TABLE derived(id INTEGER PRIMARY KEY,source_id TEXT NOT NULL REFERENCES observations(id) ON DELETE CASCADE,
data TEXT NOT NULL,confidence REAL NOT NULL CHECK(confidence>=0 AND confidence<=1),model TEXT NOT NULL);
CREATE VIRTUAL TABLE memory_fts USING fts5(text,content='observations',content_rowid='rowid',tokenize='unicode61');
CREATE TRIGGER observations_insert AFTER INSERT ON observations BEGIN INSERT INTO memory_fts(rowid,text) VALUES(new.rowid,new.text); END;
CREATE TRIGGER observations_delete AFTER DELETE ON observations BEGIN INSERT INTO memory_fts(memory_fts,rowid,text) VALUES('delete',old.rowid,old.text); END;
CREATE TRIGGER observations_immutable BEFORE UPDATE ON observations BEGIN SELECT RAISE(ABORT,'immutable'); END;
PRAGMA user_version=1;)sql");
        }
        if(v<2)exec(db_,R"sql(
CREATE TABLE source_metadata(source_id TEXT PRIMARY KEY REFERENCES observations(id) ON DELETE CASCADE,
 original_timestamp TEXT,observed_at TEXT NOT NULL,timezone TEXT NOT NULL,source_application TEXT NOT NULL,
 source_locator TEXT NOT NULL,consent_context TEXT NOT NULL,metadata TEXT NOT NULL,event_seconds INTEGER,model_version TEXT NOT NULL);
INSERT INTO source_metadata SELECT id,NULL,captured_at,'','','','{"mode":"legacy_unrecorded"}',
 '{"timestamp_semantics":"legacy_unseparated"}',unixepoch(captured_at),'' FROM observations;
CREATE INDEX source_event_time ON source_metadata(event_seconds);
CREATE INDEX source_application ON source_metadata(source_application);
CREATE TRIGGER source_metadata_immutable BEFORE UPDATE ON source_metadata BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL);
INSERT INTO schema_migrations VALUES(1,strftime('%Y-%m-%dT%H:%M:%fZ','now')),(2,strftime('%Y-%m-%dT%H:%M:%fZ','now'));
PRAGMA user_version=2;)sql");
        if(v<3){
            exec(db_,"DROP TRIGGER source_metadata_immutable; ALTER TABLE source_metadata ADD COLUMN event_key TEXT; CREATE INDEX source_event_key ON source_metadata(event_key);");
            std::vector<std::pair<std::string,std::string>> sources;
            {Statement s(db_,"SELECT o.id,o.captured_at FROM observations o;");while(s.step()==SQLITE_ROW)sources.emplace_back(s.text(0),s.text(1));}
            for(const auto& [id,time]:sources){
                std::string time_key;try{time_key=instant(time);}catch(const Error&){continue;} // Unknown legacy time stays unindexed, never discarded.
                Statement update(db_,"UPDATE source_metadata SET event_key=? WHERE source_id=?;");update.text(1,time_key);update.text(2,id);update.step();
            }
            exec(db_,"CREATE TRIGGER source_metadata_immutable BEFORE UPDATE ON source_metadata BEGIN SELECT RAISE(ABORT,'immutable'); END; INSERT INTO schema_migrations VALUES(3,strftime('%Y-%m-%dT%H:%M:%fZ','now')); PRAGMA user_version=3;");
        }
        if(v<4){
            exec(db_,"DROP TRIGGER source_metadata_immutable; ALTER TABLE source_metadata ADD COLUMN canonical_hash TEXT;");
            sqlite3_int64 after=0;
            while(true){
                std::vector<std::pair<sqlite3_int64,json>> batch;
                const auto selection=legacy_columns.substr(0,legacy_columns.size()-1)+",o.rowid"+tables+"WHERE o.rowid>? ORDER BY o.rowid LIMIT 8;";
                {Statement s(db_,selection.c_str());check(sqlite3_bind_int64(s.p,1,after));
                while(s.step()==SQLITE_ROW)batch.emplace_back(sqlite3_column_int64(s.p,17),source(s));}
                if(batch.empty())break;
                for(const auto& [rowid,value]:batch){
                    Statement update(db_,"UPDATE source_metadata SET canonical_hash=? WHERE source_id=?;");
                    update.text(1,canonical_source_hash(value));update.text(2,value.at("id").get<std::string>());update.step();after=rowid;
                }
            }
            exec(db_,"CREATE INDEX source_canonical_hash ON source_metadata(canonical_hash); CREATE TRIGGER source_metadata_immutable BEFORE UPDATE ON source_metadata BEGIN SELECT RAISE(ABORT,'immutable'); END; INSERT INTO schema_migrations VALUES(4,strftime('%Y-%m-%dT%H:%M:%fZ','now')); PRAGMA user_version=4;");
        }
        if(v<5)exec(db_,R"sql(
CREATE TABLE IF NOT EXISTS embedding_chunks(id INTEGER PRIMARY KEY,source_id TEXT NOT NULL REFERENCES observations(id) ON DELETE CASCADE,
 chunk INTEGER NOT NULL,byte_start INTEGER NOT NULL,byte_end INTEGER NOT NULL,model TEXT NOT NULL,scale REAL NOT NULL,
 vector BLOB NOT NULL CHECK(length(vector)=384),UNIQUE(source_id,model,chunk));
CREATE INDEX IF NOT EXISTS embedding_model_source ON embedding_chunks(model,source_id);
INSERT INTO schema_migrations VALUES(5,strftime('%Y-%m-%dT%H:%M:%fZ','now'));
PRAGMA user_version=5;)sql");
        // v6: optional zstd text storage (engine/text_codec.hpp). FTS reads content through a view that decodes text,
        // so search, highlight and deletes see the original text; existing rows stay plain and are re-indexed once.
        if(v<6) {  // idempotent: a database whose user_version was reset still carries the v6 columns
            bool has_codec=false;
            {Statement cols(db_,"SELECT 1 FROM pragma_table_info('observations') WHERE name='text_codec';");has_codec=cols.step()==SQLITE_ROW;}
            if(!has_codec)exec(db_,"ALTER TABLE observations ADD COLUMN text_codec INTEGER; ALTER TABLE observations ADD COLUMN text_zstd BLOB;");
            exec(db_,R"sql(
DROP TRIGGER IF EXISTS observations_insert;DROP TRIGGER IF EXISTS observations_delete;
CREATE TABLE IF NOT EXISTS text_dictionaries(id INTEGER PRIMARY KEY,created_at TEXT NOT NULL,sha256 TEXT NOT NULL UNIQUE,data BLOB NOT NULL);
CREATE TRIGGER IF NOT EXISTS text_dictionaries_immutable BEFORE UPDATE ON text_dictionaries BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE VIEW IF NOT EXISTS observation_text(rid,text) AS SELECT rowid,lens_text(text,text_codec,text_zstd) FROM observations;
DROP TABLE IF EXISTS memory_fts;
CREATE VIRTUAL TABLE memory_fts USING fts5(text,content='observation_text',content_rowid='rid',tokenize='unicode61');
INSERT INTO memory_fts(memory_fts) VALUES('rebuild');
CREATE TRIGGER observations_insert AFTER INSERT ON observations BEGIN
 INSERT INTO memory_fts(rowid,text) VALUES(new.rowid,lens_text(new.text,new.text_codec,new.text_zstd)); END;
CREATE TRIGGER observations_delete AFTER DELETE ON observations BEGIN
 INSERT INTO memory_fts(memory_fts,rowid,text) VALUES('delete',old.rowid,lens_text(old.text,old.text_codec,old.text_zstd)); END;
INSERT OR REPLACE INTO schema_migrations VALUES(6,strftime('%Y-%m-%dT%H:%M:%fZ','now'));
PRAGMA user_version=6;)sql");
        }
        // v7: episodic memory (engine/episodes.hpp), derived and rebuilt by the consolidate op.
        if(v<7)exec(db_,R"sql(
CREATE TABLE IF NOT EXISTS episodes(id TEXT PRIMARY KEY,device TEXT NOT NULL,application TEXT NOT NULL,locator TEXT NOT NULL,
 title TEXT NOT NULL,started_at TEXT NOT NULL,ended_at TEXT NOT NULL,start_seconds INTEGER NOT NULL,end_seconds INTEGER NOT NULL,
 observation_count INTEGER NOT NULL,first_source_id TEXT NOT NULL,last_source_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS episode_members(source_id TEXT PRIMARY KEY REFERENCES observations(id) ON DELETE CASCADE,
 episode_id TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS episode_time ON episodes(start_seconds,end_seconds);
CREATE INDEX IF NOT EXISTS episode_device_time ON episodes(device,start_seconds);
CREATE INDEX IF NOT EXISTS episode_member_episode ON episode_members(episode_id);
INSERT OR REPLACE INTO schema_migrations VALUES(7,strftime('%Y-%m-%dT%H:%M:%fZ','now'));
PRAGMA user_version=7;)sql");
        // v8: semantic memory (entities, facts) and project memory (engine/memory_layers.hpp), derived by consolidate.
        if(v<8)create_memory_layer_schema(db_);
        // v9: lifecycle and user memory (engine/lifecycle.hpp, engine/user_memory.hpp): pins, feedback, corrections, retention.
        if(v<9)create_lifecycle_schema(db_);
        migration.commit();
        codec_->load_dictionaries(db_);
    } catch(...) {OPENSSL_cleanse(key.data(),key.size());if(db_)sqlite3_close_v2(db_);db_=nullptr;throw;}
}
Store::~Store(){reranker_.reset();embedder_.reset();if(db_)sqlite3_close_v2(db_);}

void Store::after_purge() {
    bool empty=false;{Statement left(db_,"SELECT count(*) FROM observations;");left.step();empty=sqlite3_column_int64(left.p,0)==0;}
    if(empty&&sqlite3_get_autocommit(db_)) {  // dictionaries were deleted with the last source; never encode with them again
        auto fresh=std::make_unique<TextCodec>();fresh->register_sql(db_);fresh->load_dictionaries(db_);codec_=std::move(fresh);
    }
    checkpoint(db_,false);
}

json Store::rotate_key() {
    if(explicit_)throw Error("transaction_open");
    const auto key_path=suffixed(path_,L".key"),next_key=suffixed(key_path,L".next"),next_db=suffixed(path_,L".next");
    std::error_code ec;if(std::filesystem::exists(next_key,ec)||std::filesystem::exists(next_db,ec))throw Error("rotation_pending");
    long long sources=0;{Statement c(db_,"SELECT count(*) FROM observations;");c.step();sources=sqlite3_column_int64(c.p,0);}
    auto key=create_key_file(next_key);
    try{export_encrypted(db_,next_db,key,"lens_rekey");}
    catch(...){OPENSSL_cleanse(key.data(),key.size());for(const wchar_t* x:{L"",L"-journal"})std::filesystem::remove(suffixed(next_db,x),ec);std::filesystem::remove(next_key,ec);throw;}
    OPENSSL_cleanse(key.data(),key.size());
    fault_point("rotate_after_export");
    exec(db_,"PRAGMA wal_checkpoint(TRUNCATE);");
    sqlite3_close_v2(db_);db_=nullptr;
    try{replace_file(next_db,path_);}
    catch(...){open();std::filesystem::remove(next_db,ec);std::filesystem::remove(next_key,ec);throw;}
    for(const wchar_t* x:{L"-wal",L"-shm"})std::filesystem::remove(suffixed(path_,x),ec);  // belonged to the old file
    fault_point("rotate_after_db_swap");
    replace_file(next_key,key_path);
    open();
    long long after=0;{Statement c(db_,"SELECT count(*) FROM observations;");c.step();after=sqlite3_column_int64(c.p,0);}
    if(after!=sources)throw Error("rotation_verification_failed");
    return {{"ok",true},{"rotated",true},{"sources",after}};
}

Embedder& Store::embedder(){
    if(!embedding_.configured())throw Error("embedding_model_not_configured");
    if(!embedder_)embedder_=std::make_unique<Embedder>(embedding_);
    return *embedder_;
}

Reranker& Store::verifier(){
    if(!verification_.configured())throw Error("verifier_not_configured");
    if(!verifier_)verifier_=std::make_unique<Reranker>(verification_);
    return *verifier_;
}
Reranker& Store::reranker(){
    if(!reranking_.configured())throw Error("reranker_not_configured");
    if(!reranker_)reranker_=std::make_unique<Reranker>(reranking_);
    return *reranker_;
}

json Store::request(const json& j) {
    const auto op=j.is_object()&&j.contains("op")&&j["op"].is_string()?j["op"].get<std::string>():std::string{};
    if(op=="begin"){
        if(explicit_)throw Error("transaction_already_open");
        exec(db_,"BEGIN IMMEDIATE;");explicit_=true;poisoned_=false;return {{"ok",true},{"transaction","open"}};
    }
    if(op=="commit"||op=="rollback"){
        if(!explicit_)throw Error("no_open_transaction");
        explicit_=false;
        if(op=="rollback"||poisoned_){sqlite3_exec(db_,"ROLLBACK;",nullptr,nullptr,nullptr);
            if(op=="commit")throw Error("transaction_poisoned_rolled_back");return {{"ok",true},{"transaction","rolled_back"}};}
        exec(db_,"COMMIT;");return {{"ok",true},{"transaction","committed"}};
    }
    try{return dispatch(j);}catch(...){if(explicit_)poisoned_=true;throw;}
}

json Store::dispatch(const json& j) {
    const auto op=required(j,"op",32);
    if(op=="import_batch"){
        if(!j.value("consent",false))throw Error("consent_required");
        const auto& records=j.at("records");if(!records.is_array()||records.empty()||records.size()>128)throw Error("invalid_batch");
        Transaction tx(db_);json ids=json::array();size_t added=0;
        for(auto item:records){
            if(!item.is_object())throw Error("invalid_request");item["op"]="add";item["consent"]=true;
            const auto result=dispatch(item);ids.push_back(result.at("id"));if(!result.at("deduplicated").get<bool>())++added;
        }
        tx.commit();return {{"ok",true},{"imported",added},{"deduplicated",records.size()-added},{"source_ids",ids}};
    }
    if(op=="index")return index_sources(db_,embedder(),j);
    if(op=="recall") {
        auto result=recall(db_,[this]()->Embedder&{return embedder();},reranking_.configured()?RerankerAccess([this]()->Reranker&{return reranker();}):RerankerAccess{},embedding_.model_id,j);
        // Evidence verification (trained Lens answerability head): the top evidence must SUPPORT an answer, not merely be
        // related. Below the threshold Lens abstains; an exact full-literal match of the query still answers.
        if(verification_.configured()&&j.value("abstain",true)&&!result.value("not_found",true)&&!result["results"].empty()) {
            auto& top=result["results"][0];const auto quote=top["evidence"].value("quote",std::string());
            const double support=verifier().score(j.at("query").get<std::string>(),{quote}).at(0);
            const double min_support=j.value("min_support",default_min_support);
            result["support"]=support;result["min_support"]=min_support;
            if(support<min_support&&!result.value("full_keyword_match",false)) {
                result["not_found"]=true;result["withheld_results"]=result["results"].size();result["results"]=json::array();result["abstained_by"]="verifier";
            }
        }
        if(result.contains("results"))  // episode context (app, window, time span) for each piece of evidence
            for(auto& r:result["results"])if(r.contains("source")&&r["source"].contains("id"))r["episode"]=episode_of(db_,r["source"]["id"].get<std::string>());
        // L4: entities named in the question are an extra signal; each result carries its linked entities and facts.
        if(result.contains("results"))annotate_recall(db_,j.at("query").get<std::string>(),result,j.value("entity_boost",true));
        // Section 12: per-question relevance feedback and pinned memories (the user's own signals) order the evidence last.
        if(result.contains("results"))apply_user_signals(db_,j.at("query").get<std::string>(),result,j.value("user_signals",true));
        return result;
    }
    if(op=="consolidate"){  // L3 episodes, then L4/L5 incrementally (projects group episodes, so episodes come first)
        json retention;
        {Transaction tx(db_);retention=apply_retention(db_,*codec_);tx.commit();}  // expired sources go before anything is derived from them
        if(retention.at("deleted").get<long long>())after_purge();
        Transaction tx(db_);auto result=consolidate_episodes(db_,j);result["memory"]=consolidate_memory_layers(db_,j);tx.commit();
        result["retention"]=retention;return result;
    }
    if(op=="entities")return list_entities(db_,j);
    if(op=="entity_context")return entity_context(db_,j);
    if(op=="facts")return list_facts(db_,j);
    if(op=="projects")return list_projects(db_,j);
    if(op=="project_context")return project_context(db_,j);
    if(op=="episodes")return list_episodes(db_,j);
    if(op=="episode_context")return episode_context(db_,j);
    if(op=="train_text_dictionary") {
        const int samples=j.value("samples",2000),bytes=j.value("dictionary_bytes",65536);
        if(samples<100||samples>100000||bytes<4096||bytes>(1<<20))throw Error("invalid_request");
        Transaction tx(db_);const int id=codec_->train(db_,samples,bytes);tx.commit();
        return {{"ok",true},{"dictionary_id",id}};
    }
    if(op=="unload_models"){const bool loaded=embedder_||reranker_||verifier_;verifier_.reset();reranker_.reset();embedder_.reset();return {{"ok",true},{"unloaded",loaded}};}
    if(op=="search"||op=="retrieve_context"||op=="timeline"||op=="find_source")return memory_query(db_,j);
    if(op=="add") {
        if(!j.value("consent",false))throw Error("consent_required");
        const auto id=required(j,"id"),text=required(j,"text",1024*1024),lang=required(j,"language",32),
            timestamp=required(j,"timestamp",64),device=required(j,"device"),kind=required(j,"kind",64),prov=required(j,"provenance",8192);
        const double confidence=j.value("confidence",1.0);
        static const std::regex sensitive(R"((password|passcode|\botp\b|one.time.password|verification.code|credit.card|\bcvv\b|api.key|secret.key|密码|验证码|银行卡|contraseña))",std::regex::icase);
        if(std::regex_search(text,sensitive)||kind=="password_field"||kind=="otp_field"||kind=="financial_field")
            throw Error("sensitive_content_excluded");
        if(!std::isfinite(confidence)||confidence<0||confidence>1)throw Error("invalid_confidence");
        const auto event_seconds=epoch(timestamp);
        const auto observed=j.contains("observed_at")?required(j,"observed_at",64):timestamp;epoch(observed);
        json original=nullptr;if(j.contains("original_timestamp")&&!j.at("original_timestamp").is_null()){
            original=required(j,"original_timestamp",64);if(instant(original.get<std::string>())!=instant(timestamp))throw Error("conflicting_source_timestamp");
        }
        const auto zone=optional(j,"timezone",128),app=optional(j,"source_application"),locator=optional(j,"source_locator",8192),model=optional(j,"model_version");
        const auto consent=j.value("consent_context",json{{"mode","explicit_api_import"}}),metadata=j.value("metadata",json::object());
        if(!consent.is_object()||!metadata.is_object()||consent.dump().size()>8192||metadata.dump().size()>1048576)throw Error("invalid_source_metadata");
        const auto mode=required(consent,"mode",128);(void)mode;
        json hashed={{"text",text},{"language",lang},{"timestamp",timestamp},{"device",device},{"kind",kind},{"provenance",prov},{"confidence",confidence}};
        const auto legacy_hash=hash(hashed.dump());bool extended=false;
        for(const char* name:{"original_timestamp","timezone","source_application","source_locator","consent_context","metadata","model_version"})if(j.contains(name))extended=true;
        hashed["original_timestamp"]=original;hashed["timezone"]=zone;hashed["source_application"]=app;hashed["source_locator"]=locator;
        hashed["consent_context"]=consent;hashed["metadata"]=metadata;hashed["model_version"]=model;
        const auto content_hash=canonical_source_hash(hashed);Transaction tx(db_);
        {Statement existing(db_,"SELECT o.id,o.sha256,m.canonical_hash FROM observations o JOIN source_metadata m ON m.source_id=o.id WHERE o.id=?;");existing.text(1,id);
        if(existing.step()==SQLITE_ROW){
            if(existing.text(2)!=content_hash&&(extended||existing.text(1)!=legacy_hash))throw Error("immutable_source_conflict");
            auto canonical=existing.text(0);existing.step();tx.commit();return {{"ok",true},{"id",canonical},{"deduplicated",true}};
        }}
        {Statement existing(db_,"SELECT source_id FROM source_metadata WHERE canonical_hash=?;");existing.text(1,content_hash);
        if(existing.step()==SQLITE_ROW){auto canonical=existing.text(0);existing.step();tx.commit();return {{"ok",true},{"id",canonical},{"deduplicated",true}};}}
        if(!extended){Statement existing(db_,"SELECT id FROM observations WHERE sha256=?;");existing.text(1,legacy_hash);
        if(existing.step()==SQLITE_ROW){auto canonical=existing.text(0);existing.step();tx.commit();return {{"ok",true},{"id",canonical},{"deduplicated",true}};}}
        Statement s(db_,"INSERT INTO observations(id,text,language,captured_at,device,kind,provenance,sha256,confidence,text_codec,text_zstd) VALUES(?,?,?,?,?,?,?,?,?,?,?);");
        const auto encoded=codec_->encode(text);  // hashes above were computed on the original text
        int n=1;for(const auto& value:{id,encoded?std::string():text,lang,timestamp,device,kind,prov,content_hash})s.text(n++,value);
        check(sqlite3_bind_double(s.p,9,confidence));
        if(encoded){check(sqlite3_bind_int(s.p,10,encoded->codec));check(sqlite3_bind_blob(s.p,11,encoded->blob.data(),static_cast<int>(encoded->blob.size()),SQLITE_TRANSIENT));}
        else{check(sqlite3_bind_null(s.p,10));check(sqlite3_bind_null(s.p,11));}
        s.step();
        Statement meta(db_,"INSERT INTO source_metadata(source_id,original_timestamp,observed_at,timezone,source_application,source_locator,consent_context,metadata,event_seconds,model_version,event_key,canonical_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?);");meta.text(1,id);
        if(original.is_null())check(sqlite3_bind_null(meta.p,2));else meta.text(2,original.get<std::string>());
        int k=3;for(const auto& value:{observed,zone,app,locator,consent.dump(),metadata.dump()})meta.text(k++,value);
        check(sqlite3_bind_int64(meta.p,9,event_seconds));meta.text(10,model);meta.text(11,instant(timestamp));meta.text(12,content_hash);meta.step();tx.commit();
        return {{"ok",true},{"id",id},{"sha256",content_hash},{"deduplicated",false}};
    }
    if(op=="derive") {
        auto source_id=required(j,"source_id"),model=required(j,"model");
        const double c=j.at("confidence").get<double>();
        if(!std::isfinite(c)||c<0||c>1)throw Error("invalid_confidence");
        const auto data=j.at("data").dump();if(data.size()>65536)throw Error("derived_record_too_large");
        Statement s(db_,"INSERT INTO derived(source_id,data,confidence,model) VALUES(?,?,?,?);");
        s.text(1,source_id);s.text(2,data);check(sqlite3_bind_double(s.p,3,c));s.text(4,model);s.step();
        return {{"ok",true},{"source_id",source_id},{"id",sqlite3_last_insert_rowid(db_)}};
    }
    if(op=="delete") {
        if(!j.value("consent",false))throw Error("consent_required");
        const auto id=required(j,"id");long long deleted=0;
        {Transaction tx(db_);deleted=purge_sources(db_,{id},*codec_);tx.commit();}  // everything derived from it goes too
        if(deleted)after_purge();
        return {{"ok",true},{"deleted",deleted}};
    }
    if(op=="delete_sources") {  // delete-all and scoped deletion (application, kind, time range, import, ids)
        if(!j.value("consent",false))throw Error("consent_required");
        if(!j.contains("scope"))throw Error("invalid_scope");
        long long deleted=0;const bool all=j["scope"].is_object()&&j["scope"].contains("all");
        {Transaction tx(db_);deleted=purge_sources(db_,select_sources(db_,j["scope"]),*codec_);tx.commit();}
        after_purge();
        const bool vacuum=j.contains("compact")?j.at("compact").get<bool>():all;
        if(vacuum)checkpoint(db_,true);
        return {{"ok",true},{"deleted",deleted},{"compacted",vacuum&&sqlite3_get_autocommit(db_)!=0}};
    }
    if(op=="export")return export_sources(db_,j);
    if(op=="imports")return list_imports(db_,j);
    if(op=="backup")return backup_database(db_,j);
    if(op=="restore")return restore_database(db_,j);
    if(op=="rotate_key")return rotate_key();
    if(op=="retention_set"||op=="retention_list"||op=="retention_remove")return retention_op(db_,op,j);
    if(op=="pin"||op=="unpin"||op=="pins"||op=="feedback"||op=="correct_fact")return user_memory_op(db_,op,j);
    if(op=="stats") {
        Statement s(db_,"SELECT (SELECT count(*) FROM observations),(SELECT count(*) FROM derived),(SELECT count(*) FROM embedding_chunks),(SELECT count(DISTINCT source_id) FROM embedding_chunks),"
                        "(SELECT count(*) FROM observations WHERE text_codec IS NOT NULL),(SELECT coalesce(sum(length(text_zstd)),0) FROM observations),(SELECT count(*) FROM text_dictionaries),"
                        "(SELECT count(*) FROM entities),(SELECT count(*) FROM facts),(SELECT count(*) FROM projects),(SELECT count(*) FROM pins),(SELECT count(*) FROM user_facts),"
                        "(SELECT count(*) FROM retention_rules);");s.step();
        Statement cipher(db_,"PRAGMA cipher_version;");cipher.step();
        return {{"ok",true},{"source_count",sqlite3_column_int64(s.p,0)},{"derived_count",sqlite3_column_int64(s.p,1)},
                {"schema_version",schema_version},{"pin_count",sqlite3_column_int64(s.p,10)},{"user_fact_count",sqlite3_column_int64(s.p,11)},{"retention_rule_count",sqlite3_column_int64(s.p,12)},{"entity_count",sqlite3_column_int64(s.p,7)},{"fact_count",sqlite3_column_int64(s.p,8)},{"project_count",sqlite3_column_int64(s.p,9)},{"compressed_sources",sqlite3_column_int64(s.p,4)},{"compressed_text_bytes",sqlite3_column_int64(s.p,5)},
                {"text_dictionaries",sqlite3_column_int64(s.p,6)},{"vector_chunks",sqlite3_column_int64(s.p,2)},{"embedded_sources",sqlite3_column_int64(s.p,3)},{"embedding_model",embedding_.configured()?json(embedding_.model_id):json(nullptr)},{"models_loaded",static_cast<bool>(embedder_)||static_cast<bool>(reranker_)},{"reranker_configured",reranking_.configured()},{"cipher_version",cipher.text(0)},{"engine_version","0.2.0-dev"},{"api_version",1}};
    }
    throw Error("unsupported_operation");
}
}
