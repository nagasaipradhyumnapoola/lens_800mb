// lens-voice: consent-gated voice capture (docs/LENS_V1_SPEC.md §6; Milestone 7).
// Captures the default microphone at 16 kHz mono (miniaudio), segments speech with an energy voice-activity detector
// and emits one engine `ingest_audio` request per utterance on stdout (audio as base64 WAV, in memory only), so
// `lens-voice --consent ... | lens-engine --db ...` transcribes and stores voice notes in the encrypted memory.
// Never starts without --consent. Control on stdin: stop (or EOF). Status on stderr carries levels and counts only.
// --input-wav replaces the microphone with a file (diagnostics and tests; still requires --consent). The file is
// decoded incrementally; --pace <factor> feeds it at <factor> x real time like a device (0 = as fast as possible).
// VAD (--vad adaptive, default): an 80 Hz-3 kHz band-pass for analysis only (rumble, mains hum, hiss), a noise floor
// tracked as the 20th percentile of the last 5 s of frame levels, start/continue thresholds 8/4 dB above that floor and
// at least -65 dBFS (hysteresis), a 60 ms onset, 600 ms hangover (500 ms of it kept), 150 ms minimum speech, a soft
// split at the first pause after 12 s and a 20 s cap. Defaults chosen on the dev split only (reports/voice/).
// --vad legacy keeps the original fixed-threshold detector (-45 dBFS) for comparison.
// Owner-only capture: --enroll <profile> turns the owner's speech (>= 10 s) into a speaker embedding (sherpa-onnx,
// NeMo TitaNet-small; both CAM++ exports separated LibriSpeech speakers poorly in this runtime), saved encrypted with
// DPAPI for this Windows user; --speaker-profile <profile> then embeds every segment and
// drops segments whose cosine similarity is below --speaker-threshold before any request is emitted, so other people's
// speech never leaves this process. stderr reports only counts and similarities.
#define MINIAUDIO_IMPLEMENTATION
#define MA_NO_ENCODING
#define MA_NO_GENERATION
#define MA_NO_RESOURCE_MANAGER
#define MA_NO_NODE_GRAPH
#include "miniaudio.h"
#if __has_include("sherpa-onnx/c-api/c-api.h")
#include "sherpa-onnx/c-api/c-api.h"
#define LENS_SPEAKER 1
#endif
#include <windows.h>
#include <bcrypt.h>
#include <wincrypt.h>
#include <nlohmann/json.hpp>
#include "../asr_routes.hpp"
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <deque>
#include <iostream>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <vector>

namespace {
using json=nlohmann::json;
constexpr int rate=16000,frame=480;  // 30 ms analysis frames
constexpr size_t max_pending=static_cast<size_t>(rate)*60;  // a stalled consumer drops the oldest audio past 60 s

std::string utf8(const std::wstring& w) {
    if(w.empty())return {};
    const int n=WideCharToMultiByte(CP_UTF8,0,w.data(),static_cast<int>(w.size()),nullptr,0,nullptr,nullptr);
    std::string s(n,'\0');WideCharToMultiByte(CP_UTF8,0,w.data(),static_cast<int>(w.size()),s.data(),n,nullptr,nullptr);return s;
}
std::string sha256_hex(const void* data,size_t n) {
    BCRYPT_ALG_HANDLE alg=nullptr;BCRYPT_HASH_HANDLE h=nullptr;unsigned char d[32]{};
    BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,nullptr,0);BCryptCreateHash(alg,&h,nullptr,0,nullptr,0,0);
    BCryptHashData(h,static_cast<PUCHAR>(const_cast<void*>(data)),static_cast<ULONG>(n),0);BCryptFinishHash(h,d,32,0);
    BCryptDestroyHash(h);BCryptCloseAlgorithmProvider(alg,0);
    static const char* hex="0123456789abcdef";std::string out;for(unsigned char b:d){out+=hex[b>>4];out+=hex[b&15];}return out;
}
std::string iso(std::chrono::system_clock::time_point t) {
    const auto ms=std::chrono::duration_cast<std::chrono::milliseconds>(t.time_since_epoch()).count();
    const std::time_t s=static_cast<std::time_t>(ms/1000);std::tm u{};gmtime_s(&u,&s);char buf[40];
    std::snprintf(buf,sizeof buf,"%04d-%02d-%02dT%02d:%02d:%02d.%03dZ",u.tm_year+1900,u.tm_mon+1,u.tm_mday,u.tm_hour,u.tm_min,u.tm_sec,static_cast<int>(ms%1000));
    return buf;
}
std::string wav_base64(const std::vector<float>& pcm) {
    std::vector<unsigned char> f(44+pcm.size()*2);
    auto put32=[&](size_t at,uint32_t v){std::memcpy(&f[at],&v,4);};auto put16=[&](size_t at,uint16_t v){std::memcpy(&f[at],&v,2);};
    std::memcpy(&f[0],"RIFF",4);put32(4,static_cast<uint32_t>(f.size()-8));std::memcpy(&f[8],"WAVEfmt ",8);put32(16,16);put16(20,1);put16(22,1);
    put32(24,rate);put32(28,rate*2);put16(32,2);put16(34,16);std::memcpy(&f[36],"data",4);put32(40,static_cast<uint32_t>(pcm.size()*2));
    for(size_t i=0;i<pcm.size();++i){const auto v=static_cast<int16_t>(std::lround(std::clamp(pcm[i],-1.0f,1.0f)*32767.0f));std::memcpy(&f[44+i*2],&v,2);}
    DWORD n=0;CryptBinaryToStringA(f.data(),static_cast<DWORD>(f.size()),CRYPT_STRING_BASE64|CRYPT_STRING_NOCRLF,nullptr,&n);
    std::string out(n,'\0');CryptBinaryToStringA(f.data(),static_cast<DWORD>(f.size()),CRYPT_STRING_BASE64|CRYPT_STRING_NOCRLF,out.data(),&n);
    out.resize(n);return out;
}
// RBJ second-order high/low-pass (Q 0.707), applied to the VAD analysis copy only; ASR receives the unfiltered audio.
struct Biquad {
    double b0=1,b1=0,b2=0,a1=0,a2=0,z1=0,z2=0;
    Biquad(double hz,bool high) {
        if(hz<=0)return;  // pass-through
        const double w=2*3.14159265358979*hz/rate,c=std::cos(w),alpha=std::sin(w)/(2*0.70710678),a0=1+alpha;
        b0=(high?1+c:1-c)/2/a0;b1=(high?-(1+c):1-c)/a0;b2=b0;a1=-2*c/a0;a2=(1-alpha)/a0;
    }
    double step(double x){const double y=b0*x+z1;z1=b1*x-a1*y+z2;z2=b2*x-a2*y;return y;}
};

#ifdef LENS_SPEAKER
// Speaker embeddings through the sherpa-onnx C API, loaded at run time from the pinned runtime (its own onnxruntime).
struct Speaker {
    HMODULE h{};const SherpaOnnxSpeakerEmbeddingExtractor* ex{};int dim=0;
    decltype(&SherpaOnnxCreateSpeakerEmbeddingExtractor) create{};decltype(&SherpaOnnxDestroySpeakerEmbeddingExtractor) destroy{};
    decltype(&SherpaOnnxSpeakerEmbeddingExtractorDim) dims{};decltype(&SherpaOnnxSpeakerEmbeddingExtractorCreateStream) stream{};
    decltype(&SherpaOnnxOnlineStreamAcceptWaveform) accept{};decltype(&SherpaOnnxOnlineStreamInputFinished) finish{};
    decltype(&SherpaOnnxSpeakerEmbeddingExtractorIsReady) ready{};decltype(&SherpaOnnxSpeakerEmbeddingExtractorComputeEmbedding) compute{};
    decltype(&SherpaOnnxSpeakerEmbeddingExtractorDestroyEmbedding) release{};decltype(&SherpaOnnxDestroyOnlineStream) close{};
    template<class T>bool get(T& f,const char* name){f=reinterpret_cast<T>(GetProcAddress(h,name));return f!=nullptr;}
    bool load(const std::filesystem::path& library,const std::filesystem::path& model) {
        // Fully qualified with backslashes, or the loader may pick Windows' own System32 onnxruntime.dll.
        h=LoadLibraryExW(std::filesystem::absolute(library).make_preferred().c_str(),nullptr,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
        if(!h||!get(create,"SherpaOnnxCreateSpeakerEmbeddingExtractor")||!get(destroy,"SherpaOnnxDestroySpeakerEmbeddingExtractor")||
           !get(dims,"SherpaOnnxSpeakerEmbeddingExtractorDim")||!get(stream,"SherpaOnnxSpeakerEmbeddingExtractorCreateStream")||
           !get(accept,"SherpaOnnxOnlineStreamAcceptWaveform")||!get(finish,"SherpaOnnxOnlineStreamInputFinished")||
           !get(ready,"SherpaOnnxSpeakerEmbeddingExtractorIsReady")||!get(compute,"SherpaOnnxSpeakerEmbeddingExtractorComputeEmbedding")||
           !get(release,"SherpaOnnxSpeakerEmbeddingExtractorDestroyEmbedding")||!get(close,"SherpaOnnxDestroyOnlineStream"))return false;
        const std::string m=std::filesystem::absolute(model).make_preferred().string();
        SherpaOnnxSpeakerEmbeddingExtractorConfig cfg{};cfg.model=m.c_str();cfg.num_threads=1;cfg.provider="cpu";
        ex=create(&cfg);if(ex)dim=dims(ex);return ex&&dim>0;
    }
    std::vector<float> embed_window(const float* pcm,size_t n) {
        std::vector<float> out;const auto* st=stream(ex);if(!st)return out;
        accept(st,rate,pcm,static_cast<int32_t>(n));finish(st);
        if(ready(ex,st)){const float* v=compute(ex,st);if(v){out.assign(v,v+dim);release(v);}}
        close(st);normalise(out);return out;
    }
    static void normalise(std::vector<float>& v) {
        double n=0;for(float x:v)n+=static_cast<double>(x)*x;n=std::sqrt(n);
        if(n>0)for(float& x:v)x=static_cast<float>(x/n);else v.clear();
    }
    // Mean of 4 s window embeddings (the last window absorbs a remainder under 2 s): activation memory stays bounded
    // by the window, not by the segment length. L2-normalised; empty when the audio is too short.
    std::vector<float> embed(const std::vector<float>& pcm) {
        constexpr size_t window=rate*4,remainder=rate*2;std::vector<float> sum;
        for(size_t at=0;at<pcm.size();) {
            size_t n=std::min(window,pcm.size()-at);if(pcm.size()-(at+n)<remainder)n=pcm.size()-at;
            auto e=embed_window(pcm.data()+at,n);at+=n;
            if(e.empty())continue;if(sum.empty())sum.assign(e.size(),0.0f);
            for(size_t k=0;k<e.size();++k)sum[k]+=e[k];
        }
        normalise(sum);return sum;
    }
    ~Speaker(){if(ex)destroy(ex);if(h)FreeLibrary(h);}
};
#endif
// Speaker profiles are biometric data: DPAPI-encrypted for the current Windows user, never written in plaintext.
bool save_profile(const std::wstring& path,const json& profile) {
    const auto text=profile.dump();DATA_BLOB in{static_cast<DWORD>(text.size()),reinterpret_cast<BYTE*>(const_cast<char*>(text.data()))},out{};
    if(!CryptProtectData(&in,L"lens-voice speaker profile",nullptr,nullptr,nullptr,CRYPTPROTECT_UI_FORBIDDEN,&out))return false;
    std::ofstream f(std::filesystem::path(path),std::ios::binary);f.write(reinterpret_cast<const char*>(out.pbData),out.cbData);LocalFree(out.pbData);
    return static_cast<bool>(f);
}
json load_profile(const std::wstring& path) {
    std::ifstream f(std::filesystem::path(path),std::ios::binary);if(!f)return nullptr;
    std::string bytes((std::istreambuf_iterator<char>(f)),std::istreambuf_iterator<char>());
    DATA_BLOB in{static_cast<DWORD>(bytes.size()),reinterpret_cast<BYTE*>(bytes.data())},out{};
    if(!CryptUnprotectData(&in,nullptr,nullptr,nullptr,nullptr,CRYPTPROTECT_UI_FORBIDDEN,&out))return nullptr;
    auto j=json::parse(std::string(reinterpret_cast<char*>(out.pbData),out.cbData),nullptr,false);LocalFree(out.pbData);
    return j.is_object()?j:json(nullptr);
}

std::mutex lock;std::deque<float> pending;std::mutex out_lock;long long overrun_samples=0;
void push_audio(const float* p,size_t n) {
    std::lock_guard g(lock);pending.insert(pending.end(),p,p+n);
    if(pending.size()>max_pending){const auto drop=pending.size()-max_pending;pending.erase(pending.begin(),pending.begin()+static_cast<long>(drop));overrun_samples+=static_cast<long long>(drop);}
}
void status(const json& j){std::lock_guard g(out_lock);std::cerr<<j.dump()<<'\n';std::cerr.flush();}
void on_capture(ma_device*,void*,const void* input,ma_uint32 frames){push_audio(static_cast<const float*>(input),frames);}
}

int wmain(int argc,wchar_t** argv) {
    bool consent=false;std::wstring input_wav,model,language=L"auto",device=L"windows-local",vad_mode=L"adaptive";
    std::optional<double> threshold_flag,on_margin_flag,off_margin_flag,hpf_flag,lpf_flag,floor_pct_flag;std::optional<int> silence_flag,min_speech_flag,onset_flag,tail_flag;
    double max_seconds=600,pace=0,min_confidence=0,short_segment_s=2.5,short_min_lid=0.7;std::optional<double> soft_split_flag,max_segment_flag;
    std::wstring languages=L"en,zh,es,ar,fr,pt,ru,id,de,ja,hi,bn,te,mr,ta,ur,gu",sherpa_library;bool routes_enabled=true;  // spec §1a
    // Speaker threshold from LibriSpeech dev speakers: FAR 0.4%, FRR 4.8% (reports/voice/speaker-dev.json).
    std::wstring enroll_path,profile_path,speaker_model;double speaker_threshold=0.46;bool require_owner=false;
    for(int i=1;i<argc;++i) {
        const std::wstring a=argv[i];auto next=[&]{return i+1<argc?std::wstring(argv[++i]):std::wstring();};
        if(a==L"--consent")consent=true;
        else if(a==L"--input-wav")input_wav=next();
        else if(a==L"--model")model=next();
        else if(a==L"--language")language=next();
        else if(a==L"--device-name")device=next();
        else if(a==L"--vad")vad_mode=next();
        else if(a==L"--threshold-db")threshold_flag=std::stod(next());
        else if(a==L"--on-margin-db")on_margin_flag=std::stod(next());
        else if(a==L"--off-margin-db")off_margin_flag=std::stod(next());
        else if(a==L"--silence-ms")silence_flag=std::stoi(next());
        else if(a==L"--min-speech-ms")min_speech_flag=std::stoi(next());
        else if(a==L"--onset-ms")onset_flag=std::stoi(next());
        else if(a==L"--tail-ms")tail_flag=std::stoi(next());
        else if(a==L"--hpf-hz")hpf_flag=std::stod(next());
        else if(a==L"--lpf-hz")lpf_flag=std::stod(next());
        else if(a==L"--floor-percentile")floor_pct_flag=std::stod(next());
        else if(a==L"--max-seconds")max_seconds=std::stod(next());
        else if(a==L"--languages")languages=next();
        else if(a==L"--sherpa-library")sherpa_library=next();
        else if(a==L"--no-routes")routes_enabled=false;
        else if(a==L"--min-confidence")min_confidence=std::stod(next());
        else if(a==L"--short-segment-s")short_segment_s=std::stod(next());
        else if(a==L"--short-min-lid")short_min_lid=std::stod(next());
        else if(a==L"--soft-split-s")soft_split_flag=std::stod(next());
        else if(a==L"--max-segment-s")max_segment_flag=std::stod(next());
        else if(a==L"--pace")pace=std::stod(next());
        else if(a==L"--enroll")enroll_path=next();
        else if(a==L"--speaker-profile")profile_path=next();
        else if(a==L"--speaker-model")speaker_model=next();
        else if(a==L"--speaker-threshold")speaker_threshold=std::stod(next());
        else if(a==L"--require-owner")require_owner=true;
        else {std::cerr<<"usage: lens-voice --consent --model <ggml model> [--language auto|<code>] [--input-wav <file> [--pace <x realtime>]] [--vad adaptive|legacy] [--languages en,zh,...] [--no-routes] [--min-confidence p] [--enroll <profile> | --speaker-profile <profile> [--speaker-threshold t] [--require-owner]] [--max-seconds N]\n";return 2;}
    }
    if(!consent){std::cerr<<"{\"event\":\"refused\",\"reason\":\"consent_required\"}\n";return 2;}
    if(model.empty()){std::cerr<<"{\"event\":\"refused\",\"reason\":\"model_required\"}\n";return 2;}
    if(vad_mode!=L"adaptive"&&vad_mode!=L"legacy"){std::cerr<<"{\"event\":\"refused\",\"reason\":\"unknown_vad\"}\n";return 2;}
    const bool adaptive=vad_mode==L"adaptive";
    // Adaptive defaults were chosen on the dev split of scripts/benchmark_voice.py (reports/voice/); legacy keeps the originals.
    const double threshold_db=threshold_flag.value_or(adaptive?-65:-45),on_margin=on_margin_flag.value_or(8),off_margin=off_margin_flag.value_or(4);
    const int silence_ms=silence_flag.value_or(adaptive?600:800),min_speech_ms=min_speech_flag.value_or(adaptive?150:300);
    const int onset_frames=adaptive?std::max(1,onset_flag.value_or(60)/30):1;
    const long long tail_samples=static_cast<long long>(std::max(0,tail_flag.value_or(500)))*rate/1000;
    const size_t preroll_samples=static_cast<size_t>(adaptive?rate*3/10:rate/5);
    // Shorter segments bound the speech-end-to-memory latency: split at the first pause after 12 s, never exceed 20 s
    // (dev split: 8/15 s cost 2.2 WER points, 20/30 s allowed 18.7 s segments; reports/voice/asr-dev-seg*.log.txt).
    const size_t soft_split_samples=static_cast<size_t>(rate*soft_split_flag.value_or(adaptive?12:1e9));
    const size_t max_segment_samples=static_cast<size_t>(rate*std::min(30.0,max_segment_flag.value_or(adaptive?20:30)));
    // Automatic language identification is restricted to the user's languages; zh and hi go to their stronger
    // upstream models (Dolphin, IndicConformer) when installed beside the whisper model (<root>/models/...).
    json allowed=json::array();
    for(size_t at=0;at<=languages.size();) {
        const auto end=std::min(languages.find(L',',at),languages.size());if(end>at)allowed.push_back(utf8(languages.substr(at,end-at)));at=end+1;
    }
    json routes=json::object();
    if(routes_enabled) {
        namespace fs=std::filesystem;const fs::path models=fs::path(model).parent_path().parent_path();
        const fs::path library=sherpa_library.empty()?models.parent_path()/L".tools/sherpa-runtime/sherpa-onnx-v2.0.0-win-x64-shared-MD-Release-no-tts/lib/sherpa-onnx-c-api.dll":fs::path(sherpa_library);
        routes=lens::asr_routes(models,library);
    }
    const bool enrolling=!enroll_path.empty();json profile=nullptr;std::vector<float> owner;
    if(!profile_path.empty()&&!enrolling) {
        profile=load_profile(profile_path);
        if(!profile.is_object()){status({{"event","refused"},{"reason","speaker_profile_unreadable"}});return 2;}
        owner=profile.at("embedding").get<std::vector<float>>();
    } else if(require_owner&&!enrolling){status({{"event","refused"},{"reason","speaker_profile_required"}});return 2;}
#ifdef LENS_SPEAKER
    std::unique_ptr<Speaker> speaker;
    if(enrolling||!owner.empty()) {
        namespace fs=std::filesystem;const fs::path models=fs::path(model).parent_path().parent_path();
        const fs::path library=sherpa_library.empty()?models.parent_path()/L".tools/sherpa-runtime/sherpa-onnx-v2.0.0-win-x64-shared-MD-Release-no-tts/lib/sherpa-onnx-c-api.dll":fs::path(sherpa_library);
        const fs::path weights=speaker_model.empty()?models/L"k2-fsa--speaker-recognition/nemo_en_titanet_small.onnx":fs::path(speaker_model);
        speaker=std::make_unique<Speaker>();
        if(!speaker->load(library,weights)){status({{"event","refused"},{"reason","speaker_model_unavailable"}});return 3;}
        if(!owner.empty()&&static_cast<int>(owner.size())!=speaker->dim){status({{"event","refused"},{"reason","speaker_profile_model_mismatch"}});return 2;}
    }
#else
    if(enrolling||!owner.empty()){status({{"event","refused"},{"reason","speaker_verification_not_built"}});return 3;}
#endif
    std::vector<std::vector<float>> enrolled;double enrolled_seconds=0;int speaker_rejected=0;

    std::atomic<bool> stopping=false,input_done=false;
    ma_device dev{};ma_decoder decoder{};bool live=input_wav.empty();std::thread feeder;
    // Live capture stops on "stop" or stdin EOF; a file is always processed to the end unless "stop" arrives.
    std::thread([&,live]{std::string line;bool asked=false;while(std::getline(std::cin,line)){if(line.rfind("stop",0)==0){asked=true;break;}}
                         if(asked||live)stopping=true;}).detach();
    if(live) {
        auto cfg=ma_device_config_init(ma_device_type_capture);
        cfg.capture.format=ma_format_f32;cfg.capture.channels=1;cfg.sampleRate=rate;cfg.dataCallback=on_capture;
        cfg.resampling.linear.lpfOrder=MA_MAX_FILTER_ORDER;  // device rates (44.1/48 kHz) are low-passed before 16 kHz
        if(ma_device_init(nullptr,&cfg,&dev)!=MA_SUCCESS||ma_device_start(&dev)!=MA_SUCCESS){status({{"event","refused"},{"reason","microphone_unavailable"}});return 3;}
        status({{"event","recording"},{"source","microphone"}});  // the visible "recording" signal for supervisors/UI
    } else {
        auto cfg=ma_decoder_config_init(ma_format_f32,1,rate);cfg.resampling.linear.lpfOrder=MA_MAX_FILTER_ORDER;
        if(ma_decoder_init_file_w(input_wav.c_str(),&cfg,&decoder)!=MA_SUCCESS){status({{"event","refused"},{"reason","audio_decode_failed"}});return 3;}
        status({{"event","recording"},{"source","file"},{"pace",pace}});
        feeder=std::thread([&] {
            std::vector<float> buf(frame);ma_uint64 fed=0;const auto t0=std::chrono::steady_clock::now();
            while(!stopping) {
                ma_uint64 got=0;const auto r=ma_decoder_read_pcm_frames(&decoder,buf.data(),buf.size(),&got);
                if(!got||(r!=MA_SUCCESS&&r!=MA_AT_END))break;
                if(pace>0)std::this_thread::sleep_until(t0+std::chrono::microseconds(static_cast<long long>(static_cast<double>(fed)*1e6/rate/pace)));
                else while(!stopping){{std::lock_guard g(lock);if(pending.size()<static_cast<size_t>(rate)*10)break;}std::this_thread::sleep_for(std::chrono::milliseconds(2));}
                push_audio(buf.data(),static_cast<size_t>(got));fed+=got;
            }
            input_done=true;
        });
    }

    const auto started=std::chrono::system_clock::now();
    const double threshold=std::pow(10.0,threshold_db/20.0);
    std::vector<float> segment;std::deque<float> preroll;long long processed=0,segment_start=0,last_voiced_end=0;
    int speech_ms=0,silent_ms=0,run=0,segments=0;bool in_speech=false;double peak_db=-120,floor_db=-120;
    Biquad hp(hpf_flag.value_or(80),true),lp(lpf_flag.value_or(3000),false);std::deque<double> history;std::vector<double> scratch;
    const double floor_fraction=std::clamp(floor_pct_flag.value_or(20),0.0,90.0)/100;
    auto emit=[&] {
        if(adaptive&&in_speech) {  // keep --tail-ms after the last voiced frame; the rest of the hangover is silence
            const auto keep=static_cast<size_t>(std::max<long long>(0,last_voiced_end-segment_start+tail_samples));
            if(keep<segment.size())segment.resize(keep);
        }
        json speaker_meta=nullptr;bool keep=speech_ms>=min_speech_ms&&!segment.empty();
#ifdef LENS_SPEAKER
        if(keep&&enrolling) {  // enrolment collects the owner's speech; nothing is emitted
            auto e=speaker->embed(segment);
            if(!e.empty()){enrolled.push_back(std::move(e));enrolled_seconds+=static_cast<double>(segment.size())/rate;}
            keep=false;
        } else if(keep&&!owner.empty()) {
            const auto e=speaker->embed(segment);double sim=-1;
            if(!e.empty()){sim=0;for(size_t k=0;k<e.size();++k)sim+=static_cast<double>(e[k])*owner[k];}
            if(sim<speaker_threshold){++speaker_rejected;status({{"event","speaker_rejected"},{"similarity",std::round(sim*1000)/1000}});keep=false;}
            else speaker_meta={{"verified",true},{"similarity",std::round(sim*1000)/1000},{"threshold",speaker_threshold}};
        }
#endif
        if(keep) {
            const auto t=started+std::chrono::milliseconds(segment_start*1000/rate);
            // The same words said at another time are another memory: the id covers audio and start time.
            const auto stamp=iso(t);std::vector<unsigned char> keyed(segment.size()*sizeof(float)+stamp.size());
            std::memcpy(keyed.data(),segment.data(),segment.size()*sizeof(float));std::memcpy(keyed.data()+segment.size()*sizeof(float),stamp.data(),stamp.size());
            const auto digest=sha256_hex(keyed.data(),keyed.size());
            const auto clipped=std::count_if(segment.begin(),segment.end(),[](float v){return std::fabs(v)>=0.999f;});
            json req={{"op","ingest_audio"},{"consent",true},{"id","voice-"+digest.substr(0,24)},{"audio_base64",wav_base64(segment)},
                {"model",utf8(model)},{"language",utf8(language)},{"asr_routes",routes},{"min_confidence",min_confidence},
                {"short_segment_rule",{{"max_seconds",short_segment_s},{"min_language_probability",short_min_lid}}},{"timestamp",iso(t)},{"device",utf8(device)},{"kind","voice_note"},
                {"provenance",live?"lens-voice microphone":"lens-voice file"},{"consent_context",{{"mode","voice_explicit_consent"}}},
                {"metadata",{{"capture",live?"microphone":"file"},{"duration_ms",static_cast<long long>(segment.size())*1000/rate},{"speech_ms",speech_ms},
                    {"stream_start_ms",segment_start*1000/rate},{"stream_end_ms",(segment_start+static_cast<long long>(segment.size()))*1000/rate},
                    {"speech_end_ms",last_voiced_end*1000/rate},{"clipped_samples",clipped},{"vad",utf8(vad_mode)},
                    {"noise_floor_dbfs",adaptive?std::round(floor_db*10)/10:-120.0},{"speaker",speaker_meta}}}};
            if(language==L"auto")req["allowed_languages"]=allowed;
            {std::lock_guard g(out_lock);std::cout<<req.dump()<<'\n';std::cout.flush();}
            ++segments;
            if(clipped*200>static_cast<long long>(segment.size()))status({{"event","clipping"},{"clipped_fraction",static_cast<double>(clipped)/segment.size()}});
        }
        segment.clear();speech_ms=silent_ms=0;in_speech=false;
    };
    std::vector<float> f(frame);
    while(true) {
        const bool done=input_done;bool have=false;  // read the flag first so the feeder's last chunk is never skipped
        {std::lock_guard g(lock);if(pending.size()>=frame){std::copy(pending.begin(),pending.begin()+frame,f.begin());pending.erase(pending.begin(),pending.begin()+frame);have=true;}}
        if(!have) {
            if(stopping||done)break;
            std::this_thread::sleep_for(std::chrono::milliseconds(10));continue;
        }
        double sum=0;for(float v:f)sum+=static_cast<double>(v)*v;
        const double rms=std::sqrt(sum/frame);peak_db=std::max(peak_db,20*std::log10(rms+1e-9));
        bool voiced;
        if(!adaptive)voiced=rms>=threshold;
        else {
            double hsum=0;for(float v:f){const double y=lp.step(hp.step(v));hsum+=y*y;}
            const double level=10*std::log10(hsum/frame+1e-12);
            history.push_back(level);if(history.size()>167)history.pop_front();  // 5 s
            scratch.assign(history.begin(),history.end());const auto nth=scratch.begin()+static_cast<long>(static_cast<double>(scratch.size())*floor_fraction);
            std::nth_element(scratch.begin(),nth,scratch.end());
            // The floor falls at once to quieter evidence and rises at most 3.3 dB/s, also through long noise bursts.
            floor_db=history.size()==1?level:(*nth<floor_db?*nth:std::min(*nth,floor_db+0.1));
            voiced=level>=std::max(threshold_db,floor_db+(in_speech?off_margin:on_margin))&&history.size()>=10;
        }
        run=voiced?run+1:0;
        if(!in_speech&&run>=onset_frames) {
            in_speech=true;segment.assign(preroll.begin(),preroll.end());segment_start=processed-static_cast<long long>(preroll.size());
            speech_ms=30*(run-1);
        }
        if(in_speech) {
            segment.insert(segment.end(),f.begin(),f.end());
            if(voiced){speech_ms+=30;silent_ms=0;last_voiced_end=processed+frame;}else silent_ms+=30;
            const bool soft_split=adaptive&&!voiced&&segment.size()>=soft_split_samples;  // split long talk at a pause
            if(silent_ms>=silence_ms||soft_split||segment.size()+frame>max_segment_samples)emit();  // utterance end, or before the cap is exceeded
        }
        preroll.insert(preroll.end(),f.begin(),f.end());while(preroll.size()>preroll_samples)preroll.pop_front();
        processed+=frame;
        if((stopping&&!in_speech)||processed>=static_cast<long long>(max_seconds*rate))break;
    }
    if(in_speech)emit();
    stopping=true;if(feeder.joinable())feeder.join();
    if(live)ma_device_uninit(&dev);else ma_decoder_uninit(&decoder);
    long long overrun=0;{std::lock_guard g(lock);overrun=overrun_samples;}
    if(enrolling) {
        if(enrolled_seconds<10||enrolled.empty()){status({{"event","refused"},{"reason","enrollment_too_short"},{"speech_seconds",enrolled_seconds}});return 4;}
        std::vector<float> mean(enrolled[0].size(),0.0f);for(const auto& e:enrolled)for(size_t k=0;k<e.size();++k)mean[k]+=e[k];
        double n=0;for(float x:mean)n+=static_cast<double>(x)*x;n=std::sqrt(n);for(float& x:mean)x=static_cast<float>(x/n);
        const json saved={{"version",1},{"model","nemo_en_titanet_small"},{"dim",mean.size()},{"embedding",mean},
                          {"segments",enrolled.size()},{"speech_seconds",enrolled_seconds},{"created",iso(std::chrono::system_clock::now())}};
        if(!save_profile(enroll_path,saved)){status({{"event","refused"},{"reason","profile_write_failed"}});return 3;}
        status({{"event","enrolled"},{"segments",enrolled.size()},{"speech_seconds",enrolled_seconds}});
    }
    status({{"event","stopped"},{"segments",segments},{"processed_seconds",static_cast<double>(processed)/rate},{"peak_dbfs",peak_db},
            {"overrun_seconds",static_cast<double>(overrun)/rate},{"vad",utf8(vad_mode)},{"speaker_rejected",speaker_rejected},
            {"owner_only",!owner.empty()}});
    return 0;
}
