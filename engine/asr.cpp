// Thin adapter over whisper.cpp and its maintained miniaudio decoder.
#include "asr.hpp"
#include "input.hpp"
#include "whisper.h"
#include "common-whisper.h"
#include "ggml_cpu_dispatch.hpp"
#include <wincrypt.h>
#define MA_NO_DEVICE_IO
#define MA_NO_THREADING
#define MA_NO_ENCODING
#define MA_NO_GENERATION
#define MA_NO_RESOURCE_MANAGER
#define MA_NO_NODE_GRAPH
#include "miniaudio.h"
#include <filesystem>
#include <fstream>
#include <iterator>
#include <memory>
#include <stdexcept>
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
}
json transcribe(const json& request) {
    if(!request.value("consent",false))throw Error("consent_required");
    // "audio": path to an audio file, or "audio_base64": encoded audio bytes (live capture; never written to disk).
    std::vector<char> bytes;
    if(request.contains("audio_base64")) {
        const auto text=request.at("audio_base64").get<std::string>();DWORD size=0;
        if(text.size()>90000000||!CryptStringToBinaryA(text.data(),static_cast<DWORD>(text.size()),CRYPT_STRING_BASE64,nullptr,&size,nullptr,nullptr))throw Error("audio_decode_failed");
        bytes.resize(size);
        if(!CryptStringToBinaryA(text.data(),static_cast<DWORD>(text.size()),CRYPT_STRING_BASE64,reinterpret_cast<BYTE*>(bytes.data()),&size,nullptr,nullptr))throw Error("audio_decode_failed");
        bytes.resize(size);
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
    const auto& cpu=ensure_ggml_cpu_backend();
    if(!cpu.ready)throw Error("asr_runtime_unavailable");
    auto cp=whisper_context_default_params();cp.use_gpu=false;
    whisper_log_set(quiet_log,nullptr);
    std::ifstream model(utf8_path(request.at("model").get<std::string>()),std::ios::binary);
    if(!model)throw Error("model_unavailable");
    whisper_model_loader loader{&model,read_model,eof_model,close_model};
    std::unique_ptr<whisper_context,decltype(&whisper_free)> ctx(whisper_init_with_params(&loader,cp),whisper_free);
    if(!ctx)throw Error("model_load_failed");
    const std::string language=validated_string(request.value("language",std::string("auto")),32);
    if(language!="auto" && whisper_lang_id(language.c_str())<0)throw Error("unsupported_language");
    auto params=whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
    params.n_threads=4;params.greedy.best_of=1;params.language=language.c_str();params.no_context=true;
    params.print_progress=params.print_realtime=params.print_timestamps=params.print_special=false;
    if(whisper_full(ctx.get(),params,pcm.data(),static_cast<int>(pcm.size())))throw Error("transcription_failed");
    std::string text;json segments=json::array();double probability=0;int tokens=0;
    for(int i=0;i<whisper_full_n_segments(ctx.get());++i) {
        const std::string part=whisper_full_get_segment_text(ctx.get(),i);text+=part;
        segments.push_back({{"text",part},{"start_ms",whisper_full_get_segment_t0(ctx.get(),i)*10},
                            {"end_ms",whisper_full_get_segment_t1(ctx.get(),i)*10}});
        for(int t=0;t<whisper_full_n_tokens(ctx.get(),i);++t){probability+=whisper_full_get_token_p(ctx.get(),i,t);++tokens;}
    }
    return {{"text",text},{"language",whisper_lang_str(whisper_full_lang_id(ctx.get()))},
            {"segments",segments},{"token_probability",tokens?probability/tokens:0},
            {"duration_s",static_cast<double>(pcm.size())/WHISPER_SAMPLE_RATE},
            {"confidence_is_accuracy",false},{"cpu_backend",cpu.variant}};
}
}
