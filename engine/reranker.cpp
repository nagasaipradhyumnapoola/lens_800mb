#include "reranker.hpp"
#include "input.hpp"
#include "onnx_model.hpp"
namespace lens {
Reranker::Reranker(const RerankerConfig& config):model_(std::make_unique<OnnxModel>(config.runtime,config.model)),tokenizer_(config.tokenizer){}
Reranker::~Reranker()=default;

std::vector<float> Reranker::score(const std::string& query,const std::vector<std::string>& passages){
    std::vector<float> scores;scores.reserve(passages.size());
    for(const auto& passage:passages){
        const auto ids=tokenizer_.encode_pair(query,passage,512);
        const std::vector<std::int64_t> mask(ids.size(),1);
        std::vector<std::int64_t> shape;
        const auto logits=model_->run({"input_ids","attention_mask"},{&ids,&mask},"logits",shape);
        if(shape.size()!=2||shape[0]!=1||shape[1]!=1||logits.size()!=1)throw Error("reranker_output_shape_mismatch");
        scores.push_back(logits[0]);
    }
    return scores;
}
}
