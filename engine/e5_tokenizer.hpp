#pragma once
#include <cstdint>
#include <filesystem>
#include <string>
#include <unordered_map>
#include <vector>
namespace lens {
// XLM-R/e5 tokenizer reproduced from the model's own tokenizer.json:
// sentencepiece Precompiled charsmap normalization, whitespace-run collapse, Metaspace words,
// Unigram Viterbi with fused <unk>. Parity with Hugging Face `tokenizers` is a tested gate
// (tests/test_embedding.py).
class E5Tokenizer {
public:
    explicit E5Tokenizer(const std::filesystem::path& tokenizer_json);
    std::vector<std::int64_t> encode(const std::string& text,std::size_t max_tokens=512) const;
    // <s> A </s></s> B </s>, longest_first truncation (cross-encoder input).
    std::vector<std::int64_t> encode_pair(const std::string& first,const std::string& second,std::size_t max_tokens=512) const;
    std::string normalize(const std::string& text) const;
private:
    struct Piece {std::int32_t id;float score;};
    std::vector<std::uint32_t> units_;
    std::string normalized_;
    std::unordered_map<std::string,Piece> pieces_;
    std::size_t max_piece_bytes_{};
    float unk_score_{};
    std::int32_t unk_id_{},bos_id_{},eos_id_{};
    bool replacement(const std::string& text,std::size_t at,std::size_t n,std::string& out) const;
    std::vector<std::int64_t> pieces(const std::string& text) const;
    bool collapse_spaces_{},whitespace_split_{};
    void viterbi(const std::string& word,std::vector<std::int64_t>& ids) const;
};
}
