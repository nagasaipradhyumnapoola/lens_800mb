// Diagnostic integration of the unmodified upstream C API, not a new inference engine.
#include "whisper.h"
#include "common-whisper.h"
#include "ggml_cpu_dispatch.hpp"
#include <windows.h>
#include <psapi.h>
#include <iostream>
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

int main(int argc, char** argv) {
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
