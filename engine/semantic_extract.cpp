#include "semantic_extract.hpp"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <set>
#include <unordered_map>
#include <unordered_set>

namespace lens::extract {
namespace {
// ---------------------------------------------------------------- UTF-8 and character classes
struct Cp {std::uint32_t cp;std::size_t b,n;};
std::vector<Cp> decode(const std::string& s) {
    std::vector<Cp> out;out.reserve(s.size());
    for(std::size_t i=0;i<s.size();) {
        const auto c=static_cast<unsigned char>(s[i]);
        std::size_t n=c<0x80?1:(c>>5)==6?2:(c>>4)==14?3:(c>>3)==30?4:1;
        if(i+n>s.size())n=1;
        std::uint32_t cp=n==1?c:n==2?(c&0x1Fu):n==3?(c&0x0Fu):(c&0x07u);
        bool ok=true;
        for(std::size_t k=1;k<n;++k){const auto d=static_cast<unsigned char>(s[i+k]);if((d&0xC0)!=0x80){ok=false;break;}cp=(cp<<6)|(d&0x3Fu);}
        if(!ok){n=1;cp=0xFFFD;}
        out.push_back({cp,i,n});i+=n;
    }
    return out;
}
enum class S:unsigned char {space,newline,latin,digit,deva,taml,telu,han,other_letter,joiner,punct};
S klass(std::uint32_t cp) {
    if(cp=='\n'||cp=='\r'||cp==0x2028||cp==0x2029)return S::newline;
    if(cp==' '||cp=='\t'||cp==0xA0||cp==0x3000||(cp>=0x2000&&cp<=0x200B)||cp==0xFEFF)return S::space;
    if(cp<128){if((cp>='a'&&cp<='z')||(cp>='A'&&cp<='Z'))return S::latin;if(cp>='0'&&cp<='9')return S::digit;return S::punct;}
    if(cp>=0xC0&&cp<=0x24F&&cp!=0xD7&&cp!=0xF7)return S::latin;
    if(cp>=0x0900&&cp<=0x097F)return cp==0x964||cp==0x965?S::punct:S::deva;
    if(cp>=0x0B80&&cp<=0x0BFF)return S::taml;
    if(cp>=0x0C00&&cp<=0x0C7F)return S::telu;
    if(cp==0x200C||cp==0x200D)return S::joiner;
    if((cp>=0x4E00&&cp<=0x9FFF)||(cp>=0x3400&&cp<=0x4DBF)||(cp>=0xF900&&cp<=0xFAFF))return S::han;
    if((cp>=0x0370&&cp<=0x052F)||(cp>=0x0600&&cp<=0x06FF)||(cp>=0x0980&&cp<=0x0B7F)||(cp>=0x0C80&&cp<=0x0DFF)||
       (cp>=0x0E00&&cp<=0x0E7F)||(cp>=0x3040&&cp<=0x30FF)||(cp>=0xAC00&&cp<=0xD7AF))return S::other_letter;
    return S::punct;
}
bool indic(S s){return s==S::deva||s==S::taml||s==S::telu;}
std::string ascii_lower(const std::string& s){std::string o=s;for(auto& c:o)if(c>='A'&&c<='Z')c=static_cast<char>(c-'A'+'a');return o;}
bool starts_with(const std::string& s,const std::string& p){return s.size()>=p.size()&&s.compare(0,p.size(),p)==0;}

// ---------------------------------------------------------------- tokens and sentences
enum class T:unsigned char {word,number,han,punct};
struct Tok {
    std::size_t b=0,e=0;T t=T::punct;S script=S::punct;std::string s,low,suffix;  // suffix: letters glued to a number ("3rd", "5k")
    std::uint32_t cp=0;bool cap=false,camel=false,newline=false;int sent=0;
};
using V=std::vector<Tok>;
const std::unordered_set<std::string> abbreviations={"mr","mrs","ms","dr","prof","sr","sra","srta","dra","st","jr","inc","ltd","co","corp","vs","etc",
    "no","rs","smt","shri","jan","feb","mar","apr","jun","jul","aug","sep","sept","oct","nov","dec","pvt","mx","e","g","i","u","s","p","m","a"};
bool terminator(std::uint32_t cp){return cp=='.'||cp=='!'||cp=='?'||cp==0x3002||cp==0xFF01||cp==0xFF1F||cp==0x964||cp==0x965;}
V tokenize(const std::string& text) {
    const auto cps=decode(text);V out;bool nl=true;
    auto end_of=[&](std::size_t j){return j<cps.size()?cps[j].b:text.size();};
    for(std::size_t i=0;i<cps.size();) {
        const auto k=klass(cps[i].cp);
        if(k==S::space||k==S::joiner){++i;continue;}
        if(k==S::newline){nl=true;++i;continue;}
        Tok t;t.b=cps[i].b;t.newline=nl;nl=false;std::size_t j=i+1;
        if(k==S::han){t.t=T::han;t.script=S::han;t.cp=cps[i].cp;}
        else if(k==S::digit) {
            t.t=T::number;t.script=S::digit;
            while(j<cps.size()) {
                const auto kj=klass(cps[j].cp);if(kj==S::digit){++j;continue;}
                const auto c=cps[j].cp;
                if((c=='.'||c==','||c==':'||c=='/'||c=='-')&&j+1<cps.size()&&klass(cps[j+1].cp)==S::digit){j+=2;continue;}
                break;
            }
            const auto digits_end=j;while(j<cps.size()&&klass(cps[j].cp)==S::latin&&j-digits_end<4)++j;
            if(j<cps.size()&&klass(cps[j].cp)==S::latin)j=digits_end;  // "3rdparty" is not an ordinal
            t.suffix=ascii_lower(text.substr(end_of(digits_end),end_of(j)-end_of(digits_end)));
        }
        else if(k==S::latin){t.t=T::word;t.script=S::latin;while(j<cps.size()&&(klass(cps[j].cp)==S::latin||klass(cps[j].cp)==S::digit))++j;}
        else if(indic(k)){t.t=T::word;t.script=k;while(j<cps.size()&&(klass(cps[j].cp)==k||klass(cps[j].cp)==S::joiner))++j;}
        else if(k==S::other_letter){t.t=T::word;t.script=k;while(j<cps.size()&&klass(cps[j].cp)==S::other_letter)++j;}
        else {t.t=T::punct;t.cp=cps[i].cp;}
        t.e=end_of(j);t.s=text.substr(t.b,t.e-t.b);t.low=ascii_lower(t.s);
        if(t.t==T::word&&t.script==S::latin) {
            const auto c0=cps[i].cp;t.cap=(c0>='A'&&c0<='Z')||(c0>=0xC0&&c0<=0xDE&&c0!=0xD7);
            for(std::size_t q=i+1;q<j;++q)if(cps[q].cp>='A'&&cps[q].cp<='Z')t.camel=true;
        }
        out.push_back(std::move(t));i=j;
    }
    int sent=0;bool next=false;
    for(std::size_t i=0;i<out.size();++i) {
        if(next||(out[i].newline&&i>0)){++sent;next=false;}
        out[i].sent=sent;
        if(out[i].t==T::punct&&terminator(out[i].cp)) {
            const bool abbrev=out[i].cp=='.'&&i>0&&out[i-1].e==out[i].b&&out[i-1].t==T::word&&abbreviations.contains(out[i-1].low);
            if(!abbrev)next=true;
        }
    }
    return out;
}

// ---------------------------------------------------------------- word lists
const std::unordered_set<std::string> stop_cap={"i","we","you","he","she","they","it","the","a","an","this","that","these","those","my","our","your",
    "his","her","their","its","and","but","or","so","then","also","today","tomorrow","yesterday","tonight","monday","tuesday","wednesday","thursday",
    "friday","saturday","sunday","january","february","march","april","may","june","july","august","september","october","november","december",
    "jan","feb","mar","apr","jun","jul","aug","sep","sept","oct","nov","dec","please","thanks","thank","hi","hello","hey","dear","ok","okay","yes",
    "no","not","team","everyone","all","someone","somebody","nobody","everybody","lens","project","meeting","re","fwd","fw","note","subject",
    "el","la","los","las","yo","nosotros","usted","ella","hoy","ayer","lunes","martes","miércoles","miercoles","jueves","viernes","sábado","sabado",
    "domingo","enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","setiembre","octubre","noviembre","diciembre","hola",
    "gracias","sir","madam","mom","dad","new","final","next","last","when","where","what","who","why","how","if","in","on","at","for","with","from",
    "to","by","of","as","is","are","was","were","will","can","could","would","should","did","do","does","has","have","had","after","before","here",
    "there","now","just","still","maybe","sure","great","good","sorry","meanwhile","however","because","since","while","some","any","each","every",
    "en","de","del","con","por","para","que","un","una","es","y","pero","como","cuando","budget","deadline","decision","summary","agenda","update",
    "draft","total","invoice","bill","price","cost","reminder","todo","action","item","items","notes","minutes","call","email","message","chat",
    "sprint","release","version","report","review","plan","weekly","daily","monthly","quarterly","annual","q1","q2","q3","q4","eod","asap","fyi",
    "pm","am","ceo","cto","cfo","hr","it","ui","ux","api","faq","pdf","url","usd","inr","eur","rs","morning","evening","afternoon","night"};
const std::unordered_set<std::string> connectors={"de","del","la","van","von","bin","da","dos","di","le"};
const std::unordered_set<std::string> honorific_before={"mr","mrs","ms","dr","prof","sr","sra","srta","dra","shri","smt","thiru","mx","señor","señora","don","doña","professor","doctor"};
const std::unordered_set<std::string> verbs_after={"said","says","told","asked","wrote","mentioned","replied","called","emailed","texted","messaged",
    "agreed","suggested","shared","sent","thinks","thought","wants","wanted","confirmed","promised","explained","decided","proposed","approved","noted",
    "dijo","dice","escribió","escribio","pidió","pidio","comentó","comento","mencionó","menciono","llamó","llamo","envió","envio","confirmó","confirmo",
    "sugirió","sugirio","respondió","respondio","ne","bola","boli","bole","kaha","sonnar","sonnaru","sonnan","sonnanga","cheppadu","chepparu","cheppindi","annaru"};
const std::unordered_set<std::string> honorific_after={"ji","garu","sir","madam","anna","akka","bhai","didi","sahab","saab","sahib"};
const std::unordered_set<std::string> verbs_before={"with","ask","asked","tell","told","call","called","email","emailed","message","messaged","text",
    "texted","meet","met","ping","pinged","thank","thanks","cc","con","llamar","llamé","llame","pregunté","pregunte","dile","según","segun","remind","reminded"};
const std::unordered_set<std::string> header_words={"subject","re","fwd","fw","date","time","note","notes","todo","asunto","tema","fecha","location",
    "where","when","agenda","deadline","budget","decision","summary","title","url","link","step","q","a","status","update","total","price","cost",
    "amount","tip","warning","error","info","important","reminder","action","owner","due","venue","topic","hora","lugar","nota","p","ps","edit"};
const std::unordered_set<std::string> header_people={"from","to","cc","bcc","de","para"};
const std::unordered_set<std::string> legal_suffix={"inc","ltd","llc","corp","corporation","company","co","pvt","gmbh","plc","sa","sl","limited","llp","ag","bv","oy"};
const std::unordered_set<std::string> org_suffix={"labs","technologies","technology","systems","solutions","bank","university","college","institute",
    "foundation","hospital","group","partners","consulting","ventures","studios","software","networks","analytics","industries","enterprises",
    "associates","agency","school","academy","council","ministry","bureau","clinic","holdings","motors","airlines","pharma","media","capital"};
const std::unordered_set<std::string> org_prefix={"university","bank","universidad","banco","instituto","institute","college","hospital","ministry",
    "department","ministerio","colegio","escuela","fundación","fundacion","school","academy"};
const std::unordered_set<std::string> project_words={"project","proyecto","projet","initiative","programme"};
const std::unordered_set<std::string> project_stop={"final","new","big","side","pet","group","team","school","college","research","class","course",
    "semester","capstone","major","minor","main","current","old","next","last","first","second","whole","entire","open","source","personal","client"};
const std::unordered_set<std::string> product_words={"app","application","software","laptop","phone","tablet","watch","extension","plugin","sdk",
    "library","framework","browser","editor","console","headphones","earbuds","camera","printer"};
const std::unordered_set<std::string> product_stop={"room","chapter","section","page","floor","gate","platform","step","phase","version","level",
    "day","week","table","figure","item","part","unit","flight","bus","train","route","highway","class","grade","sprint","q","plan","option","case",
    "lot","building","block","sector","area","zone","apartment","flat","suite","question","exercise","lesson","module","task","ticket","issue",
    "number","year","act","article","rule","no","vol","volume","box","line","row","seat","window","tab","term","batch","team","stage","round","slot",
    "lecture","week","assignment","lab","problem","ward","bed","order","invoice","pin","otp","code","sem","semester"};
const std::vector<std::string> place_cues_en={"flight to","trip to","travel to","travelling to","traveling to","moved to","moving to","visit","visiting",
    "visited","office in","based in","located in","lives in","living in","arrived in","arrive in","back from","hotel in","fly to","flying to","vuelo a",
    "viaje a","vive en","oficina en","landed in","relocating to","relocated to"};
// Public, non-personal place names with their spellings in the supported scripts (a few KB; joins scripts for places).
struct Seed {const char* canonical;std::vector<std::string> spellings;};
const std::vector<Seed>& seed_places() {
    static const std::vector<Seed> seeds={
        {"Chennai",{"Chennai","சென்னை","चेन्नई","చెన్నై","金奈"}},{"Mumbai",{"Mumbai","मुंबई","மும்பை","ముంబై","孟买"}},
        {"Delhi",{"Delhi","New Delhi","दिल्ली","டெல்லி","ఢిల్లీ","德里"}},{"Bengaluru",{"Bengaluru","Bangalore","बेंगलुरु","பெங்களூரு","பெங்களூர்","బెంగళూరు","班加罗尔"}},
        {"Hyderabad",{"Hyderabad","हैदराबाद","ஹைதராபாத்","హైదరాబాద్","海得拉巴"}},{"Kolkata",{"Kolkata","कोलकाता","கொல்கத்தா","కోల్‌కతా","加尔各答"}},
        {"Pune",{"Pune","पुणे","புனே","పూణే"}},{"Coimbatore",{"Coimbatore","கோயம்புத்தூர்","कोयंबटूर"}},{"Madurai",{"Madurai","மதுரை"}},
        {"Vijayawada",{"Vijayawada","విజయవాడ"}},{"Visakhapatnam",{"Visakhapatnam","Vizag","విశాఖపట్నం"}},{"Jaipur",{"Jaipur","जयपुर"}},
        {"Lucknow",{"Lucknow","लखनऊ"}},{"Madrid",{"Madrid","马德里"}},{"Barcelona",{"Barcelona","巴塞罗那"}},{"Sevilla",{"Sevilla","Seville"}},
        {"Valencia",{"Valencia"}},{"Mexico City",{"Mexico City","Ciudad de México","Ciudad de Mexico","墨西哥城"}},{"Buenos Aires",{"Buenos Aires"}},
        {"Bogotá",{"Bogotá","Bogota"}},{"Lima",{"Lima"}},{"Santiago",{"Santiago"}},{"Beijing",{"Beijing","北京"}},{"Shanghai",{"Shanghai","上海"}},
        {"Shenzhen",{"Shenzhen","深圳"}},{"Guangzhou",{"Guangzhou","广州"}},{"Hangzhou",{"Hangzhou","杭州"}},{"Chengdu",{"Chengdu","成都"}},
        {"Hong Kong",{"Hong Kong","香港"}},{"Taipei",{"Taipei","台北"}},{"Singapore",{"Singapore","新加坡","சிங்கப்பூர்","सिंगापुर","సింగపూర్"}},
        {"London",{"London","伦敦","लंदन","லண்டன்","లండన్","Londres"}},{"New York",{"New York","纽约","न्यूयॉर्क","நியூயார்க்","న్యూయార్క్","Nueva York"}},
        {"San Francisco",{"San Francisco","旧金山"}},{"Seattle",{"Seattle","西雅图"}},{"Boston",{"Boston","波士顿"}},{"Toronto",{"Toronto","多伦多"}},
        {"Tokyo",{"Tokyo","东京","Tokio"}},{"Paris",{"Paris","巴黎","París"}},{"Berlin",{"Berlin","柏林","Berlín"}},
        {"Dubai",{"Dubai","迪拜","दुबई","துபாய்","దుబాయ్"}},{"Sydney",{"Sydney","悉尼"}},
        {"India",{"India","भारत","இந்தியா","భారతదేశం","భారత్","印度"}},{"China",{"China","中国"}},{"Spain",{"Spain","España","西班牙"}},
        {"Mexico",{"Mexico","México","墨西哥"}},{"United States",{"United States","USA","美国","Estados Unidos","अमेरिका"}},
        {"Sri Lanka",{"Sri Lanka","இலங்கை","श्रीलंका"}},{"Japan",{"Japan","日本","Japón","जापान"}},{"Germany",{"Germany","德国","Alemania"}}};
    return seeds;
}
// Indic and Han cue words. Indic cues match token prefixes (Tamil and Telugu inflect by suffixing).
const std::vector<std::string> hi_person_after={"ने","जी","बोला","बोली","बोले"};
const std::vector<std::string> ta_person_after={"சொன்னார்","சொன்னான்","சொன்னாள்","சொன்னாங்க","கூறினார்","கூறினான்","எழுதினார்","கேட்டார்","சார்"};
const std::vector<std::string> te_person_after={"చెప్పారు","చెప్పాడు","చెప్పింది","అన్నారు","అన్నాడు","అంది","రాశారు","అడిగారు","గారు"};
const std::vector<std::string> indic_honorific_before={"श्री","श्रीमती","डॉ","डॉक्टर","திரு","திருமதி","டாக்டர்","శ్రీ","శ్రీమతి","డాక్టర్"};
const std::unordered_set<std::string> indic_stop={"जी","सर","சார்","அவர்கள்","గారు","కల","कल","आज","फिर","और","तो","भी","ने","को","से","में","का","की","के","है","हैं","था","थी","थे","हम",
    "मैं","वह","यह","उस","इस","मुझे","आप","क्या","जो","कि","पर","एक","लेकिन","अब","बहुत","सब","उन्होंने","मैंने","हमने","उसने","इसने","आपने",
    "நான்","நாம்","நாங்கள்","அவர்","அவன்","அவள்","இது","அது","இன்று","நேற்று","நாளை","மேலும்","ஆனால்","என்று","ஒரு","எங்கள்","அந்த","இந்த",
    "నేను","మేము","మనం","అతను","ఆమె","ఇది","అది","ఈరోజు","నిన్న","రేపు","మరియు","కానీ","అని","ఒక","మా","ఆ","ఈ","వారు"};
const std::vector<std::string> indic_org_suffix={"कंपनी","बैंक","विश्वविद्यालय","कॉलेज","अस्पताल","लिमिटेड","संस्थान","நிறுவன","வங்கி",
    "பல்கலைக்கழக","கல்லூரி","மருத்துவமனை","லிமிடெட்","సంస్థ","బ్యాంక్","విశ్వవిద్యాలయ","కళాశాల","ఆసుపత్రి","లిమిటెడ్","కంపెనీ"};
const std::vector<std::string> indic_project_words={"प्रोजेक्ट","परियोजना","திட்ட","ப்ராஜெக்ட்","புராஜெக்ட்","ப்ரொஜெக்ட்","ప్రాజెక్ట"};
const std::vector<std::string> indic_place_suffix={"शहर","नगर","நகர","నగర"};
const std::vector<std::string> han_org_suffix={"有限公司","公司","大学","银行","集团","研究所","研究院","医院","学院","科技"};
const std::vector<std::string> han_person_after={"说","告诉","提到","问","写","发","表示","认为","同意","决定","打电话","老师","经理","先生","女士","总",
    "教授","医生","同学","主任","：",":","，",","};
const std::vector<std::string> han_titles={"老师","经理","先生","女士","总","教授","医生","主任"};
const std::unordered_set<std::string> han_person_before={"和","跟","给","问","告诉","让","请","与","同"};
const std::unordered_set<std::string> han_stop={"在","的","和","跟","去","到","从","是","了","给","我","他","她","们","说","与","对","把","被","这",
    "那","个","也","都","就","要","会","把","将","向","为","于","及","或","上","下","中","里","有","没","不","请","让","今","明","昨"};
const std::string han_surnames="王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖田董袁潘于蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆"
                               "汪范金石廖贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤";

bool name_tok(const Tok& t){return t.t==T::word&&t.script==S::latin&&t.cap&&t.s.size()>=2&&!stop_cap.contains(t.low);}
bool indic_name_tok(const Tok& t){return t.t==T::word&&indic(t.script)&&!indic_stop.contains(t.s);}
bool prefix_in(const std::string& s,const std::vector<std::string>& words){for(const auto& w:words)if(starts_with(s,w))return true;return false;}
// [i,j): capitalised Latin run of up to 4 words in one sentence; "of" joins only after an organisation word.
std::size_t cap_run(const V& tk,std::size_t i) {
    if(i>=tk.size()||!name_tok(tk[i]))return i;
    std::size_t j=i+1;
    while(j<tk.size()&&j-i<4&&tk[j].sent==tk[i].sent&&!tk[j].newline) {
        if(name_tok(tk[j])){++j;continue;}
        const bool joins=connectors.contains(tk[j].low)||(tk[j].low=="of"&&org_prefix.contains(tk[i].low));
        if(joins&&j+1<tk.size()&&name_tok(tk[j+1])&&tk[j+1].sent==tk[i].sent){j+=2;continue;}
        break;
    }
    return j;
}
std::size_t run_start(const V& tk,std::size_t j) {  // start of the capitalised run ending just before j
    std::size_t i=j;
    while(i>0&&j-i<4&&name_tok(tk[i-1])&&tk[i-1].sent==tk[j-1].sent&&!(i<j&&tk[i].newline))--i;
    return i;
}
std::string han_string(const V& tk,std::size_t i,std::size_t n) {  // n adjacent Han tokens from i, or ""
    std::string s;
    for(std::size_t k=i;k<i+n;++k){if(k>=tk.size()||tk[k].t!=T::han||(k>i&&tk[k].b!=tk[k-1].e))return "";s+=tk[k].s;}
    return s;
}
bool han_at(const V& tk,std::size_t i,const std::string& word) {  // the Han (or punctuation) word starting at token i
    std::size_t n=0;for(const auto& c:decode(word)){(void)c;++n;}
    std::string s;
    for(std::size_t k=i;k<i+n;++k){if(k>=tk.size()||(k>i&&tk[k].b!=tk[k-1].e))return false;s+=tk[k].s;}
    return s==word;
}
std::size_t han_len(const std::string& word){std::size_t n=0;for(const auto& c:decode(word)){(void)c;++n;}return n;}

// ---------------------------------------------------------------- mentions
struct Builder {
    const std::string& text;const V& tk;std::vector<Mention> out;
    void add(EntityType type,std::size_t first,std::size_t last,const std::string& rule,double conf,std::size_t name_first=SIZE_MAX,std::size_t name_last=SIZE_MAX) {
        if(first>=last||last>tk.size())return;
        Mention m{type,tk[first].b,tk[last-1].e,{},{},rule,conf};m.surface=text.substr(m.start,m.end-m.start);
        if(name_first==SIZE_MAX){name_first=first;name_last=last;}
        m.name=text.substr(tk[name_first].b,tk[name_last-1].e-tk[name_first].b);
        if(m.surface.size()>120||m.name.empty())return;
        out.push_back(std::move(m));
    }
    void add_bytes(EntityType type,std::size_t start,std::size_t end,const std::string& rule,double conf,const std::string& name) {
        if(start>=end||end>text.size()||end-start>120)return;
        out.push_back({type,start,end,text.substr(start,end-start),name,rule,conf});
    }
};
// Up to two Indic words (or a capitalised Latin run) ending just before token j.
std::size_t indic_name_start(const V& tk,std::size_t j) {
    if(j==0)return j;
    if(name_tok(tk[j-1])&&tk[j-1].sent==tk[j].sent)return run_start(tk,j);
    if(!indic_name_tok(tk[j-1])||tk[j-1].sent!=tk[j].sent)return j;
    const std::size_t i=j-1;  // one word, or two when the pair opens the sentence or follows punctuation ("अरुण कुमार ने")
    if(i>0&&indic_name_tok(tk[i-1])&&tk[i-1].sent==tk[i].sent&&!tk[i].newline&&(i-1==0||tk[i-2].sent!=tk[i].sent||tk[i-2].t==T::punct))return i-1;
    return i;
}
bool boundary_ok(const std::string& text,std::size_t start,std::size_t end) {
    // A gazetteer hit must not sit inside a longer word of the same script (Han has no word boundaries).
    auto cls_at=[&](std::size_t pos,bool before)->S{
        if(before){if(pos==0)return S::space;std::size_t p=pos-1;while(p>0&&(static_cast<unsigned char>(text[p])&0xC0)==0x80)--p;
            const auto c=decode(text.substr(p,pos-p));return c.empty()?S::space:klass(c[0].cp);}
        if(pos>=text.size())return S::space;std::size_t n=1;const auto c0=static_cast<unsigned char>(text[pos]);n=c0<0x80?1:(c0>>5)==6?2:(c0>>4)==14?3:4;
        const auto c=decode(text.substr(pos,std::min(n,text.size()-pos)));return c.empty()?S::space:klass(c[0].cp);
    };
    const auto first=decode(text.substr(start,std::min<std::size_t>(4,end-start)));
    const S own=first.empty()?S::space:klass(first[0].cp);
    if(own==S::han)return true;
    const S before=cls_at(start,true),after=cls_at(end,false);
    auto same=[&](S x){return x==own||(own==S::latin&&x==S::digit)||(indic(own)&&x==S::joiner);};
    return !same(before)&&!same(after);
}
void seed_place_mentions(const std::string& text,Builder& b) {
    for(const auto& seed:seed_places())for(const auto& spelling:seed.spellings) {
        for(std::size_t pos=text.find(spelling);pos!=std::string::npos;pos=text.find(spelling,pos+spelling.size()))
            if(boundary_ok(text,pos,pos+spelling.size()))b.add_bytes(EntityType::place,pos,pos+spelling.size(),"seed_place",0.75,seed.canonical);
    }
}

void person_rules(Builder& b) {
    const V& tk=b.tk;
    for(std::size_t i=0;i<tk.size();++i) {
        const Tok& t=tk[i];
        // Honorific before a capitalised run: "Dr. Meena Iyer", "Sra. López".
        if(t.t==T::word&&honorific_before.contains(t.low)) {
            std::size_t k=i+1;if(k<tk.size()&&tk[k].t==T::punct&&tk[k].cp=='.')++k;
            const auto j=cap_run(tk,k);if(j>k)b.add(EntityType::person,k,j,"honorific",0.9);
        }
        // Capitalised run followed by a speech verb or an honorific: "Arun said", "Priya ji", "Ravi garu".
        if(name_tok(t)&&(i==0||!name_tok(tk[i-1])||tk[i-1].sent!=t.sent)) {
            const auto j=cap_run(tk,i);
            if(j<tk.size()&&tk[j].sent==t.sent&&tk[j].t==T::word) {
                if(verbs_after.contains(tk[j].low))b.add(EntityType::person,i,j,"speech_verb",0.85);
                else if(honorific_after.contains(tk[j].low))b.add(EntityType::person,i,j,"honorific_after",0.85);
            }
            if(i>0&&tk[i-1].t==T::word&&tk[i-1].sent==t.sent&&verbs_before.contains(tk[i-1].low))b.add(EntityType::person,i,j,"verb_object",0.7);
        }
        // Chat line "Arun: …" or "[10:02] Priya: …"; e-mail headers "From: Arun Kumar".
        if(t.newline||i==0) {
            std::size_t k=i;
            if(tk[k].t==T::punct&&tk[k].cp=='['){while(k<tk.size()&&!(tk[k].t==T::punct&&tk[k].cp==']')&&k-i<16)++k;++k;}
            if(k<tk.size()&&header_people.contains(tk[k].low)&&k+1<tk.size()&&tk[k+1].t==T::punct&&(tk[k+1].cp==':'||tk[k+1].cp==0xFF1A)) {
                const auto j=cap_run(tk,k+2);if(j>k+2)b.add(EntityType::person,k+2,j,"header",0.85);
            } else {
                std::size_t j=k;
                while(j<tk.size()&&j-k<3&&(tk[j].t==T::word||tk[j].t==T::han)&&(j==k||!tk[j].newline))++j;
                for(std::size_t end=j;end>k;--end) {
                    if(end<tk.size()&&tk[end].t==T::punct&&(tk[end].cp==':'||tk[end].cp==0xFF1A)&&end+1<tk.size()&&tk[end+1].sent==tk[k].sent) {
                        bool ok=!header_words.contains(tk[k].low)&&!header_people.contains(tk[k].low);
                        for(std::size_t q=k;q<end&&ok;++q){
                            if(tk[q].script==S::latin)ok=name_tok(tk[q]);
                            else if(tk[q].t==T::han)ok=q>k||han_surnames.find(tk[q].s)!=std::string::npos;
                            else ok=indic_name_tok(tk[q]);
                        }
                        if(ok&&!(tk[k].t==T::han&&end-k<2))b.add(EntityType::person,k,end,"chat_speaker",0.8);
                        break;
                    }
                }
            }
        }
        // Hindi/Tamil/Telugu: name before an agent marker, speech verb or honorific ("अरुण ने कहा", "அருண் சொன்னார்", "అరుణ్ గారు").
        if(t.t==T::word&&indic(t.script)&&i>0) {
            const bool cue=(t.script==S::deva&&std::find(hi_person_after.begin(),hi_person_after.end(),t.s)!=hi_person_after.end())||
                           (t.script==S::taml&&prefix_in(t.s,ta_person_after))||(t.script==S::telu&&prefix_in(t.s,te_person_after));
            if(cue){const auto s=indic_name_start(tk,i);if(s<i)b.add(EntityType::person,s,i,"indic_marker",0.85);}
            if(prefix_in(t.s,indic_honorific_before)) {
                std::size_t k=i+1;if(k<tk.size()&&tk[k].t==T::punct&&tk[k].cp=='.')++k;
                std::size_t j=k;while(j<tk.size()&&j-k<2&&indic_name_tok(tk[j])&&tk[j].sent==t.sent)++j;
                if(j>k)b.add(EntityType::person,k,j,"indic_honorific",0.85);
            }
        }
        // Chinese: surname + one or two characters (or a title) followed by a speech verb/title, after a boundary.
        if(t.t==T::han&&han_surnames.find(t.s)!=std::string::npos) {
            const bool before_ok=i==0||tk[i-1].t!=T::han||tk[i-1].e!=t.b||han_person_before.contains(tk[i-1].s);
            if(!before_ok)continue;
            bool done=false;
            for(const auto& title:han_titles)if(han_at(tk,i+1,title)){b.add(EntityType::person,i,i+1+han_len(title),"zh_title",0.8);done=true;break;}
            for(std::size_t len=2;len<=3&&!done;++len) {
                if(han_string(tk,i,len).empty())break;
                bool stop=false;for(std::size_t q=i+1;q<i+len;++q)if(han_stop.contains(tk[q].s))stop=true;
                if(stop)break;
                for(const auto& marker:han_person_after)
                    if(han_at(tk,i+len,marker)){b.add(EntityType::person,i,i+len,"zh_speech_verb",0.8);done=true;break;}
            }
        }
    }
}

void organization_rules(Builder& b) {
    const V& tk=b.tk;
    for(std::size_t i=0;i<tk.size();++i) {
        const Tok& t=tk[i];
        if(name_tok(t)&&(i==0||!name_tok(tk[i-1])||tk[i-1].sent!=t.sent)) {
            const auto j=cap_run(tk,i);
            if(j>i) {
                if(org_prefix.contains(t.low)&&j-i>=3)b.add(EntityType::organization,i,j,"org_prefix",0.85);
                else if(j-i>=2&&org_suffix.contains(tk[j-1].low))b.add(EntityType::organization,i,j,"org_suffix",0.9);
                else if(j-i>=2&&legal_suffix.contains(tk[j-1].low))b.add(EntityType::organization,i,j,"legal_suffix",0.9,i,j-1);
                else if(j<tk.size()&&tk[j].sent==t.sent&&tk[j].t==T::word&&legal_suffix.contains(tk[j].low))
                    b.add(EntityType::organization,i,j+1,"legal_suffix",0.9,i,j);
            }
        }
        // Chinese organisations: "华为公司", "清华大学", "Acme公司".
        if(t.t==T::han) {
            for(const auto& suffix:han_org_suffix) {
                if(!han_at(tk,i,suffix))continue;
                std::size_t s=i;
                if(i>0&&tk[i-1].t==T::word&&tk[i-1].script==S::latin&&tk[i-1].e==t.b)s=i-1;
                else while(s>0&&i-s<6&&tk[s-1].t==T::han&&tk[s-1].e==tk[s].b&&!han_stop.contains(tk[s-1].s))--s;
                if(s<i&&(tk[s].t!=T::han||i-s>=2))b.add(EntityType::organization,s,i+han_len(suffix),"zh_org_suffix",0.85);
                break;
            }
        }
        if(t.t==T::word&&indic(t.script)&&i>0&&prefix_in(t.s,indic_org_suffix)) {
            const auto s=indic_name_start(tk,i);if(s<i)b.add(EntityType::organization,s,i+1,"indic_org_suffix",0.85,s,i);
        }
    }
}

void place_and_project_rules(Builder& b) {
    const V& tk=b.tk;
    for(std::size_t i=0;i<tk.size();++i) {
        const Tok& t=tk[i];
        for(const auto& cue:place_cues_en) {  // "flight to Lisbon", "office in Pune"
            std::size_t k=i,pos=0;bool match=true;
            while(pos<cue.size()){const auto sp=cue.find(' ',pos);const auto w=cue.substr(pos,sp==std::string::npos?std::string::npos:sp-pos);
                if(k>=tk.size()||tk[k].low!=w||tk[k].sent!=t.sent){match=false;break;}++k;pos=sp==std::string::npos?cue.size():sp+1;}
            if(match){const auto j=cap_run(tk,k);if(j>k)b.add(EntityType::place,k,j,"place_cue",0.75);break;}
        }
        if(t.t==T::han&&(t.s=="在"||t.s=="去"||t.s=="到"||t.s=="从")) {
            for(std::size_t len=1;len<=4;++len) {
                const auto name=han_string(tk,i+1,len);if(name.empty())break;
                const auto next=han_string(tk,i+1+len,1);
                if(next=="市"||next=="省"||next=="县"||next=="区"){b.add(EntityType::place,i+1,i+2+len,"zh_place_suffix",0.8);break;}
            }
        }
        if(t.t==T::word&&indic(t.script)&&i>0&&prefix_in(t.s,indic_place_suffix)&&indic_name_tok(tk[i-1])&&tk[i-1].sent==t.sent)
            b.add(EntityType::place,i-1,i,"indic_place_suffix",0.75);
        // Projects: "Project Orion", "the Orion project", "proyecto Orion", "Orion प्रोजेक्ट", "Orion项目".
        if(t.t==T::word&&project_words.contains(t.low)) {
            const std::size_t k=i+1;
            if(k<tk.size()&&tk[k].sent==t.sent&&tk[k].t==T::word&&tk[k].script==S::latin&&(name_tok(tk[k])||tk[k].camel)&&!project_stop.contains(tk[k].low)) {
                const auto j=std::max(cap_run(tk,k),k+1);b.add(EntityType::project,k,j,"project_word_before",0.9);
            }
            if(i>0&&name_tok(tk[i-1])&&tk[i-1].sent==t.sent) {
                const auto s=run_start(tk,i);std::size_t first=s;while(first<i&&project_stop.contains(tk[first].low))++first;
                if(first<i)b.add(EntityType::project,first,i,"project_word_after",0.85);
            }
        }
        if(t.t==T::word&&indic(t.script)&&i>0&&prefix_in(t.s,indic_project_words)&&tk[i-1].sent==t.sent) {
            const auto& p=tk[i-1];
            if(name_tok(p)||p.camel){b.add(EntityType::project,run_start(tk,i),i,"indic_project_word",0.85);}
            else if(indic_name_tok(p))b.add(EntityType::project,i-1,i,"indic_project_word",0.75);
        }
        if(t.t==T::han&&(han_at(tk,i,"项目")||han_at(tk,i,"计划"))) {
            if(i>0&&tk[i-1].t==T::word&&tk[i-1].script==S::latin&&tk[i-1].e==t.b&&(tk[i-1].cap||tk[i-1].camel))b.add(EntityType::project,i-1,i,"zh_project_word",0.85);
            else {std::size_t s=i;while(s>0&&i-s<4&&tk[s-1].t==T::han&&tk[s-1].e==tk[s].b&&!han_stop.contains(tk[s-1].s))--s;
                if(i-s>=2)b.add(EntityType::project,s,i,"zh_project_word",0.7);}
        }
        // Products: "Notion app", "Pixel 8", "Python 3.12", "iPhone 15".
        if((name_tok(t)||t.camel)&&(i==0||!name_tok(tk[i-1])||tk[i-1].sent!=t.sent)) {
            const auto j=std::max(cap_run(tk,i),i+1);
            if(j<tk.size()&&tk[j].sent==t.sent) {
                if(tk[j].t==T::word&&!tk[j].cap&&product_words.contains(tk[j].low))b.add(EntityType::product,i,j,"product_word",0.75);
                else if(j==i+1&&tk[j].t==T::number&&tk[j].suffix.empty()&&tk[j].s.size()<=5&&tk[j].s.find_first_of(",/:-")==std::string::npos&&
                        !product_stop.contains(t.low)&&t.low.size()>=3)b.add(EntityType::product,i,j+1,"product_version",0.7);
            }
        }
    }
}
// Overlapping mentions: the more confident one wins, then the longer, then the earlier.
std::vector<Mention> resolve(std::vector<Mention> in) {
    std::stable_sort(in.begin(),in.end(),[](const Mention& a,const Mention& b){
        if(a.confidence!=b.confidence)return a.confidence>b.confidence;
        if(a.end-a.start!=b.end-b.start)return a.end-a.start>b.end-b.start;return a.start<b.start;});
    std::vector<Mention> kept;
    for(auto& m:in){bool overlap=false;for(const auto& k:kept)if(m.start<k.end&&k.start<m.end){overlap=true;break;}if(!overlap)kept.push_back(std::move(m));}
    std::sort(kept.begin(),kept.end(),[](const Mention& a,const Mention& b){return a.start<b.start;});
    return kept;
}

// ---------------------------------------------------------------- dates
using namespace std::chrono;
const std::unordered_map<std::string,int>& months() {
    static const std::unordered_map<std::string,int> m={
        {"january",1},{"jan",1},{"february",2},{"feb",2},{"march",3},{"mar",3},{"april",4},{"apr",4},{"may",5},{"june",6},{"jun",6},{"july",7},{"jul",7},
        {"august",8},{"aug",8},{"september",9},{"sep",9},{"sept",9},{"october",10},{"oct",10},{"november",11},{"nov",11},{"december",12},{"dec",12},
        {"enero",1},{"febrero",2},{"marzo",3},{"abril",4},{"mayo",5},{"junio",6},{"julio",7},{"agosto",8},{"septiembre",9},{"setiembre",9},
        {"octubre",10},{"noviembre",11},{"diciembre",12},
        {"जनवरी",1},{"फरवरी",2},{"फ़रवरी",2},{"मार्च",3},{"अप्रैल",4},{"मई",5},{"जून",6},{"जुलाई",7},{"अगस्त",8},{"सितंबर",9},{"सितम्बर",9},
        {"अक्टूबर",10},{"नवंबर",11},{"नवम्बर",11},{"दिसंबर",12},{"दिसम्बर",12},
        {"ஜனவரி",1},{"பிப்ரவரி",2},{"மார்ச்",3},{"ஏப்ரல்",4},{"மே",5},{"ஜூன்",6},{"ஜூலை",7},{"ஆகஸ்ட்",8},{"செப்டம்பர்",9},{"அக்டோபர்",10},
        {"நவம்பர்",11},{"டிசம்பர்",12},
        {"జనవరి",1},{"ఫిబ్రవరి",2},{"మార్చి",3},{"ఏప్రిల్",4},{"మే",5},{"జూన్",6},{"జూలై",7},{"ఆగస్టు",8},{"సెప్టెంబర్",9},{"అక్టోబర్",10},
        {"నవంబర్",11},{"డిసెంబర్",12}};
    return m;
}
int month_of(const Tok& t){if(t.t!=T::word)return 0;const auto& m=months();auto it=m.find(t.script==S::latin?t.low:t.s);return it==m.end()?0:it->second;}
int weekday_of(const Tok& t) {  // Monday = 0
    static const std::vector<std::pair<std::string,int>> w={
        {"monday",0},{"tuesday",1},{"wednesday",2},{"thursday",3},{"friday",4},{"saturday",5},{"sunday",6},
        {"lunes",0},{"martes",1},{"miércoles",2},{"miercoles",2},{"jueves",3},{"viernes",4},{"sábado",5},{"sabado",5},{"domingo",6},
        {"सोमवार",0},{"मंगलवार",1},{"बुधवार",2},{"गुरुवार",3},{"बृहस्पतिवार",3},{"शुक्रवार",4},{"शनिवार",5},{"रविवार",6},
        {"திங்கள்",0},{"செவ்வாய்",1},{"புதன்",2},{"வியாழன்",3},{"வெள்ளி",4},{"சனி",5},{"ஞாயிறு",6},
        {"సోమవార",0},{"మంగళవార",1},{"బుధవార",2},{"గురువార",3},{"శుక్రవార",4},{"శనివార",5},{"ఆదివార",6}};
    if(t.t!=T::word)return -1;
    for(const auto& [name,d]:w){if(t.script==S::latin?t.low==name:(starts_with(t.s,name)&&(t.script==S::taml||t.script==S::telu||t.s==name)))return d;}
    return -1;
}
int day_num(const Tok& t) {
    if(t.t!=T::number||t.s.size()>2||t.s.find_first_not_of("0123456789")!=std::string::npos)return 0;
    if(!t.suffix.empty()&&t.suffix!="st"&&t.suffix!="nd"&&t.suffix!="rd"&&t.suffix!="th")return 0;
    const int d=std::stoi(t.s);return d>=1&&d<=31?d:0;
}
int year_num(const Tok& t) {
    if(t.t!=T::number||t.s.size()!=4||!t.suffix.empty()||t.s.find_first_not_of("0123456789")!=std::string::npos)return 0;
    const int y=std::stoi(t.s);return y>=1970&&y<=2100?y:0;
}
struct DateHit {year_month_day ymd;std::size_t first=0,last=0;bool relative=false;};
year_month_day day_of(std::int64_t secs){return year_month_day{floor<days>(sys_seconds{seconds{secs}})};}
std::optional<year_month_day> make(int y,int m,int d){year_month_day v{year{y},month{static_cast<unsigned>(m)},day{static_cast<unsigned>(d)}};if(!v.ok())return std::nullopt;return v;}
// A day and month without a year belongs to the source's year, or the next one when that is long past.
std::optional<year_month_day> infer_year(int m,int d,std::int64_t ref) {
    const auto r=day_of(ref);auto v=make(static_cast<int>(r.year()),m,d);if(!v)return std::nullopt;
    if(sys_days{*v}<sys_days{r}-days{60})v=make(static_cast<int>(r.year())+1,m,d);
    return v;
}
std::optional<DateHit> date_at(const V& tk,std::size_t i,std::int64_t ref) {
    const Tok& t=tk[i];
    auto same=[&](std::size_t k){return k<tk.size()&&tk[k].sent==t.sent;};
    if(t.t==T::number&&t.suffix.empty()) {
        int a=0,b=0,c=0;char s1=0,s2=0;
        const auto p1=t.s.find_first_of("-/."),p2=p1==std::string::npos?p1:t.s.find_first_of("-/.",p1+1);
        const bool shaped=p2!=std::string::npos&&t.s.find_first_of("-/.,:",p2+1)==std::string::npos&&p1>0&&p1<=4&&p2-p1-1>=1&&p2-p1-1<=2&&t.s.size()-p2-1>=1&&t.s.size()-p2-1<=4;
        if(shaped){a=std::stoi(t.s.substr(0,p1));b=std::stoi(t.s.substr(p1+1,p2-p1-1));c=std::stoi(t.s.substr(p2+1));s1=t.s[p1];s2=t.s[p2];}
        if(shaped&&s1==s2&&(s1=='-'||s1=='/'||s1=='.')) {
            if(t.s.size()==10&&a>=1970&&s1!='.'){if(auto v=make(a,b,c))return DateHit{*v,i,i+1};}  // 2026-11-03
            else if(c>=1970&&c<=2100) {  // day/month order only when unambiguous
                if(a>12&&b<=12){if(auto v=make(c,b,a))return DateHit{*v,i,i+1};}
                else if(b>12&&a<=12){if(auto v=make(c,a,b))return DateHit{*v,i,i+1};}
                else if(a==b){if(auto v=make(c,a,b))return DateHit{*v,i,i+1};}
            }
        }
    }
    // 3 Nov [2026] | 3rd of November | 3 de noviembre [de 2026] | 3 नवंबर
    if(const int d=day_num(t)) {
        std::size_t k=i+1;if(same(k)&&(tk[k].low=="de"||tk[k].low=="of"))++k;
        if(same(k)&&month_of(tk[k])) {
            const int m=month_of(tk[k]);std::size_t stop=k+1;int y=0;
            std::size_t q=stop;if(same(q)&&tk[q].t==T::punct&&tk[q].cp==',')++q;if(same(q)&&tk[q].low=="de")++q;
            if(same(q)&&(y=year_num(tk[q])))stop=q+1;
            const auto v=y?make(y,m,d):infer_year(m,d,ref);if(v)return DateHit{*v,i,stop};
        }
    }
    // Nov 3[rd][, 2026] | நவம்பர் 3 | నవంబర్ 3
    if(const int m=month_of(t)) {
        std::size_t k=i+1;if(same(k)&&tk[k].t==T::punct&&tk[k].cp=='.')++k;
        if(same(k)&&day_num(tk[k])) {
            const int d=day_num(tk[k]);std::size_t stop=k+1;int y=0;std::size_t q=stop;
            if(same(q)&&tk[q].t==T::punct&&tk[q].cp==',')++q;
            if(same(q)&&(y=year_num(tk[q])))stop=q+1;
            const auto v=y?make(y,m,d):infer_year(m,d,ref);if(v)return DateHit{*v,i,stop};
        }
    }
    // [2026年]11月3日/号
    if(t.t==T::number&&t.suffix.empty()&&t.s.find_first_not_of("0123456789")==std::string::npos) {
        std::size_t k=i;int y=0;
        if(t.s.size()==4&&han_at(tk,i+1,"年")){y=std::stoi(t.s);k=i+2;}
        if(k<tk.size()&&tk[k].t==T::number&&tk[k].s.size()<=2&&tk[k].s.find_first_not_of("0123456789")==std::string::npos&&han_at(tk,k+1,"月")&&
           k+2<tk.size()&&tk[k+2].t==T::number&&tk[k+2].s.size()<=2&&tk[k+2].s.find_first_not_of("0123456789")==std::string::npos&&(han_at(tk,k+3,"日")||han_at(tk,k+3,"号"))) {
            const int m=std::stoi(tk[k].s),d=std::stoi(tk[k+2].s);const auto v=y?make(y,m,d):infer_year(m,d,ref);
            if(v)return DateHit{*v,i,k+4};
        }
    }
    const auto r=sys_days{day_of(ref)};const int ref_wd=static_cast<int>((weekday{r}.c_encoding()+6)%7);
    auto ahead=[&](int wd,bool next_week){int delta=(wd-ref_wd+7)%7;if(delta==0)delta=7;if(next_week)delta=7-ref_wd+wd;return year_month_day{r+days{delta}};};
    // Weekdays: "Friday", "el viernes", "शुक्रवार", "வெள்ளிக்கிழமை", "శుక్రవారం", "周五", "下星期五"
    if(const int wd=weekday_of(t);wd>=0)return DateHit{ahead(wd,false),i,i+1,true};
    if(t.t==T::han) {
        const bool next_week=t.s=="下";const std::size_t k=next_week?i+1:i;
        for(const char* lead:{"星期","礼拜","周"}) {
            if(!han_at(tk,k,lead))continue;
            const std::size_t q=k+han_len(lead);if(q>=tk.size()||tk[q].t!=T::han||tk[q].b!=tk[q-1].e)break;
            static const std::vector<std::string> numerals={"一","二","三","四","五","六","日"};
            for(int d=0;d<7;++d)if(tk[q].s==numerals[d]||(d==6&&tk[q].s=="天"))return DateHit{ahead(d,next_week),i,q+1,true};
            break;
        }
    }
    // Today / tomorrow
    int delta=-1;
    if(t.t==T::word) {
        if(t.low=="today"||t.low=="hoy"||t.s=="आज"||t.s=="இன்று"||starts_with(t.s,"ఈరోజు"))delta=0;
        else if(t.low=="tomorrow"||t.s=="நாளை"||t.s=="రేపు")delta=1;
        else if(t.low=="mañana"&&!(i>0&&(tk[i-1].low=="la"||tk[i-1].low=="por"||tk[i-1].low=="esta")))delta=1;
    } else if(t.t==T::han){if(han_at(tk,i,"今天"))delta=0;else if(han_at(tk,i,"明天"))delta=1;else if(han_at(tk,i,"后天"))delta=2;}
    if(delta>=0)return DateHit{year_month_day{r+days{delta}},i,i+(t.t==T::han?2:1),true};
    return std::nullopt;
}
std::string iso(year_month_day d) {
    char buf[16];std::snprintf(buf,sizeof buf,"%04d-%02u-%02u",static_cast<int>(d.year()),static_cast<unsigned>(d.month()),static_cast<unsigned>(d.day()));return buf;
}

// ---------------------------------------------------------------- facts
struct Sentence {std::size_t first,last;std::string text;std::size_t start,end;};
bool has_word(const V& tk,const Sentence& s,const std::vector<std::string>& words) {
    for(std::size_t i=s.first;i<s.last;++i) {
        const auto& t=tk[i];
        for(const auto& w:words) {
            if(w.find(' ')!=std::string::npos) {  // multi-word Latin cue
                std::size_t k=i,pos=0;bool ok=true;
                while(pos<w.size()){const auto sp=w.find(' ',pos);const auto part=w.substr(pos,sp==std::string::npos?std::string::npos:sp-pos);
                    if(k>=s.last||tk[k].low!=part){ok=false;break;}++k;pos=sp==std::string::npos?w.size():sp+1;}
                if(ok)return true;
            }
            else if(t.script==S::latin?t.low==w:(indic(t.script)&&starts_with(t.s,w)))return true;
        }
    }
    return false;
}
bool has_han(const Sentence& s,const std::vector<std::string>& words){for(const auto& w:words)if(s.text.find(w)!=std::string::npos)return true;return false;}
const std::vector<std::string> deadline_words={"deadline","due","submit","submission","deliver","deliverable","deliverables","fecha límite","fecha limite",
    "plazo","vence","entregar","entrega","डेडलाइन","अंतिम","जमा","सबमिट","கடைசி","காலக்கெடு","சமர்ப்பி","டெட்லைன்","గడువు","చివరి","సమర్పించ","డెడ్"};
const std::vector<std::string> deadline_han={"截止","之前","提交","交付","期限"};
const std::vector<std::string> meeting_words={"meeting","meet","call","interview","appointment","demo","standup","sync","presentation","reunión",
    "reunion","llamada","cita","entrevista","मीटिंग","बैठक","मुलाकात","इंटरव्यू","कॉल","கூட்டம்","மீட்டிங்","சந்திப்பு","நேர்காணல்","கால்",
    "సమావేశం","మీటింగ్","ఇంటర్వ్యూ","కాల్"};
const std::vector<std::string> meeting_han={"会议","开会","见面","面试","电话会","会面"};
const std::vector<std::string> negation_words={"not","never","didn","haven","hasn","don","doesn","weren","wasn","isn","aren","undecided","no","nunca",
    "नहीं","இல்லை","வில்லை","లేదు"};
const std::vector<std::string> negation_han={"没","未","不"};
const std::vector<std::string> decision_words={"decided","agreed","chose","finalized","finalised","approved","will go with","going with","settled on",
    "decidimos","decidió","decidio","decidieron","acordamos","acordaron","se decidió","aprobamos","aprobaron","elegimos","तय","फैसला","फ़ैसला","निर्णय",
    "முடிவு","ஒப்புக்கொண்ட","నిర్ణయ","అంగీకరించ"};
const std::vector<std::string> decision_han={"决定","同意","确定","选定","批准"};
struct AmountCue {std::string predicate;std::vector<std::string> words,han;};
const std::vector<AmountCue>& amount_cues() {
    static const std::vector<AmountCue> c={
        {"budget",{"budget","presupuesto","बजट","பட்ஜெட்","బడ్జెట్"},{"预算"}},
        {"salary",{"salary","salario","sueldo","वेतन","तनख्वाह","சம்பளம்","జీతం"},{"工资","薪水"}},
        {"rent",{"rent","alquiler","renta","किराया","வாடகை","అద్దె"},{"房租","租金"}},
        {"refund",{"refund","refunded","reembolso","रिफंड","ரீஃபண்ட்","రిఫండ్"},{"退款"}},
        {"invoice",{"invoice","bill","factura","बिल","பில்","బిల్లు"},{"发票","账单"}},
        {"paid",{"paid","pay","payment","pagué","pague","pagado","pago","भुगतान","चुकाया","செலுத்தி","చెల్లించ"},{"支付","付了","付款"}},
        {"cost",{"cost","costs","price","priced","fee","fees","costo","precio","cuesta","कीमत","लागत","खर्च","விலை","செலவு","கட்டணம்","ధర","ఖర్చు"},{"价格","费用","花了"}}};
    return c;
}
struct Currency {std::string code;double scale=1;};
std::optional<Currency> currency_word(const Tok& t,bool han_text) {
    static const std::unordered_map<std::string,std::string> latin={{"rs","INR"},{"inr","INR"},{"usd","USD"},{"eur","EUR"},{"gbp","GBP"},{"mxn","MXN"},
        {"cny","CNY"},{"rmb","CNY"},{"dollars","USD"},{"dollar","USD"},{"bucks","USD"},{"euros","EUR"},{"euro","EUR"},{"rupees","INR"},{"rupee","INR"},
        {"pesos","MXN"},{"yuan","CNY"},{"pounds","GBP"}};
    if(t.t==T::punct) {
        if(t.cp=='$')return Currency{"USD"};if(t.cp==0x20B9)return Currency{"INR"};if(t.cp==0x20AC)return Currency{"EUR"};
        if(t.cp==0xA3)return Currency{"GBP"};if(t.cp==0xA5||t.cp==0xFFE5)return Currency{han_text?"CNY":"JPY"};
        return std::nullopt;
    }
    if(t.t==T::word&&t.script==S::latin){if(auto it=latin.find(t.low);it!=latin.end())return Currency{it->second};return std::nullopt;}
    if(t.t==T::word&&(starts_with(t.s,"रुप")||t.s=="रु"||starts_with(t.s,"ரூ")||starts_with(t.s,"రూ")))return Currency{"INR"};
    if(t.t==T::han&&(t.s=="元"||t.s=="块"))return Currency{"CNY"};
    return std::nullopt;
}
double multiplier(const Tok& t) {
    static const std::unordered_map<std::string,double> m={{"thousand",1e3},{"lakh",1e5},{"lakhs",1e5},{"crore",1e7},{"crores",1e7},{"million",1e6},
        {"mil",1e3},{"millones",1e6},{"हज़ार",1e3},{"हजार",1e3},{"लाख",1e5},{"करोड़",1e7},{"ஆயிரம்",1e3},{"லட்சம்",1e5},{"கோடி",1e7},{"వేల",1e3},
        {"వెయ్యి",1e3},{"లక్ష",1e5},{"లక్షలు",1e5},{"కోటి",1e7},{"కోట్లు",1e7},{"万",1e4},{"千",1e3},{"亿",1e8}};
    auto it=m.find(t.script==S::latin?t.low:t.s);return it==m.end()?0:it->second;
}
std::optional<double> number_value(const Tok& t,const std::string& language) {
    if(t.t!=T::number)return std::nullopt;
    std::string s=t.s;if(s.find_first_of(":/-")!=std::string::npos)return std::nullopt;
    const auto dots=std::count(s.begin(),s.end(),'.');
    const bool es_thousands=language=="es"&&s.find(',')==std::string::npos&&dots>=1&&s.size()-s.rfind('.')==4;
    std::string clean;for(char c:s){if(c==','||(c=='.'&&es_thousands))continue;clean+=c;}
    if(std::count(clean.begin(),clean.end(),'.')>1)return std::nullopt;
    double v=0;try{v=std::stod(clean);}catch(...){return std::nullopt;}
    if(t.suffix=="k")v*=1e3;else if(!t.suffix.empty())return std::nullopt;
    return v;
}
std::string format_amount(double v,const std::string& code) {
    char buf[64];
    if(std::fabs(v-std::round(v))<1e-9&&std::fabs(v)<1e15)std::snprintf(buf,sizeof buf,"%.0f %s",v,code.c_str());
    else {std::snprintf(buf,sizeof buf,"%.2f",v);std::string s=buf;while(!s.empty()&&s.back()=='0')s.pop_back();if(!s.empty()&&s.back()=='.')s.pop_back();
        return s+" "+code;}
    return buf;
}
int subject_in(const std::vector<Mention>& ms,std::size_t start,std::size_t end) {
    static const EntityType order[]={EntityType::project,EntityType::organization,EntityType::person,EntityType::product};
    for(const auto type:order)for(std::size_t k=0;k<ms.size();++k)if(ms[k].type==type&&ms[k].start>=start&&ms[k].end<=end)return static_cast<int>(k);
    return -1;
}
int mention_at(const std::vector<Mention>& ms,std::size_t byte,bool starting) {
    for(std::size_t k=0;k<ms.size();++k)if(starting?ms[k].start==byte:ms[k].end==byte)return static_cast<int>(k);
    return -1;
}
void fact_rules(const std::string& text,const V& tk,std::int64_t ref,const std::string& language,const std::vector<Mention>& mentions,std::vector<Fact>& facts) {
    std::vector<Sentence> sentences;
    for(std::size_t i=0;i<tk.size();) {
        std::size_t j=i;while(j<tk.size()&&tk[j].sent==tk[i].sent)++j;
        std::size_t body=j;while(body>i+1&&tk[body-1].t==T::punct&&terminator(tk[body-1].cp))--body;
        Sentence s{i,j,{},tk[i].b,tk[body-1].e};
        if(s.end-s.start>400){s.end=tk[i].b;for(std::size_t k=i;k<body&&tk[k].e-tk[i].b<=400;++k)s.end=tk[k].e;}
        s.text=text.substr(s.start,s.end-s.start);sentences.push_back(std::move(s));i=j;
    }
    const bool han_text=script_of(text).find("han")!=std::string::npos||text.find("元")!=std::string::npos;
    for(const auto& s:sentences) {
        const bool question=tk[s.last-1].t==T::punct&&(tk[s.last-1].cp=='?'||tk[s.last-1].cp==0xFF1F);
        const bool negated=has_word(tk,s,negation_words)||has_han(s,negation_han);
        std::set<std::string> seen;
        auto push=[&](Fact f){const auto key=f.type+"|"+f.predicate+"|"+f.value;if(!seen.insert(key).second)return;
            f.start=s.start;f.end=s.end;if(f.subject<0)f.subject=subject_in(mentions,s.start,s.end);facts.push_back(std::move(f));};
        // Deadlines and meetings: a dated sentence with a deadline or meeting cue.
        if(!question)for(std::size_t i=s.first;i<s.last;++i) {
            const auto hit=date_at(tk,i,ref);if(!hit)continue;
            const auto prev=hit->first>s.first?tk[hit->first-1].low:std::string();
            const auto next=hit->last<s.last?tk[hit->last]:Tok{};
            const bool deadline_marker=prev=="by"||prev=="before"||prev=="antes"||prev=="until"||
                (hit->first>s.first+1&&tk[hit->first-1].low=="del"&&tk[hit->first-2].low=="antes")||next.s=="तक"||starts_with(next.s,"க்குள்")||
                starts_with(next.s,"குள்")||next.s=="లోపు"||next.s=="లోగా"||next.s=="前"||next.s=="之前";
            const bool deadline=deadline_marker||has_word(tk,s,deadline_words)||has_han(s,deadline_han);
            const bool meeting=has_word(tk,s,meeting_words)||has_han(s,meeting_han);
            if(deadline||meeting) {
                Fact f;f.type=deadline?"deadline":"meeting";f.predicate=deadline?"due":"scheduled";f.value=iso(hit->ymd);
                f.value_seconds=sys_seconds{sys_days{hit->ymd}}.time_since_epoch().count();
                f.rule=std::string(deadline?"deadline":"meeting")+(hit->relative?"_relative_date":"_date");
                f.confidence=(deadline?0.85:0.8)-(hit->relative?0.1:0.0);push(std::move(f));
            }
            i=hit->last-1;
        }
        // Amounts with a money cue in the same sentence ("budget is ₹5,00,000", "预算5万元").
        std::string predicate;
        for(const auto& cue:amount_cues())if(has_word(tk,s,cue.words)||has_han(s,cue.han)){predicate=cue.predicate;break;}
        if(!predicate.empty()&&!question)for(std::size_t i=s.first;i<s.last;++i) {
            std::optional<Currency> cur;std::optional<double> v;std::size_t n=i;
            if((cur=currency_word(tk[i],han_text))&&tk[i].t!=T::han) {  // $500, Rs. 500, INR 500
                n=i+1;if(n<s.last&&tk[n].t==T::punct&&tk[n].cp=='.')++n;
                if(n<s.last&&tk[n].t==T::punct&&tk[n].cp=='$')++n;
                if(n<s.last)v=number_value(tk[n],language);
            } else if(tk[i].t==T::number&&(v=number_value(tk[i],language))) {  // 500 dollars, 5 lakh rupees, 5万元, 5000 ரூபாய்
                n=i;if(n+1<s.last&&multiplier(tk[n+1])>0){*v*=multiplier(tk[n+1]);++n;}
                if(n+1<s.last)cur=currency_word(tk[n+1],han_text);
                if(cur)++n;else v.reset();
            }
            if(!cur||!v){continue;}
            if(tk[i].t!=T::number&&n+1<s.last&&multiplier(tk[n+1])>0){*v*=multiplier(tk[n+1]);++n;}
            Fact f;f.type="amount";f.predicate=predicate;f.value=format_amount(*v,cur->code);f.rule="amount_"+predicate;f.confidence=0.8;
            push(std::move(f));i=n;
        }
        // Decisions: an affirmative, non-question sentence with a decision verb.
        if(!question&&!negated&&(has_word(tk,s,decision_words)||has_han(s,decision_han))) {
            Fact f;f.type="decision";f.predicate="decided";f.rule="decision_verb";f.confidence=0.75;
            for(std::size_t k=0;k<mentions.size();++k)if(mentions[k].type==EntityType::person&&mentions[k].start>=s.start&&mentions[k].end<=s.end){f.subject=static_cast<int>(k);break;}
            push(std::move(f));
        }
        // Roles and affiliations: "Meena is the lead of Project Orion", "Arun from Acme Labs", "Priya works at Globex Inc".
        for(std::size_t k=0;k<mentions.size();++k) {
            const auto& p=mentions[k];if(p.type!=EntityType::person||p.start<s.start||p.end>s.end)continue;
            std::size_t i=s.first;while(i<s.last&&tk[i].b<p.end)++i;
            if(i>=s.last)continue;
            if(tk[i].low=="is"||tk[i].low=="was"||tk[i].low=="es"||tk[i].low=="era") {
                std::size_t q=i+1;if(q<s.last&&(tk[q].low=="the"||tk[q].low=="our"||tk[q].low=="a"||tk[q].low=="an"||tk[q].low=="el"||tk[q].low=="la"))++q;
                const std::size_t role_start=q;
                while(q<s.last&&q-role_start<4&&tk[q].t==T::word&&tk[q].low!="of"&&tk[q].low!="at"&&tk[q].low!="for"&&tk[q].low!="de"&&tk[q].low!="en")++q;
                if(q>role_start&&q+1<s.last&&(tk[q].low=="of"||tk[q].low=="at"||tk[q].low=="for"||tk[q].low=="de"||tk[q].low=="en")) {
                    std::size_t at=q+1;while(at+1<s.last&&(tk[at].low=="the"||tk[at].low=="el"||tk[at].low=="la"||project_words.contains(tk[at].low)))++at;
                    const int o=mention_at(mentions,tk[at].b,true);
                    if(o>=0&&mentions[o].type!=EntityType::person) {
                        Fact f;f.type="role";f.predicate="role";f.subject=static_cast<int>(k);f.object_entity=o;f.rule="role_copula";f.confidence=0.7;
                        f.value=ascii_lower(text.substr(tk[role_start].b,tk[q-1].e-tk[role_start].b));push(std::move(f));
                    }
                }
            }
            std::size_t q=i;
            if(q<s.last&&(tk[q].low=="works"||tk[q].low=="worked"||tk[q].low=="joined"||tk[q].low=="trabaja"))++q;
            if(q<s.last&&(tk[q].low=="from"||tk[q].low=="at"||tk[q].low=="for"||tk[q].low=="de"||tk[q].low=="en"||(q>i&&tk[q-1].low=="joined"))) {
                const std::size_t at=tk[q].low=="from"||tk[q].low=="at"||tk[q].low=="for"||tk[q].low=="de"||tk[q].low=="en"?q+1:q;
                if(at<s.last){const int o=mention_at(mentions,tk[at].b,true);
                    if(o>=0&&mentions[o].type==EntityType::organization) {
                        Fact f;f.type="relationship";f.predicate="affiliated_with";f.subject=static_cast<int>(k);f.object_entity=o;f.rule="affiliation";
                        f.confidence=0.65;f.value=strict_key(mentions[o].name);push(std::move(f));
                    }}
            }
        }
    }
}

// ---------------------------------------------------------------- romanisation
struct Letter {char kind;const char* roman;};  // kind: v independent vowel, c consonant, m vowel sign, x virama, n nasal, h visarga, k nukta
const std::unordered_map<std::uint32_t,Letter>& letters() {
    static const std::unordered_map<std::uint32_t,Letter> t=[]{
        std::unordered_map<std::uint32_t,Letter> m;
        auto put=[&](std::uint32_t base,std::initializer_list<std::pair<int,Letter>> items){for(const auto& [off,l]:items)m[base+static_cast<std::uint32_t>(off)]=l;};
        put(0x0900,{{0x01,{'n',"n"}},{0x02,{'n',"n"}},{0x03,{'h',"h"}},{0x04,{'v',"a"}},{0x05,{'v',"a"}},{0x06,{'v',"aa"}},{0x07,{'v',"i"}},{0x08,{'v',"ii"}},
            {0x09,{'v',"u"}},{0x0A,{'v',"uu"}},{0x0B,{'v',"ri"}},{0x0D,{'v',"e"}},{0x0E,{'v',"e"}},{0x0F,{'v',"e"}},{0x10,{'v',"ai"}},{0x11,{'v',"o"}},
            {0x12,{'v',"o"}},{0x13,{'v',"o"}},{0x14,{'v',"au"}},{0x15,{'c',"k"}},{0x16,{'c',"kh"}},{0x17,{'c',"g"}},{0x18,{'c',"gh"}},{0x19,{'c',"n"}},
            {0x1A,{'c',"ch"}},{0x1B,{'c',"chh"}},{0x1C,{'c',"j"}},{0x1D,{'c',"jh"}},{0x1E,{'c',"n"}},{0x1F,{'c',"t"}},{0x20,{'c',"th"}},{0x21,{'c',"d"}},
            {0x22,{'c',"dh"}},{0x23,{'c',"n"}},{0x24,{'c',"t"}},{0x25,{'c',"th"}},{0x26,{'c',"d"}},{0x27,{'c',"dh"}},{0x28,{'c',"n"}},{0x29,{'c',"n"}},
            {0x2A,{'c',"p"}},{0x2B,{'c',"ph"}},{0x2C,{'c',"b"}},{0x2D,{'c',"bh"}},{0x2E,{'c',"m"}},{0x2F,{'c',"y"}},{0x30,{'c',"r"}},{0x31,{'c',"r"}},
            {0x32,{'c',"l"}},{0x33,{'c',"l"}},{0x34,{'c',"l"}},{0x35,{'c',"v"}},{0x36,{'c',"sh"}},{0x37,{'c',"sh"}},{0x38,{'c',"s"}},{0x39,{'c',"h"}},
            {0x3C,{'k',""}},{0x3E,{'m',"aa"}},{0x3F,{'m',"i"}},{0x40,{'m',"ii"}},{0x41,{'m',"u"}},{0x42,{'m',"uu"}},{0x43,{'m',"ri"}},{0x44,{'m',"rii"}},
            {0x45,{'m',"e"}},{0x46,{'m',"e"}},{0x47,{'m',"e"}},{0x48,{'m',"ai"}},{0x49,{'m',"o"}},{0x4A,{'m',"o"}},{0x4B,{'m',"o"}},{0x4C,{'m',"au"}},
            {0x4D,{'x',""}},{0x58,{'c',"q"}},{0x59,{'c',"kh"}},{0x5A,{'c',"g"}},{0x5B,{'c',"z"}},{0x5C,{'c',"r"}},{0x5D,{'c',"rh"}},{0x5E,{'c',"f"}},
            {0x5F,{'c',"y"}}});
        put(0x0B80,{{0x03,{'h',"h"}},{0x05,{'v',"a"}},{0x06,{'v',"aa"}},{0x07,{'v',"i"}},{0x08,{'v',"ii"}},{0x09,{'v',"u"}},{0x0A,{'v',"uu"}},
            {0x0E,{'v',"e"}},{0x0F,{'v',"ee"}},{0x10,{'v',"ai"}},{0x12,{'v',"o"}},{0x13,{'v',"oo"}},{0x14,{'v',"au"}},{0x15,{'c',"k"}},{0x19,{'c',"ng"}},
            {0x1A,{'c',"s"}},{0x1C,{'c',"j"}},{0x1E,{'c',"nj"}},{0x1F,{'c',"t"}},{0x23,{'c',"n"}},{0x24,{'c',"t"}},{0x28,{'c',"n"}},{0x29,{'c',"n"}},
            {0x2A,{'c',"p"}},{0x2E,{'c',"m"}},{0x2F,{'c',"y"}},{0x30,{'c',"r"}},{0x31,{'c',"r"}},{0x32,{'c',"l"}},{0x33,{'c',"l"}},{0x34,{'c',"zh"}},
            {0x35,{'c',"v"}},{0x36,{'c',"sh"}},{0x37,{'c',"sh"}},{0x38,{'c',"s"}},{0x39,{'c',"h"}},{0x3E,{'m',"aa"}},{0x3F,{'m',"i"}},{0x40,{'m',"ii"}},
            {0x41,{'m',"u"}},{0x42,{'m',"uu"}},{0x46,{'m',"e"}},{0x47,{'m',"ee"}},{0x48,{'m',"ai"}},{0x4A,{'m',"o"}},{0x4B,{'m',"oo"}},{0x4C,{'m',"au"}},
            {0x4D,{'x',""}},{0x57,{'m',"au"}}});
        put(0x0C00,{{0x01,{'n',"n"}},{0x02,{'n',"n"}},{0x03,{'h',"h"}},{0x05,{'v',"a"}},{0x06,{'v',"aa"}},{0x07,{'v',"i"}},{0x08,{'v',"ii"}},
            {0x09,{'v',"u"}},{0x0A,{'v',"uu"}},{0x0B,{'v',"ri"}},{0x0E,{'v',"e"}},{0x0F,{'v',"ee"}},{0x10,{'v',"ai"}},{0x12,{'v',"o"}},{0x13,{'v',"oo"}},
            {0x14,{'v',"au"}},{0x15,{'c',"k"}},{0x16,{'c',"kh"}},{0x17,{'c',"g"}},{0x18,{'c',"gh"}},{0x19,{'c',"n"}},{0x1A,{'c',"ch"}},{0x1B,{'c',"chh"}},
            {0x1C,{'c',"j"}},{0x1D,{'c',"jh"}},{0x1E,{'c',"n"}},{0x1F,{'c',"t"}},{0x20,{'c',"th"}},{0x21,{'c',"d"}},{0x22,{'c',"dh"}},{0x23,{'c',"n"}},
            {0x24,{'c',"t"}},{0x25,{'c',"th"}},{0x26,{'c',"d"}},{0x27,{'c',"dh"}},{0x28,{'c',"n"}},{0x2A,{'c',"p"}},{0x2B,{'c',"ph"}},{0x2C,{'c',"b"}},
            {0x2D,{'c',"bh"}},{0x2E,{'c',"m"}},{0x2F,{'c',"y"}},{0x30,{'c',"r"}},{0x31,{'c',"r"}},{0x32,{'c',"l"}},{0x33,{'c',"l"}},{0x35,{'c',"v"}},
            {0x36,{'c',"sh"}},{0x37,{'c',"sh"}},{0x38,{'c',"s"}},{0x39,{'c',"h"}},{0x3E,{'m',"aa"}},{0x3F,{'m',"i"}},{0x40,{'m',"ii"}},{0x41,{'m',"u"}},
            {0x42,{'m',"uu"}},{0x43,{'m',"ri"}},{0x46,{'m',"e"}},{0x47,{'m',"ee"}},{0x48,{'m',"ai"}},{0x4A,{'m',"o"}},{0x4B,{'m',"oo"}},{0x4C,{'m',"au"}},
            {0x4D,{'x',""}}});
        return m;
    }();
    return t;
}
// Brahmic romanisation: consonants carry an inherent "a" unless a vowel sign or virama follows; Hindi drops the
// word-final inherent vowel; Tamil stops are voiced between vowels and after nasals (முருகன் → murugan).
std::string romanize_word(const std::vector<std::uint32_t>& cps,S script) {
    std::string out;bool pending=false;const auto& L=letters();
    std::uint32_t prev_cons=0;bool prev_virama=false,prev_vowel=false;
    for(std::size_t i=0;i<cps.size();++i) {
        const auto it=L.find(cps[i]);
        if(it==L.end()){if(pending){out+='a';pending=false;}continue;}
        const auto& l=it->second;
        switch(l.kind) {
        case 'c': {
            if(pending){out+='a';pending=false;prev_vowel=true;}
            std::string r=l.roman;
            if(script==S::taml) {
                const bool stop=cps[i]==0x0B95||cps[i]==0x0B9F||cps[i]==0x0BA4||cps[i]==0x0BAA;
                const bool nasal_before=prev_virama&&(prev_cons==0x0B99||prev_cons==0x0B9E||prev_cons==0x0BA3||prev_cons==0x0BA8||prev_cons==0x0BAE||prev_cons==0x0BA9);
                const bool geminate=prev_virama&&prev_cons==cps[i];
                if(stop&&!geminate&&(nasal_before||(prev_vowel&&!out.empty())))
                    r=cps[i]==0x0B95?"g":cps[i]==0x0BAA?"b":"d";
            }
            out+=r;pending=true;prev_cons=cps[i];prev_virama=false;prev_vowel=false;break;}
        case 'k':
            if(!out.empty()){if(out.back()=='j')out.back()='z';else if(out.size()>=2&&out.compare(out.size()-2,2,"ph")==0)out.replace(out.size()-2,2,"f");
                else if(out.back()=='d')out.back()='r';else if(out.back()=='k')out.back()='q';}
            break;
        case 'm':out+=l.roman;pending=false;prev_virama=false;prev_vowel=true;break;
        case 'x':pending=false;prev_virama=true;prev_vowel=false;break;
        case 'v':if(pending){out+='a';pending=false;}out+=l.roman;prev_virama=false;prev_vowel=true;prev_cons=0;break;
        default:if(pending){out+='a';pending=false;}out+=l.roman;prev_virama=false;prev_vowel=false;break;
        }
    }
    if(pending&&script!=S::deva)out+='a';
    else if(pending&&script==S::deva&&out.size()<=2)out+='a';
    return out;
}
std::string fold_latin(std::uint32_t cp) {
    static const std::unordered_map<std::uint32_t,const char*> m={{0xE0,"a"},{0xE1,"a"},{0xE2,"a"},{0xE3,"a"},{0xE4,"a"},{0xE5,"a"},{0xE6,"ae"},{0xE7,"c"},
        {0xE8,"e"},{0xE9,"e"},{0xEA,"e"},{0xEB,"e"},{0xEC,"i"},{0xED,"i"},{0xEE,"i"},{0xEF,"i"},{0xF0,"d"},{0xF1,"n"},{0xF2,"o"},{0xF3,"o"},{0xF4,"o"},
        {0xF5,"o"},{0xF6,"o"},{0xF8,"o"},{0xF9,"u"},{0xFA,"u"},{0xFB,"u"},{0xFC,"u"},{0xFD,"y"},{0xFF,"y"},{0xDF,"ss"},{0x101,"a"},{0x103,"a"},{0x105,"a"},
        {0x107,"c"},{0x10D,"c"},{0x111,"d"},{0x113,"e"},{0x117,"e"},{0x119,"e"},{0x11B,"e"},{0x11F,"g"},{0x12B,"i"},{0x131,"i"},{0x142,"l"},{0x144,"n"},
        {0x148,"n"},{0x14D,"o"},{0x151,"o"},{0x153,"oe"},{0x159,"r"},{0x15B,"s"},{0x15F,"s"},{0x161,"s"},{0x163,"t"},{0x165,"t"},{0x16B,"u"},{0x16F,"u"},
        {0x171,"u"},{0x17A,"z"},{0x17C,"z"},{0x17E,"z"}};
    if(cp>=0xC0&&cp<=0xDE&&cp!=0xD7)cp+=0x20;  // Latin-1 capitals
    else if(cp>=0x100&&cp<=0x17F&&cp%2==0)cp+=1;  // Latin Extended-A pairs (approximate)
    auto it=m.find(cp);return it==m.end()?std::string():it->second;
}
const std::unordered_map<std::string,std::string>& seed_keys() {
    static const std::unordered_map<std::string,std::string> m=[]{
        std::unordered_map<std::string,std::string> k;
        for(const auto& seed:seed_places()){std::string c=ascii_lower(seed.canonical);for(const auto& s:seed.spellings)k[s]=c;}
        return k;
    }();
    return m;
}
}  // namespace

const char* type_name(EntityType type) {
    switch(type){case EntityType::person:return "person";case EntityType::organization:return "organization";case EntityType::place:return "place";
                 case EntityType::project:return "project";case EntityType::product:return "product";}
    return "person";
}
std::optional<EntityType> parse_type(const std::string& name) {
    for(const auto t:{EntityType::person,EntityType::organization,EntityType::place,EntityType::project,EntityType::product})if(name==type_name(t))return t;
    return std::nullopt;
}
std::string script_of(const std::string& text) {
    std::set<std::string> seen;
    for(const auto& c:decode(text)) {
        switch(klass(c.cp)){case S::latin:seen.insert("latin");break;case S::han:seen.insert("han");break;case S::deva:seen.insert("deva");break;
            case S::taml:seen.insert("taml");break;case S::telu:seen.insert("telu");break;case S::other_letter:seen.insert("other");break;default:break;}
    }
    if(seen.empty())return "other";if(seen.size()==1)return *seen.begin();
    std::string s="mixed";for(const auto& x:seen)s+=":"+x;return s;
}
std::string strict_key(const std::string& name) {
    if(auto it=seed_keys().find(name);it!=seed_keys().end())return it->second;
    std::string out;std::vector<std::uint32_t> word;S word_script=S::space;
    auto flush=[&]{if(!word.empty()){out+=romanize_word(word,word_script);word.clear();}};
    for(const auto& c:decode(name)) {
        const auto k=klass(c.cp);
        if(indic(k)||(k==S::joiner&&!word.empty())){if(k!=S::joiner){if(!word.empty()&&k!=word_script)flush();word_script=k;word.push_back(c.cp);}continue;}
        flush();
        if(k==S::latin){if(c.cp<128)out+=static_cast<char>(c.cp>='A'&&c.cp<='Z'?c.cp-'A'+'a':c.cp);else{const auto f=fold_latin(c.cp);out+=f.empty()?name.substr(c.b,c.n):f;}}
        else if(k==S::digit)out+=static_cast<char>(c.cp);
        else if(k==S::han||k==S::other_letter)out+=name.substr(c.b,c.n);
        else if(!out.empty()&&out.back()!=' ')out+=' ';
    }
    flush();
    while(!out.empty()&&out.back()==' ')out.pop_back();
    // Legal suffixes do not change which organisation is meant ("Globex Inc" = "Globex").
    for(const auto& s:legal_suffix){const auto tail=" "+s;if(out.size()>tail.size()&&out.compare(out.size()-tail.size(),tail.size(),tail)==0){out.resize(out.size()-tail.size());break;}}
    return out;
}
std::string loose_key(const std::string& name) {
    const auto strict=strict_key(name);std::string s;
    for(std::size_t i=0;i<strict.size();++i) {  // aspirates and digraphs
        const char c=strict[i];const char n=i+1<strict.size()?strict[i+1]:'\0';
        if(static_cast<unsigned char>(c)>=0x80){s+=c;continue;}
        if(c=='c'&&n=='h'){s+='C';++i;if(i+1<strict.size()&&strict[i+1]=='h')++i;continue;}
        if(c=='s'&&n=='h'){s+='s';++i;continue;}
        if(c=='z'&&n=='h'){s+='l';++i;continue;}
        if(n=='h'&&(c=='t'||c=='d'||c=='k'||c=='g'||c=='p'||c=='b'||c=='j')){s+=(c=='p'?'f':c);++i;continue;}
        s+=c;
    }
    std::string t;
    for(std::size_t i=0;i<s.size();++i) {
        char c=s[i];const char n=i+1<s.size()?s[i+1]:'\0';
        if(static_cast<unsigned char>(c)>=0x80){t+=c;continue;}
        if(c=='c')c=(n=='e'||n=='i'||n=='y')?'s':'k';
        else if(c=='C')c='c';
        else if(c=='w')c='v';else if(c=='z')c='j';else if(c=='q')c='k';
        else if(c=='g')c='k';else if(c=='d')c='t';else if(c=='b')c='p';
        if(c=='h'&&(n==' '||n=='\0')&&!t.empty())continue;  // final h
        if(!t.empty()&&t.back()==c&&c!=' ')continue;  // doubled letters and long vowels
        t+=c;
    }
    return t;
}
std::vector<std::pair<std::string,std::string>> query_keys(const std::string& question) {
    const auto tk=tokenize(question);std::vector<std::pair<std::string,std::string>> out;std::set<std::string> seen;
    for(std::size_t i=0;i<tk.size();++i) {
        if(tk[i].t!=T::word)continue;
        for(std::size_t n=1;n<=3&&i+n<=tk.size();++n) {
            if(tk[i+n-1].t!=T::word||tk[i+n-1].sent!=tk[i].sent)break;
            const auto surface=question.substr(tk[i].b,tk[i+n-1].e-tk[i].b);
            if(n==1&&(stop_cap.contains(tk[i].low)||indic_stop.contains(tk[i].s)||tk[i].s.size()<3))continue;
            const auto strict=strict_key(surface);if(strict.size()<3||!seen.insert(strict).second)continue;
            out.emplace_back(strict,loose_key(surface));
            if(out.size()>=96)return out;
        }
    }
    return out;
}

std::vector<Mention> extract_mentions(const std::string& text) {
    const auto tk=tokenize(text);
    Builder b{text,tk,{}};
    seed_place_mentions(text,b);
    person_rules(b);organization_rules(b);place_and_project_rules(b);
    return resolve(std::move(b.out));
}
std::vector<Fact> extract_facts(const std::string& text,std::int64_t event_seconds,const std::string& language,const std::vector<Mention>& mentions) {
    std::vector<Fact> facts;fact_rules(text,tokenize(text),event_seconds,language,mentions,facts);return facts;
}
Extraction extract(const std::string& text,std::int64_t event_seconds,const std::string& language) {
    Extraction x;x.mentions=extract_mentions(text);x.facts=extract_facts(text,event_seconds,language,x.mentions);return x;
}

std::vector<Mention> gazetteer_mentions(const std::string& text,const std::vector<KnownName>& names,const std::vector<Mention>& existing) {
    std::vector<Mention> found;
    for(const auto& n:names) {
        if(n.surface.size()<3)continue;
        for(std::size_t pos=text.find(n.surface);pos!=std::string::npos;pos=text.find(n.surface,pos+n.surface.size())) {
            const auto end=pos+n.surface.size();
            if(!boundary_ok(text,pos,end))continue;
            bool overlap=false;
            for(const auto& m:existing)if(pos<m.end&&m.start<end){overlap=true;break;}
            for(const auto& m:found)if(pos<m.end&&m.start<end){overlap=true;break;}
            if(!overlap)found.push_back({n.type,pos,end,n.surface,n.surface,"gazetteer",0.6});
        }
    }
    std::sort(found.begin(),found.end(),[](const Mention& a,const Mention& b){return a.start<b.start;});
    return found;
}
}
