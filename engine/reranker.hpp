#pragma once
#include "e5_tokenizer.hpp"
#include <filesystem>
#include <memory>
#include <string>
#include <vector>
namespace lens {
class OnnxModel;
struct RerankerConfig {
    std::filesystem::path runtime;   // onnxruntime.dll (hash-verified by the client)
    std::filesystem::path model;     // cross-encoder/mmarco-mMiniLMv2-L12-H384-v1 ONNX
    std::filesystem::path tokenizer; // tokenizer.json from the same revision
    bool configured() const {return !model.empty();}
};
// Multilingual cross-encoder: one relevance logit per (query, passage) pair. Loaded lazily, one pair per run
// (dynamic INT8 quantization would otherwise make scores depend on batch neighbours).
class Reranker {
public:
    explicit Reranker(const RerankerConfig& config);
    ~Reranker();
    Reranker(const Reranker&)=delete;
    Reranker& operator=(const Reranker&)=delete;
    std::vector<float> score(const std::string& query,const std::vector<std::string>& passages);
private:
    std::unique_ptr<OnnxModel> model_;
    E5Tokenizer tokenizer_;
};
}
