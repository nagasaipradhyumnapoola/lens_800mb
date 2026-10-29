// Inference is performed by Microsoft's unmodified ONNX Runtime, loaded from a hash-verified DLL.
#define ORT_API_MANUAL_INIT
#include "onnxruntime_cxx_api.h"
#include "onnx_model.hpp"
#include "input.hpp"
#include "platform.hpp"
namespace lens {
namespace {
void quiet(void*,OrtLoggingLevel,const char*,const char*,const char*,const char*){}
std::vector<float> output_of(std::vector<Ort::Value>&& result,std::vector<std::int64_t>& shape){
    auto info=result[0].GetTensorTypeAndShapeInfo();
    if(info.GetElementType()!=ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT)throw Error("onnx_output_type_mismatch");
    shape=info.GetShape();
    const float* data=result[0].GetTensorData<float>();
    return std::vector<float>(data,data+info.GetElementCount());
}
}
struct OnnxModel::State {
    void* module{};
    std::unique_ptr<Ort::Env> env;
    std::unique_ptr<Ort::Session> session;
    std::vector<std::string> inputs;
    ~State(){session.reset();env.reset();platform::close_library(module);}
};

OnnxModel::OnnxModel(const std::filesystem::path& runtime,const std::filesystem::path& model,int threads,bool low_memory):state_(std::make_unique<State>()){
    state_->module=platform::open_library(runtime);
    if(!state_->module)throw Error("onnx_runtime_unavailable");
    using GetBase=const OrtApiBase*(ORT_API_CALL*)();
    const auto get_base=reinterpret_cast<GetBase>(platform::library_symbol(state_->module,"OrtGetApiBase"));
    if(!get_base)throw Error("onnx_runtime_unavailable");
    const auto api=get_base()->GetApi(ORT_API_VERSION);if(!api)throw Error("onnx_runtime_version_mismatch");
    Ort::InitApi(api);
    state_->env=std::make_unique<Ort::Env>(ORT_LOGGING_LEVEL_FATAL,"Lens",quiet,nullptr);
    state_->env->DisableTelemetryEvents();
    Ort::SessionOptions options;options.SetIntraOpNumThreads(threads);options.SetInterOpNumThreads(1);
    options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
    if(low_memory){options.DisableCpuMemArena();options.DisableMemPattern();}
    state_->session=std::make_unique<Ort::Session>(*state_->env,model.c_str(),options);
    Ort::AllocatorWithDefaultOptions allocator;
    for(std::size_t i=0;i<state_->session->GetInputCount();++i)state_->inputs.emplace_back(state_->session->GetInputNameAllocated(i,allocator).get());
}
OnnxModel::~OnnxModel()=default;

bool OnnxModel::has_input(const std::string& name) const {
    for(const auto& n:state_->inputs)if(n==name)return true;return false;
}

std::vector<float> OnnxModel::run(const std::vector<const char*>& names,const std::vector<const std::vector<std::int64_t>*>& inputs,
                                  const char* output,std::vector<std::int64_t>& shape){
    if(names.size()!=inputs.size()||inputs.empty())throw Error("onnx_invalid_inputs");
    const std::array<std::int64_t,2> dims{1,static_cast<std::int64_t>(inputs[0]->size())};
    auto memory=Ort::MemoryInfo::CreateCpu(OrtArenaAllocator,OrtMemTypeDefault);
    std::vector<Ort::Value> values;
    for(const auto* v:inputs){
        if(v->size()!=inputs[0]->size())throw Error("onnx_invalid_inputs");
        values.push_back(Ort::Value::CreateTensor<std::int64_t>(memory,const_cast<std::int64_t*>(v->data()),v->size(),dims.data(),dims.size()));
    }
    return output_of(state_->session->Run(Ort::RunOptions{nullptr},names.data(),values.data(),values.size(),&output,1),shape);
}

std::vector<float> OnnxModel::run(const std::vector<Tensor>& inputs,const char* output,std::vector<std::int64_t>& shape){
    auto memory=Ort::MemoryInfo::CreateCpu(OrtArenaAllocator,OrtMemTypeDefault);
    std::vector<Ort::Value> values;std::vector<const char*> names;
    for(const auto& t:inputs){
        std::int64_t n=1;for(auto d:t.shape)n*=d;
        if((t.i64==nullptr)==(t.f32==nullptr)||n!=static_cast<std::int64_t>(t.count))throw Error("onnx_invalid_inputs");
        names.push_back(t.name);
        values.push_back(t.i64?Ort::Value::CreateTensor<std::int64_t>(memory,const_cast<std::int64_t*>(t.i64),t.count,t.shape.data(),t.shape.size())
                              :Ort::Value::CreateTensor<float>(memory,const_cast<float*>(t.f32),t.count,t.shape.data(),t.shape.size()));
    }
    return output_of(state_->session->Run(Ort::RunOptions{nullptr},names.data(),values.data(),values.size(),&output,1),shape);
}
}
