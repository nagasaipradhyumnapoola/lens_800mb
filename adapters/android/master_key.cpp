// Android: the app unwraps the master key with an AES key held in the Android Keystore (hardware-backed where the device
// has one) and hands it to the native engine once per process through lens_set_master_key (JNI). The native side never
// persists it; without it the engine cannot open the database.
#include "../posix/master_key.hpp"
#include "../../engine/input.hpp"
#include <openssl/crypto.h>
#include <cstring>
#include <mutex>
namespace lens {
namespace {std::mutex lock;Key held{};bool present=false;}
Key master_key(bool) {
    std::lock_guard g(lock);if(!present)throw Error("key_unavailable");
    return held;
}
}
extern "C" void lens_set_master_key(const unsigned char* bytes,int size) {
    std::lock_guard g(lens::lock);
    if(!bytes||size!=32){lens::present=false;return;}
    std::memcpy(lens::held.data(),bytes,32);lens::present=true;
}
extern "C" void lens_clear_master_key(){std::lock_guard g(lens::lock);OPENSSL_cleanse(lens::held.data(),32);lens::present=false;}
