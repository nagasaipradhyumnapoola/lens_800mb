#pragma once
// Continuous learning without training (docs/LENS_V1_SPEC.md §12) and temporal currency (L6): user corrections of
// derived facts (the original stays, marked superseded/rejected, with provenance), pinned memories, and relevance
// feedback used as a recall signal. Query text is never stored: feedback is keyed by a hash of the normalised question.
#include <nlohmann/json.hpp>
#include <string>
#include <vector>
struct sqlite3;
namespace lens {
nlohmann::json user_memory_op(sqlite3* db,const std::string& op,const nlohmann::json& request);  // pin, unpin, pins, feedback, correct_fact
// Adds user_status/superseded_by and current (latest vs superseded) to facts, in place.
void annotate_facts(sqlite3* db,nlohmann::json& facts);
// User-stated facts (corrections) about these entities (all when empty) and of this type (any when empty).
nlohmann::json user_facts_for(sqlite3* db,const std::vector<std::string>& entity_ids,const std::string& type);
// Recall: pinned and per-question feedback reorder results (positive > pinned > rest > negative).
void apply_user_signals(sqlite3* db,const std::string& question,nlohmann::json& result,bool enabled);
}
