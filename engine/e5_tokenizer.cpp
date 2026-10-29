#include "e5_tokenizer.hpp"
#include "input.hpp"
#include <nlohmann/json.hpp>
#include <algorithm>
#include <cstring>
#ifdef _WIN32
#include <windows.h>
#include <icu.h>  // the ICU that ships with Windows 10+
#else
#include <utf8proc.h>  // UAX #29 grapheme clusters without ICU's data (Linux, macOS, iOS, Android)
#endif
namespace lens {
namespace {
std::string base64(const std::string& in){
    static const std::string table="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string out;std::uint32_t buffer=0;int bits=0;
    for(char c:in){
        if(c=='=')break;
        const auto v=table.find(c);if(v==std::string::npos)throw Error("tokenizer_invalid");
        buffer=(buffer<<6)|static_cast<std::uint32_t>(v);bits+=6;
        if(bits>=8){bits-=8;out.push_back(static_cast<char>((buffer>>bits)&0xFF));}
    }
    return out;
}
std::size_t utf8_length(unsigned char b){return b<0x80?1:(b>>5)==6?2:(b>>4)==14?3:4;}
// UTF-8 byte offsets of extended grapheme cluster boundaries (Unicode UAX #29): the ICU break iterator that ships with
// Windows, utf8proc elsewhere.
std::vector<std::size_t> grapheme_boundaries(const std::string& text){
    std::vector<std::size_t> bounds{0};if(text.empty())return bounds;
#ifdef _WIN32
    std::u16string units;std::vector<std::size_t> byte_at; // UTF-16 index -> UTF-8 offset
    for(std::size_t i=0;i<text.size();){
        const auto n=std::min(utf8_length(static_cast<unsigned char>(text[i])),text.size()-i);
        std::uint32_t cp=static_cast<unsigned char>(text[i])&(n==1?0x7F:n==2?0x1F:n==3?0x0F:0x07);
        for(std::size_t k=1;k<n;++k)cp=(cp<<6)|(static_cast<unsigned char>(text[i+k])&0x3F);
        if(cp>=0x10000){cp-=0x10000;units.push_back(static_cast<char16_t>(0xD800+(cp>>10)));byte_at.push_back(i);
            units.push_back(static_cast<char16_t>(0xDC00+(cp&0x3FF)));byte_at.push_back(i);}
        else {units.push_back(static_cast<char16_t>(cp));byte_at.push_back(i);}
        i+=n;
    }
    byte_at.push_back(text.size());
    UErrorCode status=U_ZERO_ERROR;
    UBreakIterator* it=ubrk_open(UBRK_CHARACTER,"",reinterpret_cast<const UChar*>(units.data()),static_cast<int32_t>(units.size()),&status);
    if(U_FAILURE(status)||!it)throw Error("grapheme_segmentation_unavailable");
    for(auto k=ubrk_next(it);k!=UBRK_DONE;k=ubrk_next(it))bounds.push_back(byte_at.at(static_cast<std::size_t>(k)));
    ubrk_close(it);
#else
    utf8proc_int32_t state=0,previous=-1;
    for(std::size_t i=0;i<text.size();){
        utf8proc_int32_t cp=0;
        const auto n=utf8proc_iterate(reinterpret_cast<const utf8proc_uint8_t*>(text.data()+i),static_cast<utf8proc_ssize_t>(text.size()-i),&cp);
        const std::size_t step=n>0?static_cast<std::size_t>(n):1;  // invalid bytes: one boundary each, as ICU does
        if(n<=0)cp=0xFFFD;
        if(previous>=0&&utf8proc_grapheme_break_stateful(previous,cp,&state))bounds.push_back(i);
        previous=cp;i+=step;
    }
#endif
    if(bounds.back()!=text.size())bounds.push_back(text.size());
    return bounds;
}
const std::string space_mark="\xE2\x96\x81"; // U+2581
}

E5Tokenizer::E5Tokenizer(const std::filesystem::path& path){
    const auto bytes=read_file(path,64000000);
    const auto j=nlohmann::json::parse(bytes.begin(),bytes.end());
    const auto& model=j.at("model");
    if(model.at("type")!="Unigram")throw Error("tokenizer_unsupported");
    // Supported pipelines (XLM-R family): normalizer Precompiled [+ Replace(" {2,}"," ")];
    // pre-tokenizer Metaspace, optionally preceded by WhitespaceSplit.
    const auto& normalizer=j.at("normalizer");const nlohmann::json* charsmap=nullptr;
    if(normalizer.at("type")=="Precompiled")charsmap=&normalizer;
    else if(normalizer.at("type")=="Sequence"){
        for(const auto& n:normalizer.at("normalizers")){
            if(n.at("type")=="Precompiled"&&!charsmap)charsmap=&n;
            else if(n.at("type")=="Replace"&&n.at("pattern").value("Regex","")==" {2,}"&&n.at("content")==" ")collapse_spaces_=true;
            else throw Error("tokenizer_unsupported");
        }
    }
    if(!charsmap)throw Error("tokenizer_unsupported");
    const auto& pre=j.at("pre_tokenizer");
    if(pre.at("type")=="Sequence"){
        const auto& list=pre.at("pretokenizers");
        if(list.size()!=2||list[0].at("type")!="WhitespaceSplit"||list[1].at("type")!="Metaspace")throw Error("tokenizer_unsupported");
        whitespace_split_=true;
    } else if(pre.at("type")!="Metaspace")throw Error("tokenizer_unsupported");
    const auto blob=base64(charsmap->at("precompiled_charsmap").get<std::string>());
    if(blob.size()<4)throw Error("tokenizer_invalid");
    std::uint32_t size;std::memcpy(&size,blob.data(),4);
    if(size%4||4+static_cast<std::size_t>(size)>blob.size())throw Error("tokenizer_invalid");
    units_.resize(size/4);std::memcpy(units_.data(),blob.data()+4,size);
    normalized_=blob.substr(4+size);
    const auto& vocab=model.at("vocab");float minimum=0;
    pieces_.reserve(vocab.size());
    for(std::size_t i=0;i<vocab.size();++i){
        const auto piece=vocab[i].at(0).get<std::string>();const float score=vocab[i].at(1).get<float>();
        pieces_.emplace(piece,Piece{static_cast<std::int32_t>(i),score});
        max_piece_bytes_=std::max(max_piece_bytes_,piece.size());minimum=std::min(minimum,score);
    }
    unk_score_=minimum-10.0f;unk_id_=model.at("unk_id").get<std::int32_t>();
    bos_id_=pieces_.at("<s>").id;eos_id_=pieces_.at("</s>").id;
}

bool E5Tokenizer::replacement(const std::string& text,std::size_t at,std::size_t n,std::string& out) const {
    // darts-clone commonPrefixSearch over text[at,at+n); like the reference, the first (shortest) key wins.
    std::size_t pos=0;auto unit=units_.at(pos);pos^=(unit>>10)<<((unit&(1u<<9))>>6);
    for(std::size_t i=0;i<n;++i){
        const auto b=static_cast<unsigned char>(text[at+i]);
        pos^=b;if(pos>=units_.size())return false;unit=units_[pos];
        if((unit&((1u<<31)|0xFFu))!=b)return false;
        pos^=(unit>>10)<<((unit&(1u<<9))>>6);if(pos>=units_.size())return false;
        if((unit>>8)&1u){
            const auto value=units_[pos]&((1u<<31)-1);
            if(value>=normalized_.size())throw Error("tokenizer_invalid");
            const auto end=normalized_.find('\0',value);if(end==std::string::npos)throw Error("tokenizer_invalid");
            out.append(normalized_,value,end-value);return true;
        }
    }
    return false;
}

std::string E5Tokenizer::normalize(const std::string& text) const {
    // Charsmap lookups apply per extended grapheme cluster (UAX #29, via the OS ICU): a whole cluster
    // shorter than 6 bytes is looked up first, otherwise each character, as Hugging Face's Precompiled does.
    std::string out;out.reserve(text.size());
    auto emit=[&](const std::string& piece){
        if(collapse_spaces_&&piece==" "&&!out.empty()&&out.back()==' ')return; // Replace(" {2,}"," ")
        out+=piece;
    };
    const auto bounds=grapheme_boundaries(text);
    for(std::size_t g=0;g+1<bounds.size();++g){
        const auto a=bounds[g],b=bounds[g+1];std::string piece;
        if(b-a<6&&replacement(text,a,b-a,piece)){for(char c:piece)emit(std::string(1,c));continue;}
        for(std::size_t i=a;i<b;){
            auto n=std::min(utf8_length(static_cast<unsigned char>(text[i])),b-i);piece.clear();
            if(!replacement(text,i,n,piece))piece.assign(text,i,n);
            for(char c:piece)emit(std::string(1,c));i+=n;
        }
    }
    return out;
}

void E5Tokenizer::viterbi(const std::string& word,std::vector<std::int64_t>& ids) const {
    struct Node {double score;std::size_t from;std::int32_t id;bool set;};
    const auto n=word.size();std::vector<Node> best(n+1,Node{0,0,0,false});best[0].set=true;
    for(std::size_t i=0;i<n;){
        const auto mb=std::min(utf8_length(static_cast<unsigned char>(word[i])),n-i);
        const double here=best[i].score;bool single=false;
        for(std::size_t j=i+1;j<=std::min(n,i+max_piece_bytes_);++j){
            if(j<n&&(static_cast<unsigned char>(word[j])&0xC0)==0x80)continue;
            const auto it=pieces_.find(word.substr(i,j-i));if(it==pieces_.end())continue;
            const double candidate=here+it->second.score;
            if(!best[j].set||candidate>best[j].score)best[j]={candidate,i,it->second.id,true};
            if(j-i==mb)single=true;
        }
        if(!single){
            const double candidate=here+unk_score_;
            if(!best[i+mb].set||candidate>best[i+mb].score)best[i+mb]={candidate,i,unk_id_,true};
        }
        i+=mb;
    }
    std::vector<std::int64_t> path;
    for(auto j=n;j>0;j=best[j].from)path.push_back(best[j].id);
    for(auto it=path.rbegin();it!=path.rend();++it){
        if(*it==unk_id_&&!ids.empty()&&ids.back()==unk_id_)continue; // fused <unk>
        ids.push_back(*it);
    }
}

namespace {
bool unicode_space(const std::string& s,std::size_t i,std::size_t& n){
    const unsigned char b=static_cast<unsigned char>(s[i]);n=utf8_length(b);if(i+n>s.size())n=s.size()-i;
    if(n==1)return b==' '||(b>=0x09&&b<=0x0D);
    std::uint32_t cp=b&(n==2?0x1F:n==3?0x0F:0x07);for(std::size_t k=1;k<n;++k)cp=(cp<<6)|(static_cast<unsigned char>(s[i+k])&0x3F);
    return cp==0x85||cp==0xA0||cp==0x1680||(cp>=0x2000&&cp<=0x200A)||cp==0x2028||cp==0x2029||cp==0x202F||cp==0x205F||cp==0x3000;
}
}

std::vector<std::int64_t> E5Tokenizer::pieces(const std::string& text) const {
    const auto normalized=normalize(text);std::vector<std::int64_t> ids;
    if(normalized.empty())return ids;
    if(whitespace_split_){
        // WhitespaceSplit, then Metaspace prefixes every word.
        std::string word;
        auto flush=[&]{if(!word.empty()){viterbi(space_mark+word,ids);word.clear();}};
        for(std::size_t i=0;i<normalized.size();){std::size_t n;
            if(unicode_space(normalized,i,n))flush();else word.append(normalized,i,n);i+=n;}
        flush();return ids;
    }
    std::string s;s.reserve(normalized.size()+8);
    for(char c:normalized){if(c==' ')s+=space_mark;else s.push_back(c);}
    if(s.rfind(space_mark,0)!=0)s.insert(0,space_mark);
    std::size_t start=0;
    for(std::size_t k=space_mark.size();k<=s.size();++k){
        if(k==s.size()||s.compare(k,space_mark.size(),space_mark)==0){viterbi(s.substr(start,k-start),ids);start=k;}
        if(k<s.size()&&s.compare(k,space_mark.size(),space_mark)==0)k+=space_mark.size()-1;
    }
    return ids;
}

std::vector<std::int64_t> E5Tokenizer::encode(const std::string& text,std::size_t max_tokens) const {
    if(max_tokens<2)throw Error("invalid_token_limit");
    auto content=pieces(text);if(content.size()>max_tokens-2)content.resize(max_tokens-2);
    std::vector<std::int64_t> ids{bos_id_};ids.insert(ids.end(),content.begin(),content.end());ids.push_back(eos_id_);return ids;
}

std::vector<std::int64_t> E5Tokenizer::encode_pair(const std::string& first,const std::string& second,std::size_t max_tokens) const {
    if(max_tokens<5)throw Error("invalid_token_limit");
    auto a=pieces(first),b=pieces(second);
    // "longest_first" truncation: repeatedly drop the last token of the currently longer sequence.
    while(a.size()+b.size()>max_tokens-4){if(a.size()>b.size())a.pop_back();else b.pop_back();}
    std::vector<std::int64_t> ids{bos_id_};ids.insert(ids.end(),a.begin(),a.end());
    ids.push_back(eos_id_);ids.push_back(eos_id_);ids.insert(ids.end(),b.begin(),b.end());ids.push_back(eos_id_);return ids;
}
}
