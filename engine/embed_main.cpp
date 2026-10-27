// Diagnostic/benchmark adapter: tokenizes or embeds texts with the same code the store uses.
// One JSON request on stdin: {"tokenizer":..., "texts":[...], "mode":"tokens"|"embed", "runtime":..., "model":...}
#include "embedder.hpp"
#include "reranker.hpp"
#include "input.hpp"
#include <nlohmann/json.hpp>
#include <iostream>
using json=nlohmann::json;
int main(){
    try{
        std::string line;if(lens::read_line(std::cin,line,64*1024*1024)!=lens::Line::ready)throw lens::Error("invalid_request");
        const auto req=json::parse(line);const auto mode=req.value("mode",std::string("tokens"));
        std::vector<std::string> texts;for(const auto& t:req.at("texts"))texts.push_back(lens::validated_string(t.get<std::string>(),1024*1024,true));
        json out=json::array();
        if(mode=="tokens"){
            lens::E5Tokenizer tokenizer(lens::utf8_path(req.at("tokenizer").get<std::string>()));
            for(const auto& t:texts)out.push_back(tokenizer.encode(t,req.value("max_tokens",static_cast<std::size_t>(1u<<20))));
        } else if(mode=="embed"){
            lens::Embedder embedder({lens::utf8_path(req.at("runtime").get<std::string>()),lens::utf8_path(req.at("model").get<std::string>()),
                                     lens::utf8_path(req.at("tokenizer").get<std::string>()),"diagnostic"});
            const std::size_t batch=req.value("batch",16);
            for(std::size_t i=0;i<texts.size();i+=batch){
                std::vector<std::string> part(texts.begin()+i,texts.begin()+std::min(texts.size(),i+batch));
                for(const auto& v:embedder.embed(part))out.push_back(v);
            }
        } else if(mode=="pairs"||mode=="rerank"){
            // texts[0] is the query; every other text is a passage paired with it.
            if(texts.empty())throw lens::Error("invalid_request");
            const std::vector<std::string> passages(texts.begin()+1,texts.end());
            if(mode=="pairs"){
                lens::E5Tokenizer tokenizer(lens::utf8_path(req.at("tokenizer").get<std::string>()));
                for(const auto& p:passages)out.push_back(tokenizer.encode_pair(texts[0],p,req.value("max_tokens",static_cast<std::size_t>(512))));
            } else {
                lens::Reranker reranker({lens::utf8_path(req.at("runtime").get<std::string>()),lens::utf8_path(req.at("model").get<std::string>()),
                                         lens::utf8_path(req.at("tokenizer").get<std::string>())});
                for(float s:reranker.score(texts[0],passages))out.push_back(s);
            }
        } else throw lens::Error("unsupported_mode");
        std::cout<<json{{"ok",true},{"results",out}}.dump()<<'\n';
    }catch(const lens::Error& e){std::cerr<<e.what()<<'\n';return 1;}
    catch(const std::exception& e){std::cerr<<"embed_request_failed: "<<e.what()<<'\n';return 1;}
}
