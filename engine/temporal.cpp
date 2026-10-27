#include "temporal.hpp"
#include <algorithm>
#include <array>
#include <cctype>
#include <cstdio>
#include <regex>
#include <vector>
namespace lens {
using namespace std::chrono;
namespace {
struct Phrase {const char* text;const char* kind;int offset;}; // offset: 0 = current period, -1 = previous, -2 = two before
// Multilingual phrase table (lowercase ASCII for Latin scripts). Longer phrases are listed before their prefixes.
const std::vector<Phrase> phrases{
    {"day before yesterday","day",-2},{"yesterday","day",-1},{"today","day",0},{"this morning","day",0},{"tonight","day",0},
    {"last week","week",-1},{"previous week","week",-1},{"past week","week",-1},{"this week","week",0},
    {"last month","month",-1},{"previous month","month",-1},{"this month","month",0},
    {"last year","year",-1},{"previous year","year",-1},{"this year","year",0},
    {"\xE5\x89\x8D\xE5\xA4\xA9","day",-2},{"\xE6\x98\xA8\xE5\xA4\xA9","day",-1},{"\xE4\xBB\x8A\xE5\xA4\xA9","day",0},          // 前天 昨天 今天
    {"\xE4\xB8\x8A\xE5\x91\xA8","week",-1},{"\xE4\xB8\x8A\xE6\x98\x9F\xE6\x9C\x9F","week",-1},{"\xE8\xBF\x99\xE5\x91\xA8","week",0}, // 上周 上星期 这周
    {"\xE6\x9C\xAC\xE5\x91\xA8","week",0},{"\xE4\xB8\x8A\xE4\xB8\xAA\xE6\x9C\x88","month",-1},{"\xE8\xBF\x99\xE4\xB8\xAA\xE6\x9C\x88","month",0}, // 本周 上个月 这个月
    {"\xE6\x9C\xAC\xE6\x9C\x88","month",0},{"\xE5\x8E\xBB\xE5\xB9\xB4","year",-1},{"\xE4\xBB\x8A\xE5\xB9\xB4","year",0},          // 本月 去年 今年
    {"anteayer","day",-2},{"ayer","day",-1},{"hoy","day",0},{"la semana pasada","week",-1},{"esta semana","week",0},
    {"el mes pasado","month",-1},{"este mes","month",0},{"el a\xC3\xB1o pasado","year",-1},{"este a\xC3\xB1o","year",0},
    {"\xE0\xA4\xAA\xE0\xA4\xBF\xE0\xA4\x9B\xE0\xA4\xB2\xE0\xA5\x87 \xE0\xA4\xB9\xE0\xA4\xAB\xE0\xA5\x8D\xE0\xA4\xA4\xE0\xA5\x87","week",-1}, // पिछले हफ्ते
    {"\xE0\xA4\xAA\xE0\xA4\xBF\xE0\xA4\x9B\xE0\xA4\xB2\xE0\xA5\x87 \xE0\xA4\xB8\xE0\xA4\xAA\xE0\xA5\x8D\xE0\xA4\xA4\xE0\xA4\xBE\xE0\xA4\xB9","week",-1}, // पिछले सप्ताह
    {"\xE0\xA4\x87\xE0\xA4\xB8 \xE0\xA4\xB9\xE0\xA4\xAB\xE0\xA5\x8D\xE0\xA4\xA4\xE0\xA5\x87","week",0}, // इस हफ्ते
    {"\xE0\xA4\xAA\xE0\xA4\xBF\xE0\xA4\x9B\xE0\xA4\xB2\xE0\xA5\x87 \xE0\xA4\xAE\xE0\xA4\xB9\xE0\xA5\x80\xE0\xA4\xA8\xE0\xA5\x87","month",-1}, // पिछले महीने
    {"\xE0\xA4\x87\xE0\xA4\xB8 \xE0\xA4\xAE\xE0\xA4\xB9\xE0\xA5\x80\xE0\xA4\xA8\xE0\xA5\x87","month",0}, // इस महीने
    {"\xE0\xA4\xAA\xE0\xA4\xBF\xE0\xA4\x9B\xE0\xA4\xB2\xE0\xA5\x87 \xE0\xA4\xB8\xE0\xA4\xBE\xE0\xA4\xB2","year",-1}, // पिछले साल
    {"\xE0\xA4\x86\xE0\xA4\x9C","day",0}, // आज
    {"\xE0\xAE\xA8\xE0\xAF\x87\xE0\xAE\xB1\xE0\xAF\x8D\xE0\xAE\xB1\xE0\xAF\x81","day",-1}, // நேற்று
    {"\xE0\xAE\x87\xE0\xAE\xA9\xE0\xAF\x8D\xE0\xAE\xB1\xE0\xAF\x81","day",0}, // இன்று
    {"\xE0\xAE\x95\xE0\xAE\x9F\xE0\xAE\xA8\xE0\xAF\x8D\xE0\xAE\xA4 \xE0\xAE\xB5\xE0\xAE\xBE\xE0\xAE\xB0\xE0\xAE\xAE\xE0\xAF\x8D","week",-1}, // கடந்த வாரம்
    {"\xE0\xAE\x87\xE0\xAE\xA8\xE0\xAF\x8D\xE0\xAE\xA4 \xE0\xAE\xB5\xE0\xAE\xBE\xE0\xAE\xB0\xE0\xAE\xAE\xE0\xAF\x8D","week",0}, // இந்த வாரம்
    {"\xE0\xAE\x95\xE0\xAE\x9F\xE0\xAE\xA8\xE0\xAF\x8D\xE0\xAE\xA4 \xE0\xAE\xAE\xE0\xAE\xBE\xE0\xAE\xA4\xE0\xAE\xAE\xE0\xAF\x8D","month",-1}, // கடந்த மாதம்
    {"\xE0\xAE\x87\xE0\xAE\xA8\xE0\xAF\x8D\xE0\xAE\xA4 \xE0\xAE\xAE\xE0\xAE\xBE\xE0\xAE\xA4\xE0\xAE\xAE\xE0\xAF\x8D","month",0}, // இந்த மாதம்
    {"\xE0\xB0\xA8\xE0\xB0\xBF\xE0\xB0\xA8\xE0\xB1\x8D\xE0\xB0\xA8","day",-1}, // నిన్న
    {"\xE0\xB0\x88\xE0\xB0\xB0\xE0\xB1\x8B\xE0\xB0\x9C\xE0\xB1\x81","day",0}, // ఈరోజు
    {"\xE0\xB0\x97\xE0\xB0\xA4 \xE0\xB0\xB5\xE0\xB0\xBE\xE0\xB0\xB0\xE0\xB0\x82","week",-1}, // గత వారం
    {"\xE0\xB0\x88 \xE0\xB0\xB5\xE0\xB0\xBE\xE0\xB0\xB0\xE0\xB0\x82","week",0}, // ఈ వారం
    {"\xE0\xB0\x97\xE0\xB0\xA4 \xE0\xB0\xA8\xE0\xB1\x86\xE0\xB0\xB2","month",-1}, // గత నెల
    {"\xE0\xB0\x88 \xE0\xB0\xA8\xE0\xB1\x86\xE0\xB0\xB2","month",0}, // ఈ నెల
    {"kal raat","day",-1},{"pichle hafte","week",-1},{"pichle mahine","month",-1},{"aaj","day",0},{"nethu","day",-1},{"ninna","day",-1}
};
const std::array<const char*,12> months_en{"january","february","march","april","may","june","july","august","september","october","november","december"};
const std::array<const char*,12> months_es{"enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"};
bool word_at(const std::string& s,std::size_t at,std::size_t n){
    auto boundary=[&](std::size_t i){return i>=s.size()||!(std::isalnum(static_cast<unsigned char>(s[i]))&&static_cast<unsigned char>(s[i])<128);};
    return (at==0||boundary(at-1))&&boundary(at+n);
}
std::size_t find_word(const std::string& s,const std::string& w){
    for(auto at=s.find(w);at!=std::string::npos;at=s.find(w,at+1))
        if(static_cast<unsigned char>(w[0])>=128||word_at(s,at,w.size()))return at;
    return std::string::npos;
}
}

std::string iso_utc(sys_seconds t){
    const auto day=floor<days>(t);const year_month_day d{day};const hh_mm_ss hms{t-day};char out[32];
    std::snprintf(out,sizeof out,"%04d-%02u-%02uT%02lld:%02lld:%02lldZ",static_cast<int>(d.year()),static_cast<unsigned>(d.month()),static_cast<unsigned>(d.day()),
        static_cast<long long>(hms.hours().count()),static_cast<long long>(hms.minutes().count()),static_cast<long long>(hms.seconds().count()));
    return out;
}

std::optional<TimeWindow> interpret_time(const std::string& question,sys_seconds now,int utc_offset_minutes){
    std::string q=question;for(char& c:q)if(static_cast<unsigned char>(c)<128)c=static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    const minutes offset{utc_offset_minutes};
    const auto local_now=now+offset;const auto today=floor<days>(local_now);
    auto window=[&](sys_days a,sys_days b,const std::string& phrase,const char* kind)->TimeWindow{
        return {sys_seconds{a}-offset,sys_seconds{b}-offset,phrase,kind};};
    // "N days ago" / "hace N días"
    static const std::regex ago(R"((\d{1,3}) days? ago|hace (\d{1,3}) d\xC3\xADas?)");
    std::smatch m;
    if(std::regex_search(q,m,ago)){
        const int n=std::stoi(m[1].matched?m[1].str():m[2].str());
        const auto day=today-days{n};return window(day,day+days{1},m.str(),"days_ago");
    }
    std::optional<std::pair<std::size_t,const Phrase*>> best;
    for(const auto& p:phrases){
        const auto at=find_word(q,p.text);
        if(at!=std::string::npos&&(!best||std::string(p.text).size()>std::string(best->second->text).size()))best=std::make_pair(at,&p);
    }
    if(best){
        const auto& p=*best->second;const std::string kind=p.kind;
        if(kind=="day"){const auto d=today+days{p.offset};return window(d,d+days{1},p.text,p.kind);}
        if(kind=="week"){ // ISO weeks start on Monday
            const weekday wd{today};const auto monday=today-days{(wd.c_encoding()+6)%7}+weeks{p.offset};
            return window(monday,monday+weeks{1},p.text,p.kind);
        }
        const year_month_day ymd{today};
        if(kind=="month"){
            const auto first=year_month{ymd.year(),ymd.month()}+months{p.offset};
            return window(sys_days{first/1},sys_days{(first+months{1})/1},p.text,p.kind);
        }
        const auto y=ymd.year()+years{p.offset};
        return window(sys_days{y/January/1},sys_days{(y+years{1})/January/1},p.text,p.kind);
    }
    // Named month: the most recent occurrence not after today ("in October", "en octubre").
    for(int i=0;i<12;++i)for(const char* name:{months_en[i],months_es[i]}){
        if(find_word(q,name)==std::string::npos)continue;
        // English "may" is usually the modal verb; accept it only as "in may".
        if(std::string(name)=="may"&&q.find("in may")==std::string::npos)continue;
        const year_month_day ymd{today};auto y=ymd.year();
        if(static_cast<unsigned>(ymd.month())<static_cast<unsigned>(i+1))--y;
        const year_month ym{y,month{static_cast<unsigned>(i+1)}};
        return window(sys_days{ym/1},sys_days{(ym+months{1})/1},name,"month");
    }
    return std::nullopt;
}
}
