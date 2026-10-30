// macOS text extraction for one AX window (docs/LENS_V1_SPEC.md §5: the accessibility tree first, OCR only as the
// fallback), the same contract as uia_text.cpp: depth-first under node, depth, character and time budgets; elements
// whose frame lies outside the window are skipped with their subtree; text areas contribute only their visible
// character range (kAXVisibleCharacterRangeAttribute) when they report one; secure text fields (password entry,
// AXSecureTextField) and their subtrees are never read; other elements contribute their value or title.
#import <Foundation/Foundation.h>
#include "uia_text.hpp"
#include "ax_registry.hpp"
#include <algorithm>
#include <chrono>
#include <string>

namespace lens::observe {
namespace {
std::string str(CFTypeRef v){if(!v||CFGetTypeID(v)!=CFStringGetTypeID())return {};const char* c=[(__bridge NSString*)v UTF8String];return c?c:"";}
CFTypeRef copy(AXUIElementRef e,CFStringRef attr){CFTypeRef v=nullptr;return AXUIElementCopyAttributeValue(e,attr,&v)==kAXErrorSuccess?v:nullptr;}
std::string attr(AXUIElementRef e,CFStringRef a){CFTypeRef v=copy(e,a);auto s=str(v);if(v)CFRelease(v);return s;}
bool frame_of(AXUIElementRef e,CGRect& r) {
    CFTypeRef p=copy(e,kAXPositionAttribute),s=copy(e,kAXSizeAttribute);CGPoint pt{};CGSize sz{};
    const bool ok=p&&s&&AXValueGetValue(static_cast<AXValueRef>(p),static_cast<AXValueType>(kAXValueCGPointType),&pt)&&
                  AXValueGetValue(static_cast<AXValueRef>(s),static_cast<AXValueType>(kAXValueCGSizeType),&sz);
    if(p)CFRelease(p);if(s)CFRelease(s);if(ok)r=CGRectMake(pt.x,pt.y,sz.width,sz.height);return ok;
}
struct Walk {
    const UiaBudget& budget;UiaText& out;std::chrono::steady_clock::time_point deadline;CGRect area;std::string text,last;
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
    void lines(const std::string& s){size_t at=0,p;while((p=s.find('\n',at))!=std::string::npos){line(s.substr(at,p-at));at=p+1;}line(s.substr(at));}
    // A text area's visible part only, when the application reports it (never the whole document or scroll-back).
    bool visible_text(AXUIElementRef e) {
        CFTypeRef range=copy(e,kAXVisibleCharacterRangeAttribute);if(!range)return false;
        CFTypeRef value=nullptr;
        const bool ok=AXUIElementCopyParameterizedAttributeValue(e,kAXStringForRangeParameterizedAttribute,range,&value)==kAXErrorSuccess;
        CFRelease(range);if(ok){lines(str(value));++out.visible_ranges;}if(value)CFRelease(value);return ok;
    }
    void visit(AXUIElementRef e,int depth) {
        if(over()||depth>budget.max_depth)return;
        ++out.nodes;
        const auto role=attr(e,kAXRoleAttribute),subrole=attr(e,kAXSubroleAttribute);
        if(subrole=="AXSecureTextField"||role=="AXSecureTextField"){++out.password_skipped;return;}
        if(depth>0){CGRect r;if(frame_of(e,r)&&!CGRectIntersectsRect(r,area)){++out.offscreen;++out.pruned;return;}}
        const bool text_role=role=="AXTextArea"||role=="AXTextField"||role=="AXStaticText"||role=="AXWebArea";
        if(role=="AXTextArea"&&visible_text(e))return;  // its children are its text
        CFTypeRef v=copy(e,text_role?kAXValueAttribute:kAXTitleAttribute);
        if(v){lines(str(v));CFRelease(v);}
        if(role=="AXTextArea"||role=="AXTextField")return;
        CFTypeRef children=copy(e,kAXChildrenAttribute);
        if(children&&CFGetTypeID(children)==CFArrayGetTypeID()) {
            const auto n=CFArrayGetCount(static_cast<CFArrayRef>(children));
            for(CFIndex i=0;i<n&&!over();++i)visit(static_cast<AXUIElementRef>(CFArrayGetValueAtIndex(static_cast<CFArrayRef>(children),i)),depth+1);
        }
        if(children)CFRelease(children);
    }
};
}
UiaText extract_window_text(Window id,const UiaBudget& budget) {
    UiaText out;AXUIElementRef w=ax_window(id);if(!w)return out;
    AXUIElementSetMessagingTimeout(w,0.5f);  // a hung application never blocks the observer for long
    out.available=true;CGRect area=CGRectInfinite;frame_of(w,area);
    Walk walk{budget,out,std::chrono::steady_clock::now()+std::chrono::milliseconds(budget.max_ms),area};
    walk.visit(w,0);out.text=wide(walk.text);return out;
}
}
