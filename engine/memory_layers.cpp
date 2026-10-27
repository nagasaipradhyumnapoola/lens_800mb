#include "memory_layers.hpp"
#include "memory_query.hpp"
#include "semantic_extract.hpp"
#include "sql.hpp"
#include "temporal.hpp"
#include <openssl/evp.h>
#include <algorithm>
#include <cctype>
#include <iomanip>
#include <map>
#include <sstream>
#include <unordered_map>
#include <vector>

namespace lens {
using json=nlohmann::json;
using namespace sql;
namespace {
constexpr int max_backfill_sources=20000;  // per consolidate run; the rest is reported, never silently dropped
std::string short_hash(const std::string& prefix,const std::string& text) {
    unsigned char out[EVP_MAX_MD_SIZE]{};size_t n{};
    if(!EVP_Q_digest(nullptr,"SHA256",nullptr,text.data(),text.size(),out,&n))throw Error("hash_failed");
    std::ostringstream s;s<<prefix;for(size_t i=0;i<12;++i)s<<std::hex<<std::setfill('0')<<std::setw(2)<<static_cast<unsigned>(out[i]);return s.str();
}
json time_or_null(sqlite3_stmt* p,int col) {
    if(sqlite3_column_type(p,col)==SQLITE_NULL)return nullptr;
    return iso_utc(std::chrono::sys_seconds{std::chrono::seconds{sqlite3_column_int64(p,col)}});
}
void bind_int(Statement& s,int i,long long v){check(sqlite3_bind_int64(s.p,i,v));}
int limit_of(const json& j,int fallback,int max) {
    const int limit=j.contains("limit")?j.at("limit").get<int>():fallback;
    if(limit<1||limit>max)throw Error("invalid_limit");return limit;
}
std::size_t char_floor(const std::string& s,std::size_t i){i=std::min(i,s.size());while(i>0&&i<s.size()&&(static_cast<unsigned char>(s[i])&0xC0)==0x80)--i;return i;}
// A verbatim excerpt around [start,end) with its exact byte range.
json excerpt(const std::string& text,std::size_t start,std::size_t end,std::size_t context=80) {
    if(start>end||end>text.size())return nullptr;
    const auto a=char_floor(text,start>context?start-context:0),b=char_floor(text,std::min(text.size(),end+context));
    const auto stop=b<end?text.size():b;
    return {{"text",text.substr(a,stop-a)},{"byte_offset",a},{"byte_end",stop}};
}
std::string source_text(sqlite3* db,const std::string& id) {
    Statement s(db,"SELECT lens_text(text,text_codec,text_zstd) FROM observations WHERE id=?;");s.text(1,id);
    return s.step()==SQLITE_ROW?s.text(0):std::string();
}

// ---------------------------------------------------------------- entities
std::string resolve_entity(sqlite3* db,extract::EntityType type,const std::string& name,double confidence) {
    const auto key=extract::strict_key(name);
    if(key.size()<2)return {};
    const std::string type_name=extract::type_name(type);
    {Statement s(db,"SELECT id FROM entities WHERE type=? AND key=?;");s.text(1,type_name);s.text(2,key);if(s.step()==SQLITE_ROW)return s.text(0);}
    const auto loose=extract::loose_key(name),script=extract::script_of(name);
    if(loose.size()>=3) {  // the same name written in another script ("Arun" / "அருண்" / "अरुण")
        Statement s(db,"SELECT id FROM entities WHERE type=? AND loose=? AND script<>? UNION ALL "
                       "SELECT a.entity_id FROM entity_aliases a JOIN entities e ON e.id=a.entity_id WHERE e.type=? AND a.loose=? AND a.script<>? LIMIT 1;");
        s.text(1,type_name);s.text(2,loose);s.text(3,script);s.text(4,type_name);s.text(5,loose);s.text(6,script);
        if(s.step()==SQLITE_ROW)return s.text(0);
    }
    const auto id=short_hash("en-",type_name+"|"+key);
    Statement ins(db,"INSERT OR IGNORE INTO entities(id,type,name,key,loose,script,confidence) VALUES(?,?,?,?,?,?,?);");
    ins.text(1,id);ins.text(2,type_name);ins.text(3,name);ins.text(4,key);ins.text(5,loose);ins.text(6,script);
    check(sqlite3_bind_double(ins.p,7,confidence));ins.step();
    return id;
}
json entity_row(Statement& s,sqlite3* db,int alias_limit=8) {  // id,type,name,mention_count,source_count,first_seconds,last_seconds,confidence
    json e={{"id",s.text(0)},{"type",s.text(1)},{"name",s.text(2)},{"mention_count",sqlite3_column_int64(s.p,3)},
            {"source_count",sqlite3_column_int64(s.p,4)},{"first_seen",time_or_null(s.p,5)},{"last_seen",time_or_null(s.p,6)},
            {"confidence",sqlite3_column_double(s.p,7)},{"derived",true}};
    json aliases=json::array();
    Statement a(db,("SELECT alias FROM entity_aliases WHERE entity_id=? ORDER BY mentions DESC,alias LIMIT "+std::to_string(alias_limit)+";").c_str());
    a.text(1,e["id"].get<std::string>());while(a.step()==SQLITE_ROW)aliases.push_back(a.text(0));
    e["aliases"]=aliases;return e;
}
const char* entity_columns="SELECT id,type,name,mention_count,source_count,first_seconds,last_seconds,confidence FROM entities ";
json entity_by_id(sqlite3* db,const std::string& id) {
    Statement s(db,(std::string(entity_columns)+"WHERE id=?;").c_str());s.text(1,id);
    return s.step()==SQLITE_ROW?entity_row(s,db):json(nullptr);
}
void refresh_entities(sqlite3* db,const std::set<std::string>& ids) {
    for(const auto& id:ids) {
        long long mentions=0,sources=0;
        Statement c(db,"SELECT count(*),count(DISTINCT m.source_id),min(s.event_seconds),max(s.event_seconds) FROM entity_mentions m "
                       "LEFT JOIN source_metadata s ON s.source_id=m.source_id WHERE m.entity_id=?;");
        c.text(1,id);c.step();mentions=sqlite3_column_int64(c.p,0);sources=sqlite3_column_int64(c.p,1);
        if(!mentions){Statement d(db,"DELETE FROM entities WHERE id=?;");d.text(1,id);d.step();continue;}
        // Display name: the most frequent rule-confirmed surface; confidence: noisy-or of mention confidences.
        std::string name;
        {Statement n(db,"SELECT surface FROM entity_mentions WHERE entity_id=? GROUP BY surface "
                        "ORDER BY sum(rule<>'gazetteer') DESC,count(*) DESC,min(id) LIMIT 1;");n.text(1,id);n.step();name=n.text(0);}
        double miss=1;
        {Statement q(db,"SELECT confidence FROM entity_mentions WHERE entity_id=? LIMIT 1000;");q.text(1,id);while(q.step()==SQLITE_ROW)miss*=1-sqlite3_column_double(q.p,0);}
        Statement u(db,"UPDATE entities SET name=?,mention_count=?,source_count=?,first_seconds=?,last_seconds=?,confidence=? WHERE id=?;");
        u.text(1,name);bind_int(u,2,mentions);bind_int(u,3,sources);
        if(sqlite3_column_type(c.p,2)==SQLITE_NULL){check(sqlite3_bind_null(u.p,4));check(sqlite3_bind_null(u.p,5));}
        else{bind_int(u,4,sqlite3_column_int64(c.p,2));bind_int(u,5,sqlite3_column_int64(c.p,3));}
        check(sqlite3_bind_double(u.p,6,std::min(0.99,1-miss)));u.text(7,id);u.step();
        // Identity keys follow the remaining evidence, so no spelling of a deleted source lingers.
        {Statement k(db,"UPDATE OR IGNORE entities SET key=?,loose=?,script=? WHERE id=?;");
         k.text(1,extract::strict_key(name));k.text(2,extract::loose_key(name));k.text(3,extract::script_of(name));k.text(4,id);k.step();}
        {Statement d(db,"DELETE FROM entity_aliases WHERE entity_id=?;");d.text(1,id);d.step();}
        std::vector<std::pair<std::string,long long>> surfaces;
        {Statement a(db,"SELECT surface,count(*) FROM entity_mentions WHERE entity_id=? GROUP BY surface LIMIT 200;");a.text(1,id);
         while(a.step()==SQLITE_ROW)surfaces.emplace_back(a.text(0),sqlite3_column_int64(a.p,1));}
        Statement ins(db,"INSERT OR IGNORE INTO entity_aliases(entity_id,alias,key,loose,script,mentions) VALUES(?,?,?,?,?,?);");
        for(const auto& [alias,count]:surfaces) {
            sqlite3_reset(ins.p);ins.text(1,id);ins.text(2,alias);ins.text(3,extract::strict_key(alias));ins.text(4,extract::loose_key(alias));
            ins.text(5,extract::script_of(alias));bind_int(ins,6,count);ins.step();
        }
    }
}
void rebuild_projects(sqlite3* db) {
    exec(db,R"sql(
DELETE FROM project_sources; DELETE FROM project_episodes; DELETE FROM project_entities;
DELETE FROM projects WHERE entity_id NOT IN (SELECT id FROM entities WHERE type='project');
INSERT OR IGNORE INTO projects(id,entity_id) SELECT 'pr-'||substr(id,4),id FROM entities WHERE type='project';
INSERT OR IGNORE INTO project_sources(project_id,source_id,via) SELECT p.id,m.source_id,'mention' FROM projects p JOIN entity_mentions m ON m.entity_id=p.entity_id;
INSERT OR IGNORE INTO project_episodes(project_id,episode_id,via)
 SELECT DISTINCT ps.project_id,em.episode_id,'member' FROM project_sources ps JOIN episode_members em ON em.source_id=ps.source_id;
INSERT OR IGNORE INTO project_episodes(project_id,episode_id,via)
 SELECT DISTINCT p.id,e.id,'title' FROM projects p JOIN entity_aliases a ON a.entity_id=p.entity_id JOIN episodes e ON instr(e.title,a.alias)>0 WHERE length(a.alias)>=3;
INSERT OR IGNORE INTO project_sources(project_id,source_id,via)
 SELECT pe.project_id,em.source_id,'episode' FROM project_episodes pe JOIN episode_members em ON em.episode_id=pe.episode_id;
INSERT INTO project_entities(project_id,entity_id,shared_sources)
 SELECT ps.project_id,m.entity_id,count(DISTINCT m.source_id) FROM project_sources ps JOIN entity_mentions m ON m.source_id=ps.source_id
 JOIN projects p ON p.id=ps.project_id WHERE m.entity_id<>p.entity_id GROUP BY ps.project_id,m.entity_id;
)sql");
}

// ---------------------------------------------------------------- extraction into the store
struct Pending {std::string id,text,language,metadata;long long seconds=0;};
std::string fold_sentence(const std::string& s) {  // identity of a decision sentence: case and spacing folded
    std::string o;for(char c:s){const auto u=static_cast<unsigned char>(c);if(u<0x80&&!std::isalnum(u))continue;o+=static_cast<char>(u<0x80?std::tolower(u):u);}
    return o;
}
struct Counts {long long mentions=0,facts=0;};
Counts store_extraction(sqlite3* db,const Pending& p,const extract::Extraction& x,const std::vector<std::pair<std::string,extract::Mention>>& field_mentions,
                        std::set<std::string>& touched) {
    Counts n;
    std::vector<std::string> ids(x.mentions.size());
    Statement mention(db,"INSERT OR IGNORE INTO entity_mentions(source_id,entity_id,byte_start,byte_end,field,surface,rule,confidence) VALUES(?,?,?,?,?,?,?,?);");
    auto put=[&](const extract::Mention& m,const std::string& field)->std::string{
        const auto id=resolve_entity(db,m.type,m.name,m.confidence);if(id.empty())return id;
        sqlite3_reset(mention.p);mention.text(1,p.id);mention.text(2,id);bind_int(mention,3,static_cast<long long>(m.start));
        bind_int(mention,4,static_cast<long long>(m.end));mention.text(5,field);mention.text(6,m.surface);mention.text(7,m.rule);
        check(sqlite3_bind_double(mention.p,8,m.confidence));mention.step();n.mentions+=sqlite3_changes(db);touched.insert(id);return id;
    };
    for(std::size_t k=0;k<x.mentions.size();++k)ids[k]=put(x.mentions[k],"text");
    for(const auto& [field,m]:field_mentions)put(m,field);
    std::string project_context;  // a project named anywhere in this source
    for(std::size_t k=0;k<x.mentions.size();++k)if(x.mentions[k].type==extract::EntityType::project&&!ids[k].empty()){project_context=ids[k];break;}
    Statement fact(db,"INSERT OR IGNORE INTO facts(id,type,predicate,subject_id,object_entity_id,value,value_seconds,confidence,rule) VALUES(?,?,?,?,?,?,?,?,?);");
    Statement raise(db,"UPDATE facts SET confidence=max(confidence,?) WHERE id=?;");
    Statement link(db,"INSERT OR IGNORE INTO fact_sources(fact_id,source_id,byte_start,byte_end,subject_basis) VALUES(?,?,?,?,?);");
    for(const auto& f:x.facts) {
        std::string subject=f.subject>=0?ids[static_cast<std::size_t>(f.subject)]:std::string(),basis=subject.empty()?"none":"explicit";
        double confidence=f.confidence;
        if(subject.empty()&&!project_context.empty()&&f.type!="relationship"&&f.type!="role"){subject=project_context;basis="same_source";confidence-=0.15;}
        const std::string object=f.object_entity>=0?ids[static_cast<std::size_t>(f.object_entity)]:std::string();
        if((f.type=="role"||f.type=="relationship")&&(subject.empty()||object.empty()))continue;
        const auto identity=f.type+"|"+f.predicate+"|"+subject+"|"+object+"|"+f.value+"|"+(f.type=="decision"?fold_sentence(p.text.substr(f.start,f.end-f.start)):"");
        const auto id=short_hash("fa-",identity);
        sqlite3_reset(fact.p);fact.text(1,id);fact.text(2,f.type);fact.text(3,f.predicate);
        if(subject.empty())check(sqlite3_bind_null(fact.p,4));else fact.text(4,subject);
        if(object.empty())check(sqlite3_bind_null(fact.p,5));else fact.text(5,object);
        fact.text(6,f.value);if(f.value_seconds)bind_int(fact,7,*f.value_seconds);else check(sqlite3_bind_null(fact.p,7));
        check(sqlite3_bind_double(fact.p,8,confidence));fact.text(9,f.rule);fact.step();
        if(!sqlite3_changes(db)){sqlite3_reset(raise.p);check(sqlite3_bind_double(raise.p,1,confidence));raise.text(2,id);raise.step();}
        sqlite3_reset(link.p);link.text(1,id);link.text(2,p.id);bind_int(link,3,static_cast<long long>(f.start));bind_int(link,4,static_cast<long long>(f.end));
        link.text(5,basis);link.step();n.facts+=sqlite3_changes(db);
    }
    Statement state(db,"INSERT OR REPLACE INTO extraction_state(source_id,extractor,mentions,facts) VALUES(?,?,?,?);");
    state.text(1,p.id);state.text(2,extract::extractor_version);bind_int(state,3,n.mentions);bind_int(state,4,n.facts);state.step();
    return n;
}
// People named in import metadata (chat sender, mail author) are evidence too; their provenance is the field.
std::vector<std::pair<std::string,extract::Mention>> metadata_mentions(const std::string& metadata) {
    std::vector<std::pair<std::string,extract::Mention>> out;
    json m;try{m=json::parse(metadata);}catch(...){return out;}
    if(!m.is_object())return out;
    for(const char* field:{"sender","author","from"}) {
        if(!m.contains(field)||!m[field].is_string())continue;
        const auto v=m[field].get<std::string>();
        if(v.empty()||v.size()>80||v.find('@')!=std::string::npos||v.find_first_of("0123456789")!=std::string::npos)continue;
        out.push_back({std::string("metadata.")+field,{extract::EntityType::person,0,v.size(),v,v,"metadata_"+std::string(field),0.95}});
    }
    return out;
}
// Names confirmed by a rule somewhere in the user's memories form the user's own gazetteer.
bool gazetteer_worthy(const std::string& surface,const std::string& rule) {
    if(surface.size()<3||rule=="gazetteer"||rule=="seed_place")return false;
    const auto c=static_cast<unsigned char>(surface[0]);return c>=0x80||(c>='A'&&c<='Z');  // Latin names are capitalised
}
std::vector<extract::KnownName> known_names(sqlite3* db) {
    std::vector<extract::KnownName> out;
    Statement s(db,"SELECT DISTINCT m.surface,e.type,m.rule FROM entity_mentions m JOIN entities e ON e.id=m.entity_id WHERE m.field='text';");
    std::set<std::string> seen;
    while(s.step()==SQLITE_ROW) {
        const auto surface=s.text(0);const auto type=extract::parse_type(s.text(1));
        if(type&&gazetteer_worthy(surface,s.text(2))&&seen.insert(surface).second)out.push_back({surface,*type});
    }
    return out;
}
std::vector<std::pair<std::size_t,std::size_t>> text_spans(sqlite3* db,const std::string& source_id) {
    std::vector<std::pair<std::size_t,std::size_t>> spans;
    Statement s(db,"SELECT byte_start,byte_end FROM entity_mentions WHERE source_id=? AND field='text';");s.text(1,source_id);
    while(s.step()==SQLITE_ROW)spans.emplace_back(static_cast<std::size_t>(sqlite3_column_int64(s.p,0)),static_cast<std::size_t>(sqlite3_column_int64(s.p,1)));
    return spans;
}
// Newly learned names are looked up in older sources (FTS for spaced scripts, a substring scan for Han).
std::pair<long long,long long> backfill(sqlite3* db,const std::vector<extract::KnownName>& names,const std::set<std::string>& skip,std::set<std::string>& touched) {
    std::set<std::string> candidates;std::vector<std::string> han;
    for(const auto& n:names) {
        if(extract::script_of(n.surface).find("han")!=std::string::npos){han.push_back(n.surface);continue;}
        Statement s(db,"SELECT o.id FROM memory_fts JOIN observations o ON o.rowid=memory_fts.rowid WHERE memory_fts MATCH ? LIMIT 5000;");
        s.text(1,query::quote(n.surface));while(s.step()==SQLITE_ROW)candidates.insert(s.text(0));
    }
    if(!han.empty()) {
        std::string any="0";for(std::size_t i=0;i<han.size()&&i<64;++i)any+=" OR instr(lens_text(text,text_codec,text_zstd),?)>0";
        Statement s(db,("SELECT id FROM observations WHERE "+any+" LIMIT 5000;").c_str());
        for(std::size_t i=0;i<han.size()&&i<64;++i)s.text(static_cast<int>(i+1),han[i]);
        while(s.step()==SQLITE_ROW)candidates.insert(s.text(0));
    }
    long long scanned=0,added=0;
    Statement mention(db,"INSERT OR IGNORE INTO entity_mentions(source_id,entity_id,byte_start,byte_end,field,surface,rule,confidence) VALUES(?,?,?,?,'text',?,?,?);");
    for(const auto& id:candidates) {
        if(skip.contains(id))continue;
        if(scanned>=max_backfill_sources)break;
        ++scanned;const auto text=source_text(db,id);
        std::vector<extract::Mention> existing;for(const auto& [a,b]:text_spans(db,id))existing.push_back({extract::EntityType::person,a,b,{},{},{},0});
        for(const auto& m:extract::gazetteer_mentions(text,names,existing)) {
            const auto entity=resolve_entity(db,m.type,m.name,m.confidence);if(entity.empty())continue;
            sqlite3_reset(mention.p);mention.text(1,id);mention.text(2,entity);bind_int(mention,3,static_cast<long long>(m.start));
            bind_int(mention,4,static_cast<long long>(m.end));mention.text(5,m.surface);mention.text(6,m.rule);check(sqlite3_bind_double(mention.p,7,m.confidence));
            mention.step();added+=sqlite3_changes(db);touched.insert(entity);
        }
    }
    return {scanned,added};
}

// ---------------------------------------------------------------- facts as JSON
const char* fact_columns="SELECT f.id,f.type,f.predicate,f.subject_id,f.object_entity_id,f.value,f.value_seconds,f.confidence,f.rule FROM facts f ";
json brief_entity(sqlite3* db,const std::string& id) {
    if(id.empty())return nullptr;
    Statement s(db,"SELECT id,type,name FROM entities WHERE id=?;");s.text(1,id);
    return s.step()==SQLITE_ROW?json{{"id",s.text(0)},{"type",s.text(1)},{"name",s.text(2)}}:json(nullptr);
}
json fact_row(sqlite3* db,Statement& s,int source_limit=5) {
    const auto id=s.text(0);
    json f={{"id",id},{"type",s.text(1)},{"predicate",s.text(2)},{"subject",brief_entity(db,s.text(3))},{"object_entity",brief_entity(db,s.text(4))},
            {"value",s.text(5).empty()?json(nullptr):json(s.text(5))},{"value_date",time_or_null(s.p,6)},{"confidence",sqlite3_column_double(s.p,7)},
            {"rule",s.text(8)},{"status","observed"},{"derived",true}};
    if(f["value_date"].is_string())f["value_date"]=f["value_date"].get<std::string>().substr(0,10);
    json sources=json::array();std::set<std::string> bases;long long count=0;json first=nullptr,last=nullptr;
    {Statement agg(db,"SELECT count(*),min(m.event_seconds),max(m.event_seconds) FROM fact_sources fs JOIN source_metadata m ON m.source_id=fs.source_id WHERE fs.fact_id=?;");
     agg.text(1,id);agg.step();count=sqlite3_column_int64(agg.p,0);first=time_or_null(agg.p,1);last=time_or_null(agg.p,2);}
    {Statement b(db,"SELECT DISTINCT subject_basis FROM fact_sources WHERE fact_id=?;");b.text(1,id);while(b.step()==SQLITE_ROW)bases.insert(b.text(0));}
    // Only the returned sources are decrypted and decompressed.
    Statement src(db,"SELECT fs.source_id,fs.byte_start,fs.byte_end,fs.subject_basis,lens_text(o.text,o.text_codec,o.text_zstd),o.captured_at,o.device,"
                     "m.source_application FROM fact_sources fs JOIN observations o ON o.id=fs.source_id JOIN source_metadata m ON m.source_id=o.id "
                     "WHERE fs.fact_id=? ORDER BY m.event_seconds,fs.source_id LIMIT ?;");
    src.text(1,id);bind_int(src,2,source_limit);
    while(src.step()==SQLITE_ROW) {
        const auto text=src.text(4);const auto a=static_cast<std::size_t>(sqlite3_column_int64(src.p,1)),b=static_cast<std::size_t>(sqlite3_column_int64(src.p,2));
        if(a>b||b>text.size())continue;
        sources.push_back({{"source_id",src.text(0)},{"timestamp",src.text(5)},{"device",src.text(6)},{"source_application",src.text(7)},
                           {"quote",text.substr(a,b-a)},{"byte_offset",a},{"byte_end",b},{"subject_basis",src.text(3)}});
    }
    // Observed: the statement is verbatim in the source. The subject is explicit when named in the same sentence;
    // otherwise it was inferred from the same source (never presented as certain).
    const std::string basis=bases.contains("explicit")?"explicit":bases.contains("same_source")?"inferred":"none";
    f["subject_basis"]=basis;f["certain"]=basis!="inferred";
    f["object"]=sources.empty()?json(nullptr):sources[0]["quote"];f["sources"]=sources;f["source_count"]=count;
    f["first_seen"]=first;f["last_seen"]=last;
    return f;
}
// Entities named in a question: exact or romanised/folded keys of 1–3 word n-grams, and Han aliases by substring.
std::vector<std::pair<std::string,std::string>> match_entities(sqlite3* db,const std::string& text) {
    std::vector<std::pair<std::string,std::string>> out;std::set<std::string> seen;
    auto add=[&](const std::string& id,const std::string& phrase){if(seen.insert(id).second)out.emplace_back(id,phrase);};
    Statement by_key(db,"SELECT entity_id,alias FROM entity_aliases WHERE key=? UNION ALL SELECT id,name FROM entities WHERE key=? LIMIT 8;");
    Statement by_loose(db,"SELECT entity_id,alias FROM entity_aliases WHERE loose=? LIMIT 8;");
    for(const auto& [strict,loose]:extract::query_keys(text)) {
        sqlite3_reset(by_key.p);by_key.text(1,strict);by_key.text(2,strict);bool hit=false;
        while(by_key.step()==SQLITE_ROW){add(by_key.text(0),by_key.text(1));hit=true;}
        if(!hit&&loose.size()>=4){sqlite3_reset(by_loose.p);by_loose.text(1,loose);while(by_loose.step()==SQLITE_ROW)add(by_loose.text(0),by_loose.text(1));}
    }
    Statement han(db,"SELECT entity_id,alias FROM entity_aliases WHERE script LIKE '%han%' AND length(alias)>=2 AND instr(?,alias)>0 LIMIT 16;");
    han.text(1,text);while(han.step()==SQLITE_ROW)add(han.text(0),han.text(1));
    if(out.size()>16)out.resize(16);
    return out;
}
std::string resolve_target(sqlite3* db,const json& j) {  // {"id": …} or {"name": …[, "type": …]}
    if(j.contains("id"))return required(j,"id",64);
    const auto name=required(j,"name",256);
    std::string type;if(j.contains("type")){type=required(j,"type",32);if(!extract::parse_type(type))throw Error("invalid_type");}
    for(const auto& [id,phrase]:match_entities(db,name)) {
        Statement s(db,"SELECT type FROM entities WHERE id=?;");s.text(1,id);
        if(s.step()==SQLITE_ROW&&(type.empty()||s.text(0)==type))return id;
    }
    return {};
}
}  // namespace

void create_memory_layer_schema(sqlite3* db) {
    exec(db,R"sql(
CREATE TABLE IF NOT EXISTS entities(id TEXT PRIMARY KEY,type TEXT NOT NULL CHECK(type IN('person','organization','place','project','product')),
 name TEXT NOT NULL,key TEXT NOT NULL,loose TEXT NOT NULL,script TEXT NOT NULL,mention_count INTEGER NOT NULL DEFAULT 0,
 source_count INTEGER NOT NULL DEFAULT 0,first_seconds INTEGER,last_seconds INTEGER,confidence REAL NOT NULL DEFAULT 0,UNIQUE(type,key));
CREATE INDEX IF NOT EXISTS entity_loose ON entities(type,loose);
CREATE TABLE IF NOT EXISTS entity_aliases(entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,alias TEXT NOT NULL,key TEXT NOT NULL,
 loose TEXT NOT NULL,script TEXT NOT NULL,mentions INTEGER NOT NULL,PRIMARY KEY(entity_id,alias));
CREATE INDEX IF NOT EXISTS entity_alias_key ON entity_aliases(key);
CREATE INDEX IF NOT EXISTS entity_alias_loose ON entity_aliases(loose);
CREATE TABLE IF NOT EXISTS entity_mentions(id INTEGER PRIMARY KEY,source_id TEXT NOT NULL REFERENCES observations(id) ON DELETE CASCADE,
 entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,byte_start INTEGER NOT NULL,byte_end INTEGER NOT NULL,field TEXT NOT NULL,
 surface TEXT NOT NULL,rule TEXT NOT NULL,confidence REAL NOT NULL CHECK(confidence>=0 AND confidence<=1),UNIQUE(source_id,field,byte_start,entity_id));
CREATE INDEX IF NOT EXISTS entity_mention_entity ON entity_mentions(entity_id);
CREATE TABLE IF NOT EXISTS facts(id TEXT PRIMARY KEY,type TEXT NOT NULL,predicate TEXT NOT NULL,subject_id TEXT REFERENCES entities(id) ON DELETE CASCADE,
 object_entity_id TEXT REFERENCES entities(id) ON DELETE SET NULL,value TEXT NOT NULL,value_seconds INTEGER,
 confidence REAL NOT NULL CHECK(confidence>=0 AND confidence<=1),rule TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS fact_subject ON facts(subject_id);
CREATE INDEX IF NOT EXISTS fact_object ON facts(object_entity_id);
CREATE INDEX IF NOT EXISTS fact_type_time ON facts(type,value_seconds);
CREATE TABLE IF NOT EXISTS fact_sources(fact_id TEXT NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
 source_id TEXT NOT NULL REFERENCES observations(id) ON DELETE CASCADE,byte_start INTEGER NOT NULL,byte_end INTEGER NOT NULL,
 subject_basis TEXT NOT NULL,PRIMARY KEY(fact_id,source_id,byte_start));
CREATE INDEX IF NOT EXISTS fact_source_source ON fact_sources(source_id);
CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,entity_id TEXT NOT NULL UNIQUE REFERENCES entities(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS project_sources(project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 source_id TEXT NOT NULL REFERENCES observations(id) ON DELETE CASCADE,via TEXT NOT NULL,PRIMARY KEY(project_id,source_id));
CREATE INDEX IF NOT EXISTS project_source_source ON project_sources(source_id);
CREATE TABLE IF NOT EXISTS project_episodes(project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 episode_id TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,via TEXT NOT NULL,PRIMARY KEY(project_id,episode_id));
CREATE TABLE IF NOT EXISTS project_entities(project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,shared_sources INTEGER NOT NULL,PRIMARY KEY(project_id,entity_id));
CREATE TABLE IF NOT EXISTS extraction_state(source_id TEXT PRIMARY KEY REFERENCES observations(id) ON DELETE CASCADE,
 extractor TEXT NOT NULL,mentions INTEGER NOT NULL,facts INTEGER NOT NULL);
CREATE TRIGGER IF NOT EXISTS fact_sources_orphan AFTER DELETE ON fact_sources BEGIN
 DELETE FROM facts WHERE id=old.fact_id AND NOT EXISTS(SELECT 1 FROM fact_sources WHERE fact_id=old.fact_id); END;
CREATE TRIGGER IF NOT EXISTS entity_mentions_orphan AFTER DELETE ON entity_mentions BEGIN
 DELETE FROM entities WHERE id=old.entity_id AND NOT EXISTS(SELECT 1 FROM entity_mentions WHERE entity_id=old.entity_id); END;
INSERT OR REPLACE INTO schema_migrations VALUES(8,strftime('%Y-%m-%dT%H:%M:%fZ','now'));
PRAGMA user_version=8;)sql");
}

json consolidate_memory_layers(sqlite3* db,const json& j) {
    const long long limit=j.contains("extract_limit")?j.at("extract_limit").get<long long>():2000;
    if(limit<1||limit>100000)throw Error("invalid_limit");
    Transaction tx(db);
    std::set<std::string> touched,batch;
    {   // sources extracted by an older rule set are re-extracted
        Statement t(db,"SELECT DISTINCT entity_id FROM entity_mentions WHERE source_id IN (SELECT source_id FROM extraction_state WHERE extractor<>?);");
        t.text(1,extract::extractor_version);while(t.step()==SQLITE_ROW)touched.insert(t.text(0));
        Statement s(db,"DELETE FROM entity_mentions WHERE source_id IN (SELECT source_id FROM extraction_state WHERE extractor<>?);");s.text(1,extract::extractor_version);s.step();
        Statement f(db,"DELETE FROM fact_sources WHERE source_id IN (SELECT source_id FROM extraction_state WHERE extractor<>?);");f.text(1,extract::extractor_version);f.step();
        Statement x(db,"DELETE FROM extraction_state WHERE extractor<>?;");x.text(1,extract::extractor_version);x.step();
    }
    std::vector<Pending> pending;
    {Statement s(db,"SELECT o.id,lens_text(o.text,o.text_codec,o.text_zstd),o.language,coalesce(m.event_seconds,0),m.metadata FROM observations o "
                    "JOIN source_metadata m ON m.source_id=o.id WHERE NOT EXISTS(SELECT 1 FROM extraction_state x WHERE x.source_id=o.id) ORDER BY o.rowid LIMIT ?;");
     bind_int(s,1,limit);while(s.step()==SQLITE_ROW)pending.push_back({s.text(0),s.text(1),s.text(2),s.text(4),sqlite3_column_int64(s.p,3)});}
    // Two passes over the batch: rule mentions first, so names learned anywhere in the batch reach every source
    // of it as gazetteer mentions before its facts (whose subjects need those mentions) are extracted.
    const auto known=known_names(db);std::set<std::string> known_before;for(const auto& k:known)known_before.insert(k.surface);
    auto names=known;std::set<std::string> name_set=known_before;
    std::vector<std::vector<extract::Mention>> mentions;mentions.reserve(pending.size());
    for(const auto& p:pending) {
        mentions.push_back(extract::extract_mentions(p.text));
        for(const auto& m:mentions.back())if(gazetteer_worthy(m.surface,m.rule)&&name_set.insert(m.surface).second)names.push_back({m.surface,m.type});
    }
    Counts total;
    for(std::size_t i=0;i<pending.size();++i) {
        const auto& p=pending[i];batch.insert(p.id);
        extract::Extraction x;x.mentions=std::move(mentions[i]);
        const auto more=extract::gazetteer_mentions(p.text,names,x.mentions);x.mentions.insert(x.mentions.end(),more.begin(),more.end());
        x.facts=extract::extract_facts(p.text,p.seconds,p.language,x.mentions);
        const auto c=store_extraction(db,p,x,metadata_mentions(p.metadata),touched);total.mentions+=c.mentions;total.facts+=c.facts;
    }
    std::vector<extract::KnownName> learned;
    for(const auto& n:names)if(!known_before.contains(n.surface))learned.push_back(n);
    std::pair<long long,long long> filled{0,0};
    if(!learned.empty())filled=backfill(db,learned,batch,touched);  // older sources may name what this batch taught
    refresh_entities(db,touched);
    rebuild_projects(db);
    long long remaining=0,entities=0,facts=0,projects=0;
    {Statement s(db,"SELECT (SELECT count(*) FROM observations o WHERE NOT EXISTS(SELECT 1 FROM extraction_state x WHERE x.source_id=o.id)),"
                    "(SELECT count(*) FROM entities),(SELECT count(*) FROM facts),(SELECT count(*) FROM projects);");s.step();
     remaining=sqlite3_column_int64(s.p,0);entities=sqlite3_column_int64(s.p,1);facts=sqlite3_column_int64(s.p,2);projects=sqlite3_column_int64(s.p,3);}
    tx.commit();
    return {{"extractor",extract::extractor_version},{"sources_extracted",pending.size()},{"pending_sources",remaining},{"mentions_added",total.mentions+filled.second},
            {"fact_links_added",total.facts},{"gazetteer_names_learned",learned.size()},{"backfill_sources_scanned",filled.first},
            {"entities",entities},{"facts",facts},{"projects",projects}};
}

std::set<std::string> entities_of_source(sqlite3* db,const std::string& source_id) {
    std::set<std::string> ids;Statement s(db,"SELECT DISTINCT entity_id FROM entity_mentions WHERE source_id=?;");s.text(1,source_id);
    while(s.step()==SQLITE_ROW)ids.insert(s.text(0));return ids;
}
void refresh_after_delete(sqlite3* db,const std::set<std::string>& ids){refresh_entities(db,ids);rebuild_projects(db);}

json list_entities(sqlite3* db,const json& j) {
    const int limit=limit_of(j,25,200);
    std::string where="WHERE 1=1";std::vector<std::string> values;
    if(j.contains("type")){const auto t=required(j,"type",32);if(!extract::parse_type(t))throw Error("invalid_type");where+=" AND type=?";values.push_back(t);}
    if(j.contains("start")){where+=" AND last_seconds>=?";values.push_back(std::to_string(epoch(required(j,"start",64))));}
    if(j.contains("end")){where+=" AND first_seconds<?";values.push_back(std::to_string(epoch(required(j,"end",64))));}
    if(j.contains("query")) {
        const auto q=required(j,"query",256);std::string in;
        for(const auto& [id,phrase]:match_entities(db,q)){in+=in.empty()?"?":",?";values.push_back(id);}
        if(in.empty())return {{"ok",true},{"entities",json::array()},{"not_found",true}};
        where+=" AND id IN ("+in+")";
    }
    Statement s(db,(std::string(entity_columns)+where+" ORDER BY mention_count DESC,id LIMIT "+std::to_string(limit)+";").c_str());
    query::bind_values(s,values);
    json out=json::array();while(s.step()==SQLITE_ROW)out.push_back(entity_row(s,db));
    return {{"ok",true},{"entities",out},{"not_found",out.empty()}};
}

json entity_context(sqlite3* db,const json& j) {
    const auto id=resolve_target(db,j);
    const auto entity=id.empty()?json(nullptr):entity_by_id(db,id);
    if(entity.is_null())return {{"ok",true},{"not_found",true},{"entity",nullptr}};
    const int limit=limit_of(j,20,100);
    json aliases=json::array(),mentions=json::array(),facts=json::array(),related=json::array(),projects=json::array(),episodes=json::array();
    {Statement a(db,"SELECT alias,script,mentions FROM entity_aliases WHERE entity_id=? ORDER BY mentions DESC,alias LIMIT 50;");a.text(1,id);
     while(a.step()==SQLITE_ROW)aliases.push_back({{"alias",a.text(0)},{"script",a.text(1)},{"mentions",sqlite3_column_int64(a.p,2)}});}
    {Statement m(db,("SELECT em.source_id,em.byte_start,em.byte_end,em.field,em.rule,em.confidence,em.surface,o.captured_at,s.source_application,o.device,"
                     "lens_text(o.text,o.text_codec,o.text_zstd) FROM entity_mentions em JOIN observations o ON o.id=em.source_id JOIN source_metadata s ON s.source_id=o.id "
                     "WHERE em.entity_id=? ORDER BY s.event_seconds DESC,em.id LIMIT "+std::to_string(limit)+";").c_str());m.text(1,id);
     while(m.step()==SQLITE_ROW) {
        const auto field=m.text(3);const auto text=m.text(10);
        mentions.push_back({{"source_id",m.text(0)},{"field",field},{"rule",m.text(4)},{"confidence",sqlite3_column_double(m.p,5)},{"surface",m.text(6)},
            {"timestamp",m.text(7)},{"source_application",m.text(8)},{"device",m.text(9)},{"byte_offset",sqlite3_column_int64(m.p,1)},{"byte_end",sqlite3_column_int64(m.p,2)},
            {"excerpt",field=="text"?excerpt(text,static_cast<std::size_t>(sqlite3_column_int64(m.p,1)),static_cast<std::size_t>(sqlite3_column_int64(m.p,2))):json(nullptr)}});
     }}
    {Statement f(db,(std::string(fact_columns)+"WHERE f.subject_id=? OR f.object_entity_id=? ORDER BY coalesce(f.value_seconds,0) DESC,f.id LIMIT 50;").c_str());
     f.text(1,id);f.text(2,id);while(f.step()==SQLITE_ROW)facts.push_back(fact_row(db,f,3));}
    {Statement r(db,"SELECT e.id,e.type,e.name,count(DISTINCT b.source_id) n FROM entity_mentions a JOIN entity_mentions b ON b.source_id=a.source_id AND b.entity_id<>a.entity_id "
                    "JOIN entities e ON e.id=b.entity_id WHERE a.entity_id=? GROUP BY e.id ORDER BY n DESC,e.id LIMIT 20;");r.text(1,id);
     while(r.step()==SQLITE_ROW)related.push_back({{"id",r.text(0)},{"type",r.text(1)},{"name",r.text(2)},{"shared_sources",sqlite3_column_int64(r.p,3)}});}
    {Statement p(db,"SELECT p.id,e.name,'project' FROM projects p JOIN entities e ON e.id=p.entity_id WHERE p.entity_id=? UNION ALL "
                    "SELECT p.id,e.name,'member' FROM project_entities pe JOIN projects p ON p.id=pe.project_id JOIN entities e ON e.id=p.entity_id WHERE pe.entity_id=? LIMIT 20;");
     p.text(1,id);p.text(2,id);while(p.step()==SQLITE_ROW)projects.push_back({{"id",p.text(0)},{"name",p.text(1)},{"role",p.text(2)}});}
    {Statement e(db,"SELECT DISTINCT ep.id,ep.application,ep.title,ep.started_at,ep.ended_at FROM entity_mentions m JOIN episode_members em ON em.source_id=m.source_id "
                    "JOIN episodes ep ON ep.id=em.episode_id WHERE m.entity_id=? ORDER BY ep.start_seconds DESC LIMIT 10;");e.text(1,id);
     while(e.step()==SQLITE_ROW)episodes.push_back({{"id",e.text(0)},{"application",e.text(1)},{"title",e.text(2)},{"started_at",e.text(3)},{"ended_at",e.text(4)}});}
    return {{"ok",true},{"not_found",false},{"entity",entity},{"aliases",aliases},{"mentions",mentions},{"facts",facts},{"related",related},
            {"projects",projects},{"episodes",episodes}};
}

json list_facts(sqlite3* db,const json& j) {
    static const std::set<std::string> types={"deadline","meeting","amount","decision","role","relationship"};
    const int limit=limit_of(j,50,200);
    std::string where="WHERE 1=1";std::vector<std::string> values;std::vector<long long> bounds;  // bounds are bound after values
    const std::string when="coalesce(f.value_seconds,(SELECT min(m.event_seconds) FROM fact_sources fs JOIN source_metadata m ON m.source_id=fs.source_id WHERE fs.fact_id=f.id))";
    std::vector<std::string> entity_ids;
    if(j.contains("entity_id"))entity_ids.push_back(required(j,"entity_id",64));
    if(j.contains("entity")) {
        for(const auto& [id,phrase]:match_entities(db,required(j,"entity",256)))entity_ids.push_back(id);
        if(entity_ids.empty())return {{"ok",true},{"facts",json::array()},{"not_found",true}};
    }
    if(!entity_ids.empty()) {
        std::string in;for(const auto& id:entity_ids){in+=in.empty()?"?":",?";values.push_back(id);}
        for(const auto& id:entity_ids)values.push_back(id);
        where+=" AND (f.subject_id IN ("+in+") OR f.object_entity_id IN ("+in+"))";
    }
    if(j.contains("type")){const auto t=required(j,"type",32);if(!types.contains(t))throw Error("invalid_type");where+=" AND f.type=?";values.push_back(t);}
    if(j.contains("project_id")) {
        const auto p=required(j,"project_id",64);
        where+=" AND (f.subject_id=(SELECT entity_id FROM projects WHERE id=?) OR EXISTS(SELECT 1 FROM fact_sources fs JOIN project_sources ps ON ps.source_id=fs.source_id WHERE fs.fact_id=f.id AND ps.project_id=?))";
        values.push_back(p);values.push_back(p);
    }
    if(j.contains("source_id")){where+=" AND EXISTS(SELECT 1 FROM fact_sources fs WHERE fs.fact_id=f.id AND fs.source_id=?)";values.push_back(required(j,"source_id"));}
    if(j.contains("start")){where+=" AND "+when+">=?";bounds.push_back(epoch(required(j,"start",64)));}
    if(j.contains("end")){where+=" AND "+when+"<?";bounds.push_back(epoch(required(j,"end",64)));}
    Statement s(db,(std::string(fact_columns)+where+" ORDER BY "+when+" DESC,f.id LIMIT "+std::to_string(limit)+";").c_str());
    // The time expression has no column affinity, so its bounds are bound as integers.
    query::bind_values(s,values);
    for(std::size_t i=0;i<bounds.size();++i)bind_int(s,static_cast<int>(values.size()+i+1),bounds[i]);
    json out=json::array();while(s.step()==SQLITE_ROW)out.push_back(fact_row(db,s));
    return {{"ok",true},{"facts",out},{"not_found",out.empty()}};
}

namespace {
json project_summary(sqlite3* db,const std::string& id) {
    Statement s(db,"SELECT p.id,p.entity_id,e.name,"
                   "(SELECT count(*) FROM project_sources WHERE project_id=p.id),(SELECT count(*) FROM project_sources WHERE project_id=p.id AND via='mention'),"
                   "(SELECT count(*) FROM project_episodes WHERE project_id=p.id),(SELECT count(*) FROM project_entities WHERE project_id=p.id),"
                   "(SELECT min(m.event_seconds) FROM project_sources ps JOIN source_metadata m ON m.source_id=ps.source_id WHERE ps.project_id=p.id),"
                   "(SELECT max(m.event_seconds) FROM project_sources ps JOIN source_metadata m ON m.source_id=ps.source_id WHERE ps.project_id=p.id),"
                   "(SELECT count(*) FROM facts f WHERE f.subject_id=p.entity_id OR EXISTS(SELECT 1 FROM fact_sources fs JOIN project_sources ps ON ps.source_id=fs.source_id "
                   " WHERE fs.fact_id=f.id AND ps.project_id=p.id)) FROM projects p JOIN entities e ON e.id=p.entity_id WHERE p.id=?;");
    s.text(1,id);if(s.step()!=SQLITE_ROW)return nullptr;
    json aliases=json::array();
    {Statement a(db,"SELECT alias FROM entity_aliases WHERE entity_id=? ORDER BY mentions DESC,alias LIMIT 8;");a.text(1,s.text(1));while(a.step()==SQLITE_ROW)aliases.push_back(a.text(0));}
    json people=json::array();
    {Statement p(db,"SELECT e.id,e.name FROM project_entities pe JOIN entities e ON e.id=pe.entity_id WHERE pe.project_id=? AND e.type='person' "
                    "ORDER BY pe.shared_sources DESC,e.id LIMIT 5;");p.text(1,id);while(p.step()==SQLITE_ROW)people.push_back({{"id",p.text(0)},{"name",p.text(1)}});}
    return {{"id",s.text(0)},{"entity_id",s.text(1)},{"name",s.text(2)},{"aliases",aliases},{"source_count",sqlite3_column_int64(s.p,3)},
            {"mention_sources",sqlite3_column_int64(s.p,4)},{"episode_count",sqlite3_column_int64(s.p,5)},{"entity_count",sqlite3_column_int64(s.p,6)},
            {"first_seen",time_or_null(s.p,7)},{"last_seen",time_or_null(s.p,8)},{"fact_count",sqlite3_column_int64(s.p,9)},{"people",people},{"derived",true}};
}
std::string resolve_project(sqlite3* db,const json& j) {
    if(j.contains("id"))return required(j,"id",64);
    const auto name=required(j,"name",256);
    for(const auto& [id,phrase]:match_entities(db,name)) {
        Statement s(db,"SELECT id FROM projects WHERE entity_id=?;");s.text(1,id);if(s.step()==SQLITE_ROW)return s.text(0);
    }
    return {};
}
}

json list_projects(sqlite3* db,const json& j) {
    const int limit=limit_of(j,25,200);
    std::vector<std::string> ids;
    if(j.contains("query")) {
        for(const auto& [id,phrase]:match_entities(db,required(j,"query",256))){Statement s(db,"SELECT id FROM projects WHERE entity_id=?;");s.text(1,id);if(s.step()==SQLITE_ROW)ids.push_back(s.text(0));}
    } else {
        Statement s(db,("SELECT p.id FROM projects p LEFT JOIN project_sources ps ON ps.project_id=p.id LEFT JOIN source_metadata m ON m.source_id=ps.source_id "
                        "GROUP BY p.id ORDER BY max(m.event_seconds) DESC,p.id LIMIT "+std::to_string(limit)+";").c_str());
        while(s.step()==SQLITE_ROW)ids.push_back(s.text(0));
    }
    json out=json::array();for(const auto& id:ids){if(static_cast<int>(out.size())>=limit)break;if(auto p=project_summary(db,id);!p.is_null())out.push_back(p);}
    return {{"ok",true},{"projects",out},{"not_found",out.empty()}};
}

json project_context(sqlite3* db,const json& j) {
    const auto id=resolve_project(db,j);
    const auto project=id.empty()?json(nullptr):project_summary(db,id);
    if(project.is_null())return {{"ok",true},{"not_found",true},{"project",nullptr}};
    const int limit=limit_of(j,20,100);
    const auto entity_id=project["entity_id"].get<std::string>();
    json entities=json::array(),episodes=json::array(),facts=json::array(),sources=json::array();
    {Statement e(db,"SELECT e.id,e.type,e.name,pe.shared_sources FROM project_entities pe JOIN entities e ON e.id=pe.entity_id WHERE pe.project_id=? "
                    "ORDER BY pe.shared_sources DESC,e.id LIMIT 50;");e.text(1,id);
     while(e.step()==SQLITE_ROW)entities.push_back({{"id",e.text(0)},{"type",e.text(1)},{"name",e.text(2)},{"shared_sources",sqlite3_column_int64(e.p,3)}});}
    {Statement e(db,("SELECT ep.id,ep.application,ep.title,ep.started_at,ep.ended_at,ep.observation_count,pe.via FROM project_episodes pe JOIN episodes ep ON ep.id=pe.episode_id "
                     "WHERE pe.project_id=? ORDER BY ep.start_seconds DESC LIMIT "+std::to_string(limit)+";").c_str());e.text(1,id);
     while(e.step()==SQLITE_ROW)episodes.push_back({{"id",e.text(0)},{"application",e.text(1)},{"title",e.text(2)},{"started_at",e.text(3)},{"ended_at",e.text(4)},
                                                    {"observation_count",sqlite3_column_int64(e.p,5)},{"via",e.text(6)}});}
    {Statement f(db,(std::string(fact_columns)+"WHERE f.subject_id=? OR EXISTS(SELECT 1 FROM fact_sources fs JOIN project_sources ps ON ps.source_id=fs.source_id "
                     "WHERE fs.fact_id=f.id AND ps.project_id=?) ORDER BY coalesce(f.value_seconds,0) DESC,f.id LIMIT 50;").c_str());f.text(1,entity_id);f.text(2,id);
     while(f.step()==SQLITE_ROW) {
        auto fact=fact_row(db,f,3);
        std::string link="subject";
        if(!fact["subject"].is_object()||fact["subject"]["id"]!=entity_id) {
            Statement v(db,"SELECT min(ps.via) FROM fact_sources fs JOIN project_sources ps ON ps.source_id=fs.source_id WHERE fs.fact_id=? AND ps.project_id=?;");
            v.text(1,fact["id"].get<std::string>());v.text(2,id);v.step();link=v.text(0)=="mention"?"same_source":"same_episode";
        }
        fact["project_link"]=link;facts.push_back(fact);
     }}
    {Statement s(db,("SELECT ps.source_id,ps.via,o.captured_at,m.source_application,o.device,lens_text(o.text,o.text_codec,o.text_zstd) FROM project_sources ps "
                     "JOIN observations o ON o.id=ps.source_id JOIN source_metadata m ON m.source_id=o.id WHERE ps.project_id=? ORDER BY m.event_seconds DESC,o.id LIMIT "+std::to_string(limit)+";").c_str());
     s.text(1,id);
     while(s.step()==SQLITE_ROW){const auto text=s.text(5);sources.push_back({{"source_id",s.text(0)},{"via",s.text(1)},{"timestamp",s.text(2)},{"source_application",s.text(3)},
                                 {"device",s.text(4)},{"excerpt",excerpt(text,0,std::min<std::size_t>(text.size(),220),0)}});}}
    return {{"ok",true},{"not_found",false},{"project",project},{"entities",entities},{"episodes",episodes},{"facts",facts},{"sources",sources}};
}

void annotate_recall(sqlite3* db,const std::string& question,json& result,bool boost) {
    const auto matched=match_entities(db,question);
    std::set<std::string> matched_ids;json entities=json::array();
    for(const auto& [id,phrase]:matched){if(auto e=brief_entity(db,id);!e.is_null()){e["matched"]=phrase;entities.push_back(e);matched_ids.insert(id);}}
    auto& results=result["results"];
    for(auto& r:results) {
        if(!r.contains("source")||!r["source"].contains("id"))continue;
        const auto sid=r["source"]["id"].get<std::string>();
        json linked=json::array();bool hit=false;
        {Statement s(db,"SELECT DISTINCT e.id,e.type,e.name FROM entity_mentions m JOIN entities e ON e.id=m.entity_id WHERE m.source_id=? LIMIT 12;");s.text(1,sid);
         while(s.step()==SQLITE_ROW){linked.push_back({{"id",s.text(0)},{"type",s.text(1)},{"name",s.text(2)}});hit|=matched_ids.contains(s.text(0));}}
        json facts=json::array();
        {Statement f(db,(std::string(fact_columns)+"WHERE EXISTS(SELECT 1 FROM fact_sources fs WHERE fs.fact_id=f.id AND fs.source_id=?) ORDER BY f.id LIMIT 5;").c_str());
         f.text(1,sid);while(f.step()==SQLITE_ROW)facts.push_back(fact_row(db,f,3));}
        r["entities"]=linked;r["facts"]=facts;
        if(r.contains("scores"))r["scores"]["entity_match"]=hit;
    }
    // Extra signal: when the question names a known entity, evidence linked to it moves ahead (stable within groups).
    bool reordered=false;
    if(boost&&!matched_ids.empty()&&results.is_array()) {
        std::vector<json> items(results.begin(),results.end());
        std::stable_partition(items.begin(),items.end(),[](const json& r){return r.contains("scores")&&r["scores"].value("entity_match",false);});
        json reordered_results=json::array();for(auto& i:items)reordered_results.push_back(std::move(i));
        reordered=reordered_results!=results;results=std::move(reordered_results);
    }
    json entity_facts=json::array();
    if(!matched_ids.empty()) {
        std::string in;for(std::size_t i=0;i<matched_ids.size();++i)in+=i?",?":"?";
        Statement f(db,(std::string(fact_columns)+"WHERE f.subject_id IN ("+in+") OR f.object_entity_id IN ("+in+") ORDER BY coalesce(f.value_seconds,0) DESC,f.id LIMIT 10;").c_str());
        int k=1;for(int pass=0;pass<2;++pass)for(const auto& id:matched_ids)f.text(k++,id);
        while(f.step()==SQLITE_ROW)entity_facts.push_back(fact_row(db,f,3));
    }
    result["entities"]=entities;result["entity_facts"]=entity_facts;result["entity_boosted"]=reordered;
}
}
