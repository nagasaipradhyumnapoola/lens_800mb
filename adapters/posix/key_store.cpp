// Linux, macOS, iOS and Android: the 32-byte database key is wrapped with a per-user master key that only the OS secret
// store holds (adapters/<os>/master_key.cpp: Secret Service, Keychain, Android Keystore via the app). Same contract as
// DPAPI on Windows: the key file beside the database is useless without the user's OS credentials. AES-256-GCM from
// OpenSSL; file = "LENSKEY1" | 12-byte nonce | 32-byte ciphertext | 16-byte tag. No custom encryption primitives.
#include "../key_store.hpp"
#include "master_key.hpp"
#include "../../engine/input.hpp"
#include "../../engine/platform.hpp"
#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/rand.h>
#include <algorithm>
#include <cstring>
#include <memory>
#include <string>
namespace lens {
namespace {
constexpr char MAGIC[8]={'L','E','N','S','K','E','Y','1'};
constexpr size_t NONCE=12,TAG=16,FILE_SIZE=sizeof MAGIC+NONCE+32+TAG;
struct Ctx{EVP_CIPHER_CTX* p=EVP_CIPHER_CTX_new();~Ctx(){EVP_CIPHER_CTX_free(p);}};
}
Key random_key() {
    Key key{};if(RAND_bytes(key.data(),static_cast<int>(key.size()))!=1)throw Error("key_generation_failed");
    return key;
}
Key unwrap_key_file(const std::filesystem::path& path) {
    const auto raw=read_file(path,16384);
    if(raw.size()!=FILE_SIZE||std::memcmp(raw.data(),MAGIC,sizeof MAGIC)!=0)throw Error("key_unavailable");
    Key master=master_key(false),key{};Ctx c;int n=0;bool ok=c.p;
    const auto* nonce=reinterpret_cast<const unsigned char*>(raw.data())+sizeof MAGIC;const auto* body=nonce+NONCE;const auto* tag=body+32;
    ok=ok&&EVP_DecryptInit_ex(c.p,EVP_aes_256_gcm(),nullptr,master.data(),nonce)==1&&
       EVP_CIPHER_CTX_ctrl(c.p,EVP_CTRL_GCM_SET_TAG,TAG,const_cast<unsigned char*>(tag))==1&&
       EVP_DecryptUpdate(c.p,key.data(),&n,body,32)==1&&n==32&&EVP_DecryptFinal_ex(c.p,key.data()+n,&n)==1;  // tag verified here
    OPENSSL_cleanse(master.data(),master.size());
    if(!ok){OPENSSL_cleanse(key.data(),key.size());throw Error("key_unavailable");}
    return key;
}
Key create_key_file(const std::filesystem::path& path) {
    Key key=random_key(),master=master_key(true);std::string out(MAGIC,sizeof MAGIC);out.resize(FILE_SIZE);
    auto* nonce=reinterpret_cast<unsigned char*>(out.data())+sizeof MAGIC;auto* body=nonce+NONCE;auto* tag=body+32;
    Ctx c;int n=0;
    bool ok=c.p&&RAND_bytes(nonce,NONCE)==1&&EVP_EncryptInit_ex(c.p,EVP_aes_256_gcm(),nullptr,master.data(),nonce)==1&&
            EVP_EncryptUpdate(c.p,body,&n,key.data(),32)==1&&n==32&&EVP_EncryptFinal_ex(c.p,body+n,&n)==1&&
            EVP_CIPHER_CTX_ctrl(c.p,EVP_CTRL_GCM_GET_TAG,TAG,tag)==1;
    OPENSSL_cleanse(master.data(),master.size());
    if(!ok){OPENSSL_cleanse(key.data(),key.size());throw Error("key_protection_failed");}
    try{platform::write_new_file(path,out);}catch(const Error&){OPENSSL_cleanse(key.data(),key.size());throw Error("key_write_failed");}
    return key;
}
Key load_or_create_key(const std::filesystem::path& path,bool database_exists) {
    if(std::filesystem::exists(path))return unwrap_key_file(path);
    if(database_exists)throw Error("key_unavailable");
    return create_key_file(path);
}
}
