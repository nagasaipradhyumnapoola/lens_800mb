// lens-voice: consent-gated voice capture (docs/LENS_V1_SPEC.md §6; Milestone 7).
// Captures the default microphone at 16 kHz mono (miniaudio), segments speech with an energy voice-activity detector
// and emits one engine `ingest_audio` request per utterance on stdout (audio as base64 WAV, in memory only), so
// `lens-voice --consent ... | lens-engine --db ...` transcribes and stores voice notes in the encrypted memory.
// Never starts without --consent. Control on stdin: stop (or EOF). Status on stderr carries levels and counts only.
// --input-wav replaces the microphone with a file (diagnostics and tests; still requires --consent).
#define MINIAUDIO_IMPLEMENTATION
#define MA_NO_ENCODING
#define MA_NO_GENERATION
#define MA_NO_RESOURCE_MANAGER
#define MA_NO_NODE_GRAPH
#include "miniaudio.h"
#include <windows.h>
#include <bcrypt.h>
#include <wincrypt.h>
#include <nlohmann/json.hpp>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <deque>
#include <iostream>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace {
using json=nlohmann::json;
constexpr int rate=16000,frame=480;  // 30 ms analysis frames

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

std::mutex lock;std::deque<float> pending;std::mutex out_lock;
void status(const json& j){std::lock_guard g(out_lock);std::cerr<<j.dump()<<'\n';std::cerr.flush();}
void on_capture(ma_device*,void*,const void* input,ma_uint32 frames) {
    const auto* p=static_cast<const float*>(input);std::lock_guard g(lock);pending.insert(pending.end(),p,p+frames);
}
}

int wmain(int argc,wchar_t** argv) {
    bool consent=false;std::wstring input_wav,model,language=L"auto",device=L"windows-local";
    double threshold_db=-45,max_seconds=600;int silence_ms=800,min_speech_ms=300;
    for(int i=1;i<argc;++i) {
        const std::wstring a=argv[i];auto next=[&]{return i+1<argc?std::wstring(argv[++i]):std::wstring();};
        if(a==L"--consent")consent=true;
        else if(a==L"--input-wav")input_wav=next();
        else if(a==L"--model")model=next();
        else if(a==L"--language")language=next();
        else if(a==L"--device-name")device=next();
        else if(a==L"--threshold-db")threshold_db=std::stod(next());
        else if(a==L"--silence-ms")silence_ms=std::stoi(next());
        else if(a==L"--min-speech-ms")min_speech_ms=std::stoi(next());
        else if(a==L"--max-seconds")max_seconds=std::stod(next());
        else {std::cerr<<"usage: lens-voice --consent --model <ggml model> [--language auto|<code>] [--input-wav <file>] [--max-seconds N]\n";return 2;}
    }
    if(!consent){std::cerr<<"{\"event\":\"refused\",\"reason\":\"consent_required\"}\n";return 2;}
    if(model.empty()){std::cerr<<"{\"event\":\"refused\",\"reason\":\"model_required\"}\n";return 2;}

    std::atomic<bool> stopping=false;
    ma_device dev{};bool live=input_wav.empty();bool input_done=false;
    // Live capture stops on "stop" or stdin EOF; a file is always processed to the end unless "stop" arrives.
    std::thread([&,live]{std::string line;bool asked=false;while(std::getline(std::cin,line)){if(line.rfind("stop",0)==0){asked=true;break;}}
                         if(asked||live)stopping=true;}).detach();
    if(live) {
        auto cfg=ma_device_config_init(ma_device_type_capture);
        cfg.capture.format=ma_format_f32;cfg.capture.channels=1;cfg.sampleRate=rate;cfg.dataCallback=on_capture;
        if(ma_device_init(nullptr,&cfg,&dev)!=MA_SUCCESS||ma_device_start(&dev)!=MA_SUCCESS){status({{"event","refused"},{"reason","microphone_unavailable"}});return 3;}
        status({{"event","recording"},{"source","microphone"}});  // the visible "recording" signal for supervisors/UI
    } else {
        ma_decoder decoder{};auto cfg=ma_decoder_config_init(ma_format_f32,1,rate);
        if(ma_decoder_init_file_w(input_wav.c_str(),&cfg,&decoder)!=MA_SUCCESS){status({{"event","refused"},{"reason","audio_decode_failed"}});return 3;}
        std::vector<float> buf(4096);ma_uint64 got=0;
        while(ma_decoder_read_pcm_frames(&decoder,buf.data(),buf.size(),&got)==MA_SUCCESS&&got){std::lock_guard g(lock);pending.insert(pending.end(),buf.begin(),buf.begin()+static_cast<long>(got));}
        ma_decoder_uninit(&decoder);input_done=true;status({{"event","recording"},{"source","file"}});
    }

    const auto started=std::chrono::system_clock::now();
    const double threshold=std::pow(10.0,threshold_db/20.0);
    std::vector<float> segment;std::deque<float> preroll;long long processed=0,segment_start=0;int speech_ms=0,silent_ms=0;bool in_speech=false;
    int segments=0;double peak_db=-120;
    auto emit=[&] {
        if(speech_ms>=min_speech_ms&&!segment.empty()) {
            const auto t=started+std::chrono::milliseconds(segment_start*1000/rate);
            // The same words said at another time are another memory: the id covers audio and start time.
            const auto stamp=iso(t);std::vector<unsigned char> keyed(segment.size()*sizeof(float)+stamp.size());
            std::memcpy(keyed.data(),segment.data(),segment.size()*sizeof(float));std::memcpy(keyed.data()+segment.size()*sizeof(float),stamp.data(),stamp.size());
            const auto digest=sha256_hex(keyed.data(),keyed.size());
            json req={{"op","ingest_audio"},{"consent",true},{"id","voice-"+digest.substr(0,24)},{"audio_base64",wav_base64(segment)},
                {"model",utf8(model)},{"language",utf8(language)},{"timestamp",iso(t)},{"device",utf8(device)},{"kind","voice_note"},
                {"provenance",live?"lens-voice microphone":"lens-voice file"},{"consent_context",{{"mode","voice_explicit_consent"}}},
                {"metadata",{{"capture",live?"microphone":"file"},{"duration_ms",static_cast<long long>(segment.size())*1000/rate},{"speech_ms",speech_ms}}}};
            {std::lock_guard g(out_lock);std::cout<<req.dump()<<'\n';std::cout.flush();}
            ++segments;
        }
        segment.clear();speech_ms=silent_ms=0;in_speech=false;
    };
    std::vector<float> f(frame);
    while(true) {
        bool have=false;
        {std::lock_guard g(lock);if(pending.size()>=frame){std::copy(pending.begin(),pending.begin()+frame,f.begin());pending.erase(pending.begin(),pending.begin()+frame);have=true;}}
        if(!have) {
            if(stopping||input_done||processed>=static_cast<long long>(max_seconds*rate))break;
            std::this_thread::sleep_for(std::chrono::milliseconds(20));continue;
        }
        double sum=0;for(float v:f)sum+=static_cast<double>(v)*v;
        const double rms=std::sqrt(sum/frame);peak_db=std::max(peak_db,20*std::log10(rms+1e-9));
        const bool voiced=rms>=threshold;
        if(voiced&&!in_speech){in_speech=true;segment.assign(preroll.begin(),preroll.end());segment_start=processed-static_cast<long long>(preroll.size());}
        if(in_speech) {
            segment.insert(segment.end(),f.begin(),f.end());
            if(voiced){speech_ms+=30;silent_ms=0;}else silent_ms+=30;
            if(silent_ms>=silence_ms||segment.size()>=static_cast<size_t>(rate*30))emit();  // utterance end, or 30 s cap
        }
        preroll.insert(preroll.end(),f.begin(),f.end());while(preroll.size()>static_cast<size_t>(rate/5))preroll.pop_front();  // 200 ms
        processed+=frame;
        if(stopping&&!in_speech)break;
    }
    if(in_speech)emit();
    if(live){ma_device_uninit(&dev);}
    status({{"event","stopped"},{"segments",segments},{"processed_seconds",static_cast<double>(processed)/rate},{"peak_dbfs",peak_db}});
    return 0;
}
