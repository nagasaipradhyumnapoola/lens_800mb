#pragma once
// OCR fallback support for lens-observer (docs/LENS_V1_SPEC.md §4–5): in-memory window capture, changed-region detection
// and a one-request call into the native OCR worker. Frames are never written to disk.
#include "os_window.hpp"
#include <optional>
#include <string>
#include <vector>

namespace lens::observe {
struct Frame {int w=0,h=0;std::vector<unsigned char> bgr;};  // 24-bit BGR, top-down rows
struct Rect {int x=0,y=0,w=0,h=0;};

// Renders the window's own content (PrintWindow, full-content first). Empty frame when capture fails or is blank.
Frame capture_window(Window window);  // Windows: PrintWindow; Linux: the frame's screen area from the X server
// Bounding box of 32x32 tiles that differ; nullopt when nothing changed. Different sizes count as a full change.
std::optional<Rect> changed_region(const Frame& before,const Frame& after);
// 24-bit BMP file bytes, base64-encoded (the OCR worker decodes them in memory).
std::string bmp_base64(const Frame& f);

// A long-lived `<exe> --serve` worker answering one JSON line per request line. Started on first use; a request that
// exceeds its timeout kills the worker (the next request starts a new one). stop() closes stdin so the worker exits.
class ServeWorker {
public:
    explicit ServeWorker(std::filesystem::path exe):exe_(std::move(exe)) {}
    ~ServeWorker(){stop();}
    ServeWorker(const ServeWorker&)=delete;ServeWorker& operator=(const ServeWorker&)=delete;
    std::optional<std::string> request(const std::string& line,unsigned timeout_ms);
    void stop();
    bool running() const {return process_!=0;}
    unsigned long long last_used() const {return last_used_;}
    unsigned long long cpu_ms() const;  // CPU time of every worker process this object has run (kernel + user)
private:
    bool start();
    std::filesystem::path exe_;std::uintptr_t process_=0,in_=0,out_=0;  // HANDLEs on Windows; pid and fds elsewhere
    std::string buffer_;unsigned long long last_used_=0,finished_cpu_ms_=0;
};
}
