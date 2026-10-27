// OS-provided randomness and per-user DPAPI. No custom encryption primitives.
#include "key_store.hpp"
#include "../../engine/input.hpp"
#include <windows.h>
#include <wincrypt.h>
#include <bcrypt.h>
#include <algorithm>
#include <fstream>
#include <iterator>
#include <stdexcept>
#include <vector>
namespace lens {
Key load_or_create_key(const std::filesystem::path& path, bool database_exists) {
    Key key{};
    if (std::filesystem::exists(path)) {
        auto encrypted=read_file(path,16384);
        DATA_BLOB blob{static_cast<DWORD>(encrypted.size()),reinterpret_cast<unsigned char*>(encrypted.data())}, plain{};
        if (!CryptUnprotectData(&blob,nullptr,nullptr,nullptr,nullptr,CRYPTPROTECT_UI_FORBIDDEN,&plain))
            throw Error("key_unavailable");
        const bool valid=plain.cbData==key.size();
        if (valid) std::copy_n(plain.pbData,key.size(),key.begin());
        SecureZeroMemory(plain.pbData,plain.cbData); LocalFree(plain.pbData);
        if (!valid) throw Error("key_unavailable");
        return key;
    }
    if (database_exists) throw Error("key_unavailable");
    if (BCryptGenRandom(nullptr,key.data(),static_cast<ULONG>(key.size()),BCRYPT_USE_SYSTEM_PREFERRED_RNG)!=0)
        throw Error("key_generation_failed");
    DATA_BLOB plain{static_cast<DWORD>(key.size()),key.data()}, protected_blob{};
    if (!CryptProtectData(&plain,L"Lens Micro memory key",nullptr,nullptr,nullptr,
                         CRYPTPROTECT_UI_FORBIDDEN,&protected_blob)) {
        SecureZeroMemory(key.data(),key.size()); throw Error("key_protection_failed");
    }
    HANDLE file=CreateFileW(path.c_str(),GENERIC_WRITE,0,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);
    DWORD written{};
    bool ok=file!=INVALID_HANDLE_VALUE && WriteFile(file,protected_blob.pbData,protected_blob.cbData,&written,nullptr)
            && written==protected_blob.cbData && FlushFileBuffers(file);
    if (file!=INVALID_HANDLE_VALUE) CloseHandle(file);
    LocalFree(protected_blob.pbData);
    if (!ok) {SecureZeroMemory(key.data(),key.size());throw Error("key_write_failed");}
    return key;
}
}
