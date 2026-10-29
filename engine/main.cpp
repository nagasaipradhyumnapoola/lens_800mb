#include "store.hpp"
#include "asr.hpp"
#include "input.hpp"
#include <chrono>
#include <condition_variable>
#include <iostream>
#include <mutex>
#include <string>
#include <stdexcept>
#include <thread>
#include <vector>
namespace {
int run(int argc,wchar_t** argv) {
    // lens-engine --db <db> [--ort <onnxruntime.dll> --embedding-model <onnx> --embedding-tokenizer <json> --embedding-id <id>
    //                       [--reranker-model <onnx> --reranker-tokenizer <json>]] [--model-idle-unload-ms <ms>]
    // Retrieval models are released after <ms> without requests (default 60000; 0 keeps them until unload_models),
    // so an idle engine returns to its model-free footprint (docs/LENS_V1_SPEC.md §15).
    std::filesystem::path db;lens::EmbedderConfig embedding;lens::RerankerConfig reranking,verification;bool valid=argc%2==1;
    long long idle_unload_ms=60000;
    for(int i=1;valid&&i+1<argc;i+=2){
        const std::wstring name=argv[i];const std::filesystem::path value=argv[i+1];
        if(name==L"--db")db=value;
        else if(name==L"--ort")embedding.runtime=value;
        else if(name==L"--embedding-model")embedding.model=value;
        else if(name==L"--embedding-tokenizer")embedding.tokenizer=value;
        else if(name==L"--embedding-id"){const auto u8=value.u8string();embedding.model_id.assign(u8.begin(),u8.end());}
        else if(name==L"--reranker-model")reranking.model=value;
        else if(name==L"--reranker-tokenizer")reranking.tokenizer=value;
        else if(name==L"--verifier-model")verification.model=value;
        else if(name==L"--verifier-tokenizer")verification.tokenizer=value;
        else if(name==L"--model-idle-unload-ms") {
            try{size_t used=0;const std::wstring text=argv[i+1];idle_unload_ms=std::stoll(text,&used);valid=used==text.size()&&idle_unload_ms>=0;}
            catch(...){valid=false;}
        }
        else valid=false;
    }
    reranking.runtime=embedding.runtime;verification.runtime=embedding.runtime;
    if(!valid||db.empty()||(embedding.configured()&&(embedding.runtime.empty()||embedding.tokenizer.empty()||embedding.model_id.empty()))||
       (reranking.configured()&&(!embedding.configured()||reranking.tokenizer.empty()))||
       (verification.configured()&&(!embedding.configured()||verification.tokenizer.empty()))){
        std::cerr<<"usage: lens-engine --db <encrypted database> [--ort <dll> --embedding-model <onnx> --embedding-tokenizer <json> --embedding-id <id> [--reranker-model <onnx> --reranker-tokenizer <json>]] [--model-idle-unload-ms <ms>]\n";return 2;
    }
    try {
        lens::Store store{db,embedding,reranking,verification};
        std::mutex busy;std::condition_variable wake;bool stopping=false;
        auto last_request=std::chrono::steady_clock::now();bool models_may_be_loaded=false;
        std::thread idle_unloader;
        if(idle_unload_ms>0&&embedding.configured()) idle_unloader=std::thread([&] {
            const auto timeout=std::chrono::milliseconds(idle_unload_ms);
            std::unique_lock lock(busy);
            while(!stopping) {
                if(!models_may_be_loaded){wake.wait(lock);continue;}
                if(wake.wait_until(lock,last_request+timeout,[&]{return stopping;}))break;
                if(std::chrono::steady_clock::now()-last_request>=timeout) {
                    store.request({{"op","unload_models"}});models_may_be_loaded=false;
                }
            }
        });
        struct Join{std::thread& t;std::mutex& m;std::condition_variable& c;bool& stop;
            ~Join(){{std::lock_guard g(m);stop=true;}c.notify_all();if(t.joinable())t.join();}} join{idle_unloader,busy,wake,stopping};
        std::string line;
        while(true) {
            const auto status=lens::read_line(std::cin,line,2*1024*1024);
            if(status==lens::Line::end)break;
            if(status==lens::Line::too_large) {std::cout<<"{\"ok\":false,\"error\":\"request_too_large\"}\n";return 2;}
            std::lock_guard request_lock(busy);
            try {
                auto request=nlohmann::json::parse(line);
                if(request.value("op",std::string{})=="ingest_audio") {
                    const auto result=lens::transcribe(request);
                    if(result.at("text").get<std::string>().empty())throw lens::Error("no_speech_found");
                    request["op"]="add";request["text"]=result.at("text");request["language"]=result.at("language");
                    request["confidence"]=result.at("token_probability");
                    if(!request.contains("metadata"))request["metadata"]=nlohmann::json::object();
                    request["metadata"]["segments"]=result.at("segments");request["metadata"]["audio_duration_seconds"]=result.at("duration_s");
                    auto response=store.request(request);response["transcript"]=result;
                    std::cout<<response.dump()<<'\n';
                } else if(request.value("op",std::string{})=="transcribe") {  // a spoken question: transcript only, nothing stored
                    std::cout<<nlohmann::json{{"ok",true},{"transcript",lens::transcribe(request)}}.dump()<<'\n';
                } else std::cout<<store.request(request).dump()<<'\n';
            }
            catch(const lens::Error& e){std::cout<<nlohmann::json{{"ok",false},{"error",e.what()}}.dump()<<'\n';}
            catch(...){std::cout<<"{\"ok\":false,\"error\":\"invalid_request\"}\n";}
            std::cout.flush();
            last_request=std::chrono::steady_clock::now();models_may_be_loaded=true;wake.notify_all();
        }
    } catch(const lens::Error& e) {std::cerr<<"database_open_failed: "<<e.what()<<"\n";return 1;}  // a reason code, never content
    catch(...) {std::cerr<<"database_open_failed\n";return 1;}
    return 0;
}
}
#ifdef _WIN32
int wmain(int argc,wchar_t** argv){return run(argc,argv);}
#else
int main(int argc,char** argv) {  // UTF-8 arguments on POSIX
    std::vector<std::wstring> args;std::vector<wchar_t*> ptrs;
    for(int i=0;i<argc;++i)args.push_back(std::filesystem::path(std::u8string(reinterpret_cast<const char8_t*>(argv[i]))).wstring());
    for(auto& a:args)ptrs.push_back(a.data());
    return run(argc,ptrs.data());
}
#endif
