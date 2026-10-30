// Android app library (liblens-core.so): the memory core runs inside the app's process, no worker processes. Kotlin side:
// android/core/src/main/java/ai/secondbrain/lens/NativeCore.kt. Same request contract as lens-engine's stdin protocol
// (one JSON object in, one out, errors as {"ok":false,"error":code}), one request at a time per store. Strings cross as
// UTF-8 byte arrays: JNI's own string conversion is modified UTF-8, which breaks characters outside the BMP.
#include <jni.h>
#include "../../engine/store.hpp"
#include "../../engine/input.hpp"
#include <openssl/crypto.h>
#include <malloc.h>
#include <memory>
#include <mutex>
#include <string>
#include <vector>
extern "C" void lens_set_master_key(const unsigned char* bytes,int size);  // adapters/android/master_key.cpp
extern "C" void lens_clear_master_key();
namespace {
struct Core{std::mutex busy;lens::Store store;
    Core(const std::filesystem::path& db,lens::EmbedderConfig e,lens::RerankerConfig r,lens::RerankerConfig v):store(db,std::move(e),std::move(r),std::move(v)){}};
std::string bytes(JNIEnv* env,jbyteArray array,std::size_t limit) {
    if(!array)throw lens::Error("invalid_request");
    const auto n=static_cast<std::size_t>(env->GetArrayLength(array));if(n>limit)throw lens::Error("request_too_large");
    std::string out(n,'\0');env->GetByteArrayRegion(array,0,static_cast<jsize>(n),reinterpret_cast<jbyte*>(out.data()));return out;
}
jbyteArray array(JNIEnv* env,const std::string& s) {
    auto* out=env->NewByteArray(static_cast<jsize>(s.size()));
    if(out)env->SetByteArrayRegion(out,0,static_cast<jsize>(s.size()),reinterpret_cast<const jbyte*>(s.data()));
    return out;
}
void fail(JNIEnv* env,const char* code){if(auto* c=env->FindClass("java/lang/IllegalStateException"))env->ThrowNew(c,code);}
}
extern "C" {
JNIEXPORT void JNICALL Java_ai_secondbrain_lens_NativeCore_setMasterKey(JNIEnv* env,jclass,jbyteArray key) {
    if(!key||env->GetArrayLength(key)!=32){lens_clear_master_key();return;}
    unsigned char raw[32];env->GetByteArrayRegion(key,0,32,reinterpret_cast<jbyte*>(raw));
    lens_set_master_key(raw,32);OPENSSL_cleanse(raw,sizeof raw);
}
JNIEXPORT void JNICALL Java_ai_secondbrain_lens_NativeCore_clearMasterKey(JNIEnv*,jclass){lens_clear_master_key();}
// Opens (creating on first use) the encrypted database; throws IllegalStateException with a reason code, never content.
// models: {} for keyword-only, or the retrieval models as lens-engine's arguments name them (runtime = the ONNX Runtime
// library the app ships, e.g. "libonnxruntime.so"; the reranker may also verify answers, with gate.json beside it).
JNIEXPORT jlong JNICALL Java_ai_secondbrain_lens_NativeCore_open(JNIEnv* env,jclass,jbyteArray path,jbyteArray models) {
    try{
        const auto m=nlohmann::json::parse(bytes(env,models,65536));
        auto file=[&](const char* k){return m.contains(k)?lens::utf8_path(m.at(k).get<std::string>()):std::filesystem::path{};};
        lens::EmbedderConfig embedding{file("runtime"),file("embedding_model"),file("embedding_tokenizer"),m.value("embedding_id",std::string{})};
        lens::RerankerConfig reranking{embedding.runtime,file("reranker_model"),file("reranker_tokenizer"),true},
                             verification{embedding.runtime,file("verifier_model"),file("verifier_tokenizer"),true};
        embedding.low_memory=true;  // a phone app: no ONNX Runtime arena that keeps every peak shape resident
        if((embedding.configured()&&(embedding.runtime.empty()||embedding.tokenizer.empty()||embedding.model_id.empty()))||
           (reranking.configured()&&(!embedding.configured()||reranking.tokenizer.empty()))||
           (verification.configured()&&(!embedding.configured()||verification.tokenizer.empty())))throw lens::Error("invalid_model_configuration");
        return reinterpret_cast<jlong>(new Core(lens::utf8_path(bytes(env,path,32768)),embedding,reranking,verification));
    }
    catch(const lens::Error& e){fail(env,e.what());}
    catch(...){fail(env,"database_open_failed");}
    return 0;
}
JNIEXPORT jbyteArray JNICALL Java_ai_secondbrain_lens_NativeCore_request(JNIEnv* env,jclass,jlong handle,jbyteArray request) {
    auto* core=reinterpret_cast<Core*>(handle);
    if(!core){fail(env,"store_closed");return nullptr;}
    std::string response;
    try {
        const auto j=nlohmann::json::parse(bytes(env,request,2*1024*1024));
        std::lock_guard g(core->busy);response=core->store.request(j).dump();
        if(j.value("op",std::string{})=="unload_models")mallopt(M_PURGE,0);  // hand the released model memory back to the system
    }
    catch(const lens::Error& e){response=nlohmann::json{{"ok",false},{"error",e.what()}}.dump();}
    catch(...){response="{\"ok\":false,\"error\":\"invalid_request\"}";}
    return array(env,response);
}
// The caller guarantees no request is in flight (LocalMemory serialises open, requests and close).
JNIEXPORT void JNICALL Java_ai_secondbrain_lens_NativeCore_close(JNIEnv*,jclass,jlong handle){delete reinterpret_cast<Core*>(handle);}
}
