#pragma once
#include <filesystem>
#include <memory>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>
namespace lens {
class OnnxModel;
// English text -> Kokoro phonemes from the misaki US lexicons (Apache-2.0); no espeak-ng (GPL-3.0).
// Numbers, ordinals, years, times, money and percentages are spelled out; out-of-lexicon words are decomposed into
// known parts (CamelCase, hyphens, suffixes, longest known prefixes), else read by the trained Lens G2P model
// (models/Lens--g2p-en, lens_model/train/train_g2p.py) when given, else spelled letter by letter; all are reported.
class EnglishG2P {
public:
    EnglishG2P(const std::filesystem::path& gold,const std::filesystem::path& silver,
               const std::filesystem::path& runtime={},const std::filesystem::path& model_dir={});
    ~EnglishG2P();
    std::string phonemize(std::string_view text,std::vector<std::string>& unknown) const;
    std::string word(const std::string& w,std::vector<std::string>& unknown) const;
private:
    const std::string* find(const std::string& w) const;
    std::string compose(const std::string& w) const;
    std::string neural(const std::string& w) const;
    std::unordered_map<std::string,std::string> lex_;
    std::unique_ptr<OnnxModel> encoder_,decoder_;std::unordered_map<char,std::int64_t> chars_;std::vector<std::string> phonemes_;
    size_t in_len_=0,out_len_=0;
};
std::string spell_number(std::string_view digits);  // "2026" -> "two thousand twenty-six" (integer part only)
}
