#pragma once
// Operating-system side of lens-observer: which window the user is looking at, whose process it belongs to, whether the
// OS lets it be read, and the observer's own CPU accounting. Windows: Win32 + DWM (os_window_win.cpp). Linux: AT-SPI
// frames on the accessibility bus and /proc (os_window_linux.cpp). The capture loop (observer_main.cpp) is shared.
#include <cstdint>
#include <filesystem>
#include <optional>
#include <string>

namespace lens::observe {
using Window=std::uintptr_t;  // HWND on Windows; an AT-SPI frame elsewhere (valid until the next foreground query)
struct WindowInfo {Window id=0;std::wstring title,process;long pid=0;};

bool init_thread();    // per-thread OS state the text extractor needs (COM on Windows; the AT-SPI connection on Linux)
void uninit_thread();
void lower_priority(); // background work never competes with the user's applications (workers inherit it)
std::optional<WindowInfo> foreground_window();
std::optional<WindowInfo> window_for_pid(long pid);  // the process's main visible top-level window
std::string os_privacy_block(Window w);  // "not_visible" | "capture_protected" | "" (OS-level checks only)
long current_pid();
unsigned long long process_cpu_ms();
unsigned long long thread_cpu_ms();
unsigned long long tick_ms();            // monotonic milliseconds
std::string utc_now();                   // ISO-8601 UTC with milliseconds
std::string utf8(const std::wstring& w);
std::wstring wide(const std::string& s);
std::filesystem::path worker_path(const char* name);  // a sibling executable (lens-ocr)
}
