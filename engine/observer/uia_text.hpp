#pragma once
// UI Automation text extraction for one top-level window (docs/LENS_V1_SPEC.md §5: UIA first, OCR only as fallback).
// Walks the control view depth-first with cached properties under node, depth, character and time budgets.
// Visible text only: an element is read only when its bounding rectangle intersects the visible area (the window on
// the screen, narrowed by every ancestor that clips its children: native child windows and scroll containers), and
// subtrees entirely outside it are not walked. Edit/document elements with a TextPattern contribute only their visible
// ranges (never the whole document or scroll-back) and their subtree is not walked again.
// Password elements (UIA IsPassword) and their subtrees are never read; elements UIA reports off-screen are skipped.
#include "os_window.hpp"
#include <string>

namespace lens::observe {
struct UiaBudget {int max_nodes=4000;int max_depth=48;size_t max_chars=8000;unsigned max_ms=300;};
struct UiaText {
    std::wstring text;          // visible text, one line per element (or text line), consecutive duplicates removed
    int nodes=0;                // elements visited
    int password_skipped=0;     // password elements whose content was not read
    int offscreen=0;            // elements skipped because they are off-screen or outside the visible area
    int pruned=0;               // subtrees not walked because they lie entirely outside the visible area
    int visible_ranges=0;       // TextPattern visible ranges read
    bool truncated=false;       // a budget stopped the walk early
    bool timed_out=false;       // the time budget stopped it (the text is a partial, unreliable view)
    bool available=false;       // UIA returned an element for the window
};
// Requires init_thread() on the calling thread. Windows: UI Automation (uia_text.cpp); Linux: AT-SPI (uia_text_atspi.cpp).
UiaText extract_window_text(Window window,const UiaBudget& budget);
}
