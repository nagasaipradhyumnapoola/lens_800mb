#include "memory_query.hpp"
#include "sql.hpp"
#include <algorithm>
#include <cctype>
#include <set>
#include <sstream>
#include <vector>
namespace lens {
using json=nlohmann::json;using namespace sql;
namespace query {
std::string quote(const std::string& s){std::string q="\"";for(char c:s){q+=c;if(c=='\"')q+='\"';}return q+'\"';}
Filters filters(const json& request){
    Filters f;if(!request.contains("filters"))return f;
    const auto& j=request.at("filters");if(!j.is_object())throw Error("invalid_filter");
    for(const auto& [name,value]:j.items()){
        if(name=="application_contains"){ // case-insensitive substrings of source_application, any of them
            if(!value.is_array()||value.empty()||value.size()>16)throw Error("invalid_filter");
            std::string any;
            for(const auto& v:value){
                auto token=validated_string(v.get<std::string>(),64);
                for(char& c:token)if(static_cast<unsigned char>(c)<128)c=static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
                std::string escaped;for(char c:token){if(c=='%'||c=='_'||c=='\\')escaped+='\\';escaped+=c;}
                any+=any.empty()?"lower(m.source_application) LIKE ? ESCAPE '\\'":" OR lower(m.source_application) LIKE ? ESCAPE '\\'";
                f.values.push_back("%"+escaped+"%");
            }
            f.where+=" AND ("+any+")";continue;
        }
        const std::string s=validated_string(value.get<std::string>(),1024);
        std::string column;
        if(name=="from"||name=="to"){
            f.where+=name=="from"?" AND m.event_key>=?":" AND m.event_key<?";
            f.values.push_back(instant(s));continue;
        }
        if(name=="application")column="m.source_application";
        else if(name=="source_locator")column="m.source_locator";
        else if(name=="device")column="o.device";
        else if(name=="kind")column="o.kind";
        else if(name=="language")column="o.language";
        else if(name=="source_id")column="o.id";
        else throw Error("invalid_filter");
        f.where+=" AND "+column+"=?";f.values.push_back(s);
    }
    if(j.contains("from")&&j.contains("to")&&instant(j["from"].get<std::string>())>=instant(j["to"].get<std::string>()))throw Error("invalid_time_range");
    return f;
}
void bind_values(Statement& s,const std::vector<std::string>& values,int start){for(const auto& v:values)s.text(start++,v);}
std::vector<std::string> terms(std::string q){
    static const std::set<std::string> stop={"what","did","does","do","i","we","you","the","a","an","was","were","is","are","about","say","said","tell","told","me","my","our","please","find","show","remember","that","which","where","when","wanted","want","of","in","on","to","for","and","it","last"};
    for(char& c:q)if(static_cast<unsigned char>(c)<128){if(!std::isalnum(static_cast<unsigned char>(c)))c=' ';else c=static_cast<char>(std::tolower(static_cast<unsigned char>(c)));}
    std::istringstream stream(q);std::vector<std::string> result;std::string word;
    while(stream>>word)if(!stop.contains(word)&&std::find(result.begin(),result.end(),word)==result.end()){
        result.push_back(word);if(result.size()>12)throw Error("query_too_complex");
    }
    return result;
}
}
using namespace query;
json memory_query(sqlite3* db,const json& j){
    const auto op=required(j,"op",32);auto f=filters(j);json rows=json::array();
    const int limit=j.value("limit",op=="timeline"?25:5);
    if(limit<1||limit>(op=="timeline"?100:5))throw Error("invalid_limit");
    if(op=="find_source"){
        Statement s(db,(columns+tables+"WHERE o.id=?"+f.where+";").c_str());s.text(1,required(j,"id"));bind_values(s,f.values,2);
        if(s.step()==SQLITE_ROW)return {{"ok",true},{"not_found",false},{"source",source(s)}};
        return {{"ok",true},{"not_found",true},{"source",nullptr}};
    }
    auto collect=[&](const std::string& statement,const std::vector<std::string>& values){
        Statement s(db,statement.c_str());bind_values(s,values);
        while(s.step()==SQLITE_ROW&&rows.size()<static_cast<size_t>(limit)){
            auto item=source(s);bool duplicate=false;
            for(const auto& prior:rows)if(prior.at("id")==item.at("id"))duplicate=true;
            if(!duplicate)rows.push_back(std::move(item));
        }
    };
    if(op=="timeline")collect(columns+tables+"WHERE 1=1"+f.where+" ORDER BY m.event_key DESC,o.id LIMIT "+std::to_string(limit),f.values);
    else {
        auto q=required(j,"query",1024);std::vector<std::string> words=op=="retrieve_context"?terms(q):std::vector<std::string>{q};
        if(!words.empty()){
            std::string match,literal;
            for(const auto& word:words){if(!match.empty())match+=" AND ";match+=quote(word);literal+=" AND instr(lower(lens_text(o.text,o.text_codec,o.text_zstd)),lower(?))>0";}
            auto values=std::vector<std::string>{match};values.insert(values.end(),f.values.begin(),f.values.end());
            collect(columns+tables+"JOIN memory_fts ON memory_fts.rowid=o.rowid WHERE memory_fts MATCH ?"+f.where+" ORDER BY bm25(memory_fts),m.event_key DESC,o.id LIMIT "+std::to_string(limit),values);
            if(rows.size()<static_cast<size_t>(limit)){
                values=words;values.insert(values.end(),f.values.begin(),f.values.end());
                collect(columns+tables+"WHERE 1=1"+literal+f.where+" ORDER BY m.event_key DESC,o.id LIMIT "+std::to_string(limit),values);
            }
        }
    }
    if(op!="retrieve_context")return {{"ok",true},{"not_found",rows.empty()},{"sources",rows},{"retrieval","FTS5 / literal source search with metadata filters"}};
    const int budget=j.value("max_context_bytes",8192);if(budget<256||budget>65536)throw Error("invalid_context_budget");
    json citations=json::array();size_t used=0;
    for(const auto& row:rows){
        if(used>=static_cast<size_t>(budget))break;
        const auto text=row.at("text").get<std::string>();auto lowered=text;
        for(char& c:lowered)if(static_cast<unsigned char>(c)<128)c=static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        size_t anchor=std::string::npos;for(const auto& word:terms(required(j,"query",1024)))anchor=std::min(anchor,lowered.find(word));
        if(anchor==std::string::npos){
            // Use the same upstream unicode61 match positions, including case/diacritic folding.
            std::string marker;bool unique=false;
            for(int attempt=0;attempt<64;++attempt){marker="\x1eLENS_MATCH_"+std::to_string(attempt)+"\x1f";if(text.find(marker)==std::string::npos){unique=true;break;}}
            if(!unique)throw Error("matching_context_unavailable");
            std::string match;for(const auto& word:terms(required(j,"query",1024))){if(!match.empty())match+=" AND ";match+=quote(word);}
            Statement marked(db,"SELECT highlight(memory_fts,0,?,?) FROM memory_fts WHERE memory_fts MATCH ? AND rowid=(SELECT rowid FROM observations WHERE id=?);");
            marked.text(1,marker);marked.text(2,marker);marked.text(3,match);marked.text(4,row.at("id").get<std::string>());
            if(marked.step()==SQLITE_ROW)anchor=marked.text(0).find(marker);
        }
        if(anchor==std::string::npos)continue;
        size_t start=anchor>64?anchor-64:0;while(start<text.size()&&(static_cast<unsigned char>(text[start])&0xc0)==0x80)++start;
        size_t n=std::min(text.size()-start,static_cast<size_t>(budget)-used);
        while(start+n<text.size()&&n>0&&(static_cast<unsigned char>(text[start+n])&0xc0)==0x80)--n;
        if(!n)break;
        citations.push_back({{"source_id",row.at("id")},{"quote",text.substr(start,n)},{"byte_offset",start},{"timestamp",row.at("timestamp")},
            {"device",row.at("device")},{"source_application",row.at("source_application")},
            {"source_locator",row.at("source_locator")},{"language",row.at("language")},
            {"match_explanation","source matched query terms; quote is an exact bounded excerpt"},{"truncated",start>0||n<text.size()}});used+=n;
    }
    return {{"ok",true},{"not_found",citations.empty()},{"answer_kind","source_quotes"},{"citations",citations},
        {"context_text_bytes",used},{"max_context_bytes",budget},{"generated_claims",false}};
}
}
