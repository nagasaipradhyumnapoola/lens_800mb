#pragma once
#include "e5_tokenizer.hpp"
#include <array>
#include <filesystem>
#include <memory>
#include <string>
#include <vector>
namespace lens {
constexpr std::size_t embedding_dim=384;
using Embedding=std::array<float,embedding_dim>;
struct EmbedderConfig {
    std::filesystem::path runtime;      // onnxruntime.dll (hash-verified by the client)
    std::filesystem::path model;        // multilingual-e5-small ONNX
    std::filesystem::path tokenizer;    // tokenizer.json from the same revision
    std::string model_id;               // recorded with every stored vector
    bool low_memory=false;              // phones: no ONNX Runtime arena, memory patterns or pre-packed weight copies
    bool configured() const {return !model.empty();}
};
// multilingual-e5-small: "query: "/"passage: " prefixes, mean pooling over the attention mask, L2 norm.
// Loaded lazily by the store and released with it; never resident without a request that needs it.
class Embedder {
public:
    explicit Embedder(const EmbedderConfig& config);
    ~Embedder();
    Embedder(const Embedder&)=delete;
    Embedder& operator=(const Embedder&)=delete;
    std::vector<Embedding> embed(const std::vector<std::string>& texts);
    const std::string& model_id() const {return id_;}
private:
    Embedding embed_one(const std::string& text);
    struct Runtime;
    std::unique_ptr<Runtime> runtime_;
    E5Tokenizer tokenizer_;
    std::string id_;
};
}
