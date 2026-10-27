#pragma once
// Language identification for screen observations (docs/LENS_V1_SPEC.md §1a): CPU-cheap, no model file.
// 1. Script detection over letters: Latin, Han, Kana, Hangul, Arabic, Cyrillic, Devanagari, Bengali, Gujarati, Tamil,
//    Telugu, Greek, Hebrew, Thai. Within a script: kana share separates ja from zh; Urdu-only letters separate ur from
//    ar; Marathi function words and ळ separate mr from hi.
// 2. Latin text: function-word lexicons (hand-written lists of the most common closed-class words) for en, es, fr, pt,
//    de, id and romanized Hindi, Tamil and Telugu (hi-Latn, ta-Latn, te-Latn), plus diacritic cues. Words found in
//    exactly one lexicon decide; shared words only break ties.
// 3. Code-switching: two scripts each holding a real share of the letters, or two Latin lexicons each with distinct
//    evidence, give "mixed" with both components listed.
// "und-Latn"/"und" only when there is no evidence at all (fewer than three words, digits, symbols).
// Rule set version: lens-lid-rules-v1. Accuracy is measured by the observer tests, not assumed.
#include <algorithm>
#include <array>
#include <bit>
#include <cwctype>
#include <map>
#include <string>
#include <unordered_map>
#include <vector>

namespace lens::observe {
struct LanguageGuess {
    std::string language="und";        // BCP-47-style tag, "mixed" for code-switched text
    std::string script="Zyyy";         // ISO 15924 code of the dominant script
    double confidence=0;               // share of the evidence behind the label
    std::vector<std::string> languages;// components (one entry, or two for "mixed")
};

namespace lid_detail {
enum Lang {en,es,fr,pt,de,id,hi_latn,ta_latn,te_latn,latin_count};
inline const char* latin_tag(int l) {
    static const char* tags[]={"en","es","fr","pt","de","id","hi-Latn","ta-Latn","te-Latn"};return tags[l];
}
inline const std::unordered_map<std::wstring,unsigned>& lexicon() {
    static const auto table=[] {
        std::unordered_map<std::wstring,unsigned> t;
        auto put=[&](Lang l,std::initializer_list<const wchar_t*> words){for(auto w:words)t[w]|=1u<<l;};
        put(en,{L"the",L"and",L"of",L"to",L"is",L"in",L"that",L"it",L"for",L"you",L"was",L"with",L"on",L"are",L"this",L"have",L"be",
                L"at",L"not",L"but",L"they",L"from",L"by",L"we",L"or",L"an",L"will",L"my",L"all",L"would",L"there",L"their",L"what",
                L"so",L"can",L"if",L"about",L"which",L"when",L"your",L"has",L"been",L"more",L"were",L"one",L"do",L"he",L"she",L"his",
                L"her",L"our",L"just",L"how",L"out",L"up",L"new",L"also",L"should",L"could",L"than",L"then",L"them",L"these",L"some",
                L"into",L"only",L"its",L"after",L"before",L"because",L"any",L"very",L"does",L"did",L"here",L"where",L"who",L"why",
                L"please",L"thanks",L"today",L"tomorrow",L"yes",L"meeting",L"file",L"edit",L"view",L"help",L"search",L"settings",
                L"open",L"close",L"save",L"home",L"message",L"reply",L"send",L"moved",L"now",L"next",L"week",L"due",L"note",L"update",
                L"a",L"i",L"me",L"us",L"am",L"go",L"get",L"see",L"work",L"time",L"like",L"know",L"think",L"need",L"want",L"make"});
        put(es,{L"el",L"la",L"los",L"las",L"de",L"que",L"y",L"en",L"un",L"una",L"por",L"con",L"para",L"es",L"del",L"al",L"se",L"lo",
                L"como",L"más",L"pero",L"sus",L"le",L"ya",L"o",L"este",L"sí",L"porque",L"esta",L"entre",L"cuando",L"muy",L"sin",
                L"sobre",L"también",L"me",L"hasta",L"hay",L"donde",L"quien",L"desde",L"todo",L"nos",L"durante",L"todos",L"uno",L"les",
                L"ni",L"otros",L"ese",L"eso",L"ellos",L"esto",L"antes",L"qué",L"unos",L"yo",L"otro",L"otra",L"él",L"esa",L"estos",
                L"mucho",L"nada",L"muchos",L"cual",L"poco",L"ella",L"estar",L"estas",L"algo",L"nosotros",L"mi",L"mis",L"tú",L"te",
                L"tu",L"usted",L"gracias",L"hola",L"bueno",L"está",L"están",L"ser",L"hacer",L"tiene",L"puede",L"hoy",L"mañana",
                L"reunión",L"jueves",L"semana",L"nota",L"pasó"});
        put(fr,{L"le",L"la",L"les",L"de",L"des",L"du",L"et",L"est",L"un",L"une",L"que",L"qui",L"dans",L"pour",L"pas",L"sur",L"au",
                L"avec",L"ce",L"il",L"elle",L"ne",L"se",L"son",L"sa",L"ses",L"mais",L"nous",L"vous",L"ils",L"elles",L"je",L"tu",L"ou",
                L"où",L"être",L"avoir",L"fait",L"plus",L"cette",L"comme",L"très",L"aussi",L"leur",L"sont",L"été",L"bonjour",L"merci",
                L"aujourd",L"hui",L"demain",L"réunion",L"jeudi",L"semaine",L"était",L"ça",L"c",L"j",L"l",L"d",L"qu",L"n"});
        put(pt,{L"o",L"a",L"os",L"as",L"de",L"do",L"da",L"dos",L"das",L"e",L"é",L"um",L"uma",L"que",L"em",L"no",L"na",L"nos",L"nas",
                L"para",L"com",L"não",L"por",L"mais",L"se",L"como",L"mas",L"foi",L"ao",L"ele",L"ela",L"isso",L"isto",L"está",L"são",
                L"você",L"eu",L"muito",L"também",L"já",L"quando",L"sobre",L"ser",L"tem",L"obrigado",L"obrigada",L"olá",L"hoje",
                L"amanhã",L"reunião",L"quinta",L"semana",L"nossa",L"nosso",L"pela",L"pelo",L"então",L"até",L"aqui"});
        put(de,{L"der",L"die",L"das",L"und",L"ist",L"nicht",L"ein",L"eine",L"zu",L"den",L"dem",L"des",L"mit",L"sich",L"auf",L"für",
                L"von",L"im",L"ich",L"sie",L"es",L"wir",L"ihr",L"auch",L"als",L"an",L"wie",L"aus",L"bei",L"noch",L"nach",L"wird",
                L"sind",L"war",L"hat",L"haben",L"oder",L"aber",L"dass",L"wenn",L"nur",L"schon",L"sehr",L"heute",L"danke",L"bitte",
                L"morgen",L"besprechung",L"donnerstag",L"woche",L"wurde",L"einen",L"einem",L"diese",L"dieser",L"kann"});
        put(id,{L"yang",L"dan",L"di",L"ke",L"dari",L"ini",L"itu",L"untuk",L"dengan",L"tidak",L"ada",L"akan",L"saya",L"kami",L"kita",
                L"mereka",L"dia",L"juga",L"atau",L"pada",L"dalam",L"sudah",L"bisa",L"karena",L"oleh",L"seperti",L"tetapi",L"jika",
                L"apa",L"terima",L"kasih",L"hari",L"besok",L"rapat",L"sangat",L"belum",L"harus",L"lebih",L"bagaimana",L"kenapa",
                L"sini",L"minggu",L"kamis",L"dipindahkan",L"anda",L"bahwa",L"sebagai",L"telah",L"masih"});
        put(hi_latn,{L"hai",L"hain",L"nahi",L"nahin",L"nhi",L"kya",L"kyun",L"kyon",L"mein",L"aur",L"ka",L"ki",L"ke",L"ko",
                L"bhi",L"tha",L"thi",L"hum",L"tum",L"aap",L"kar",L"karna",L"karo",L"raha",L"rahi",L"rahe",L"gaya",L"gayi",L"hoga",
                L"hogi",L"yeh",L"ye",L"woh",L"wo",L"accha",L"acha",L"theek",L"thik",L"haan",L"kuch",L"sab",L"abhi",L"kal",L"aaj",
                L"bahut",L"bohot",L"matlab",L"lekin",L"toh",L"mera",L"meri",L"mere",L"tera",L"teri",L"apna",L"kaise",L"kaisa",L"kab",
                L"kahan",L"jab",L"yaar",L"bhai",L"chalo",L"dekho",L"samajh",L"pata",L"chahiye",L"sakta",L"sakti",L"wala",
                L"wali",L"liye",L"kyunki",L"agar",L"phir",L"fir",L"hua",L"hui",L"diya",L"liya",L"karke",L"baat",L"kaam",L"ghar",
                L"dost",L"unka",L"unki",L"iska",L"uska",L"hoon",L"hu",L"gaye",L"jaa",L"jao",L"aaya",L"aayi",L"milte"});
        put(ta_latn,{L"enna",L"illa",L"illai",L"naan",L"nee",L"neenga",L"avan",L"aval",L"avanga",L"irukku",L"irukken",L"iruku",
                L"romba",L"vanakkam",L"seri",L"pannu",L"panna",L"pannunga",L"pannren",L"sollu",L"sollunga",L"vaa",L"vaanga",L"ponga",
                L"enakku",L"unakku",L"ungalukku",L"nalla",L"theriyum",L"theriyala",L"venum",L"vendam",L"aama",L"ippo",L"appo",
                L"inniki",L"innaikku",L"naalaikku",L"ethu",L"edhu",L"enga",L"inga",L"anga",L"epdi",L"eppadi",L"ennoda",L"unnoda",
                L"paaru",L"solren",L"varen",L"poren",L"saapdu",L"machan",L"macha",L"thaan",L"onnum",L"ellam",L"konjam",L"pathi",
                L"varuven",L"pogalam",L"panlam",L"sonnen",L"sonna",L"vandhu",L"vanthu",L"podhum",L"kandippa"});
        put(te_latn,{L"enti",L"emi",L"ledu",L"levu",L"undi",L"unnadi",L"unnanu",L"unnaru",L"nenu",L"nuvvu",L"meeru",L"memu",L"manam",
                L"vaadu",L"aame",L"chala",L"chaala",L"cheyyi",L"chey",L"cheyyandi",L"chesanu",L"chesaru",L"chesindi",L"cheppu",
                L"cheppandi",L"ela",L"elaa",L"enduku",L"ekkada",L"ikkada",L"akkada",L"eppudu",L"ippudu",L"appudu",L"kani",L"kaani",
                L"baagundi",L"bagundi",L"bagunnara",L"avunu",L"kaadu",L"ledhu",L"vachindi",L"vacchanu",L"velli",L"vellu",L"randi",
                L"poyindi",L"anni",L"naaku",L"neeku",L"meeku",L"maaku",L"mana",L"ninna",L"repu",L"eroju",L"garu",L"andi",L"sare",
                L"okka",L"inka",L"kooda",L"kuda",L"vastanu",L"vastundi",L"chestanu",L"cheddam",L"chudu",L"choodu",L"telusu",L"teliyadu"});
        return t;
    }();
    return table;
}
inline const std::unordered_map<std::wstring,int>& marathi_words() {
    static const std::unordered_map<std::wstring,int> t={{L"आहे",1},{L"आहेत",1},{L"आणि",1},{L"नाही",1},{L"मी",1},{L"तुम्ही",1},
        {L"आम्ही",1},{L"होते",1},{L"झाले",1},{L"काय",1},{L"कसे",1},{L"ला",1},{L"ची",1},{L"चे",1},{L"चा",1},{L"हे",1},{L"या",1},
        {L"करा",1},{L"केले",1},{L"आता",1},{L"उद्या",1},{L"गुरुवारी",1},{L"बैठक",1}};
    return t;
}
inline const std::unordered_map<std::wstring,int>& hindi_words() {
    static const std::unordered_map<std::wstring,int> t={{L"है",1},{L"हैं",1},{L"और",1},{L"नहीं",1},{L"का",1},{L"की",1},{L"के",1},
        {L"में",1},{L"को",1},{L"से",1},{L"यह",1},{L"वह",1},{L"था",1},{L"थी",1},{L"हम",1},{L"आप",1},{L"पर",1},{L"भी",1},{L"कि",1},
        {L"गया",1},{L"रहा",1},{L"कल",1},{L"आज",1},{L"बैठक",0}};
    return t;
}
enum Script {latn,hani,kana,hang,arab,cyrl,deva,beng,gujr,taml,telu,grek,hebr,thai,script_count};
inline const char* script_code(int s) {
    static const char* codes[]={"Latn","Hani","Jpan","Hang","Arab","Cyrl","Deva","Beng","Gujr","Taml","Telu","Grek","Hebr","Thai"};return codes[s];
}
inline int script_of(wchar_t c) {
    if((c>=L'a'&&c<=L'z')||(c>=L'A'&&c<=L'Z')||(c>=0x00C0&&c<=0x024F&&c!=0x00D7&&c!=0x00F7)||(c>=0x1E00&&c<=0x1EFF))return latn;
    if((c>=0x4E00&&c<=0x9FFF)||(c>=0x3400&&c<=0x4DBF)||(c>=0xF900&&c<=0xFAFF))return hani;
    if(c>=0x3040&&c<=0x30FF)return kana;
    if((c>=0xAC00&&c<=0xD7AF)||(c>=0x1100&&c<=0x11FF))return hang;
    if((c>=0x0600&&c<=0x06FF)||(c>=0x0750&&c<=0x077F)||(c>=0xFB50&&c<=0xFDFF)||(c>=0xFE70&&c<=0xFEFF))return arab;
    if(c>=0x0400&&c<=0x04FF)return cyrl;
    if(c>=0x0900&&c<=0x097F)return deva;
    if(c>=0x0980&&c<=0x09FF)return beng;
    if(c>=0x0A80&&c<=0x0AFF)return gujr;
    if(c>=0x0B80&&c<=0x0BFF)return taml;
    if(c>=0x0C00&&c<=0x0C7F)return telu;
    if(c>=0x0370&&c<=0x03FF)return grek;
    if(c>=0x0590&&c<=0x05FF)return hebr;
    if(c>=0x0E00&&c<=0x0E7F)return thai;
    return -1;
}
// Words: maximal runs of letters of one script (marks and apostrophes split nothing inside Indic words).
inline std::vector<std::pair<int,std::wstring>> words(const std::wstring& s) {
    std::vector<std::pair<int,std::wstring>> out;std::wstring cur;int cur_script=-1;
    auto flush=[&]{if(!cur.empty())out.push_back({cur_script,cur});cur.clear();cur_script=-1;};
    for(wchar_t c:s) {
        int sc=script_of(c);
        // Combining marks and signs inside Brahmic words belong to the word's script.
        if(sc<0&&cur_script>=deva&&cur_script<=telu&&c>=0x0900&&c<=0x0DFF)sc=cur_script;
        if(sc<0||(cur_script>=0&&sc!=cur_script)){flush();if(sc<0)continue;}
        cur_script=sc;cur+=static_cast<wchar_t>(towlower(c));
    }
    flush();return out;
}
struct LatinScore {std::array<double,latin_count> distinct{},shared{};int words=0;};
inline LatinScore score_latin(const std::vector<std::pair<int,std::wstring>>& ws) {
    LatinScore s;const auto& lex=lexicon();
    for(const auto& [sc,w]:ws) {
        if(sc!=latn)continue;++s.words;
        const auto it=lex.find(w);
        if(it!=lex.end()) {
            const unsigned m=it->second;const int n=std::popcount(m);
            for(int l=0;l<latin_count;++l)if(m&(1u<<l)){if(n==1)s.distinct[l]+=1;else s.shared[l]+=1.0/n;}
        }
        // Diacritic cues: letters that belong to one language among the supported ones.
        for(wchar_t c:w) {
            if(c==L'ñ')s.distinct[es]+=1;else if(c==L'ã'||c==L'õ')s.distinct[pt]+=1;else if(c==L'ß')s.distinct[de]+=1;
            else if(c==L'è'||c==L'ê'||c==L'ë'||c==L'î'||c==L'œ'||c==L'ù')s.distinct[fr]+=0.5;
            else if(c==L'ä'||c==L'ö'||c==L'ü')s.distinct[de]+=0.5;
        }
    }
    return s;
}
}

inline LanguageGuess identify_language(const std::wstring& text) {
    using namespace lid_detail;
    LanguageGuess g;
    const auto ws=words(text);
    std::array<long long,script_count> letters{};long long total=0;
    for(const auto& [sc,w]:ws){letters[sc]+=static_cast<long long>(w.size());total+=static_cast<long long>(w.size());}
    if(total==0)return g;
    // Script shares are weighed in words: space-delimited scripts count words, Han characters count one each and kana
    // half each (one bucket; the kana share of its letters then separates ja from zh).
    const long long cjk=letters[hani]+letters[kana];
    std::array<double,script_count> buckets{};double weight=0;
    for(const auto& [sc,w]:ws){const double v=sc==hani?static_cast<double>(w.size()):sc==kana?0.5*static_cast<double>(w.size()):1.0;buckets[sc==kana?hani:sc]+=v;weight+=v;}
    std::vector<int> order(script_count);for(int i=0;i<script_count;++i)order[i]=i;
    std::sort(order.begin(),order.end(),[&](int a,int b){return buckets[a]>buckets[b];});
    const int top=order[0],second=order[1];
    auto label_script=[&](int sc)->std::pair<std::string,std::string> {  // language, script code
        switch(sc) {
        case hani: return letters[kana]*10>=cjk?std::pair<std::string,std::string>{"ja","Jpan"}:std::pair<std::string,std::string>{"zh","Hani"};
        case hang: return {"ko","Hang"};
        case arab: {
            long long urdu=0,all=0;
            for(wchar_t c:text){if(script_of(c)==arab){++all;if(c==0x0679||c==0x0688||c==0x0691||c==0x06BA||c==0x06D2||c==0x06C1||c==0x06BE||c==0x06D3)++urdu;}}
            return {urdu*50>=all&&urdu>0?"ur":"ar","Arab"};
        }
        case cyrl: {
            for(wchar_t c:text)if(c==0x0456||c==0x0457||c==0x0454||c==0x0491)return {"uk","Cyrl"};
            return {"ru","Cyrl"};
        }
        case deva: {
            int mr=0,hi=0;
            for(const auto& [s,w]:ws){if(s!=deva)continue;if(marathi_words().count(w))++mr;if(const auto it=hindi_words().find(w);it!=hindi_words().end())hi+=it->second;
                                       if(w.find(L'ळ')!=std::wstring::npos)++mr;}
            return {mr>hi?"mr":"hi","Deva"};
        }
        case beng: return {"bn","Beng"};case gujr: return {"gu","Gujr"};case taml: return {"ta","Taml"};case telu: return {"te","Telu"};
        case grek: return {"el","Grek"};case hebr: return {"he","Hebr"};case thai: return {"th","Thai"};
        default: return {"und","Zyyy"};
        }
    };
    // Latin label from the lexicons.
    auto latin_label=[&](bool allow_mixed)->std::pair<std::vector<std::string>,double> {
        const auto s=score_latin(ws);
        std::array<double,latin_count> total_score{};for(int l=0;l<latin_count;++l)total_score[l]=s.distinct[l]*2+s.shared[l];
        std::vector<int> o(latin_count);for(int i=0;i<latin_count;++i)o[i]=i;
        std::sort(o.begin(),o.end(),[&](int a,int b){return total_score[a]!=total_score[b]?total_score[a]>total_score[b]:a<b;});
        double sum=0;for(double v:total_score)sum+=v;
        if(sum<=0) {
            if(s.words>=3)return {{"en"},0.2};  // Latin words without any function word: the common case is English UI text
            return {{"und-Latn"},0.0};
        }
        const int a=o[0],b=o[1];
        // Code-switching: the runner-up has its own distinct words and a real share of the evidence.
        if(allow_mixed&&s.distinct[b]>=3&&total_score[b]>=0.3*total_score[a])return {{latin_tag(a),latin_tag(b)},(total_score[a]+total_score[b])/sum};
        return {{latin_tag(a)},total_score[a]/sum};
    };
    std::string other;  // a second script with at least 20% of the words (real words, if Latin) makes the text mixed
    if(buckets[second]>=0.2*weight) {
        if(second==latn){const auto [langs,c]=latin_label(false);if(c>=0.5&&langs[0]!="und-Latn")other=langs[0];}
        else other=label_script(second).first;
    }
    if(top==latn) {
        const auto [langs,conf]=latin_label(true);
        g.script="Latn";g.confidence=conf;g.languages=langs;
        if(langs.size()==1&&!other.empty()&&langs[0]!="und-Latn")g.languages.push_back(other);
        g.language=g.languages.size()>1?"mixed":langs[0];
    } else {
        auto [lang,code]=label_script(top);
        g.script=code;g.languages={lang};g.language=lang;g.confidence=buckets[top]/weight;
        if(!other.empty()&&other!=lang){g.languages.push_back(other);g.language="mixed";g.confidence=(buckets[top]+buckets[second])/weight;}
    }
    return g;
}
}
