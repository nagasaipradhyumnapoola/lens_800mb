// Thin UTF-8/PCM adapter around the upstream sherpa-onnx C API; no ASR implementation here.
#include "input.hpp"
#include "sherpa-onnx/c-api/c-api.h"
#define MA_NO_DEVICE_IO
#define MA_NO_THREADING
#define MA_NO_ENCODING
#define MA_NO_GENERATION
#define MA_NO_RESOURCE_MANAGER
#define MA_NO_NODE_GRAPH
#include "miniaudio.h"
#include <windows.h>
#include <wincrypt.h>
#include <nlohmann/json.hpp>
#include <iostream>
#include <memory>
using json=nlohmann::json;
struct Module {HMODULE h{};~Module(){if(h)FreeLibrary(h);}};
struct Audio {ma_decoder d{};bool loaded=false;~Audio(){if(loaded)ma_decoder_uninit(&d);}};
template<class T>T api(HMODULE h,const char* name){auto p=reinterpret_cast<T>(GetProcAddress(h,name));if(!p)throw lens::Error("asr_api_unavailable");return p;}
int main(){
  try{
    // "audio": a file path, or "audio_base64": encoded audio piped from lens-engine (voice capture; never on disk).
    std::string line;if(lens::read_line(std::cin,line,4*1024*1024)!=lens::Line::ready)throw lens::Error("invalid_request");
    const auto req=json::parse(line);if(!req.value("consent",false))throw lens::Error("consent_required");
    const auto model_type=lens::validated_string(req.value("model_type",std::string("dolphin")),64);
    if(model_type!="dolphin"&&model_type!="nemo_ctc")throw lens::Error("unsupported_asr_model_type");
    std::vector<char> bytes;
    if(req.contains("audio_base64")) {
        const auto text=req.at("audio_base64").get<std::string>();DWORD size=0;
        if(!CryptStringToBinaryA(text.data(),static_cast<DWORD>(text.size()),CRYPT_STRING_BASE64,nullptr,&size,nullptr,nullptr))throw lens::Error("audio_decode_failed");
        bytes.resize(size);
        if(!CryptStringToBinaryA(text.data(),static_cast<DWORD>(text.size()),CRYPT_STRING_BASE64,reinterpret_cast<BYTE*>(bytes.data()),&size,nullptr,nullptr))throw lens::Error("audio_decode_failed");
        bytes.resize(size);
    } else bytes=lens::read_file(lens::utf8_path(req.at("audio").get<std::string>()),64000000);
    Audio audio;auto cfg=ma_decoder_config_init(ma_format_f32,1,16000);
    if(ma_decoder_init_memory(bytes.data(),bytes.size(),&cfg,&audio.d)!=MA_SUCCESS)throw lens::Error("audio_decode_failed");audio.loaded=true;
    ma_uint64 count{};if(ma_decoder_get_length_in_pcm_frames(&audio.d,&count)!=MA_SUCCESS)throw lens::Error("audio_decode_failed");
    if(!count||count>16000ULL*600)throw lens::Error("audio_duration_limit_exceeded");
    std::vector<float> pcm(static_cast<size_t>(count));ma_uint64 got{};
    if(ma_decoder_read_pcm_frames(&audio.d,pcm.data(),count,&got)!=MA_SUCCESS||!got)throw lens::Error("audio_decode_failed");
    const auto model=lens::validated_string(req.at("model").get<std::string>(),32768);
    const auto tokens=lens::validated_string(req.at("tokens").get<std::string>(),32768);
    // Fully qualified with backslashes, or LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR is ignored and Windows' System32 onnxruntime.dll loads.
    const auto library=std::filesystem::absolute(lens::utf8_path(req.at("library").get<std::string>())).make_preferred();
    if(!std::filesystem::is_regular_file(lens::utf8_path(model))||!std::filesystem::is_regular_file(lens::utf8_path(tokens)))throw lens::Error("model_unavailable");
    Module module{LoadLibraryExW(library.c_str(),nullptr,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_DEFAULT_DIRS)};
    if(!module.h)throw lens::Error("asr_runtime_unavailable");
    auto create=api<decltype(&SherpaOnnxCreateOfflineRecognizer)>(module.h,"SherpaOnnxCreateOfflineRecognizer");
    auto destroy=api<decltype(&SherpaOnnxDestroyOfflineRecognizer)>(module.h,"SherpaOnnxDestroyOfflineRecognizer");
    auto stream_create=api<decltype(&SherpaOnnxCreateOfflineStream)>(module.h,"SherpaOnnxCreateOfflineStream");
    auto stream_destroy=api<decltype(&SherpaOnnxDestroyOfflineStream)>(module.h,"SherpaOnnxDestroyOfflineStream");
    auto accept=api<decltype(&SherpaOnnxAcceptWaveformOffline)>(module.h,"SherpaOnnxAcceptWaveformOffline");
    auto decode=api<decltype(&SherpaOnnxDecodeOfflineStream)>(module.h,"SherpaOnnxDecodeOfflineStream");
    auto result_get=api<decltype(&SherpaOnnxGetOfflineStreamResultAsJson)>(module.h,"SherpaOnnxGetOfflineStreamResultAsJson");
    auto result_destroy=api<decltype(&SherpaOnnxDestroyOfflineStreamResultJson)>(module.h,"SherpaOnnxDestroyOfflineStreamResultJson");
    SherpaOnnxOfflineRecognizerConfig config{};config.feat_config.sample_rate=16000;config.feat_config.feature_dim=80;
    if(model_type=="dolphin")config.model_config.dolphin.model=model.c_str();else config.model_config.nemo_ctc.model=model.c_str();
    config.model_config.tokens=tokens.c_str();
    config.model_config.num_threads=2;config.model_config.provider="cpu";config.model_config.debug=0;config.decoding_method="greedy_search";
    std::unique_ptr<const SherpaOnnxOfflineRecognizer,decltype(destroy)> recognizer(create(&config),destroy);
    if(!recognizer)throw lens::Error("asr_model_load_failed");
    std::unique_ptr<const SherpaOnnxOfflineStream,decltype(stream_destroy)> stream(stream_create(recognizer.get()),stream_destroy);
    if(!stream)throw lens::Error("asr_stream_failed");
    accept(stream.get(),16000,pcm.data(),static_cast<int32_t>(got));decode(recognizer.get(),stream.get());
    std::unique_ptr<const char,decltype(result_destroy)> raw(result_get(stream.get()),result_destroy);
    if(!raw)throw lens::Error("transcription_failed");
    auto result=json::parse(raw.get());result["ok"]=true;result["confidence"]=nullptr;
    result["confidence_status"]="not_provided_by_model";
    result["provider"]=model_type=="dolphin"?"sherpa-onnx-dolphin-ctc":"sherpa-onnx-indicconformer-ctc";
    result["language"]=lens::validated_string(req.value("language",std::string("und")),32);
    result["language_source"]="user_supplied; language identification not scored";
    std::cout<<result.dump()<<'\n';
  }catch(const lens::Error& e){std::cerr<<e.what()<<'\n';return 1;}catch(...){std::cerr<<"asr_request_failed\n";return 1;}
}
