#include "uia_text.hpp"
#include <UIAutomation.h>
#include <comdef.h>
#include <atlbase.h>
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
    const auto first=s.find_first_not_of(L" \t\r\n ");if(first==std::wstring::npos)return {};
    const auto last=s.find_last_not_of(L" \t\r\n ");return s.substr(first,last-first+1);
}

struct Walker {
    CComPtr<IUIAutomation> uia;CComPtr<IUIAutomationTreeWalker> walker;CComPtr<IUIAutomationCacheRequest> cache;
    const UiaBudget& budget;UiaText& out;ULONGLONG deadline;std::wstring last_line;

    bool over() {
        if(out.nodes>=budget.max_nodes||out.text.size()>=budget.max_chars||GetTickCount64()>deadline){out.truncated=true;return true;}
        return false;
    }
    void add(const std::wstring& raw) {
        auto line=trimmed(raw);if(line.empty()||line==last_line)return;
        if(out.text.size()+line.size()+1>budget.max_chars){line.resize(budget.max_chars-out.text.size());out.truncated=true;}
        out.text+=line;out.text+=L'\n';last_line=std::move(line);
    }
    void read(IUIAutomationElement* e) {
        BOOL password=FALSE;e->get_CachedIsPassword(&password);
        if(password){++out.password_skipped;return;}
        CONTROLTYPEID type=0;e->get_CachedControlType(&type);
        if(!content_type(type))return;
        CComBSTR name;e->get_CachedName(&name);
        if(type==UIA_EditControlTypeId||type==UIA_DocumentControlTypeId) {
            CComPtr<IUIAutomationTextPattern> text;
            if(SUCCEEDED(e->GetCachedPatternAs(UIA_TextPatternId,__uuidof(IUIAutomationTextPattern),reinterpret_cast<void**>(&text)))&&text) {
                CComPtr<IUIAutomationTextRange> range;CComBSTR value;
                const int room=static_cast<int>(budget.max_chars-out.text.size());
                if(room>0&&SUCCEEDED(text->get_DocumentRange(&range))&&range&&SUCCEEDED(range->GetText(room,&value))&&value){add(bstr(value));return;}
            }
            CComVariant value;
            if(SUCCEEDED(e->GetCachedPropertyValue(UIA_ValueValuePropertyId,&value))&&value.vt==VT_BSTR&&value.bstrVal){add(std::wstring(value.bstrVal,SysStringLen(value.bstrVal)));return;}
        }
        add(bstr(name));
    }
    void walk(IUIAutomationElement* e,int depth) {
        if(over()||depth>budget.max_depth)return;
        ++out.nodes;
        BOOL offscreen=FALSE;e->get_CachedIsOffscreen(&offscreen);
        BOOL password=FALSE;e->get_CachedIsPassword(&password);
        if(password){++out.password_skipped;return;}  // never descend into a password element
        if(offscreen)++out.offscreen;else read(e);
        CComPtr<IUIAutomationElement> child;
        if(FAILED(walker->GetFirstChildElementBuildCache(e,cache,&child)))return;
        while(child&&!over()) {
            walk(child,depth+1);
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
    for(PROPERTYID p:{UIA_NamePropertyId,UIA_ControlTypePropertyId,UIA_IsPasswordPropertyId,UIA_IsOffscreenPropertyId,UIA_ValueValuePropertyId})cache->AddProperty(p);
    cache->AddPattern(UIA_TextPatternId);
    CComPtr<IUIAutomationTreeWalker> walker;if(FAILED(uia->get_ControlViewWalker(&walker)))return out;
    CComPtr<IUIAutomationElement> root;
    if(FAILED(uia->ElementFromHandleBuildCache(window,cache,&root))||!root)return out;
    out.available=true;
    Walker w{uia,walker,cache,budget,out,GetTickCount64()+budget.max_ms,{}};
    w.walk(root,0);
    return out;
}
}
