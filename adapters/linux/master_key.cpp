// Linux: the master key lives in the user's Secret Service keyring (GNOME Keyring, KWallet, KeePassXC) via libsecret,
// hex-encoded, as the item "Lens memory master key". A locked or absent keyring is an error, never a plaintext fallback.
#include "../posix/master_key.hpp"
#include "../../engine/input.hpp"
#include <libsecret/secret.h>
#include <openssl/crypto.h>
#include <cstdio>
#include <cstring>
#include <string>
namespace lens {
namespace {
const SecretSchema* schema() {
    static const SecretSchema s={"org.secondbrain.lens.MasterKey",SECRET_SCHEMA_NONE,{{"purpose",SECRET_SCHEMA_ATTRIBUTE_STRING},{nullptr,SECRET_SCHEMA_ATTRIBUTE_STRING}},
                                 0,nullptr,nullptr,nullptr,nullptr,nullptr,nullptr,nullptr};
    return &s;
}
}
Key master_key(bool create) {
    GError* error=nullptr;
    gchar* stored=secret_password_lookup_sync(schema(),nullptr,&error,"purpose","database-key-wrapping",nullptr);
    if(error){g_error_free(error);throw Error("key_unavailable");}
    Key key{};
    if(stored) {
        const size_t n=std::strlen(stored);bool ok=n==64;
        for(size_t i=0;ok&&i<32;++i){unsigned v=0;ok=std::sscanf(stored+2*i,"%2x",&v)==1;key[i]=static_cast<std::uint8_t>(v);}
        secret_password_free(stored);
        if(!ok)throw Error("key_unavailable");
        return key;
    }
    if(!create)throw Error("key_unavailable");
    key=random_key();std::string hex(64,'0');
    for(size_t i=0;i<32;++i)std::snprintf(hex.data()+2*i,3,"%02x",key[i]);
    const bool ok=secret_password_store_sync(schema(),SECRET_COLLECTION_DEFAULT,"Lens memory master key",hex.c_str(),nullptr,&error,
                                             "purpose","database-key-wrapping",nullptr);
    OPENSSL_cleanse(hex.data(),hex.size());
    if(!ok||error){if(error)g_error_free(error);OPENSSL_cleanse(key.data(),key.size());throw Error("key_unavailable");}
    return key;
}
}
