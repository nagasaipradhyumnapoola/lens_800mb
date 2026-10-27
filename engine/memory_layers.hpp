#pragma once
// Semantic memory L4 (entities, facts) and project memory L5 (docs/LENS_V1_SPEC.md §8), schema v8. Derived
// incrementally by the consolidate op from the immutable observations with the model-free rules in
// semantic_extract.hpp. Every mention and every fact links to its source observations (provenance); deleting a
// source deletes what was derived only from it (triggers) and refreshes names and project links that used it.
#include <nlohmann/json.hpp>
#include <set>
#include <string>
struct sqlite3;
namespace lens {
void create_memory_layer_schema(sqlite3* db);  // schema v8, idempotent
nlohmann::json consolidate_memory_layers(sqlite3* db,const nlohmann::json& request);  // part of op "consolidate"
nlohmann::json list_entities(sqlite3* db,const nlohmann::json& request);    // op "entities"
nlohmann::json entity_context(sqlite3* db,const nlohmann::json& request);   // op "entity_context"
nlohmann::json list_facts(sqlite3* db,const nlohmann::json& request);       // op "facts"
nlohmann::json list_projects(sqlite3* db,const nlohmann::json& request);    // op "projects"
nlohmann::json project_context(sqlite3* db,const nlohmann::json& request);  // op "project_context"
std::set<std::string> entities_of_source(sqlite3* db,const std::string& source_id);
// After a deletion: names, aliases and counts of the touched entities, and project links, from what remains.
void refresh_after_delete(sqlite3* db,const std::set<std::string>& entity_ids);
// Recall: entities named in the question (an extra ranking signal), entity links and facts per result.
void annotate_recall(sqlite3* db,const std::string& question,nlohmann::json& result,bool boost);
}
