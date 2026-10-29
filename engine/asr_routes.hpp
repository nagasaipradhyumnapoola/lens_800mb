#pragma once
// Language -> stronger upstream ASR routes for engine/asr.cpp ("asr_routes"), from the models installed under <models>:
// zh -> Dolphin, hi/bn/te/mr/ta/ur/gu -> IndicConformer, en/es/de/fr -> Canary-180M-flash. Only languages whose files
// exist are routed. Shared by lens-voice (continuous capture) and lens-agent (push-to-talk questions).
#include <nlohmann/json.hpp>
#include <filesystem>
#include <string>
namespace lens {
inline nlohmann::json asr_routes(const std::filesystem::path& models,const std::filesystem::path& library) {
    namespace fs=std::filesystem;
    auto u8=[](const fs::path& p){const auto s=fs::path(p).make_preferred().u8string();return std::string(reinterpret_cast<const char*>(s.data()),s.size());};
    nlohmann::json routes=nlohmann::json::object();std::error_code ec;
    if(!fs::is_regular_file(library,ec))return routes;
    auto add=[&](const char* code,const char* type,const fs::path& weights,const fs::path& tokens,const fs::path& decoder={}) {
        if(fs::is_regular_file(weights,ec)&&fs::is_regular_file(tokens,ec)&&(decoder.empty()||fs::is_regular_file(decoder,ec))) {
            routes[code]={{"model_type",type},{"model",u8(weights)},{"tokens",u8(tokens)},{"library",u8(library)}};
            if(!decoder.empty())routes[code]["decoder"]=u8(decoder);
        }
    };
    const auto dolphin=models/L"csukuangfj--sherpa-onnx-dolphin-small-ctc-multi-lang-int8-2025-04-02";
    const auto indic=models/L"parismitaglobalsolutions--indicconformer-sherpa-onnx";
    const auto canary=models/L"csukuangfj--sherpa-onnx-nemo-canary-180m-flash-en-es-de-fr-int8";
    add("zh","dolphin",dolphin/L"model.int8.onnx",dolphin/L"tokens.txt");
    for(const char* code:{"hi","bn","te","mr","ta","ur","gu"})add(code,"nemo_ctc",indic/fs::path(code)/L"model.int8.onnx",indic/L"tokens.txt");
    // Canary-180M-flash (Open ASR LibriSpeech clean/other 1.87/3.83% WER vs whisper base) for English, Spanish, German, French.
    for(const char* code:{"en","es","de","fr"})add(code,"canary",canary/L"encoder.int8.onnx",canary/L"tokens.txt",canary/L"decoder.int8.onnx");
    return routes;
}
}
