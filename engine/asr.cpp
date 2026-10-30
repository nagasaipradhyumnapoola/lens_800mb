// Thin adapter over whisper.cpp and its maintained miniaudio decoder.
// Speech requests may restrict automatic language identification to "allowed_languages" (best whisper LID
// probability among them) and route a language to a stronger upstream model ("asr_routes": language -> sherpa-onnx
// Dolphin/IndicConformer). A routed language runs in a lens-sherpa child process after the whisper context is freed,
// so two speech models are never resident together; the audio reaches it over a pipe, never a file.
// Transcripts are rejected rather than stored when they are only annotations ([BLANK_AUDIO], (music)), punctuation,
// a repetition loop, or whisper's mean token probability is below "min_confidence".
#include "asr.hpp"
#include "input.hpp"
#include "whisper.h"
#include "common-whisper.h"
#include "ggml_cpu_dispatch.hpp"
#include "platform.hpp"
#define MA_NO_DEVICE_IO
#define MA_NO_THREADING
#define MA_NO_ENCODING
#define MA_NO_GENERATION
#define MA_NO_RESOURCE_MANAGER
#define MA_NO_NODE_GRAPH
#include "miniaudio.h"
#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <memory>
#include <stdexcept>
#include <thread>
#include <vector>

namespace lens {
using json=nlohmann::json;
namespace {
void quiet_log(ggml_log_level,const char*,void*) {}
size_t read_model(void* context,void* output,size_t size) {
    auto& file=*static_cast<std::ifstream*>(context);
    file.read(static_cast<char*>(output),static_cast<std::streamsize>(size));
    return static_cast<size_t>(file.gcount());
}
bool eof_model(void* context){return static_cast<std::ifstream*>(context)->eof();}
void close_model(void*) {}

std::vector<char32_t> codepoints(const std::string& s) {
    std::vector<char32_t> out;
    for(size_t i=0;i<s.size();) {
        const auto c=static_cast<unsigned char>(s[i]);const int n=c<0x80?1:c<0xE0?2:c<0xF0?3:4;char32_t v=n==1?c:c&(0x7F>>n);
        for(int k=1;k<n&&i+k<s.size();++k)v=(v<<6)|(static_cast<unsigned char>(s[i+k])&0x3F);
        out.push_back(v);i+=static_cast<size_t>(n);
    }
    return out;
}
bool is_mark(char32_t c) {  // spaces and punctuation in the scripts Lens transcribes
    if(c<0x80)return !((c>='0'&&c<='9')||(c>='a'&&c<='z')||(c>='A'&&c<='Z'));
    return (c>=0x2000&&c<=0x206F)||(c>=0x3000&&c<=0x303F)||(c>=0xFF00&&c<=0xFF0F)||(c>=0xFF1A&&c<=0xFF20)||c==0x266A||c==0x266B||c==0x0964||c==0x0965;
}
// Drops whisper's non-speech annotations: [BLANK_AUDIO], [MUSIC], (music), (speaking in foreign language), *laughs*, ♪.
std::string strip_annotations(const std::string& text) {
    std::string out;
    for(size_t i=0;i<text.size();++i) {
        const char open=text[i];const char close=open=='['?']':open=='('?')':open=='*'?'*':0;
        if(close) {
            const auto end=text.find(close,i+1);
            if(end!=std::string::npos&&end-i<=48&&std::all_of(text.begin()+static_cast<long>(i)+1,text.begin()+static_cast<long>(end),
                    [](char c){return static_cast<unsigned char>(c)<0x80;})){i=end;continue;}
        }
        if(text.compare(i,3,"\xE2\x99\xAA")==0||text.compare(i,3,"\xE2\x99\xAB")==0){i+=2;continue;}
        out.push_back(text[i]);
    }
    return out;
}
// Whisper can split a multi-byte character across tokens; invalid UTF-8 is dropped so the JSON response never fails.
std::string valid_utf8(const std::string& s) {
    std::string out;
    for(size_t i=0;i<s.size();) {
        const auto c=static_cast<unsigned char>(s[i]);
        const size_t n=c<0x80?1:(c>>5)==6?2:(c>>4)==14?3:(c>>3)==30?4:0;
        bool ok=n&&i+n<=s.size();
        for(size_t k=1;ok&&k<n;++k)ok=(static_cast<unsigned char>(s[i+k])&0xC0)==0x80;
        if(ok){out.append(s,i,n);i+=n;}else ++i;
    }
    return out;
}
// A unit (word, or character for unspaced scripts) sequence repeated three or more times and covering at least 80% of
// the transcript, four times covering half, or eight times anywhere, is a decoding loop, not speech.
bool repetition_loop(const std::string& text) {
    std::vector<std::u32string> units;std::u32string word;size_t spaces=0;const auto cps=codepoints(text);
    for(char32_t c:cps)if(c==U' ')++spaces;
    const bool words=spaces>=3;
    for(char32_t c:cps) {
        if(is_mark(c)){if(words&&!word.empty()){units.push_back(word);word.clear();}continue;}
        const char32_t lower=c<0x80&&c>='A'&&c<='Z'?c+32:c;
        if(words)word.push_back(lower);else units.push_back(std::u32string(1,lower));
    }
    if(!word.empty())units.push_back(word);
    const size_t n=units.size();
    for(size_t len=1;len<=8&&len*4<=n;++len)
        for(size_t i=0;i+len*2<=n;++i) {
            size_t reps=1;
            while(i+(reps+1)*len<=n&&std::equal(units.begin()+static_cast<long>(i),units.begin()+static_cast<long>(i+len),units.begin()+static_cast<long>(i+reps*len)))++reps;
            if(reps>=8||(reps>=4&&reps*len*2>=n)||(reps>=3&&reps*len*5>=n*4))return true;
        }
    return false;
}

// The routed model in its own process (lens-sherpa), fed the request's audio over stdin.
json transcribe_routed(const json& request,const json& route,const std::string& language,const std::string& audio_base64) {
    json child={{"consent",true},{"audio_base64",audio_base64},{"language",language},
                {"model_type",validated_string(route.at("model_type").get<std::string>(),64)},
                {"model",validated_string(route.at("model").get<std::string>(),32768)},
                {"tokens",validated_string(route.at("tokens").get<std::string>(),32768)},
                {"library",validated_string(route.at("library").get<std::string>(),32768)}};
    if(route.contains("decoder"))child["decoder"]=validated_string(route.at("decoder").get<std::string>(),32768);  // encoder-decoder models (Canary)
    (void)request;int code=1;
    const auto run=platform::run_child(platform::sibling("lens-sherpa"),child.dump()+"\n",code);
    if(!run)throw Error("asr_route_unavailable");
    if(code!=0)throw Error("asr_route_failed");
    const auto& out=*run;
    const auto start=out.find('{');if(start==std::string::npos)throw Error("asr_route_failed");
    auto result=json::parse(out.substr(start),nullptr,false);
    if(!result.is_object()||!result.value("ok",false))throw Error("asr_route_failed");
    return result;
}
}
json transcribe(const json& request) {
    if(!request.value("consent",false))throw Error("consent_required");
    // "audio": path to an audio file, or "audio_base64": encoded audio bytes (live capture; never written to disk).
    std::vector<char> bytes;std::string audio_base64;
    if(request.contains("audio_base64")) {
        audio_base64=request.at("audio_base64").get<std::string>();
        if(audio_base64.size()>90000000)throw Error("audio_decode_failed");
        try{bytes=platform::base64_decode(audio_base64);}catch(const Error&){throw Error("audio_decode_failed");}
    } else bytes=read_file(utf8_path(request.at("audio").get<std::string>()),64000000);
    auto config=ma_decoder_config_init(ma_format_f32,1,WHISPER_SAMPLE_RATE);
    ma_decoder decoder{};
    if(ma_decoder_init_memory(bytes.data(),bytes.size(),&config,&decoder)!=MA_SUCCESS)throw Error("audio_decode_failed");
    ma_uint64 frames{};const auto length_result=ma_decoder_get_length_in_pcm_frames(&decoder,&frames);
    ma_decoder_uninit(&decoder);
    if(length_result!=MA_SUCCESS)throw Error("audio_decode_failed");
    if(frames>static_cast<ma_uint64>(WHISPER_SAMPLE_RATE)*600)throw Error("audio_duration_limit_exceeded");
    std::vector<float> pcm;
    std::vector<std::vector<float>> stereo;
    if(!read_audio_data(bytes.data(),bytes.size(),pcm,stereo,false)||pcm.empty())throw Error("audio_decode_failed");
    const std::string requested=validated_string(request.value("language",std::string("auto")),32);
    std::vector<std::string> allowed;
    if(request.contains("allowed_languages"))for(const auto& l:request.at("allowed_languages")) {
        const auto code=validated_string(l.get<std::string>(),32);if(whisper_lang_id(code.c_str())<0)throw Error("unsupported_language");allowed.push_back(code);
    }
    const json routes=request.value("asr_routes",json::object());
    const double min_confidence=request.value("min_confidence",0.0);
    // Short segments with an uncertain language are mostly noise-triggered hallucinations (dev split: 70% of garbage
    // rejected, 1.2% of real segments; reports/voice/confidence-dev.json).
    const json short_rule=request.value("short_segment_rule",json::object());
    const double short_seconds=short_rule.value("max_seconds",0.0),short_min_lid=short_rule.value("min_language_probability",0.0);
    auto finish=[&](std::string text,json result) {
        text=valid_utf8(strip_annotations(text));const auto cps=codepoints(text);
        if(std::all_of(cps.begin(),cps.end(),is_mark))throw Error("no_speech_found");
        if(repetition_loop(text))throw Error("repetition_rejected");
        result["text"]=text;result["duration_s"]=static_cast<double>(pcm.size())/WHISPER_SAMPLE_RATE;result["confidence_is_accuracy"]=false;
        return result;
    };
    // A routed model that returns nothing or loops ("T H I N T H I N ...", seen on 1 of 100 FLEURS English clips with
    // Canary) is not stored: the segment falls back to whisper, and the response says so.
    auto usable=[](const json& r) {
        const auto t=valid_utf8(strip_annotations(r.value("text",std::string())));const auto cps=codepoints(t);
        return !std::all_of(cps.begin(),cps.end(),is_mark)&&!repetition_loop(t);
    };
    json fallback=nullptr;
    // Explicitly configured routed language: no whisper at all, unless the routed model fails.
    if(requested!="auto"&&routes.contains(requested)) {
        if(audio_base64.empty())throw Error("asr_route_requires_audio_base64");
        auto r=transcribe_routed(request,routes.at(requested),requested,audio_base64);
        if(usable(r))return finish(r.value("text",std::string()),{{"language",requested},{"language_source","configured"},{"provider",r.value("provider","")},
                      {"segments",json::array()},{"token_probability",0.0},{"confidence_status","not_provided_by_model; 0 means unavailable"},{"cpu_backend","onnxruntime"}});
        if(!request.contains("model"))throw Error("repetition_rejected");
        fallback={{"provider",r.value("provider","")},{"reason","degenerate_output"}};
    }
    const auto& cpu=ensure_ggml_cpu_backend();
    if(!cpu.ready)throw Error("asr_runtime_unavailable");
    auto cp=whisper_context_default_params();cp.use_gpu=false;
    whisper_log_set(quiet_log,nullptr);
    std::ifstream model(utf8_path(request.at("model").get<std::string>()),std::ios::binary);
    if(!model)throw Error("model_unavailable");
    whisper_model_loader loader{&model,read_model,eof_model,close_model};
    std::unique_ptr<whisper_context,decltype(&whisper_free)> ctx(whisper_init_with_params(&loader,cp),whisper_free);
    if(!ctx)throw Error("model_load_failed");
    if(requested!="auto" && whisper_lang_id(requested.c_str())<0)throw Error("unsupported_language");
    std::string language=requested,language_source="configured";json lid=nullptr;
    if(requested=="auto"&&!allowed.empty()) {
        // Whisper's language probabilities, restricted to the user's languages (never ko/ml/ca unless enabled).
        if(whisper_pcm_to_mel(ctx.get(),pcm.data(),static_cast<int>(pcm.size()),4))throw Error("transcription_failed");
        std::vector<float> probs(static_cast<size_t>(whisper_lang_max_id()+1),0.0f);
        const int top=whisper_lang_auto_detect(ctx.get(),0,4,probs.data());if(top<0)throw Error("transcription_failed");
        float best=-1;for(const auto& code:allowed){const float p=probs[static_cast<size_t>(whisper_lang_id(code.c_str()))];if(p>best){best=p;language=code;}}
        lid={{"unrestricted",whisper_lang_str(top)},{"unrestricted_probability",probs[static_cast<size_t>(top)]},{"chosen_probability",best}};
        language_source="whisper_lid_restricted";
        if(static_cast<double>(pcm.size())/WHISPER_SAMPLE_RATE<short_seconds&&best<short_min_lid)throw Error("uncertain_short_segment");
    }
    if(language!="auto"&&routes.contains(language)&&!audio_base64.empty()&&fallback.is_null()) {
        ctx.reset();model.close();  // free whisper before the routed model loads: one speech model resident at a time
        auto r=transcribe_routed(request,routes.at(language),language,audio_base64);
        if(usable(r))return finish(r.value("text",std::string()),{{"language",language},{"language_source",language_source},{"language_identification",lid},
                      {"provider",r.value("provider","")},{"segments",json::array()},{"token_probability",0.0},{"confidence_status","not_provided_by_model; 0 means unavailable"},{"cpu_backend","onnxruntime"}});
        fallback={{"provider",r.value("provider","")},{"reason","degenerate_output"}};
        model.clear();model.open(utf8_path(request.at("model").get<std::string>()),std::ios::binary);  // whisper again, after the routed model exited
        if(!model)throw Error("model_unavailable");
        ctx.reset(whisper_init_with_params(&loader,cp));if(!ctx)throw Error("model_load_failed");
    }
    auto params=whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
    params.n_threads=4;params.greedy.best_of=1;params.language=language.c_str();params.no_context=true;
    params.print_progress=params.print_realtime=params.print_timestamps=params.print_special=false;
    if(whisper_full(ctx.get(),params,pcm.data(),static_cast<int>(pcm.size())))throw Error("transcription_failed");
    std::string text;json segments=json::array();double probability=0;int tokens=0;
    for(int i=0;i<whisper_full_n_segments(ctx.get());++i) {
        const std::string part=valid_utf8(whisper_full_get_segment_text(ctx.get(),i));text+=part;
        segments.push_back({{"text",part},{"start_ms",whisper_full_get_segment_t0(ctx.get(),i)*10},
                            {"end_ms",whisper_full_get_segment_t1(ctx.get(),i)*10}});
        for(int t=0;t<whisper_full_n_tokens(ctx.get(),i);++t){probability+=whisper_full_get_token_p(ctx.get(),i,t);++tokens;}
    }
    const double mean_probability=tokens?probability/tokens:0;
    if(mean_probability<min_confidence)throw Error("low_confidence_transcript");
    return finish(text,{{"language",whisper_lang_str(whisper_full_lang_id(ctx.get()))},{"language_source",language_source},
            {"language_identification",lid},{"provider","whisper.cpp"},{"segments",segments},{"token_probability",mean_probability},
            {"cpu_backend",cpu.variant},{"routed_fallback",fallback}});
}
}
