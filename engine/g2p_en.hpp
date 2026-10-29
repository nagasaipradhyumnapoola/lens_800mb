#pragma once
#include <filesystem>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>
namespace lens {
// English text -> Kokoro phonemes from the misaki US lexicons (Apache-2.0); no espeak-ng (GPL-3.0).
// Numbers, ordinals, years, times, money and percentages are spelled out; out-of-lexicon words are decomposed into
// known parts (CamelCase, hyphens, suffixes, longest known prefixes) or spelled letter by letter, and reported.
class EnglishG2P {
public:
    EnglishG2P(const std::filesystem::path& gold,const std::filesystem::path& silver);
    std::string phonemize(std::string_view text,std::vector<std::string>& unknown) const;
    std::string word(const std::string& w,std::vector<std::string>& unknown) const;
private:
    const std::string* find(const std::string& w) const;
    std::string compose(const std::string& w) const;
    std::unordered_map<std::string,std::string> lex_;
};
std::string spell_number(std::string_view digits);  // "2026" -> "two thousand twenty-six" (integer part only)
}
