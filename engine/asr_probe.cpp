// Diagnostic integration of the unmodified upstream C API, not a new inference engine.
#include "whisper.h"
#include "common-whisper.h"
#include "ggml_cpu_dispatch.hpp"
#include <windows.h>
#include <psapi.h>
#include <iostream>
#include <string>
#include <memory>
#include <vector>

static void snapshot(const char* stage) {
    PROCESS_MEMORY_COUNTERS_EX m{};
    m.cb = sizeof(m);
    if (GetProcessMemoryInfo(GetCurrentProcess(), reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&m), sizeof(m))) {
        std::cout << stage << " working_set=" << m.WorkingSetSize << " private=" << m.PrivateUsage
                  << " peak_working_set=" << m.PeakWorkingSetSize << " peak_commit=" << m.PeakPagefileUsage << '\n';
    }
}

// --lid <model>: one audio path per stdin line; prints whisper's probability for every language as one JSON line each
// (language-identification calibration in scripts/benchmark_voice.py; the model is loaded once).
static int identify(const char* model) {
    const auto& cpu = lens::ensure_ggml_cpu_backend();
    if (!cpu.ready) return 7;
    auto cp = whisper_context_default_params();
    cp.use_gpu = false;
    std::unique_ptr<whisper_context, decltype(&whisper_free)> ctx(whisper_init_from_file_with_params(model, cp), whisper_free);
    if (!ctx) return 3;
    std::vector<float> probs(static_cast<size_t>(whisper_lang_max_id() + 1));
    std::string path;
    while (std::getline(std::cin, path)) {
        if (path.empty()) continue;
        std::vector<float> pcm;
        std::vector<std::vector<float>> stereo;
        std::string escaped;
        for (char c : path) { if (c == '\\' || c == '"') escaped += '\\'; escaped += c; }
        if (!read_audio_data(path, pcm, stereo, false) || whisper_pcm_to_mel(ctx.get(), pcm.data(), static_cast<int>(pcm.size()), 4) ||
            whisper_lang_auto_detect(ctx.get(), 0, 4, probs.data()) < 0) {
            std::cout << "{\"file\":\"" << escaped << "\",\"error\":true}\n";
            continue;
        }
        std::cout << "{\"file\":\"" << escaped << "\",\"p\":{";
        for (int i = 0; i <= whisper_lang_max_id(); ++i) std::cout << (i ? "," : "") << '"' << whisper_lang_str(i) << "\":" << probs[static_cast<size_t>(i)];
        std::cout << "}}\n" << std::flush;
    }
    return 0;
}

int main(int argc, char** argv) {
    if (argc == 3 && std::string(argv[1]) == "--lid") return identify(argv[2]);
    if (argc < 3) return 2;
    snapshot("before");
    const auto& cpu = lens::ensure_ggml_cpu_backend();
    if (!cpu.ready) return 7;
    std::cout << "cpu_backend=" << cpu.variant << '\n';
    auto cp = whisper_context_default_params();
    cp.use_gpu = false;
    std::unique_ptr<whisper_context, decltype(&whisper_free)> ctx(
        whisper_init_from_file_with_params_no_state(argv[1], cp), whisper_free);
    if (!ctx) return 3;
    snapshot("model-loaded-no-state");
    std::unique_ptr<whisper_state, decltype(&whisper_free_state)> state(whisper_init_state(ctx.get()), whisper_free_state);
    if (!state) return 4;
    snapshot("state-created");
    std::vector<float> pcm;
    std::vector<std::vector<float>> stereo;
    if (!read_audio_data(argv[2], pcm, stereo, false)) return 5;
    snapshot("audio-decoded");
    auto params = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
    params.n_threads = 4;
    params.greedy.best_of = 1;
    params.print_progress = params.print_realtime = params.print_timestamps = false;
    params.language = argc > 3 ? argv[3] : "en";
    if (whisper_full_with_state(ctx.get(), state.get(), params, pcm.data(), static_cast<int>(pcm.size()))) return 6;
    snapshot("inference-done");
    for (int i=0;i<whisper_full_n_segments_from_state(state.get());++i)
        std::cout << whisper_full_get_segment_text_from_state(state.get(),i);
    std::cout << '\n';
    state.reset(); ctx.reset();
    snapshot("unloaded");
}
