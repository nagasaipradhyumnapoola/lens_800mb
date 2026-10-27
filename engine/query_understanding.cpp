#include "query_understanding.hpp"
#include <cctype>
namespace lens {
namespace {
struct AppRule {const char* phrase;std::vector<std::string> matches;};
// Phrases are lowercase (ASCII) or exact native script. Generic classes expand to concrete applications.
const std::vector<AppRule> app_rules{
    {"google chrome",{"chrome"}},{"chrome",{"chrome"}},{"microsoft edge",{"edge","msedge"}},{"firefox",{"firefox"}},
    {"browser",{"chrome","edge","msedge","firefox","brave","opera","browser"}},{"web page",{"chrome","edge","msedge","firefox","brave","browser"}},
    {"website",{"chrome","edge","msedge","firefox","brave","browser"}},{"whatsapp",{"whatsapp"}},{"slack",{"slack"}},
    {"microsoft teams",{"teams"}},{"teams",{"teams"}},{"outlook",{"outlook"}},{"gmail",{"gmail"}},
    {"email",{"outlook","gmail","mail","thunderbird"}},{"e-mail",{"outlook","gmail","mail","thunderbird"}},
    {"vs code",{"code","vscode","visual studio code"}},{"visual studio code",{"code","vscode","visual studio code"}},
    {"excel",{"excel"}},{"powerpoint",{"powerpoint"}},{"word document",{"word"}},{"youtube",{"youtube"}},
    {"figma",{"figma"}},{"zoom",{"zoom"}},{"notepad",{"notepad"}},{"telegram",{"telegram"}},
    {"\xE5\xBE\xAE\xE4\xBF\xA1",{"wechat","weixin","\xE5\xBE\xAE\xE4\xBF\xA1"}},                 // 微信
    {"\xE9\x82\xAE\xE4\xBB\xB6",{"outlook","gmail","mail","thunderbird"}},                       // 邮件
    {"\xE6\xB5\x8F\xE8\xA7\x88\xE5\x99\xA8",{"chrome","edge","msedge","firefox","browser"}},    // 浏览器
    {"\xE7\xBD\x91\xE9\xA1\xB5",{"chrome","edge","msedge","firefox","browser"}},                 // 网页
    {"correo",{"outlook","gmail","mail","thunderbird"}},{"navegador",{"chrome","edge","msedge","firefox","browser"}},
    {"p\xC3\xA1gina web",{"chrome","edge","msedge","firefox","browser"}},
    {"\xE0\xA4\x88\xE0\xA4\xAE\xE0\xA5\x87\xE0\xA4\xB2",{"outlook","gmail","mail","thunderbird"}},                      // ईमेल
    {"\xE0\xA4\xB5\xE0\xA5\x8D\xE0\xA4\xB9\xE0\xA4\xBE\xE0\xA4\x9F\xE0\xA5\x8D\xE0\xA4\xB8\xE0\xA4\x90\xE0\xA4\xAA",{"whatsapp"}}, // व्हाट्सऐप
    {"\xE0\xAE\xAE\xE0\xAE\xBF\xE0\xAE\xA9\xE0\xAF\x8D\xE0\xAE\xA9\xE0\xAE\x9E\xE0\xAF\x8D\xE0\xAE\x9A\xE0\xAE\xB2\xE0\xAF\x8D",{"outlook","gmail","mail","thunderbird"}}, // மின்னஞ்சல்
    {"\xE0\xB0\x88\xE0\xB0\xAE\xE0\xB1\x86\xE0\xB0\xAF\xE0\xB0\xBF\xE0\xB0\xB2\xE0\xB1\x8D",{"outlook","gmail","mail","thunderbird"}}, // ఈమెయిల్
};
struct ActionRule {const char* phrase;const char* action;};
const std::vector<ActionRule> action_rules{
    {"downloaded","downloaded"},{"download","downloaded"},{"read","read"},{"watched","watched"},{"saw","watched"},
    {"sent","sent"},{"booked","booked"},{"ordered","ordered"},{"bought","ordered"},
    {"descargu\xC3\xA9","downloaded"},{"le\xC3\xAD","read"},{"vi ","watched"},{"envi\xC3\xA9","sent"},{"reserv\xC3\xA9","booked"},{"compr\xC3\xA9","ordered"},
    {"\xE4\xB8\x8B\xE8\xBD\xBD","downloaded"},{"\xE8\xAF\xBB","read"},{"\xE7\x9C\x8B\xE4\xBA\x86","watched"},{"\xE5\x8F\x91\xE4\xBA\x86","sent"}, // 下载 读 看了 发了
    {"\xE0\xA4\xA1\xE0\xA4\xBE\xE0\xA4\x89\xE0\xA4\xA8\xE0\xA4\xB2\xE0\xA5\x8B\xE0\xA4\xA1","downloaded"},{"\xE0\xA4\xAA\xE0\xA4\xA2\xE0\xA4\xBC","read"}, // डाउनलोड पढ़
    {"\xE0\xAE\xAA\xE0\xAE\x9F\xE0\xAE\xBF\xE0\xAE\x9A\xE0\xAF\x8D\xE0\xAE\x9A","read"},{"\xE0\xB0\x9A\xE0\xB0\xA6\xE0\xB0\xBF\xE0\xB0\xB5","read"}, // படிச்ச చదివ
};
bool boundary_ok(const std::string& s,std::size_t at,std::size_t n){
    auto alnum=[&](std::size_t i){const auto c=static_cast<unsigned char>(s[i]);return c<128&&std::isalnum(c);};
    if(static_cast<unsigned char>(s[at])>=128)return true; // native-script phrases are matched as substrings
    return (at==0||!alnum(at-1))&&(at+n>=s.size()||!alnum(at+n));
}
std::size_t find_phrase(const std::string& s,const std::string& p){
    for(auto at=s.find(p);at!=std::string::npos;at=s.find(p,at+1))if(boundary_ok(s,at,p.size()))return at;
    return std::string::npos;
}
}

QueryInterpretation interpret_query(const std::string& question){
    std::string q=question;for(char& c:q)if(static_cast<unsigned char>(c)<128)c=static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    QueryInterpretation out;std::vector<std::pair<std::size_t,std::size_t>> used;
    auto overlaps=[&](std::size_t a,std::size_t n){for(auto [b,m]:used)if(a<b+m&&b<a+n)return true;return false;};
    for(const auto& rule:app_rules){ // longer phrases come first, so "google chrome" wins over "chrome"
        const std::string phrase=rule.phrase;const auto at=find_phrase(q,phrase);
        if(at==std::string::npos||overlaps(at,phrase.size()))continue;
        used.emplace_back(at,phrase.size());out.applications.push_back({phrase,rule.matches});
    }
    for(const auto& rule:action_rules){
        const std::string phrase=rule.phrase;const auto at=find_phrase(q,phrase);
        if(at==std::string::npos||overlaps(at,phrase.size()))continue;
        out.action=rule.action;out.action_phrase=phrase;break;
    }
    return out;
}
}
