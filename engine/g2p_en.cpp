#include "g2p_en.hpp"
#include "input.hpp"
#include "onnx_model.hpp"
#include <nlohmann/json.hpp>
#include <algorithm>
#include <array>
#include <cctype>
#include <fstream>
#include <string_view>
namespace lens {
namespace {
std::string lower(std::string s){for(auto& c:s)c=static_cast<char>(std::tolower(static_cast<unsigned char>(c)));return s;}
bool upper_ascii(char c){return c>='A'&&c<='Z';}
bool lower_ascii(char c){return c>='a'&&c<='z';}
bool digit(char c){return c>='0'&&c<='9';}
// One UTF-8 code point starting at s[i] (invalid bytes read as U+FFFD, one byte).
char32_t next_cp(std::string_view s,std::size_t i,std::size_t& len){
    const auto b=static_cast<unsigned char>(s[i]);
    const int n=b<0x80?1:(b>>5)==6?2:(b>>4)==14?3:(b>>3)==30?4:0;
    if(n==0||i+n>s.size()){len=1;return 0xFFFD;}
    char32_t cp=n==1?b:b&(0x7F>>n);
    for(int k=1;k<n;++k){const auto c=static_cast<unsigned char>(s[i+k]);if((c>>6)!=2){len=1;return 0xFFFD;}cp=(cp<<6)|(c&0x3F);}
    len=n;return cp;
}
const std::array<const char*,20> ONES{"zero","one","two","three","four","five","six","seven","eight","nine","ten","eleven","twelve",
                                      "thirteen","fourteen","fifteen","sixteen","seventeen","eighteen","nineteen"};
const std::array<const char*,10> TENS{"","","twenty","thirty","forty","fifty","sixty","seventy","eighty","ninety"};
std::string below_thousand(int n){
    std::string out;
    if(n>=100){out=std::string(ONES[n/100])+" hundred";n%=100;if(n)out+=' ';}
    if(n>=20){out+=TENS[n/10];if(n%10)out+=std::string(" ")+ONES[n%10];}
    else if(n>0||out.empty())out+=ONES[n];
    return out;
}
std::string year(int y){  // 1984 -> nineteen eighty four; 2005 -> two thousand five; 2026 -> twenty twenty six
    if(y>=2000&&y<2010)return spell_number(std::to_string(y));
    const int hi=y/100,lo=y%100;
    return below_thousand(hi)+(lo==0?" hundred":lo<10?std::string(" oh ")+ONES[lo]:" "+below_thousand(lo));
}
std::string ordinal(const std::string& cardinal){
    const auto cut=cardinal.find_last_of(' ');const auto head=cut==std::string::npos?std::string():cardinal.substr(0,cut+1);
    const auto last=cut==std::string::npos?cardinal:cardinal.substr(cut+1);
    static const std::unordered_map<std::string,std::string> irregular{{"one","first"},{"two","second"},{"three","third"},{"five","fifth"},
                                                                       {"eight","eighth"},{"nine","ninth"},{"twelve","twelfth"}};
    if(const auto it=irregular.find(last);it!=irregular.end())return head+it->second;
    if(last.ends_with('y'))return head+last.substr(0,last.size()-1)+"ieth";
    return head+last+"th";
}
std::string s_suffix(const std::string& p){  // plural / possessive / 3rd person -s, by the stem's last sound
    const auto c=p.empty()?std::string():p.substr(p.size()-(static_cast<unsigned char>(p.back())>=0x80?2:1));
    for(const char* v:{"p","t","k","f","θ"})if(c==v)return p+"s";
    for(const char* v:{"s","z","ʃ","ʒ","ʧ","ʤ"})if(c==v)return p+"ᵻz";
    return p+"z";
}
std::string ed_suffix(const std::string& p){
    const auto c=p.empty()?std::string():p.substr(p.size()-(static_cast<unsigned char>(p.back())>=0x80?2:1));
    if(c=="t"||c=="d")return p+"ᵻd";
    for(const char* v:{"p","k","f","θ","ʃ","s","ʧ"})if(c==v)return p+"t";
    return p+"d";
}
}

std::string spell_number(std::string_view digits){
    std::string s(digits);s.erase(0,std::min(s.find_first_not_of('0'),s.size()?s.size()-1:0));
    if(s.size()>15)throw Error("number_too_long");
    long long n=std::stoll(s.empty()?"0":s);if(n==0)return "zero";
    static const std::array<const char*,5> SCALE{""," thousand"," million"," billion"," trillion"};
    std::vector<std::string> parts;
    for(int k=0;n>0;++k,n/=1000)if(n%1000)parts.insert(parts.begin(),below_thousand(static_cast<int>(n%1000))+SCALE[k]);
    std::string out;for(const auto& p:parts)out+=(out.empty()?"":" ")+p;
    return out;
}

EnglishG2P::~EnglishG2P()=default;

// Greedy decoding with the trained Lens G2P: lower-case letters/apostrophes in, Kokoro phonemes out.
std::string EnglishG2P::neural(const std::string& w) const {
    if(!encoder_||w.empty()||w.size()+2>in_len_)return {};
    std::vector<std::int64_t> ids(in_len_,0);size_t n=0;  // fixed shapes, PAD (0) padded: the graphs mask the padding
    for(char c:lower(w)){const auto it=chars_.find(c);if(it==chars_.end())return {};ids[n++]=it->second;}
    std::vector<std::int64_t> shape;const std::vector<std::int64_t> ishape{1,static_cast<std::int64_t>(in_len_)};
    const auto memory=encoder_->run({{"chars",ishape,ids.data(),nullptr,ids.size()}},"memory",shape);
    const auto mshape=shape;std::vector<std::int64_t> out(out_len_,0);out[0]=1;size_t t=1;std::string text;  // 1 = <s>
    while(t<out_len_) {
        const auto logits=decoder_->run({{"memory",mshape,nullptr,memory.data(),memory.size()},{"chars",ishape,ids.data(),nullptr,ids.size()},
                                         {"phonemes",{1,static_cast<std::int64_t>(out_len_)},out.data(),nullptr,out.size()}},"logits",shape);
        const size_t v=static_cast<size_t>(shape.back());const auto row=logits.begin()+static_cast<std::ptrdiff_t>((t-1)*v);
        const auto best=static_cast<std::int64_t>(std::max_element(row,row+static_cast<std::ptrdiff_t>(v))-row);
        if(best==2)break;  // </s>
        if(best>2&&best<static_cast<std::int64_t>(phonemes_.size()))text+=phonemes_[static_cast<size_t>(best)];
        out[t++]=best;
    }
    return text;
}

EnglishG2P::EnglishG2P(const std::filesystem::path& gold,const std::filesystem::path& silver,
                       const std::filesystem::path& runtime,const std::filesystem::path& model_dir){
    if(!model_dir.empty()) {
        std::ifstream f(model_dir/"vocab.json",std::ios::binary);if(!f)throw Error("g2p_model_unavailable");
        const auto v=nlohmann::json::parse(f);const auto chars=v.at("chars").get<std::vector<std::string>>();
        for(size_t i=0;i<chars.size();++i)if(chars[i].size()==1)chars_[chars[i][0]]=static_cast<std::int64_t>(i);
        phonemes_=v.at("phonemes").get<std::vector<std::string>>();
        in_len_=v.at("input_length").get<size_t>();out_len_=v.at("output_length").get<size_t>();
        encoder_=std::make_unique<OnnxModel>(runtime,model_dir/"encoder.onnx",1);decoder_=std::make_unique<OnnxModel>(runtime,model_dir/"decoder.onnx",1);
    }
    for(const auto* path:{&silver,&gold}) {  // gold is loaded last so it wins
        std::ifstream f(*path,std::ios::binary);if(!f)throw Error("lexicon_unavailable");
        const auto j=nlohmann::json::parse(f);
        for(const auto& [k,v]:j.items()) {
            if(v.is_string()){lex_[k]=v.get<std::string>();continue;}
            if(!v.is_object())continue;
            // shortcut: no part-of-speech tagging, heteronyms (read, record, live) use DEFAULT; upgrade with a POS head.
            if(v.contains("DEFAULT")&&v["DEFAULT"].is_string())lex_[k]=v["DEFAULT"].get<std::string>();
            else for(const auto& [_,x]:v.items())if(x.is_string()){lex_[k]=x.get<std::string>();break;}
        }
    }
}

const std::string* EnglishG2P::find(const std::string& w) const {
    if(auto it=lex_.find(w);it!=lex_.end())return &it->second;
    const auto l=lower(w);
    if(auto it=lex_.find(l);it!=lex_.end())return &it->second;
    auto cap=l;if(!cap.empty())cap[0]=static_cast<char>(std::toupper(static_cast<unsigned char>(cap[0])));
    if(auto it=lex_.find(cap);it!=lex_.end())return &it->second;
    return nullptr;
}

// Out-of-lexicon word from known parts; empty when no decomposition is found.
std::string EnglishG2P::compose(const std::string& w) const {
    for(std::size_t i=1;i<w.size();++i)  // CamelCase: GitHub -> Git + Hub
        if(lower_ascii(w[i-1])&&upper_ascii(w[i])) {
            const auto* a=find(w.substr(0,i));const auto b=a?compose(w.substr(i)):std::string();
            if(a&&(find(w.substr(i))||!b.empty()))return *a+(find(w.substr(i))?*find(w.substr(i)):b);
        }
    const auto l=lower(w);
    auto stem=[&](std::size_t cut,const char* add)->const std::string*{return l.size()>cut+1?find(l.substr(0,l.size()-cut)+add):nullptr;};
    if(l.ends_with("'s")||(l.ends_with('s')&&!l.ends_with("ss")))
        if(const auto* p=stem(l.ends_with("'s")?2:1,""))return s_suffix(*p);
    if(l.ends_with("es"))if(const auto* p=stem(2,""))return s_suffix(*p);
    if(l.ends_with("ed")) {
        for(const auto& [cut,add]:std::array<std::pair<std::size_t,const char*>,3>{{{2,""},{1,""},{3,""}}})
            if(const auto* p=stem(cut,add))return ed_suffix(*p);
    }
    if(l.ends_with("ing")) {
        for(const auto& [cut,add]:std::array<std::pair<std::size_t,const char*>,3>{{{3,""},{3,"e"},{4,""}}})
            if(const auto* p=stem(cut,add))return *p+"ɪŋ";
    }
    // Fewest known parts (each >= 3 letters, at most 3 parts) covering the whole word: dp over prefixes.
    const auto n=l.size();std::vector<int> parts(n+1,99),from(n+1,-1);parts[0]=0;
    for(std::size_t i=0;i<n;++i)if(parts[i]<3)for(std::size_t j=i+3;j<=n;++j)
        if(parts[i]+1<parts[j]&&lex_.count(l.substr(i,j-i))){parts[j]=parts[i]+1;from[j]=static_cast<int>(i);}
    if(parts[n]>=2&&parts[n]<=3){std::string out;for(int j=static_cast<int>(n);j>0;j=from[j])out=lex_.at(l.substr(from[j],j-from[j]))+out;return out;}
    return {};
}

std::string EnglishG2P::word(const std::string& w,std::vector<std::string>& unknown) const {
    const bool caps=w.size()>=2&&w.size()<=6&&std::all_of(w.begin(),w.end(),[](char c){return upper_ascii(c);});
    if(!caps)if(const auto* p=find(w))return *p;
    if(!caps)if(auto c=compose(w);!c.empty())return c;
    if(caps)if(const auto* p=find(w);p&&lex_.count(w))return *p;  // acronyms with their own entry (NASA)
    if(!caps)if(auto p=neural(w);!p.empty()){unknown.push_back(w);return p;}
    std::string out;bool spelled=false;  // letter by letter: acronyms (USA) and unknown words
    for(char c:w)if(std::isalpha(static_cast<unsigned char>(c)))if(const auto* p=find(std::string(1,static_cast<char>(std::toupper(static_cast<unsigned char>(c)))))){out+=*p;spelled=true;}
    if(!caps)unknown.push_back(w);
    return spelled?out:std::string();
}

std::string EnglishG2P::phonemize(std::string_view text,std::vector<std::string>& unknown) const {
    std::string out;
    auto words=[&](const std::string& spoken){  // space-separated plain words (number readings, symbol names)
        std::size_t a=0;
        while(a<spoken.size()){auto b=spoken.find(' ',a);if(b==std::string::npos)b=spoken.size();
            const auto p=word(spoken.substr(a,b-a),unknown);if(!p.empty()){if(!out.empty()&&out.back()!=' '&&out.back()!='(')out+=' ';out+=p;}a=b+1;}
    };
    auto punct=[&](const char* p){while(!out.empty()&&out.back()==' ')out.pop_back();if(!out.empty())out+=p;};
    for(std::size_t i=0;i<text.size();) {
        std::size_t len=1;const char32_t cp=next_cp(text,i,len);const char c=text[i];
        if(digit(c)||(c=='$'&&i+1<text.size()&&digit(text[i+1]))) {
            const bool money=c=='$';std::size_t j=money?i+1:i;std::string intpart,frac;bool time=false;std::string minutes;
            while(j<text.size()&&(digit(text[j])||(text[j]==','&&j+1<text.size()&&digit(text[j+1]))))if(text[j++]!=',')intpart+=text[j-1];
            if(j+1<text.size()&&text[j]=='.'&&digit(text[j+1])){++j;while(j<text.size()&&digit(text[j]))frac+=text[j++];}
            else if(!money&&j+2<text.size()&&text[j]==':'&&digit(text[j+1])&&digit(text[j+2])){time=true;minutes=std::string(text.substr(j+1,2));j+=3;}
            std::string spoken;const auto suffix=lower(std::string(text.substr(j,std::min<std::size_t>(2,text.size()-j))));
            if(time){const int m=std::stoi(minutes);spoken=spell_number(intpart)+(m==0?" o'clock":m<10?" oh "+spell_number(minutes):" "+spell_number(minutes));}
            else if(money){spoken=spell_number(intpart)+(intpart=="1"?" dollar":" dollars");
                if(!frac.empty()){frac.resize(2,'0');spoken+=" "+spell_number(frac)+(frac=="01"?" cent":" cents");}}
            else if(frac.empty()&&(suffix=="st"||suffix=="nd"||suffix=="rd"||suffix=="th")){spoken=ordinal(spell_number(intpart));j+=2;}
            else if(frac.empty()&&intpart.size()==4&&text[i]!='0'&&std::stoi(intpart)>=1100&&std::stoi(intpart)<2100&&!(j<text.size()&&text[j]=='%'))spoken=year(std::stoi(intpart));
            else {spoken=spell_number(intpart);if(!frac.empty()){spoken+=" point";for(char d:frac)spoken+=std::string(" ")+ONES[d-'0'];}}
            if(j<text.size()&&text[j]=='%'){spoken+=" percent";++j;}
            words(spoken);i=j;continue;
        }
        if(std::isalpha(static_cast<unsigned char>(c))||(cp>=0xC0&&cp!=0xD7&&cp!=0xF7&&cp<0x2000)) {
            std::string w;std::size_t j=i;
            while(j<text.size()){
                std::size_t l=1;const char32_t q=next_cp(text,j,l);
                const bool letter=std::isalpha(static_cast<unsigned char>(text[j]))||(q>=0xC0&&q!=0xD7&&q!=0xF7&&q<0x2000);
                const bool apostrophe=(q=='\''||q==0x2019)&&!w.empty()&&j+l<text.size()&&std::isalpha(static_cast<unsigned char>(text[j+l]));
                if(!letter&&!apostrophe)break;
                w+=apostrophe?std::string("'"):std::string(text.substr(j,l));j+=l;
            }
            const auto p=word(w,unknown);if(!p.empty()){if(!out.empty()&&out.back()!=' '&&out.back()!='(')out+=' ';out+=p;}
            // "github.com": a dot between letters is read as "dot"
            if(j+1<text.size()&&text[j]=='.'&&std::isalpha(static_cast<unsigned char>(text[j+1]))){words("dot");++j;}
            i=j;continue;
        }
        switch(cp) {
            case '.':case '!':case '?':case ',':case ';':case ':':{const char p[2]{c,0};punct(p);out+=' ';break;}
            case 0x2014:case 0x2013:punct("—");out+=' ';break;
            case 0x2026:punct("…");out+=' ';break;
            case '\n':if(!out.empty()&&std::string(".!?,;:").find(out.back())==std::string::npos&&!out.ends_with("— ")){punct(".");out+=' ';}break;
            case '"':case 0x201C:case 0x201D:case '(':case ')':{
                const std::string q=cp=='('?"(":cp==')'?")":cp==0x201C?"“":cp==0x201D?"”":"\"";
                if(cp=='('||cp==0x201C){if(!out.empty()&&out.back()!=' ')out+=' ';out+=q;}else{while(!out.empty()&&out.back()==' ')out.pop_back();out+=q+" ";}
                break;}
            case '&':words("and");break;case '@':words("at");break;case '+':words("plus");break;case '=':words("equals");break;
            case '%':words("percent");break;case '#':words("number");break;
            default:if(!out.empty()&&out.back()!=' ')out+=' ';  // other symbols and spaces separate words
        }
        i+=len;
    }
    while(!out.empty()&&out.back()==' ')out.pop_back();
    return out;
}
}
