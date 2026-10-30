// Linux text extraction for one AT-SPI frame (docs/LENS_V1_SPEC.md §5: the accessibility tree first, OCR only as the
// fallback). Depth-first walk under node, depth, character and time budgets, the same contract as uia_text.cpp:
// - visible text only: an element without the SHOWING state (scrolled away, hidden, another tab) is skipped with its
//   subtree; text elements contribute the ranges inside the frame's on-screen area where the toolkit reports them
//   (atspi_text_get_bounded_ranges), otherwise their text up to the character budget;
// - password fields (role PASSWORD_TEXT) and their subtrees are never read;
// - other elements contribute their accessible name (labels, buttons, list items); consecutive duplicates are dropped.
#include "uia_text.hpp"
#include "atspi_registry.hpp"
#include <algorithm>
#include <chrono>
#include <string>

namespace lens::observe {
namespace {
struct Walk {
    const UiaBudget& budget;UiaText& out;std::chrono::steady_clock::time_point deadline;std::string text,last;
    AtspiRect area{};bool have_area=false;
    bool over() {
        if(std::chrono::steady_clock::now()>deadline){out.timed_out=out.truncated=true;return true;}
        if(out.nodes>=budget.max_nodes||text.size()>=budget.max_chars){out.truncated=true;return true;}
        return false;
    }
    void line(std::string s) {
        while(!s.empty()&&(s.back()==' '||s.back()=='\n'||s.back()=='\r'||s.back()=='\t'))s.pop_back();
        size_t a=0;while(a<s.size()&&(s[a]==' '||s[a]=='\t'))++a;s.erase(0,a);
        if(s.empty()||s==last)return;
        if(text.size()+s.size()+1>budget.max_chars){s.resize(budget.max_chars>text.size()+1?budget.max_chars-text.size()-1:0);out.truncated=true;}
        if(s.empty())return;
        text+=s;text+='\n';last=s;
    }
    static bool showing(AtspiAccessible* a) {
        AtspiStateSet* set=atspi_accessible_get_state_set(a);if(!set)return false;
        const bool r=atspi_state_set_contains(set,ATSPI_STATE_SHOWING);g_object_unref(set);return r;
    }
    // Text inside the frame's on-screen area when the toolkit supports bounded ranges; whole text (capped) otherwise.
    void read_text(AtspiText* t) {
        GError* e=nullptr;const int count=atspi_text_get_character_count(t,&e);if(e){g_clear_error(&e);return;}
        if(count<=0)return;
        if(have_area) {
            GArray* ranges=atspi_text_get_bounded_ranges(t,area.x,area.y,area.width,area.height,ATSPI_COORD_TYPE_SCREEN,
                                                        ATSPI_TEXT_CLIP_BOTH,ATSPI_TEXT_CLIP_BOTH,&e);
            if(e)g_clear_error(&e);
            if(ranges&&ranges->len>0) {
                for(guint i=0;i<ranges->len;++i) {
                    auto* r=g_array_index(ranges,AtspiTextRange*,i);
                    if(r&&r->content){std::string s(r->content);size_t p;while((p=s.find('\n'))!=std::string::npos){line(s.substr(0,p));s.erase(0,p+1);}line(s);}
                    if(r){g_free(r->content);g_free(r);}
                    ++out.visible_ranges;
                }
                g_array_free(ranges,TRUE);return;
            }
            if(ranges)g_array_free(ranges,TRUE);
        }
        const int end=std::min(count,static_cast<int>(budget.max_chars));
        gchar* raw=atspi_text_get_text(t,0,end,&e);if(e)g_clear_error(&e);
        if(raw){std::string s(raw);g_free(raw);size_t p;while((p=s.find('\n'))!=std::string::npos){line(s.substr(0,p));s.erase(0,p+1);}line(s);}
    }
    void visit(AtspiAccessible* a,int depth) {
        if(over()||depth>budget.max_depth)return;
        ++out.nodes;GError* e=nullptr;
        const AtspiRole role=atspi_accessible_get_role(a,&e);if(e)g_clear_error(&e);
        if(role==ATSPI_ROLE_PASSWORD_TEXT){++out.password_skipped;return;}
        if(depth>0&&!showing(a)){++out.offscreen;++out.pruned;return;}
        if(AtspiText* t=atspi_accessible_get_text_iface(a)) {
            read_text(t);g_object_unref(t);
            if(role==ATSPI_ROLE_TEXT||role==ATSPI_ROLE_ENTRY||role==ATSPI_ROLE_DOCUMENT_TEXT||role==ATSPI_ROLE_TERMINAL)return;  // its children are its text
        } else {  // the frame's own name is the window title, as UI Automation reports it on Windows
            gchar* name=atspi_accessible_get_name(a,&e);if(e)g_clear_error(&e);
            if(name){line(name);g_free(name);}
        }
        const int n=atspi_accessible_get_child_count(a,&e);if(e){g_clear_error(&e);return;}
        for(int i=0;i<n&&!over();++i) {
            AtspiAccessible* c=atspi_accessible_get_child_at_index(a,i,&e);if(e)g_clear_error(&e);
            if(c){visit(c,depth+1);g_object_unref(c);}
        }
    }
};
}
UiaText extract_window_text(Window id,const UiaBudget& budget) {
    UiaText out;AtspiAccessible* frame=atspi_frame(id);if(!frame)return out;
    out.available=true;
    Walk w{budget,out,std::chrono::steady_clock::now()+std::chrono::milliseconds(budget.max_ms)};
    if(AtspiComponent* c=atspi_accessible_get_component_iface(frame)) {
        GError* e=nullptr;AtspiRect* r=atspi_component_get_extents(c,ATSPI_COORD_TYPE_SCREEN,&e);if(e)g_clear_error(&e);
        if(r){w.area=*r;w.have_area=r->width>0&&r->height>0;g_free(r);}
        g_object_unref(c);
    }
    w.visit(frame,0);
    out.text=wide(w.text);return out;
}
}
