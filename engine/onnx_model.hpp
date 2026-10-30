#pragma once
#include <cstdint>
#include <filesystem>
#include <memory>
#include <string>
#include <vector>
namespace lens {
// One ONNX Runtime CPU session over a hash-verified onnxruntime.dll loaded at runtime (no telemetry,
// fatal-only logging). Released with the object so models never stay resident beyond their owner.
class OnnxModel {
public:
    // low_memory: no CPU arena or memory patterns (variable-shape models whose arena would keep every peak shape).
    // no_prepacking: weights stay in their stored layout instead of a second, pre-packed copy (phones).
    OnnxModel(const std::filesystem::path& runtime,const std::filesystem::path& model,int threads=4,bool low_memory=false,bool no_prepacking=false);
    ~OnnxModel();
    OnnxModel(const OnnxModel&)=delete;
    OnnxModel& operator=(const OnnxModel&)=delete;
    bool has_input(const std::string& name) const;
    // Runs one sequence (batch 1) of int64 inputs named in `names`; returns the float output and its shape.
    std::vector<float> run(const std::vector<const char*>& names,const std::vector<const std::vector<std::int64_t>*>& inputs,
                           const char* output,std::vector<std::int64_t>& shape);
    // Any-shape int64 or float inputs (set exactly one of i64/f32, `count` elements); returns the float output.
    struct Tensor {const char* name;std::vector<std::int64_t> shape;const std::int64_t* i64=nullptr;const float* f32=nullptr;std::size_t count=0;};
    std::vector<float> run(const std::vector<Tensor>& inputs,const char* output,std::vector<std::int64_t>& shape);
private:
    struct State;
    std::unique_ptr<State> state_;
};
}
