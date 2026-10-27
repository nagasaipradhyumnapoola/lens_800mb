#pragma once
// Runtime CPU dispatch for whisper.cpp / ggml (docs/LENS_V1_SPEC.md §15).
// whisper.dll, ggml.dll and ggml-base.dll are delay-loaded; the ggml CPU backend ships as one DLL per instruction-set
// level (ggml-cpu-x64 = SSE2 baseline … ggml-cpu-icelake = AVX-512 VNNI). Before the first whisper call this picks the
// highest-scoring variant the running CPU supports, loading only from the executable's own directory: no current
// directory search and no GGML_BACKEND_PATH override (ggml_backend_load_all would honour both).
#include "ggml-backend.h"
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <filesystem>
#include <mutex>
#include <string>

namespace lens {
inline std::filesystem::path executable_directory() {
    std::wstring buffer(32768,L'\0');
    const DWORD n=GetModuleFileNameW(nullptr,buffer.data(),static_cast<DWORD>(buffer.size()));
    buffer.resize(n);return std::filesystem::path(buffer).parent_path();
}

struct CpuBackend {bool ready=false;std::string variant;};

// Returns the selected ggml CPU variant, or ready=false when the runtime DLLs are missing or no variant runs here.
inline const CpuBackend& ensure_ggml_cpu_backend() {
    static CpuBackend result;static std::once_flag once;
    std::call_once(once,[] {
        const auto dir=executable_directory();
        constexpr DWORD search=LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_SYSTEM32;
        // Load the delay-loaded import first so a missing DLL is an error result, not a delay-load exception.
        if(!LoadLibraryExW((dir/L"whisper.dll").c_str(),nullptr,search))return;
        using score_fn=int(*)();
        int best_score=0;std::filesystem::path best;std::error_code ec;
        for(const auto& entry:std::filesystem::directory_iterator(dir,ec)) {
            const auto name=entry.path().filename().wstring();
            if(name.rfind(L"ggml-cpu-",0)!=0||entry.path().extension()!=L".dll")continue;
            HMODULE module=LoadLibraryExW(entry.path().c_str(),nullptr,search);
            if(!module)continue;
            const auto score=reinterpret_cast<score_fn>(GetProcAddress(module,"ggml_backend_score"));
            const int s=score?score():0;
            if(s>best_score){best_score=s;best=entry.path();}
            FreeLibrary(module);
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
