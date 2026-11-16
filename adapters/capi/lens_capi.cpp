// Lens C API (adapters/capi/lens.h): the memory core for app shells off the JVM, and the device side of the Lens link.
// The store part mirrors adapters/android/lens_jni.cpp; the link part is the client of engine/mesh/mesh_main.cpp:
// newline-delimited JSON over TLS 1.3, mutual authentication with self-signed P-256 certificates, the laptop pinned by
// the SHA-256 fingerprint of its certificate (the pairing code carries it), so no certificate authority is involved.
#include "lens.h"
#include "../../engine/store.hpp"
#include "../../engine/input.hpp"
#include <openssl/bio.h>
#include <openssl/bn.h>
#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/pem.h>
#include <openssl/rand.h>
#include <openssl/ssl.h>
#include <openssl/x509.h>
#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <mutex>
#include <string>
#ifdef _WIN32
#include <winsock2.h>
#else
#include <sys/socket.h>
#include <sys/time.h>
#endif

struct lens_store {
    std::mutex busy;lens::Store store;
    lens_store(const std::filesystem::path& db,lens::EmbedderConfig e,lens::RerankerConfig r,lens::RerankerConfig v):store(db,std::move(e),std::move(r),std::move(v)){}
};
struct lens_link {
    SSL_CTX* ctx=nullptr;SSL* ssl=nullptr;std::string pending;
    ~lens_link(){if(ssl){SSL_shutdown(ssl);SSL_free(ssl);}if(ctx)SSL_CTX_free(ctx);}
};

namespace {
using json=nlohmann::json;
char* copy(const std::string& s) {
    auto* out=static_cast<char*>(std::malloc(s.size()+1));
    if(out){std::memcpy(out,s.data(),s.size());out[s.size()]='\0';}
    return out;
}
void set_error(char** error,const std::string& code){if(error)*error=copy(code);}
char* failure(const char* code){return copy(json{{"ok",false},{"error",code}}.dump());}
std::string hex(const unsigned char* d,unsigned n){static const char* h="0123456789abcdef";std::string s;for(unsigned i=0;i<n;++i){s+=h[d[i]>>4];s+=h[d[i]&15];}return s;}
std::string fingerprint_of(X509* c){unsigned char d[EVP_MAX_MD_SIZE];unsigned n=0;X509_digest(c,EVP_sha256(),d,&n);return hex(d,n);}
std::string bio_text(BIO* b){char* data=nullptr;const long n=BIO_get_mem_data(b,&data);return n>0?std::string(data,static_cast<size_t>(n)):std::string();}
X509* read_cert(const char* pem){if(!pem)return nullptr;BIO* b=BIO_new_mem_buf(pem,-1);X509* c=b?PEM_read_bio_X509(b,nullptr,nullptr,nullptr):nullptr;BIO_free(b);return c;}
void read_timeout(BIO* b,int ms) {
    const auto fd=BIO_get_fd(b,nullptr);
#ifdef _WIN32
    const DWORD t=static_cast<DWORD>(ms);
    setsockopt(static_cast<SOCKET>(fd),SOL_SOCKET,SO_RCVTIMEO,reinterpret_cast<const char*>(&t),sizeof t);
    setsockopt(static_cast<SOCKET>(fd),SOL_SOCKET,SO_SNDTIMEO,reinterpret_cast<const char*>(&t),sizeof t);
#else
    const timeval t{ms/1000,(ms%1000)*1000};
    setsockopt(static_cast<int>(fd),SOL_SOCKET,SO_RCVTIMEO,&t,sizeof t);setsockopt(static_cast<int>(fd),SOL_SOCKET,SO_SNDTIMEO,&t,sizeof t);
#endif
}
}

extern "C" {
lens_store* lens_store_open(const char* db_path,const char* models_json,char** error) {
    if(error)*error=nullptr;
    try {
        if(!db_path||!*db_path)throw lens::Error("invalid_request");
        const auto m=json::parse(models_json&&*models_json?models_json:"{}");
        auto file=[&](const char* k){return m.contains(k)?lens::utf8_path(m.at(k).get<std::string>()):std::filesystem::path{};};
        lens::EmbedderConfig embedding{file("runtime"),file("embedding_model"),file("embedding_tokenizer"),m.value("embedding_id",std::string{})};
        lens::RerankerConfig reranking{embedding.runtime,file("reranker_model"),file("reranker_tokenizer"),true},
                             verification{embedding.runtime,file("verifier_model"),file("verifier_tokenizer"),true};
        embedding.low_memory=true;  // an app: no ONNX Runtime arena that keeps every peak shape resident
        if((embedding.configured()&&(embedding.runtime.empty()||embedding.tokenizer.empty()||embedding.model_id.empty()))||
           (reranking.configured()&&(!embedding.configured()||reranking.tokenizer.empty()))||
           (verification.configured()&&(!embedding.configured()||verification.tokenizer.empty())))throw lens::Error("invalid_model_configuration");
        return new lens_store(lens::utf8_path(db_path),embedding,reranking,verification);
    }
    catch(const lens::Error& e){set_error(error,e.what());}
    catch(const json::exception&){set_error(error,"invalid_model_configuration");}
    catch(...){set_error(error,"database_open_failed");}
    return nullptr;
}

char* lens_store_request(lens_store* store,const char* request_json) {
    if(!store)return failure("store_closed");
    if(!request_json||std::strlen(request_json)>2*1024*1024)return failure("request_too_large");
    try {
        const auto j=json::parse(request_json);
        std::lock_guard g(store->busy);return copy(store->store.request(j).dump());
    }
    catch(const lens::Error& e){return failure(e.what());}
    catch(...){return failure("invalid_request");}
}

void lens_store_close(lens_store* store){delete store;}

int lens_link_identity(char** key_pem,char** cert_pem,char** fingerprint) {
    if(!key_pem||!cert_pem||!fingerprint)return -1;
    *key_pem=*cert_pem=*fingerprint=nullptr;
    EVP_PKEY* key=EVP_PKEY_Q_keygen(nullptr,nullptr,"EC","P-256");X509* x=X509_new();BIO* kb=BIO_new(BIO_s_mem());BIO* cb=BIO_new(BIO_s_mem());
    bool ok=key&&x&&kb&&cb;
    if(ok) {
        X509_set_version(x,2);unsigned char serial[16];RAND_bytes(serial,16);BIGNUM* bn=BN_bin2bn(serial,16,nullptr);
        BN_to_ASN1_INTEGER(bn,X509_get_serialNumber(x));BN_free(bn);
        X509_gmtime_adj(X509_getm_notBefore(x),-3600);X509_gmtime_adj(X509_getm_notAfter(x),60L*60*24*365*20);X509_set_pubkey(x,key);
        X509_NAME* name=X509_get_subject_name(x);
        X509_NAME_add_entry_by_txt(name,"CN",MBSTRING_ASC,reinterpret_cast<const unsigned char*>("Lens companion"),-1,-1,0);
        X509_set_issuer_name(x,name);
        ok=X509_sign(x,key,EVP_sha256())>0&&PEM_write_bio_PrivateKey(kb,key,nullptr,nullptr,0,nullptr,nullptr)==1&&PEM_write_bio_X509(cb,x)==1;
    }
    if(ok) {
        std::string k=bio_text(kb);*key_pem=copy(k);OPENSSL_cleanse(k.data(),k.size());
        *cert_pem=copy(bio_text(cb));*fingerprint=copy(fingerprint_of(x));
        ok=*key_pem&&*cert_pem&&*fingerprint;
    }
    BIO_free(kb);BIO_free(cb);X509_free(x);EVP_PKEY_free(key);
    if(!ok){lens_free(*key_pem);lens_free(*cert_pem);lens_free(*fingerprint);*key_pem=*cert_pem=*fingerprint=nullptr;return -1;}
    return 0;
}

char* lens_link_fingerprint(const char* cert_pem) {
    X509* c=read_cert(cert_pem);if(!c)return nullptr;
    char* out=copy(fingerprint_of(c));X509_free(c);return out;
}

lens_link* lens_link_connect(const char* hosts_json,int port,const char* fingerprint,const char* key_pem,const char* cert_pem,int timeout_ms,char** error) {
    if(error)*error=nullptr;
    try {
        const auto hosts=json::parse(hosts_json?hosts_json:"[]");
        std::string pin=fingerprint?fingerprint:"";std::transform(pin.begin(),pin.end(),pin.begin(),[](unsigned char c){return static_cast<char>(std::tolower(c));});
        if(!hosts.is_array()||port<1||port>65535||pin.size()!=64||!key_pem||!cert_pem){set_error(error,"invalid_request");return nullptr;}
        auto link=std::make_unique<lens_link>();
        link->ctx=SSL_CTX_new(TLS_client_method());
        if(!link->ctx){set_error(error,"tls_failed");return nullptr;}
        SSL_CTX_set_min_proto_version(link->ctx,TLS1_3_VERSION);
        SSL_CTX_set_verify(link->ctx,SSL_VERIFY_NONE,nullptr);  // self-signed laptop: authenticated by the pinned fingerprint below
        BIO* kb=BIO_new_mem_buf(key_pem,-1);EVP_PKEY* key=kb?PEM_read_bio_PrivateKey(kb,nullptr,nullptr,nullptr):nullptr;BIO_free(kb);
        X509* cert=read_cert(cert_pem);
        const bool identity=key&&cert&&SSL_CTX_use_certificate(link->ctx,cert)==1&&SSL_CTX_use_PrivateKey(link->ctx,key)==1&&SSL_CTX_check_private_key(link->ctx)==1;
        EVP_PKEY_free(key);X509_free(cert);  // the context keeps its own references
        if(!identity){set_error(error,"identity_unreadable");return nullptr;}
        const int wait=std::clamp(timeout_ms,1000,60000);
        std::string last="laptop_unreachable";
        for(const auto& h:hosts) {
            if(!h.is_string())continue;
            const auto host=h.get<std::string>();if(host.empty()||host.size()>253)continue;
            const auto address=(host.find(':')!=std::string::npos?"["+host+"]":host)+":"+std::to_string(port);
            BIO* b=BIO_new_connect(address.c_str());if(!b)continue;
            BIO_set_nbio(b,1);
            if(BIO_do_connect_retry(b,wait/1000,100)<=0){BIO_free_all(b);continue;}
            BIO_socket_nbio(static_cast<int>(BIO_get_fd(b,nullptr)),0);read_timeout(b,30000);
            SSL* ssl=SSL_new(link->ctx);
            if(!ssl){BIO_free_all(b);last="tls_failed";continue;}
            SSL_set_bio(ssl,b,b);
            if(SSL_connect(ssl)!=1){SSL_free(ssl);last="tls_failed";continue;}
            X509* peer=SSL_get1_peer_certificate(ssl);const auto got=peer?fingerprint_of(peer):std::string();X509_free(peer);
            if(got!=pin){SSL_free(ssl);last="laptop_mismatch";continue;}
            link->ssl=ssl;return link.release();
        }
        set_error(error,last);
    }
    catch(...){set_error(error,"invalid_request");}
    return nullptr;
}

char* lens_link_ask(lens_link* link,const char* request_json) {
    if(!link||!link->ssl)return failure("link_closed");
    std::string line;
    try{line=json::parse(request_json?request_json:"").dump()+"\n";}  // re-serialised: one line, nothing smuggled after it
    catch(...){return failure("invalid_request");}
    for(size_t off=0;off<line.size();) {
        const int n=SSL_write(link->ssl,line.data()+off,static_cast<int>(std::min<size_t>(line.size()-off,1<<20)));
        if(n<=0)return failure("link_closed");
        off+=static_cast<size_t>(n);
    }
    for(;;) {
        const auto pos=link->pending.find('\n');
        if(pos!=std::string::npos){auto out=link->pending.substr(0,pos);link->pending.erase(0,pos+1);return copy(out);}
        if(link->pending.size()>(1u<<20))return failure("response_too_large");
        char buf[16384];const int n=SSL_read(link->ssl,buf,sizeof buf);
        if(n<=0)return failure("link_closed");
        link->pending.append(buf,static_cast<size_t>(n));
    }
}

void lens_link_close(lens_link* link){delete link;}

void lens_free(char* text){std::free(text);}
}
