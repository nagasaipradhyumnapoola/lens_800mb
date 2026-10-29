#pragma once
// Runtime CPU dispatch for whisper.cpp / ggml (docs/LENS_V1_SPEC.md §15).
// whisper, ggml and ggml-base are shared libraries (delay-loaded on Windows); the ggml CPU backend ships as one library
// per instruction-set level (ggml-cpu-x64 = SSE2 baseline … ggml-cpu-icelake = AVX-512 VNNI on x86; per-feature
// variants on ARM). Before the first whisper call this picks the highest-scoring variant the running CPU supports,
// loading only from the executable's own directory: no current directory search and no GGML_BACKEND_PATH override
// (ggml_backend_load_all would honour both).
#include "ggml-backend.h"
#include "platform.hpp"
#include <filesystem>
#include <mutex>
#include <string>

namespace lens {
struct CpuBackend {bool ready=false;std::string variant;};

// Returns the selected ggml CPU variant, or ready=false when the runtime libraries are missing or no variant runs here.
inline const CpuBackend& ensure_ggml_cpu_backend() {
    static CpuBackend result;static std::once_flag once;
    std::call_once(once,[] {
        const auto dir=platform::executable_dir();
#ifdef _WIN32
        const char* ext=".dll";const char* prefix="ggml-cpu-";const auto whisper=dir/"whisper.dll";
#elif defined(__APPLE__)
        const char* ext=".dylib";const char* prefix="libggml-cpu-";const auto whisper=dir/"libwhisper.dylib";
#else
        const char* ext=".so";const char* prefix="libggml-cpu-";const auto whisper=dir/"libwhisper.so";
#endif
        // Load whisper first so a missing library is an error result, not a delay-load exception (Windows).
        void* self=platform::open_library(whisper);if(!self)return;
        using score_fn=int(*)();
        int best_score=0;std::filesystem::path best;std::error_code ec;
        for(const auto& entry:std::filesystem::directory_iterator(dir,ec)) {
            const auto name=entry.path().filename().string();
            if(name.rfind(prefix,0)!=0||entry.path().extension()!=ext)continue;
            void* module=platform::open_library(entry.path());if(!module)continue;
            const auto score=reinterpret_cast<score_fn>(platform::library_symbol(module,"ggml_backend_score"));
            const int s=score?score():0;
            if(s>best_score){best_score=s;best=entry.path();}
            platform::close_library(module);
        }
        if(best.empty())return;
        const auto utf8=best.u8string();
        if(!ggml_backend_load(reinterpret_cast<const char*>(utf8.c_str())))return;
        if(!ggml_backend_dev_by_type(GGML_BACKEND_DEVICE_TYPE_CPU))return;
        const auto stem=best.stem().u8string();
        result.variant.assign(reinterpret_cast<const char*>(stem.c_str()),stem.size());result.ready=true;
    });
    return result;
}
}
