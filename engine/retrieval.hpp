#pragma once
#include "embedder.hpp"
#include "reranker.hpp"
#include <functional>
#include <nlohmann/json.hpp>
#include <string>
#include <vector>
struct sqlite3;
namespace lens {
struct Chunk {std::size_t start,end;};
// Byte ranges of the original text embedded as passages; ranges are exact, so evidence quotes are verbatim.
std::vector<Chunk> chunk_text(const std::string& text);
using EmbedderAccess=std::function<Embedder&()>;
using RerankerAccess=std::function<Reranker&()>;
// {"op":"index"}: embeds sources that have no vectors for the configured model (incremental).
nlohmann::json index_sources(sqlite3* db,Embedder& embedder,const nlohmann::json& request);
// {"op":"recall"}: keyword, semantic or hybrid (RRF) retrieval with source-backed evidence or not_found.
nlohmann::json recall(sqlite3* db,const EmbedderAccess& embedder,const RerankerAccess& reranker,const std::string& model_id,const nlohmann::json& request);
}
