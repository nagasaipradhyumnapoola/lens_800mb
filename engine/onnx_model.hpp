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
    OnnxModel(const std::filesystem::path& runtime,const std::filesystem::path& model,int threads=4);
    ~OnnxModel();
    OnnxModel(const OnnxModel&)=delete;
    OnnxModel& operator=(const OnnxModel&)=delete;
    bool has_input(const std::string& name) const;
    // Runs one sequence (batch 1) of int64 inputs named in `names`; returns the float output and its shape.
    std::vector<float> run(const std::vector<const char*>& names,const std::vector<const std::vector<std::int64_t>*>& inputs,
                           const char* output,std::vector<std::int64_t>& shape);
private:
    struct State;
    std::unique_ptr<State> state_;
};
}
