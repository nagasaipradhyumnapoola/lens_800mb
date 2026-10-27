#pragma once
// Episodic memory, L3 (docs/LENS_V1_SPEC.md §8): consecutive observations of one device, application and window/
// document with gaps of at most `gap_seconds` form an episode. Episodes are derived and fully rebuildable from the
// immutable observations; every episode lists its member sources (provenance) and carries no inferred content.
#include <nlohmann/json.hpp>
struct sqlite3;
namespace lens {
nlohmann::json consolidate_episodes(sqlite3* db,const nlohmann::json& request);  // op "consolidate"
nlohmann::json list_episodes(sqlite3* db,const nlohmann::json& request);         // op "episodes"
nlohmann::json episode_context(sqlite3* db,const nlohmann::json& request);       // op "episode_context"
nlohmann::json episode_of(sqlite3* db,const std::string& source_id);             // null when not consolidated
}
