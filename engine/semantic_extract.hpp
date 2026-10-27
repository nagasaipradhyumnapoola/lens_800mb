#pragma once
// L4 extraction (docs/LENS_V1_SPEC.md §8): model-free, CPU-cheap rules over one observation's text in English,
// Chinese, Spanish, Hindi, Tamil and Telugu. Every mention and fact carries the exact byte range it came from,
// so derived memory always points back to verbatim evidence; nothing here invents text.
#include <cstdint>
#include <optional>
#include <string>
#include <utility>
#include <vector>
namespace lens::extract {
inline constexpr const char* extractor_version="rules-v1";
enum class EntityType {person,organization,place,project,product};
const char* type_name(EntityType type);
std::optional<EntityType> parse_type(const std::string& name);
struct Mention {
    EntityType type;
    std::size_t start=0,end=0;  // byte range of the mention in the source text
    std::string surface;        // text[start,end)
    std::string name;           // identity part of the surface (legal suffixes, honorifics removed)
    std::string rule;
    double confidence=0;
};
struct Fact {
    std::string type,predicate;   // deadline/due, meeting/scheduled, amount/<budget|cost|...>, decision/decided, role/role, relationship/affiliated_with
    std::string value;            // normalised value: ISO date or "<number> <currency>"; empty for decisions and roles
    std::optional<std::int64_t> value_seconds;  // UTC midnight of a dated value
    std::size_t start=0,end=0;    // byte range of the supporting sentence (the fact's object text)
    int subject=-1,object_entity=-1;  // indexes into Extraction::mentions
    std::string rule;
    double confidence=0;
};
struct Extraction {std::vector<Mention> mentions;std::vector<Fact> facts;};
// Mentions found by the rules alone (no gazetteer).
std::vector<Mention> extract_mentions(const std::string& text);
// Facts over the final mentions of a source (rules plus gazetteer); `event_seconds` is the source's own time, the
// reference for relative dates ("Friday", "明天", "நாளை"). Fact subjects index into `mentions`.
std::vector<Fact> extract_facts(const std::string& text,std::int64_t event_seconds,const std::string& language,const std::vector<Mention>& mentions);
Extraction extract(const std::string& text,std::int64_t event_seconds,const std::string& language);  // both, without a gazetteer
// Mentions of names the user's own memories already established (the gazetteer), outside existing spans.
struct KnownName {std::string surface;EntityType type;};
std::vector<Mention> gazetteer_mentions(const std::string& text,const std::vector<KnownName>& names,const std::vector<Mention>& existing);
std::string script_of(const std::string& text);  // latin, han, deva, taml, telu, other, mixed
std::string strict_key(const std::string& name);  // identity within one script (case/accents folded; Indic romanised)
std::string loose_key(const std::string& name);   // romanised and folded for length/voicing/aspiration: joins scripts
// Query-side keys: every 1–3 word n-gram of a question, as {strict, loose} keys (Han handled by substring).
std::vector<std::pair<std::string,std::string>> query_keys(const std::string& question);
}
