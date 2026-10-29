// Spoken replies: English text -> misaki-lexicon phonemes (engine/g2p_en.cpp) -> Kokoro-82M (Apache-2.0, unmodified ONNX
// INT8) through the hash-verified ONNX Runtime -> 24 kHz 16-bit mono WAV. One JSON request on stdin:
// {"text","voice":path to a voices/*.bin style table,"speed":1.0,"runtime","model","tokenizer","lexicon":[gold,silver],
//  "threads":2,"output":optional WAV path} -> {"ok","sample_rate","duration_s","audio_base64" (no "output"),"phonemes",
//  "unknown_words","timing_ms"}. The model is loaded per request and released on exit (spec §15: never resident).
#include "g2p_en.hpp"
#include "input.hpp"
#include "onnx_model.hpp"
#include "platform.hpp"
#include <nlohmann/json.hpp>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <fstream>
#include <iostream>
using json=nlohmann::json;
namespace {
constexpr int RATE=24000;
constexpr std::size_t MAX_TOKENS=500;  // Kokoro's context is 512 including the two pad tokens
constexpr std::size_t PACK_TOKENS=200;  // sentences are packed up to this; activation memory grows with chunk length
std::vector<std::string> code_points(const std::string& s){
    std::vector<std::string> out;
    for(std::size_t i=0;i<s.size();){const auto b=static_cast<unsigned char>(s[i]);const std::size_t n=b<0x80?1:(b>>5)==6?2:(b>>4)==14?3:4;
        out.push_back(s.substr(i,n));i+=n;}
    return out;
}
// Sentences packed into chunks of at most MAX_TOKENS phonemes; an over-long sentence is cut at commas, then spaces.
std::vector<std::vector<std::string>> chunks(const std::string& phonemes){
    const auto cps=code_points(phonemes);std::vector<std::vector<std::string>> out;std::vector<std::string> cur;std::size_t cut=0,soft=0;
    for(std::size_t i=0;i<cps.size();++i){
        cur.push_back(cps[i]);const auto& c=cps[i];
        if(c=="."||c=="!"||c=="?"||c==";"||c=="…")cut=cur.size();else if(c==",")soft=cur.size();
        if(cur.size()>=MAX_TOKENS||(cut&&cur.size()>=PACK_TOKENS)){
            std::size_t at=cut?cut:soft;if(!at)for(std::size_t k=cur.size();k-->1;)if(cur[k]==" "){at=k;break;}
            if(!at)at=cur.size();
            out.emplace_back(cur.begin(),cur.begin()+static_cast<std::ptrdiff_t>(at));cur.erase(cur.begin(),cur.begin()+static_cast<std::ptrdiff_t>(at));
            cut=soft=0;
        }
    }
    if(!cur.empty())out.push_back(cur);
    for(auto& c:out){while(!c.empty()&&c.front()==" ")c.erase(c.begin());while(!c.empty()&&c.back()==" ")c.pop_back();}
    std::erase_if(out,[](const auto& c){return c.empty();});
    return out;
}
std::string wav(const std::vector<float>& pcm){
    std::string out(44,'\0');auto put=[&](std::size_t at,std::uint32_t v,int n){for(int k=0;k<n;++k)out[at+k]=static_cast<char>((v>>(8*k))&0xFF);};
    const auto bytes=static_cast<std::uint32_t>(pcm.size()*2);
    out.replace(0,4,"RIFF");put(4,36+bytes,4);out.replace(8,8,"WAVEfmt ");put(16,16,4);put(20,1,2);put(22,1,2);put(24,RATE,4);put(28,RATE*2,4);
    put(32,2,2);put(34,16,2);out.replace(36,4,"data");put(40,bytes,4);
    for(float s:pcm){const auto v=static_cast<std::int16_t>(std::lround(std::clamp(s,-1.0f,1.0f)*32767.0f));out.push_back(static_cast<char>(v&0xFF));out.push_back(static_cast<char>((v>>8)&0xFF));}
    return out;
}
double ms(std::chrono::steady_clock::time_point t){return std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-t).count();}
// Loaded once per worker and reused across requests; the worker's owner ends it when idle (spec §15).
struct Cache {
    std::string lexicon_key,model_key,tokenizer_key;std::unique_ptr<lens::EnglishG2P> g2p;std::unique_ptr<lens::OnnxModel> model;
    std::unordered_map<std::string,std::int64_t> vocab;std::unordered_map<std::string,std::vector<float>> voices;
};
json speak(const json& req,Cache& c){
    const auto t0=std::chrono::steady_clock::now();
    const auto text=lens::validated_string(req.at("text").get<std::string>(),5000);
    if(text.find_first_not_of(" \t\r\n")==std::string::npos)throw lens::Error("empty_text");
    const float speed=std::clamp(req.value("speed",1.0f),0.5f,2.0f);
    auto str=[&](const json& v){return lens::validated_string(v.get<std::string>(),32768);};
    const auto& lex=req.at("lexicon");if(!lex.is_array()||lex.size()!=2)throw lens::Error("invalid_request");
    const auto g2p_model=req.contains("g2p_model")?str(req.at("g2p_model")):std::string();  // trained fallback for unknown words
    if(const auto key=str(lex.at(0))+"|"+str(lex.at(1))+"|"+g2p_model;key!=c.lexicon_key) {
        c.g2p=std::make_unique<lens::EnglishG2P>(lens::utf8_path(str(lex.at(0))),lens::utf8_path(str(lex.at(1))),
                                                 g2p_model.empty()?std::filesystem::path():lens::utf8_path(str(req.at("runtime"))),
                                                 g2p_model.empty()?std::filesystem::path():lens::utf8_path(g2p_model));
        c.lexicon_key=key;
    }
    if(const auto key=str(req.at("tokenizer"));key!=c.tokenizer_key) {
        std::ifstream f(lens::utf8_path(key),std::ios::binary);if(!f)throw lens::Error("model_unavailable");
        const auto tok=json::parse(f);  // named: a range-for over a member of a temporary would dangle
        c.vocab.clear();for(const auto& [k,v]:tok.at("model").at("vocab").items())c.vocab[k]=v.get<std::int64_t>();c.tokenizer_key=key;
    }
    const auto voice_key=str(req.at("voice"));auto& style=c.voices[voice_key];
    if(style.empty()) {
        std::ifstream f(lens::utf8_path(voice_key),std::ios::binary|std::ios::ate);if(!f){c.voices.erase(voice_key);throw lens::Error("voice_unavailable");}
        const auto n=static_cast<std::size_t>(f.tellg());
        if(n%(256*sizeof(float))||n<256*sizeof(float)*MAX_TOKENS){c.voices.erase(voice_key);throw lens::Error("voice_invalid");}
        style.resize(n/sizeof(float));f.seekg(0);f.read(reinterpret_cast<char*>(style.data()),static_cast<std::streamsize>(n));
    }
    std::vector<std::string> unknown;const auto phonemes=c.g2p->phonemize(text,unknown);
    const auto parts=chunks(phonemes);if(parts.empty())throw lens::Error("nothing_to_speak");
    const double prep_ms=ms(t0);const auto t1=std::chrono::steady_clock::now();
    if(const auto key=str(req.at("runtime"))+"|"+str(req.at("model"));key!=c.model_key) {
        c.model.reset();c.model=std::make_unique<lens::OnnxModel>(lens::utf8_path(str(req.at("runtime"))),lens::utf8_path(str(req.at("model"))),
                                                                 std::clamp(req.value("threads",2),1,8),true);
        c.model_key=key;
    }
    const double load_ms=ms(t1);const auto t2=std::chrono::steady_clock::now();
    std::vector<float> pcm;json said=json::array();std::size_t tokens=0;
    for(const auto& part:parts){
        std::vector<std::int64_t> ids{0};std::string text_part;
        for(const auto& p:part){if(const auto it=c.vocab.find(p);it!=c.vocab.end())ids.push_back(it->second);text_part+=p;}
        ids.push_back(0);said.push_back(text_part);tokens+=ids.size()-2;
        const std::size_t row=std::min(ids.size()-2,style.size()/256-1);  // the style vector is chosen by phoneme count
        std::vector<std::int64_t> shape;
        auto audio=c.model->run({{"input_ids",{1,static_cast<std::int64_t>(ids.size())},ids.data(),nullptr,ids.size()},
                                 {"style",{1,256},nullptr,style.data()+row*256,256},{"speed",{1},nullptr,&speed,1}},"waveform",shape);
        pcm.insert(pcm.end(),audio.begin(),audio.end());
    }
    const double synth_ms=ms(t2);const auto audio=wav(pcm);
    json out={{"ok",true},{"sample_rate",RATE},{"duration_s",static_cast<double>(pcm.size())/RATE},{"phonemes",said},{"tokens",tokens},{"unknown_words",unknown},
              {"timing_ms",{{"phonemize",prep_ms},{"model_load",load_ms},{"synthesize",synth_ms}}},
              {"real_time_factor",synth_ms/1000.0/std::max(1e-9,static_cast<double>(pcm.size())/RATE)}};
    if(req.contains("output")){std::ofstream f(lens::utf8_path(str(req.at("output"))),std::ios::binary);if(!f.write(audio.data(),static_cast<std::streamsize>(audio.size())))throw lens::Error("write_failed");}
    else out["audio_base64"]=lens::platform::base64_encode(audio);
    return out;
}
}
int main(){
    Cache cache;std::string line;bool failed=false;
    while(true){
        const auto status=lens::read_line(std::cin,line,1024*1024);
        if(status==lens::Line::end)break;
        json out;
        try{if(status!=lens::Line::ready)throw lens::Error("invalid_request");out=speak(json::parse(line),cache);}
        catch(const lens::Error& e){out={{"ok",false},{"error",e.what()}};failed=true;}
        catch(const std::exception&){out={{"ok",false},{"error","invalid_request"}};failed=true;}
        std::cout<<out.dump()<<'\n';std::cout.flush();
        if(status==lens::Line::too_large)break;
    }
    return failed?1:0;
}
