#pragma once
// UI Automation text extraction for one top-level window (docs/LENS_V1_SPEC.md §5: UIA first, OCR only as fallback).
// Walks the control view depth-first with cached properties under node, depth, character and time budgets.
// Password elements (UIA IsPassword) and their subtrees are never read; off-screen elements are skipped.
#include <windows.h>
#include <string>

namespace lens::observe {
struct UiaBudget {int max_nodes=4000;int max_depth=48;size_t max_chars=32000;DWORD max_ms=400;};
struct UiaText {
    std::wstring text;          // visible text, one element per line, consecutive duplicates removed
    int nodes=0;                // elements visited
    int password_skipped=0;     // password elements whose content was not read
    int offscreen=0;            // elements skipped because UIA reports them off-screen
    bool truncated=false;       // a budget stopped the walk early
    bool available=false;       // UIA returned an element for the window
};
// Requires COM initialised on the calling thread (COINIT_MULTITHREADED).
UiaText extract_window_text(HWND window,const UiaBudget& budget);
}
