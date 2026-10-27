#pragma once
#include <filesystem>
#include "embedder.hpp"
#include "reranker.hpp"
#include <memory>
#include <nlohmann/json.hpp>
struct sqlite3;
namespace lens {
class TextCodec;
class Store {
public:
    explicit Store(const std::filesystem::path& path,EmbedderConfig embedding={},RerankerConfig reranking={},RerankerConfig verification={});
    ~Store();
    Store(const Store&)=delete;
    Store& operator=(const Store&)=delete;
    nlohmann::json request(const nlohmann::json& request);
private:
    nlohmann::json dispatch(const nlohmann::json& request);
    void open();                                   // keys and migrates db_ (recovers an interrupted key rotation first)
    nlohmann::json rotate_key();                   // crash-safe re-key: export under a new key, then atomic swaps
    void after_purge();                            // checkpoint, and a fresh text codec once no source remains
    Embedder& embedder();
    Reranker& reranker();
    Reranker& verifier();
    std::unique_ptr<TextCodec> codec_;  // must outlive db_ (lens_text() is registered with it)
    sqlite3* db_{};
    std::filesystem::path path_;
    EmbedderConfig embedding_;
    std::unique_ptr<Embedder> embedder_; // loaded on first semantic request, released by unload_models
    RerankerConfig reranking_;
    std::unique_ptr<Reranker> reranker_; // loaded on first reranked recall, released by unload_models
    RerankerConfig verification_;        // trained Lens answerability head (lens_model/), same architecture as the reranker
    std::unique_ptr<Reranker> verifier_; // loaded on first verified recall, released by unload_models
    // Explicit client transaction (begin/commit). Any failed request inside it poisons the commit.
    bool explicit_{},poisoned_{};
};
}
