// multilingual-e5-small via ONNX Runtime. Pooling follows the model's 1_Pooling/config.json
// (mean over attention mask) and the model card's L2 normalization.
#include "embedder.hpp"
#include "input.hpp"
#include "onnx_model.hpp"
#include <cmath>
namespace lens {
struct Embedder::Runtime {std::unique_ptr<OnnxModel> model;};

Embedder::Embedder(const EmbedderConfig& config):runtime_(std::make_unique<Runtime>()),tokenizer_(config.tokenizer),id_(config.model_id){
    if(id_.empty())throw Error("embedding_model_id_required");
    runtime_->model=std::make_unique<OnnxModel>(config.runtime,config.model);
}
Embedder::~Embedder()=default;

std::vector<Embedding> Embedder::embed(const std::vector<std::string>& texts){
    // INT8 dynamic quantization scales activations per tensor, so padding would make a vector depend on
    // its batch neighbours. One text per run keeps every stored vector reproducible.
    std::vector<Embedding> all;all.reserve(texts.size());
    for(const auto& text:texts)all.push_back(embed_one(text));
    return all;
}

Embedding Embedder::embed_one(const std::string& text){
    const auto ids=tokenizer_.encode(text,512);
    const std::vector<std::int64_t> mask(ids.size(),1),types(ids.size(),0);
    std::vector<const char*> names{"input_ids","attention_mask"};std::vector<const std::vector<std::int64_t>*> inputs{&ids,&mask};
    if(runtime_->model->has_input("token_type_ids")){names.push_back("token_type_ids");inputs.push_back(&types);}
    std::vector<std::int64_t> shape;
    const auto hidden=runtime_->model->run(names,inputs,"last_hidden_state",shape);
    if(shape.size()!=3||shape[0]!=1||shape[1]!=static_cast<std::int64_t>(ids.size())||shape[2]!=static_cast<std::int64_t>(embedding_dim))
        throw Error("embedding_output_shape_mismatch");
    Embedding v{};
    for(std::size_t t=0;t<ids.size();++t)for(std::size_t d=0;d<embedding_dim;++d)v[d]+=hidden[t*embedding_dim+d];
    double norm=0;for(auto& x:v){x=static_cast<float>(x/static_cast<double>(ids.size()));norm+=static_cast<double>(x)*x;}
    norm=std::sqrt(norm);if(!(norm>0))throw Error("embedding_degenerate");
    for(auto& x:v)x=static_cast<float>(x/norm);
    return v;
}
}
