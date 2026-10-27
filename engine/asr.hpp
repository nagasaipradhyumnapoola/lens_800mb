#pragma once
#include <nlohmann/json.hpp>
namespace lens {
nlohmann::json transcribe(const nlohmann::json& request);
}
