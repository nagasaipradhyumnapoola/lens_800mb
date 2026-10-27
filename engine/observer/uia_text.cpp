#include "uia_text.hpp"
#include <UIAutomation.h>
#include <comdef.h>
#include <atlbase.h>
#include <algorithm>
#include <optional>
#include <vector>

namespace lens::observe {
namespace {
bool content_type(CONTROLTYPEID t) {
    switch(t) {
    case UIA_TextControlTypeId: case UIA_EditControlTypeId: case UIA_DocumentControlTypeId: case UIA_HyperlinkControlTypeId:
    case UIA_ListItemControlTypeId: case UIA_TreeItemControlTypeId: case UIA_DataItemControlTypeId: case UIA_HeaderItemControlTypeId:
    case UIA_TabItemControlTypeId: case UIA_TitleBarControlTypeId: return true;
    default: return false;
    }
}
std::wstring bstr(const CComBSTR& b){return b?std::wstring(b,SysStringLen(b)):std::wstring();}
std::wstring trimmed(std::wstring s) {
    const auto first=s.find_first_not_of(L" \t\r\n ");if(first==std::wstring::npos)return {};
    const auto last=s.find_last_not_of(L" \t\r\n ");return s.substr(first,last-first+1);
}
bool empty(const RECT& r){return r.right<=r.left||r.bottom<=r.top;}
RECT intersect(const RECT& a,const RECT& b){return {std::max(a.left,b.left),std::max(a.top,b.top),std::min(a.right,b.right),std::min(a.bottom,b.bottom)};}

struct Walker {
    CComPtr<IUIAutomation> uia;CComPtr<IUIAutomationTreeWalker> walker;CComPtr<IUIAutomationCacheRequest> cache;
    const UiaBudget& budget;UiaText& out;ULONGLONG deadline;std::wstring last_line;

    bool over() {
        if(GetTickCount64()>deadline){out.truncated=out.timed_out=true;return true;}
        if(out.nodes>=budget.max_nodes||out.text.size()>=budget.max_chars){out.truncated=true;return true;}
        return false;
    }
    void add_line(std::wstring line) {
        line=trimmed(std::move(line));if(line.empty()||line==last_line||out.text.size()>=budget.max_chars)return;
        if(out.text.size()+line.size()+1>budget.max_chars){line.resize(budget.max_chars-out.text.size());out.truncated=true;}
        out.text+=line;out.text+=L'\n';last_line=std::move(line);
    }
    void add(const std::wstring& raw) {  // one element's text, split into lines
        size_t start=0;
        while(start<=raw.size()) {
            const auto end=raw.find_first_of(L"\r\n\v\x2028\x2029",start);
            add_line(raw.substr(start,end==std::wstring::npos?std::wstring::npos:end-start));
            if(end==std::wstring::npos)break;start=end+1;
        }
    }
    // Visible lines of a native multi-line Edit control: from its first visible line to the first line below its client
    // area, each read with EM_GETLINE (the system marshals these edit messages across processes; 200 ms timeout each).
    static std::optional<std::wstring> native_edit_visible(IUIAutomationElement* e) {
        UIA_HWND raw=nullptr;e->get_CachedNativeWindowHandle(&raw);const auto hwnd=static_cast<HWND>(raw);
        wchar_t cls[32]{};if(!hwnd||!GetClassNameW(hwnd,cls,32)||_wcsicmp(cls,L"Edit")!=0)return std::nullopt;
        if(!(GetWindowLongPtrW(hwnd,GWL_STYLE)&ES_MULTILINE))return std::nullopt;
        auto send=[&](UINT m,WPARAM wp,LPARAM lp=0)->std::optional<LRESULT> {
            DWORD_PTR r=0;if(!SendMessageTimeoutW(hwnd,m,wp,lp,SMTO_ABORTIFHUNG|SMTO_BLOCK,200,&r))return std::nullopt;return static_cast<LRESULT>(r);
        };
        RECT client{};if(!GetClientRect(hwnd,&client))return std::nullopt;
        const auto first=send(EM_GETFIRSTVISIBLELINE,0),count=send(EM_GETLINECOUNT,0);if(!first||!count)return std::nullopt;
        std::wstring out;std::vector<wchar_t> buf(1024);
        for(LRESULT line=*first;line<*count&&line<*first+200;++line) {
            if(line>*first) {
                const auto index=send(EM_LINEINDEX,static_cast<WPARAM>(line));if(!index||*index<0)break;
                const auto pos=send(EM_POSFROMCHAR,static_cast<WPARAM>(*index));if(!pos)break;
                if(static_cast<short>(HIWORD(*pos))>=client.bottom)break;
            }
            *reinterpret_cast<WORD*>(buf.data())=static_cast<WORD>(buf.size()-1);
            const auto n=send(EM_GETLINE,static_cast<WPARAM>(line),reinterpret_cast<LPARAM>(buf.data()));if(!n)break;
            out.append(buf.data(),static_cast<size_t>(std::clamp<LRESULT>(*n,0,static_cast<LRESULT>(buf.size()-1))));out+=L'\n';
        }
        return out;
    }
    // Reads one visible element. Returns true when its text pattern already covered the whole subtree.
    bool read(IUIAutomationElement* e) {
        CONTROLTYPEID type=0;e->get_CachedControlType(&type);
        if(!content_type(type))return false;
        CComBSTR name;e->get_CachedName(&name);
        if(type==UIA_EditControlTypeId||type==UIA_DocumentControlTypeId) {
            CComPtr<IUIAutomationTextPattern> text;
            if(SUCCEEDED(e->GetCachedPatternAs(UIA_TextPatternId,__uuidof(IUIAutomationTextPattern),reinterpret_cast<void**>(&text)))&&text) {
                CComPtr<IUIAutomationTextRangeArray> ranges;int n=0;
                if(SUCCEEDED(text->GetVisibleRanges(&ranges))&&ranges&&SUCCEEDED(ranges->get_Length(&n))&&n>0) {
                    const auto before=out.text.size();
                    for(int i=0;i<n&&!over();++i) {
                        CComPtr<IUIAutomationTextRange> range;CComBSTR value;
                        const int room=static_cast<int>(budget.max_chars-out.text.size());
                        if(SUCCEEDED(ranges->GetElement(i,&range))&&range&&SUCCEEDED(range->GetText(room,&value))&&value){add(bstr(value));++out.visible_ranges;}
                    }
                    if(out.text.size()>before)return true;  // otherwise try the fallbacks below
                }
            }
            // No visible-range support: a native multi-line edit control reports its visible lines; a single-line value
            // is visible as a whole; another multi-line value may hold scroll-back, so only its first lines (bounded by
            // the element's height) are read.
            if(const auto visible=native_edit_visible(e)){add(*visible);return true;}
            CComVariant value;std::optional<std::wstring> full;
            if(SUCCEEDED(e->GetCachedPropertyValue(UIA_ValueValuePropertyId,&value))&&value.vt==VT_BSTR&&value.bstrVal)
                full=std::wstring(value.bstrVal,SysStringLen(value.bstrVal));
            if((!full||full->empty())&&text) {  // multi-line edits expose their text only through the document range
                CComPtr<IUIAutomationTextRange> range;CComBSTR doc;
                if(SUCCEEDED(text->get_DocumentRange(&range))&&range&&SUCCEEDED(range->GetText(1<<20,&doc))&&doc)full=bstr(doc);
            }
            if(full) {
                std::wstring v=std::move(*full);
                RECT r{};e->get_CachedBoundingRectangle(&r);
                const auto max_lines=static_cast<size_t>(std::max<LONG>(1,(r.bottom-r.top)/14));size_t lines=0,cut=0;
                while(cut<v.size()&&lines<max_lines){cut=v.find(L'\n',cut);if(cut==std::wstring::npos){cut=v.size();break;}++cut;++lines;}
                if(cut<v.size()){v.resize(cut);out.truncated=true;}
                add(v);return true;
            }
        }
        add(bstr(name));return false;
    }
    // Native child windows and scroll containers clip what their descendants show.
    static bool clips(IUIAutomationElement* e) {
        UIA_HWND hwnd=nullptr;e->get_CachedNativeWindowHandle(&hwnd);
        CComVariant scroll;e->GetCachedPropertyValue(UIA_IsScrollPatternAvailablePropertyId,&scroll);
        return hwnd||(scroll.vt==VT_BOOL&&scroll.boolVal);
    }
    void walk(IUIAutomationElement* e,int depth,RECT clip) {
        if(over()||depth>budget.max_depth)return;
        ++out.nodes;
        BOOL password=FALSE;e->get_CachedIsPassword(&password);
        if(password){++out.password_skipped;return;}  // never descend into a password element
        RECT r{};e->get_CachedBoundingRectangle(&r);
        // An element entirely outside the visible area shows nothing, and nor does anything below it.
        if(!empty(r)&&empty(intersect(r,clip))){++out.offscreen;++out.pruned;return;}
        BOOL offscreen=FALSE;e->get_CachedIsOffscreen(&offscreen);
        if(empty(r)||offscreen)++out.offscreen;
        else if(read(e))return;
        if(!empty(r)&&depth>0&&clips(e))clip=intersect(clip,r);
        CComPtr<IUIAutomationElement> child;
        if(FAILED(walker->GetFirstChildElementBuildCache(e,cache,&child)))return;
        while(child&&!over()) {
            walk(child,depth+1,clip);
            CComPtr<IUIAutomationElement> next;
            if(FAILED(walker->GetNextSiblingElementBuildCache(child,cache,&next)))break;
            child=next;
        }
    }
};
}

UiaText extract_window_text(HWND window,const UiaBudget& budget) {
    UiaText out;
    CComPtr<IUIAutomation> uia;
    if(FAILED(uia.CoCreateInstance(__uuidof(CUIAutomation),nullptr,CLSCTX_INPROC_SERVER))||!uia)return out;
    CComPtr<IUIAutomationCacheRequest> cache;if(FAILED(uia->CreateCacheRequest(&cache)))return out;
    for(PROPERTYID p:{UIA_NamePropertyId,UIA_ControlTypePropertyId,UIA_IsPasswordPropertyId,UIA_IsOffscreenPropertyId,UIA_ValueValuePropertyId,
                      UIA_BoundingRectanglePropertyId,UIA_NativeWindowHandlePropertyId,UIA_IsScrollPatternAvailablePropertyId})cache->AddProperty(p);
    cache->AddPattern(UIA_TextPatternId);
    CComPtr<IUIAutomationTreeWalker> walker;if(FAILED(uia->get_ControlViewWalker(&walker)))return out;
    CComPtr<IUIAutomationElement> root;
    if(FAILED(uia->ElementFromHandleBuildCache(window,cache,&root))||!root)return out;
    out.available=true;
    // The visible area starts as the window's rectangle on the virtual screen (both in UIA's physical coordinates).
    RECT clip{};root->get_CachedBoundingRectangle(&clip);
    const RECT screen{GetSystemMetrics(SM_XVIRTUALSCREEN),GetSystemMetrics(SM_YVIRTUALSCREEN),
                      GetSystemMetrics(SM_XVIRTUALSCREEN)+GetSystemMetrics(SM_CXVIRTUALSCREEN),GetSystemMetrics(SM_YVIRTUALSCREEN)+GetSystemMetrics(SM_CYVIRTUALSCREEN)};
    if(empty(clip))clip=screen;else clip=intersect(clip,screen);
    Walker w{uia,walker,cache,budget,out,GetTickCount64()+budget.max_ms,{}};
    w.walk(root,0,clip);
    return out;
}
}
