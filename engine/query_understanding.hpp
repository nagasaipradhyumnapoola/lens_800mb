#pragma once
#include <string>
#include <vector>
namespace lens {
// Bounded, rule-based interpretation of a question's non-content constraints. It never invents filters
// that the question does not state, and every interpreted item names the phrase it came from.
struct ApplicationHint {std::string phrase;std::vector<std::string> matches;}; // matches: lowercase substrings of source_application
struct QueryInterpretation {
    std::vector<ApplicationHint> applications;
    std::string action;        // read | watched | downloaded | sent | booked | ordered | "" ; trace only until observers record kinds
    std::string action_phrase;
};
QueryInterpretation interpret_query(const std::string& question);
}
