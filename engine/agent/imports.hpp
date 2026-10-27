#pragma once
// History import jobs for the Lens app (docs/LENS_V1_SPEC.md §11): preview, start, progress, cancel and
// delete-by-import. The user picks a file in the app; the agent (same user) reads it, parses it here and adds each
// record to memory through the engine. Formats: WhatsApp chat export (.txt, day/month order chosen by the user),
// JSON Lines ({"text", optional "timestamp", "language", "source_application"} per line) and plain text (one memory
// per paragraph). Every import is recorded in <data>\imports.json with the ids it created, so it can be deleted as a
// whole. Logs and status carry counts and error codes only, never content.
#include <windows.h>
#include <bcrypt.h>
#include <nlohmann/json.hpp>
#include <algorithm>
#include <atomic>
#include <filesystem>
#include <fstream>
#include <functional>
#include <map>
#include <mutex>
#include <optional>
#include <regex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

namespace lens::agent::imports {
using json=nlohmann::json;namespace fs=std::filesystem;

inline std::string hex_sha256(const std::string& data) {
    BCRYPT_ALG_HANDLE alg=nullptr;BCRYPT_HASH_HANDLE h=nullptr;unsigned char d[32]{};
    BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,nullptr,0);BCryptCreateHash(alg,&h,nullptr,0,nullptr,0,0);
    BCryptHashData(h,reinterpret_cast<PUCHAR>(const_cast<char*>(data.data())),static_cast<ULONG>(data.size()),0);
    BCryptFinishHash(h,d,32,0);BCryptDestroyHash(h);BCryptCloseAlgorithmProvider(alg,0);
    static const char* hx="0123456789abcdef";std::string out;for(unsigned char b:d){out+=hx[b>>4];out+=hx[b&15];}return out;
}
inline std::string narrow(const fs::path& p){const auto u=p.u8string();return std::string(u.begin(),u.end());}
inline std::string iso(const SYSTEMTIME& t){char b[32];snprintf(b,sizeof b,"%04u-%02u-%02uT%02u:%02u:%02uZ",t.wYear,t.wMonth,t.wDay,t.wHour,t.wMinute,t.wSecond);return b;}
inline std::string now_utc(){SYSTEMTIME t;GetSystemTime(&t);return iso(t);}
// Local wall-clock time (as written in a chat export) to UTC, using this PC's time-zone rules for that date.
inline std::optional<std::string> local_to_utc(int y,int mo,int d,int h,int mi,int s) {
    SYSTEMTIME local{static_cast<WORD>(y),static_cast<WORD>(mo),0,static_cast<WORD>(d),static_cast<WORD>(h),static_cast<WORD>(mi),static_cast<WORD>(s),0},utc{};
    FILETIME ft;if(mo<1||mo>12||d<1||d>31||h>23||mi>59||s>59||!SystemTimeToFileTime(&local,&ft))return std::nullopt;  // validates the date
    if(!TzSpecificLocalTimeToSystemTime(nullptr,&local,&utc))return std::nullopt;
    return iso(utc);
}
inline std::string file_time_utc(const fs::path& p) {
    WIN32_FILE_ATTRIBUTE_DATA a{};SYSTEMTIME t{};
    if(!GetFileAttributesExW(p.c_str(),GetFileExInfoStandard,&a)||!FileTimeToSystemTime(&a.ftLastWriteTime,&t))return now_utc();
    return iso(t);
}
inline bool valid_utf8(const std::string& s) {
    return MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,s.data(),static_cast<int>(s.size()),nullptr,0)>0||s.empty();
}
inline void strip_marks(std::string& s) {  // WhatsApp inserts U+200E/U+200F direction marks and a BOM
    for(const char* m:{"\xE2\x80\x8E","\xE2\x80\x8F","\xEF\xBB\xBF"})for(size_t p;(p=s.find(m))!=std::string::npos;)s.erase(p,3);
    if(!s.empty()&&s.back()=='\r')s.pop_back();
}

struct Parsed {std::vector<json> records;size_t skipped=0;std::map<std::string,int> skipped_by;std::string error,export_sha256;};
// Format names shared with scripts/import-history.ps1, so the engine's `imports` / `delete_sources {scope:{import}}` see these records.
inline std::string format_name(const std::string& f){return f=="whatsapp"?"WhatsApp":f=="jsonl"?"LensJsonl":f=="text"?"Text":f;}
constexpr const char* importer_version="lens-agent-import/1.0";

// Records carry everything except id/provenance, which the job adds.
inline Parsed parse(const fs::path& path,const std::string& format,const std::string& date_order) {
    Parsed out;std::error_code ec;const auto size=fs::file_size(path,ec);
    if(ec){out.error="file_unreadable";return out;}
    if(size>64ull*1024*1024){out.error="file_too_large";return out;}
    std::ifstream f(path,std::ios::binary);if(!f){out.error="file_unreadable";return out;}
    std::string content((std::istreambuf_iterator<char>(f)),std::istreambuf_iterator<char>());
    if(!valid_utf8(content)){out.error="not_utf8";return out;}
    out.export_sha256=hex_sha256(content);
    auto skip=[&](const char* why){++out.skipped;++out.skipped_by[why];};
    std::istringstream lines(content);std::string line;
    if(format=="whatsapp") {
        if(date_order!="dmy"&&date_order!="mdy"){out.error="date_order_required";return out;}
        static const std::regex head(R"(^\[?(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4}),?\s+(\d{1,2}):(\d{2})(?::(\d{2}))?\s?([AaPp]\.?[Mm]\.?)?\]?\s?(?:-\s)?(.*)$)");
        json* last=nullptr;
        while(std::getline(lines,line)) {
            strip_marks(line);std::smatch m;
            if(std::regex_match(line,m,head)) {
                int a=std::stoi(m[1]),b=std::stoi(m[2]),y=std::stoi(m[3]),h=std::stoi(m[4]),mi=std::stoi(m[5]),s=m[6].matched?std::stoi(m[6]):0;
                if(y<100)y+=2000;
                if(m[7].matched){const bool pm=m[7].str()[0]=='p'||m[7].str()[0]=='P';if(h==12)h=pm?12:0;else if(pm)h+=12;}
                const int day=date_order=="dmy"?a:b,month=date_order=="dmy"?b:a;
                const auto when=local_to_utc(y,month,day,h,mi,s);
                std::string rest=m[8];
                if(!when){skip("invalid_date");last=nullptr;continue;}
                std::string sender;const auto colon=rest.find(": ");
                if(colon!=std::string::npos&&colon<128){sender=rest.substr(0,colon);rest=rest.substr(colon+2);}
                if(rest.empty()||rest=="<Media omitted>"||rest=="<attached: image omitted>"){skip("media_or_empty");last=nullptr;continue;}
                out.records.push_back({{"text",sender.empty()?rest:sender+": "+rest},{"timestamp",*when},{"language","und"},{"kind","imported_message"},
                    {"source_application","WhatsApp"},{"metadata",{{"sender",sender},{"import_format","whatsapp"}}}});
                last=&out.records.back();
            } else if(last&&!line.empty()) {(*last)["text"]=(*last)["text"].get<std::string>()+"\n"+line;}  // continuation of a multi-line message
            else if(!line.empty())skip("unrecognised_line");
        }
    } else if(format=="jsonl") {
        while(std::getline(lines,line)) {
            strip_marks(line);if(line.find_first_not_of(" \t")==std::string::npos)continue;
            const auto j=json::parse(line,nullptr,false);
            if(!j.is_object()||!j.contains("text")||!j["text"].is_string()||j["text"].get<std::string>().empty()){skip("invalid_record");continue;}
            json r={{"text",j["text"]},{"timestamp",j.value("timestamp",file_time_utc(path))},{"language",j.value("language",std::string("und"))},{"kind","imported_note"},
                    {"source_application",j.value("source_application",std::string("Import"))},{"metadata",{{"import_format","jsonl"}}}};
            if(!r["timestamp"].is_string()||!r["language"].is_string()||!r["source_application"].is_string()){skip("invalid_record");continue;}
            out.records.push_back(r);
        }
    } else if(format=="text") {
        const auto when=file_time_utc(path);std::string para;
        auto flush=[&]{if(para.find_first_not_of(" \t\n")!=std::string::npos)out.records.push_back({{"text",para},{"timestamp",when},{"language","und"},{"kind","imported_note"},
            {"source_application","Import"},{"metadata",{{"import_format","text"}}}});para.clear();};
        while(std::getline(lines,line)){strip_marks(line);if(line.find_first_not_of(" \t")==std::string::npos)flush();else{if(!para.empty())para+="\n";para+=line;}}
        flush();
    } else out.error="unsupported_format";
    for(auto& r:out.records)if(r["text"].get<std::string>().size()>1024*1024)r["text"]=r["text"].get<std::string>().substr(0,1024*1024);
    return out;
}

// One import at a time (bounded memory); state persisted in imports.json.
class Jobs {
public:
    using Ask=std::function<std::optional<json>(const json&)>;
    Jobs(fs::path store,Ask ask):path_(std::move(store)),ask_(std::move(ask)) {
        std::ifstream f(path_);if(f){const auto j=json::parse(f,nullptr,false);if(j.is_array())imports_=j;}
        for(auto& i:imports_)if(i.value("status","")=="running")i["status"]="interrupted";  // agent stopped mid-import
    }
    ~Jobs(){cancel_all();}
    json preview(const json& req) {
        const auto p=parse(target(req),req.value("format",std::string()),req.value("date_order",std::string()));
        if(!p.error.empty())return {{"ok",false},{"error",p.error}};
        json sample=json::array();
        for(size_t i=0;i<p.records.size()&&i<5;++i){auto t=p.records[i]["text"].get<std::string>();if(t.size()>240){t.resize(240);while(!t.empty()&&(static_cast<unsigned char>(t.back())&0xC0)==0x80)t.pop_back();}
            sample.push_back({{"timestamp",p.records[i]["timestamp"]},{"text",t},{"source_application",p.records[i]["source_application"]}});}
        json first=nullptr,last=nullptr;
        for(const auto& r:p.records){const auto& t=r["timestamp"];if(first.is_null()||t<first)first=t;if(last.is_null()||t>last)last=t;}
        return {{"ok",true},{"records",p.records.size()},{"skipped",p.skipped},{"skipped_by",p.skipped_by},{"sample",sample},{"first",first},{"last",last}};
    }
    json start(const json& req) {
        std::lock_guard g(lock_);
        if(worker_.joinable()&&running_)return {{"ok",false},{"error","import_running"}};
        if(worker_.joinable())worker_.join();
        const auto file=target(req);const auto format=req.value("format",std::string()),order=req.value("date_order",std::string());
        auto parsed=std::make_shared<Parsed>(parse(file,format,order));
        if(!parsed->error.empty())return {{"ok",false},{"error",parsed->error}};
        const auto id="imp-"+hex_sha256(narrow(file)+now_utc()+std::to_string(GetTickCount64())).substr(0,12);
        json job={{"id",id},{"file",narrow(file.filename())},{"format",format},{"export_sha256",parsed->export_sha256},{"status","running"},{"started_utc",now_utc()},{"total",parsed->records.size()},
                  {"processed",0},{"imported",0},{"deduplicated",0},{"failed",0},{"failed_by",json::object()},{"skipped",parsed->skipped},{"source_ids",json::array()}};
        imports_.push_back(job);save();cancel_=false;running_=true;
        worker_=std::thread([this,id,parsed,format]{run(id,*parsed,format);});
        return {{"ok",true},{"import",public_view(job)}};
    }
    json status(const json& req) {
        std::lock_guard g(lock_);
        if(req.contains("id")){for(const auto& i:imports_)if(i["id"]==req["id"])return {{"ok",true},{"import",public_view(i)}};return {{"ok",false},{"error","unknown_import"}};}
        json all=json::array();for(auto it=imports_.rbegin();it!=imports_.rend();++it)all.push_back(public_view(*it));
        return {{"ok",true},{"imports",all},{"running",running_.load()}};
    }
    json cancel(const json& req) {
        std::lock_guard g(lock_);
        for(const auto& i:imports_)if(i["id"]==req.value("id",std::string())){if(i["status"]!="running")return {{"ok",false},{"error","not_running"}};cancel_=true;return {{"ok",true}};}
        return {{"ok",false},{"error","unknown_import"}};
    }
    json remove(const json& req) {  // deletes every memory this import created (originals the user imported, not the file)
        json ids;
        {std::lock_guard g(lock_);
         auto it=std::find_if(imports_.begin(),imports_.end(),[&](const json& i){return i["id"]==req.value("id",std::string());});
         if(it==imports_.end())return {{"ok",false},{"error","unknown_import"}};
         if((*it)["status"]=="running")return {{"ok",false},{"error","import_running"}};
         ids=(*it)["source_ids"];}
        size_t deleted=0;
        for(const auto& id:ids){const auto r=ask_({{"op","delete"},{"consent",true},{"id",id}});if(r&&r->value("ok",false))deleted+=r->value("deleted",0);}
        std::lock_guard g(lock_);
        for(auto& i:imports_)if(i["id"]==req["id"]){i["status"]="deleted";i["deleted"]=deleted;i["deleted_utc"]=now_utc();i["source_ids"]=json::array();}
        save();return {{"ok",true},{"deleted",deleted}};
    }
    void cancel_all(){cancel_=true;if(worker_.joinable())worker_.join();}
private:
    static fs::path target(const json& req){const auto p=req.value("path",std::string());return fs::path(std::u8string(p.begin(),p.end()));}
    static json public_view(json i){i["source_count"]=i["source_ids"].size();i.erase("source_ids");return i;}
    void save(){std::ofstream f(path_);f<<imports_.dump(1);}
    json* find(const std::string& id){for(auto& i:imports_)if(i["id"]==id)return &i;return nullptr;}
    void run(const std::string& id,const Parsed& parsed,const std::string& format) {
        size_t k=0;
        for(const auto& rec:parsed.records) {
            if(cancel_)break;
            json add=rec;add["op"]="add";add["consent"]=true;add["device"]="laptop";
            // Tagged like scripts/import-history.ps1: export hash + record number (no file name), provenance with the format.
            const auto locator="sha256:"+parsed.export_sha256+"#record="+std::to_string(k+1);
            add["id"]="import-"+hex_sha256(locator).substr(0,24);add["source_locator"]=locator;
            // Importing the same file again yields the same ids and records (deduplicated); the import id stays out of the
            // stored record, and imports.json lists which memories each import created.
            add["provenance"]=json{{"export_sha256",parsed.export_sha256},{"format",format_name(format)},{"importer_version",importer_version}}.dump();
            add["consent_context"]={{"mode","user_selected_import"}};
            const auto r=ask_(add);
            std::lock_guard g(lock_);auto* job=find(id);if(!job)break;
            (*job)["processed"]=++k;
            if(r&&r->value("ok",false)) {
                if(r->value("deduplicated",false))(*job)["deduplicated"]=(*job)["deduplicated"].get<int>()+1;
                else{(*job)["imported"]=(*job)["imported"].get<int>()+1;(*job)["source_ids"].push_back(r->value("id",add["id"].get<std::string>()));}
            } else {
                const auto code=r?r->value("error",std::string("engine_error")):std::string("engine_unavailable");
                (*job)["failed"]=(*job)["failed"].get<int>()+1;(*job)["failed_by"][code]=(*job)["failed_by"].value(code,0)+1;
            }
            if(k%200==0)save();
        }
        std::lock_guard g(lock_);
        if(auto* job=find(id)){(*job)["status"]=cancel_?"cancelled":"done";(*job)["finished_utc"]=now_utc();}
        save();running_=false;
    }
    fs::path path_;Ask ask_;std::mutex lock_;json imports_=json::array();std::thread worker_;std::atomic<bool> cancel_=false,running_=false;
};
}
