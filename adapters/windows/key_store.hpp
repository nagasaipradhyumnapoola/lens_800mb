#pragma once
#include <array>
#include <filesystem>
#include <cstdint>
namespace lens {
using Key = std::array<std::uint8_t,32>;
Key load_or_create_key(const std::filesystem::path& path, bool database_exists);
Key unwrap_key_file(const std::filesystem::path& path);                // existing DPAPI key file
Key create_key_file(const std::filesystem::path& path);                // new random key, DPAPI-wrapped, CREATE_NEW + flush
Key random_key();
}
