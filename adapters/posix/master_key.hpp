#pragma once
#include "../key_store.hpp"
namespace lens {
// The per-user master key from the OS secret store; created there on first use when `create` is true. Throws
// Error("key_unavailable") when the store is locked or missing (Lens then cannot open, never falls back to plaintext).
Key master_key(bool create);
}
