#pragma once
#include "sql.hpp"
#include <nlohmann/json.hpp>
#include <string>
#include <vector>
namespace lens {
nlohmann::json memory_query(sqlite3*,const nlohmann::json&);
namespace query {
// Shared by keyword search (memory_query.cpp) and hybrid recall (retrieval.cpp).
struct Filters {std::string where;std::vector<std::string> values;};
Filters filters(const nlohmann::json& request);
void bind_values(sql::Statement& s,const std::vector<std::string>& values,int start=1);
std::vector<std::string> terms(std::string q);
std::string quote(const std::string& s);
}
}
