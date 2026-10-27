#pragma once
// Memory lifecycle L9 (docs/LENS_V1_SPEC.md §8, §17), schema v9: encrypted backup and verified restore, export of the
// user's own sources (JSONL with provenance), scoped deletion that leaves nothing derived behind, and retention rules.
// Backups are SQLCipher exports written page-encrypted (no plaintext copy on disk); their key is DPAPI-wrapped beside
// the file or is the user's passphrase (SQLCipher's KDF). Passphrases travel only inside JSON requests on stdin.
#include <nlohmann/json.hpp>
#include <array>
#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>
struct sqlite3;
namespace lens {
inline constexpr int schema_version=9;
void create_lifecycle_schema(sqlite3* db);  // v9: pins, recall_feedback, user_facts, fact_status, retention_rules
// Source ids matching a deletion/export scope: {"all":true} | any of source_ids, application, kind, start, end,
// import (the export SHA-256 of a history import). Unknown or empty scopes are rejected.
std::vector<std::string> select_sources(sqlite3* db,const nlohmann::json& scope);
// Deletes the sources and everything derived from them (vectors, FTS terms, mentions, facts, projects, episodes,
// pins, feedback), refreshes derived names, and merges the FTS index so no deleted term survives. Inside a transaction.
long long purge_sources(sqlite3* db,const std::vector<std::string>& ids);
void checkpoint(sqlite3* db,bool vacuum);  // outside any transaction: WAL truncate (+ VACUUM)
nlohmann::json list_imports(sqlite3* db,const nlohmann::json& request);  // op "imports": history imports by export SHA-256
nlohmann::json export_sources(sqlite3* db,const nlohmann::json& request);
nlohmann::json backup_database(sqlite3* db,const nlohmann::json& request);
nlohmann::json restore_database(sqlite3* db,const nlohmann::json& request);
nlohmann::json retention_op(sqlite3* db,const std::string& op,const nlohmann::json& request);  // retention_set/list/remove
nlohmann::json apply_retention(sqlite3* db);  // consolidate; pinned sources are never expired
// File helpers for key rotation (engine/store.cpp).
bool database_opens_with(const std::filesystem::path& path,const std::array<std::uint8_t,32>& key);
void replace_file(const std::filesystem::path& from,const std::filesystem::path& to);  // atomic, write-through
void export_encrypted(sqlite3* db,const std::filesystem::path& target,const std::array<std::uint8_t,32>& key,const char* alias);
void fault_point(const char* name);  // test-only crash simulation, active only when LENS_FAULT_INJECTION names it
}
