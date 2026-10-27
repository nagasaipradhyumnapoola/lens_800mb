// lens-observer: consent-gated Windows screen-text observer (docs/LENS_V1_SPEC.md §3–5, §15; Milestone 3).
// Emits one engine `add` request (JSON line) on stdout per new piece of window content, so
// `lens-observer --consent | lens-engine --db ...` stores observations in the encrypted memory. UI Automation text of
// the visible area first, OCR of changed regions as the fallback. Never reads password elements, excluded processes,
// private-browsing windows or capture-protected windows. Control on stdin: pause | resume | status | stop (or
// {"op":...}); EOF stops. Diagnostics go to stderr as JSON and never contain window text or titles.
// Real-screen behaviour (fixes from the 2026-10-27 owner-consented run):
// - settle: content that keeps changing (streaming text) is captured once it has been stable for settle_ms, or after
//   max_settle_ms at the latest; a window that keeps hitting that bound backs off (longer bound, slower polling).
// - delta: per window, a fingerprint of stored lines; a capture stores only new lines (capture_mode "delta", linked to
//   the window's previous and base captures), tiny deltas and near-duplicate re-renders are not stored, and a full
//   "snapshot" is taken on the first capture, a document (title) change, or every full_snapshot_ms.
// - each stored text is capped at max_capture_chars (metadata.truncated records a cut) and labelled with a language.
// - CPU: below-normal priority, polling stretched to keep extraction under ~5% duty, and a throttle that slows every
//   interval while the observer's own CPU use exceeds cpu_budget_percent of one core.
// --identify-language: reads {"text":...} lines on stdin, writes the language label of each (no capture, no consent).
#include "uia_text.hpp"
#include "screen_capture.hpp"
#include "capture_delta.hpp"
#include "language_id.hpp"
#include <windows.h>
#include <bcrypt.h>
#include <dwmapi.h>
#include <nlohmann/json.hpp>
#include <psapi.h>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <fstream>
#include <iostream>
#include <map>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace {
using json=nlohmann::json;
std::string utf8(const std::wstring& w) {
    if(w.empty())return {};
    const int n=WideCharToMultiByte(CP_UTF8,0,w.data(),static_cast<int>(w.size()),nullptr,0,nullptr,nullptr);
    std::string s(n,'\0');WideCharToMultiByte(CP_UTF8,0,w.data(),static_cast<int>(w.size()),s.data(),n,nullptr,nullptr);return s;
}
std::wstring lower(std::wstring s){std::transform(s.begin(),s.end(),s.begin(),[](wchar_t c){return static_cast<wchar_t>(towlower(c));});return s;}
std::string sha256_hex(const std::string& data) {
    BCRYPT_ALG_HANDLE alg=nullptr;BCRYPT_HASH_HANDLE h=nullptr;unsigned char digest[32]{};
    BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,nullptr,0);BCryptCreateHash(alg,&h,nullptr,0,nullptr,0,0);
    BCryptHashData(h,reinterpret_cast<PUCHAR>(const_cast<char*>(data.data())),static_cast<ULONG>(data.size()),0);
    BCryptFinishHash(h,digest,32,0);BCryptDestroyHash(h);BCryptCloseAlgorithmProvider(alg,0);
    static const char* hex="0123456789abcdef";std::string out;for(unsigned char b:digest){out+=hex[b>>4];out+=hex[b&15];}return out;
}
std::string utc_now() {
    SYSTEMTIME t;GetSystemTime(&t);char buf[40];
    std::snprintf(buf,sizeof buf,"%04u-%02u-%02uT%02u:%02u:%02u.%03uZ",t.wYear,t.wMonth,t.wDay,t.wHour,t.wMinute,t.wSecond,t.wMilliseconds);return buf;
}
json language_json(const lens::observe::LanguageGuess& g) {
    return {{"language",g.language},{"script",g.script},{"confidence",std::round(g.confidence*1000)/1000},{"languages",g.languages},
            {"method","lens-lid-rules-v1"}};
}
// The document a window shows, for snapshot decisions: the title without a leading unread counter such as "(3) ".
std::wstring document_identity(const std::wstring& title) {
    if(title.size()>2&&title[0]==L'(') {
        size_t i=1;while(i<title.size()&&iswdigit(title[i]))++i;
        if(i>1&&i+1<title.size()&&title[i]==L')'&&title[i+1]==L' ')return title.substr(i+2);
    }
    return title;
}
unsigned long long process_cpu_ms() {
    FILETIME c,e,k,u;if(!GetProcessTimes(GetCurrentProcess(),&c,&e,&k,&u))return 0;
    auto v=[](const FILETIME& f){return (static_cast<unsigned long long>(f.dwHighDateTime)<<32)|f.dwLowDateTime;};
    return (v(k)+v(u))/10000;
}
unsigned long long thread_cpu_ms() {
    FILETIME c,e,k,u;if(!GetThreadTimes(GetCurrentThread(),&c,&e,&k,&u))return 0;
    auto v=[](const FILETIME& f){return (static_cast<unsigned long long>(f.dwHighDateTime)<<32)|f.dwLowDateTime;};
    return (v(k)+v(u))/10000;
}
std::wstring window_title(HWND w){wchar_t buf[512]{};InternalGetWindowText(w,buf,512);return buf;}
std::wstring process_name(DWORD pid) {
    HANDLE p=OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,FALSE,pid);if(!p)return {};
    wchar_t path[MAX_PATH]{};DWORD size=MAX_PATH;std::wstring name;
    if(QueryFullProcessImageNameW(p,0,path,&size)){name=path;name=name.substr(name.find_last_of(L"\\/")+1);}
    CloseHandle(p);return lower(name);
}

struct Config {
    std::vector<std::wstring> excluded={L"keepass.exe",L"keepassxc.exe",L"1password.exe",L"bitwarden.exe",L"lastpass.exe",L"dashlane.exe",
        L"enpass.exe",L"credentialuibroker.exe",L"consent.exe",L"logonui.exe",L"lockapp.exe",L"lens-observer.exe"};
    std::vector<std::wstring> allowed;  // empty = every non-excluded process
    std::vector<std::wstring> private_markers={L"inprivate",L"incognito",L"private browsing",L"private window",L"navigation privée",
        L"navegación privada",L"privates fenster"};
    int min_interval_ms=1000,max_interval_ms=30000;std::string device="windows-local";
    // OCR fallback (optional): a lens-ocr screen-mode request template (runtime, detector, recognizers, thresholds).
    // Used only when UI Automation yields fewer than min_uia_chars characters beyond the window title.
    json ocr;int min_uia_chars=20;int ocr_idle_ms=30000;  // the OCR worker exits after this long without requests
    int settle_ms=2000,max_settle_ms=12000;               // stable-content wait, and its upper bound
    size_t max_capture_chars=4000;                        // stored text per observation (UTF-8 bytes)
    size_t min_delta_chars=4;                             // smaller deltas are never stored
    double near_duplicate_overlap=0.9;size_t near_duplicate_chars=24;  // re-render (clock, counter, typing indicator):
                                                          // this much overlap and fewer new characters
    int full_snapshot_ms=600000;                          // periodic full snapshot of a window
    double cpu_budget_percent=5.0;                        // the observer's own CPU, percent of one core
};
std::wstring wide(const std::string& s) {
    const int n=MultiByteToWideChar(CP_UTF8,0,s.data(),static_cast<int>(s.size()),nullptr,0);
    std::wstring w(n,L'\0');MultiByteToWideChar(CP_UTF8,0,s.data(),static_cast<int>(s.size()),w.data(),n);return w;
}
void load_config(Config& c,const std::wstring& path) {
    std::ifstream f(path);if(!f)throw std::runtime_error("config_unreadable");
    const auto j=json::parse(f);
    auto list=[&](const char* key,std::vector<std::wstring>& out,bool replace) {
        if(!j.contains(key))return;if(replace)out.clear();
        for(const auto& v:j.at(key))out.push_back(lower(wide(v.get<std::string>())));
    };
    list("excluded_processes",c.excluded,false);list("allowed_processes",c.allowed,true);list("private_title_markers",c.private_markers,false);
    c.min_interval_ms=j.value("min_interval_ms",c.min_interval_ms);c.max_interval_ms=j.value("max_interval_ms",c.max_interval_ms);
    c.device=j.value("device",c.device);
    if(j.contains("ocr"))c.ocr=j.at("ocr");
    c.min_uia_chars=j.value("min_uia_chars",c.min_uia_chars);c.ocr_idle_ms=j.value("ocr_idle_ms",c.ocr_idle_ms);
    c.settle_ms=j.value("settle_ms",c.settle_ms);c.max_settle_ms=j.value("max_settle_ms",c.max_settle_ms);
    c.max_capture_chars=j.value("max_capture_chars",c.max_capture_chars);c.min_delta_chars=j.value("min_delta_chars",c.min_delta_chars);
    c.near_duplicate_overlap=j.value("near_duplicate_overlap",c.near_duplicate_overlap);
    c.near_duplicate_chars=j.value("near_duplicate_chars",c.near_duplicate_chars);
    c.full_snapshot_ms=j.value("full_snapshot_ms",c.full_snapshot_ms);c.cpu_budget_percent=j.value("cpu_budget_percent",c.cpu_budget_percent);
    if(c.max_capture_chars<64||c.settle_ms<0||c.max_settle_ms<c.settle_ms||c.cpu_budget_percent<=0)throw std::runtime_error("invalid_config");
}

// Returns an empty string when the window may be read, otherwise the reason it must not be.
std::string privacy_block(HWND w,const Config& c,const std::wstring& process,const std::wstring& title) {
    if(!w||!IsWindowVisible(w)||IsIconic(w))return "not_visible";
    BOOL cloaked=FALSE;if(SUCCEEDED(DwmGetWindowAttribute(w,DWMWA_CLOAKED,&cloaked,sizeof cloaked))&&cloaked)return "not_visible";
    DWORD affinity=WDA_NONE;if(GetWindowDisplayAffinity(w,&affinity)&&affinity!=WDA_NONE)return "capture_protected";
    DWORD pid=0;GetWindowThreadProcessId(w,&pid);if(pid==GetCurrentProcessId())return "excluded_process";
    if(process.empty())return "process_unknown";
    if(std::find(c.excluded.begin(),c.excluded.end(),process)!=c.excluded.end())return "excluded_process";
    if(!c.allowed.empty()&&std::find(c.allowed.begin(),c.allowed.end(),process)==c.allowed.end())return "not_allowed_process";
    const auto t=lower(title);
    for(const auto& m:c.private_markers)if(!m.empty()&&t.find(m)!=std::wstring::npos)return "private_browsing";
    return {};
}

struct FindPid{DWORD pid;HWND found=nullptr;};
BOOL CALLBACK find_pid_window(HWND w,LPARAM p) {
    auto& f=*reinterpret_cast<FindPid*>(p);DWORD pid=0;GetWindowThreadProcessId(w,&pid);
    if(pid==f.pid&&IsWindowVisible(w)&&!GetWindow(w,GW_OWNER)){f.found=w;return FALSE;}return TRUE;
}

std::mutex out_lock;
void status(const json& j){std::lock_guard g(out_lock);std::cerr<<j.dump()<<'\n';std::cerr.flush();}
}

int identify_language_lines() {
    std::string line;
    while(std::getline(std::cin,line)) {
        json j=json::parse(line,nullptr,false);
        const std::string text=j.is_object()?j.value("text",std::string()):line;
        std::cout<<language_json(lens::observe::identify_language(wide(text))).dump()<<'\n';std::cout.flush();
    }
    return 0;
}

int wmain(int argc,wchar_t** argv) {
    SetConsoleOutputCP(CP_UTF8);
    if(argc==2&&std::wstring(argv[1])==L"--identify-language")return identify_language_lines();
    bool consent=false;std::wstring follow=L"foreground",config_path;Config config;
    for(int i=1;i<argc;++i) {
        const std::wstring a=argv[i];
        if(a==L"--consent")consent=true;
        else if(a==L"--follow"&&i+1<argc)follow=argv[++i];
        else if(a==L"--config"&&i+1<argc)config_path=argv[++i];
        else {std::cerr<<"usage: lens-observer --consent [--follow foreground|pid:<n>] [--config <json>]\n";return 2;}
    }
    if(!consent) {
        std::cerr<<"{\"event\":\"refused\",\"reason\":\"consent_required\"}\nusage: lens-observer --consent [--follow foreground|pid:<n>] [--config <json>]\n";
        return 2;
    }
    DWORD follow_pid=0;
    if(follow.rfind(L"pid:",0)==0){try{follow_pid=static_cast<DWORD>(std::stoul(follow.substr(4)));}catch(...){return 2;}}
    else if(follow!=L"foreground")return 2;
    try{if(!config_path.empty())load_config(config,config_path);}catch(...){std::cerr<<"{\"event\":\"refused\",\"reason\":\"invalid_config\"}\n";return 2;}
    // Background work never competes with the user's foreground applications (the OCR worker inherits the class).
    SetPriorityClass(GetCurrentProcess(),BELOW_NORMAL_PRIORITY_CLASS);
    if(FAILED(CoInitializeEx(nullptr,COINIT_MULTITHREADED)))return 1;

    std::atomic<bool> paused=false,stopping=false,status_requested=false;
    std::thread control([&] {
        std::string line;
        while(!stopping&&std::getline(std::cin,line)) {
            std::string op=line;
            try{const auto j=json::parse(line);if(j.is_object())op=j.value("op",std::string{});}catch(...){}
            op.erase(op.find_last_not_of(" \r\n\t")+1);
            if(op=="pause"){paused=true;status({{"event","paused"}});}
            else if(op=="resume"){paused=false;status({{"event","resumed"}});}
            else if(op=="status")status_requested=true;
            else if(op=="stop")break;
        }
        stopping=true;
    });
    control.detach();

    using clock=std::chrono::steady_clock;using ms=std::chrono::milliseconds;
    status({{"event","started"},{"follow",follow_pid?"pid":"foreground"},{"capture","uia"}});
    std::map<std::string,int> skipped;json last_extract=json::object();
    std::map<std::string,long long> counts;  // records, unchanged, snapshots, deltas, near_duplicates, settle_waits, forced_captures
    std::deque<std::string> recent;HWND last_window=nullptr;std::wstring last_title;
    int interval=config.min_interval_ms;auto next_check=clock::now();
    lens::observe::UiaBudget budget;budget.max_chars=std::max<size_t>(2*config.max_capture_chars,4000);
    lens::observe::Frame previous_frame;HWND previous_frame_window=nullptr;  // last OCR'd frame
    lens::observe::Frame settle_frame;HWND settle_frame_window=nullptr;long long frame_generation=0;  // last checked frame
    std::wstring ocr_exe;
    {std::wstring self(32768,L'\0');self.resize(GetModuleFileNameW(nullptr,self.data(),32768));ocr_exe=self.substr(0,self.find_last_of(L"\\/")+1)+L"lens-ocr.exe";}
    lens::observe::ServeWorker ocr_worker(ocr_exe);
    struct OcrLine {std::string text;int x0,y0,y1;};std::vector<OcrLine> ocr_lines;  // last OCR text of the followed window

    // Per-window state: fingerprint of stored lines, links to the previous and base captures, settle back-off.
    struct WindowState {
        std::string key;std::wstring document;bool stored=false;lens::observe::LineFingerprint seen;
        std::string last_id,snapshot_id;clock::time_point snapshot_at{},used{};int churn=0;uint64_t considered=0;
    };
    std::map<HWND,WindowState> windows;
    auto state_for=[&](HWND w,const std::wstring& process)->WindowState& {
        auto it=windows.find(w);
        if(it==windows.end()) {
            if(windows.size()>=32)windows.erase(std::min_element(windows.begin(),windows.end(),[](const auto& a,const auto& b){return a.second.used<b.second.used;}));
            it=windows.emplace(w,WindowState{}).first;
            it->second.key=sha256_hex(utf8(process)+"\n"+std::to_string(reinterpret_cast<uintptr_t>(w))+"\n"+std::to_string(GetCurrentProcessId())).substr(0,16);
        }
        it->second.used=clock::now();return it->second;
    };
    // Settle: the pending content (by hash) must stay unchanged for settle_ms; max_settle_ms (doubled per consecutive
    // forced capture of the same window, up to 8x) bounds the wait for content that never stops changing.
    struct Pending {bool active=false;uint64_t hash=0;clock::time_point first{},stable{};} pending;
    auto settled=[&](uint64_t hash,WindowState& ws)->bool {
        const auto now=clock::now();
        const auto bound=ms(static_cast<long long>(config.max_settle_ms)<<std::min(ws.churn,3));
        if(!pending.active){pending={true,hash,now,now};if(config.settle_ms>0){++counts["settle_waits"];return false;}pending.active=false;return true;}
        if(pending.hash!=hash){pending.hash=hash;pending.stable=now;}
        else if(now-pending.stable>=ms(config.settle_ms)){pending.active=false;ws.churn=0;return true;}
        if(now-pending.first>=bound){pending.active=false;++ws.churn;++counts["forced_captures"];return true;}
        return false;
    };

    auto emit=[&](const std::string& body,const std::string& context,const std::wstring& process,const std::wstring& title,const json& capture)->std::optional<std::string> {
        const auto digest=sha256_hex(utf8(process)+"\n"+utf8(title)+"\n"+body);
        if(body.size()<3||std::find(recent.begin(),recent.end(),digest)!=recent.end())return std::nullopt;
        recent.push_back(digest);if(recent.size()>256)recent.pop_front();
        // The stored text decides the language; a short delta without evidence borrows the visible text's label.
        auto guess=lens::observe::identify_language(wide(body));
        if(guess.language.rfind("und",0)==0||guess.confidence<0.3) {
            const auto wider=lens::observe::identify_language(wide(context));
            if(wider.language.rfind("und",0)!=0&&wider.confidence>guess.confidence)guess=wider;
        }
        json metadata={{"window_title",utf8(title)},{"language_detail",language_json(guess)}};metadata.update(capture);
        const auto id="obs-"+digest.substr(0,32);
        json request={{"op","add"},{"consent",true},{"id",id},{"text",body},{"language",guess.language},
            {"timestamp",utc_now()},{"device",config.device},{"kind","screen_observation"},{"provenance","lens-observer "+capture.value("capture",std::string("uia"))},
            {"source_application",utf8(process)},{"source_locator","window:"+utf8(title)},
            {"consent_context",{{"mode","observer_explicit_consent"}}},{"metadata",metadata}};
        {std::lock_guard g(out_lock);std::cout<<request.dump()<<'\n';std::cout.flush();}
        ++counts["records"];return id;
    };
    // Delta pipeline: decides snapshot vs delta vs skip for one settled capture of a window, then emits.
    auto store=[&](WindowState& ws,const std::string& visible,bool extract_truncated,const std::wstring& process,const std::wstring& title,json capture)->bool {
        const auto now=clock::now();const auto lines=lens::observe::split_lines(visible);
        const auto document=document_identity(title);
        const char* reason=!ws.stored?"first":document!=ws.document?"document_changed":
                           now-ws.snapshot_at>=ms(config.full_snapshot_ms)?"periodic":nullptr;
        std::string text;lens::observe::LineDelta d;
        if(reason) {
            ws.seen.clear();d=lens::observe::diff_lines(lines,ws.seen);text=lens::observe::join_lines(lines);
        } else {
            d=lens::observe::diff_lines(lines,ws.seen);
            const bool tiny=d.new_chars<config.min_delta_chars;
            const bool near_duplicate=d.overlap>=config.near_duplicate_overlap&&d.new_chars<config.near_duplicate_chars;
            if(tiny||near_duplicate){for(const auto& l:lines)ws.seen.add(lens::observe::line_hash(l));++counts["near_duplicates"];return false;}
            text=lens::observe::join_lines(d.new_lines);
        }
        for(const auto& l:lines)ws.seen.add(lens::observe::line_hash(l));
        bool capped=false;text=lens::observe::cap_utf8(text,config.max_capture_chars,capped);
        capture.update({{"capture_mode",reason?"snapshot":"delta"},{"snapshot_reason",reason?json(reason):json(nullptr)},{"window_key",ws.key},
            {"previous_capture",ws.last_id.empty()?json(nullptr):json(ws.last_id)},{"base_snapshot",reason||ws.snapshot_id.empty()?json(nullptr):json(ws.snapshot_id)},
            {"lines_visible",d.lines},{"lines_new",d.new_lines.size()},{"line_overlap",std::round(d.overlap*1000)/1000},
            {"visible_chars",visible.size()},{"truncated",extract_truncated||capped}});
        const auto id=emit(text,visible,process,title,capture);
        if(!id&&reason&&lines.empty())return false;  // nothing visible yet: the next capture is still the window's first
        ws.stored=true;ws.document=document;
        if(reason){ws.snapshot_at=now;if(id)ws.snapshot_id=*id;}
        if(!id)return false;
        ws.last_id=*id;++counts[reason?"snapshots":"deltas"];return true;
    };

    // CPU budget: the observer's own CPU over ~5 s windows; above budget every interval is stretched (up to 16x).
    int throttle=1;double cpu_percent=0;auto cpu_at=clock::now();auto cpu_ms_at=process_cpu_ms();long long last_work_ms=0;
    auto schedule=[&](int base_ms) {
        // The observer's own CPU per check at most ~5% of the time (UIA wall time is mostly waiting on the target app).
        const long long duty=std::min<long long>(20*last_work_ms,config.max_interval_ms);
        next_check=clock::now()+ms(std::max<long long>(static_cast<long long>(base_ms)*throttle,duty));
    };
    while(!stopping) {
        std::this_thread::sleep_for(ms(250));
        if(const auto t=clock::now();t-cpu_at>=std::chrono::seconds(5)) {
            const auto c=process_cpu_ms();
            cpu_percent=100.0*static_cast<double>(c-cpu_ms_at)/static_cast<double>(std::chrono::duration_cast<ms>(t-cpu_at).count());
            if(cpu_percent>config.cpu_budget_percent)throttle=std::min(throttle*2,16);
            else if(cpu_percent<config.cpu_budget_percent/2&&throttle>1)throttle/=2;
            cpu_at=t;cpu_ms_at=c;
        }
        if(status_requested.exchange(false)) {
            json c=json::object();for(const auto& [k,v]:counts)c[k]=v;
            status({{"event","status"},{"paused",paused.load()},{"records",counts["records"]},{"unchanged",counts["unchanged"]},{"counts",c},
                    {"skipped",skipped},{"interval_ms",interval},{"throttle",throttle},{"cpu_percent",std::round(cpu_percent*10)/10},{"last_extract",last_extract}});
        }
        // Release the OCR worker (and its models) after a quiet period; it restarts on the next OCR need.
        if(ocr_worker.running()&&GetTickCount64()-ocr_worker.last_used()>static_cast<ULONGLONG>(config.ocr_idle_ms))ocr_worker.stop();
        if(paused)continue;
        HWND w=nullptr;
        if(follow_pid){FindPid f{follow_pid};EnumWindows(find_pid_window,reinterpret_cast<LPARAM>(&f));w=f.found;}
        else w=GetForegroundWindow();
        const auto title=w?window_title(w):std::wstring();
        const auto now=clock::now();
        if(w!=last_window||title!=last_title){last_window=w;last_title=title;interval=config.min_interval_ms;next_check=now;pending.active=false;}
        if(now<next_check)continue;
        DWORD pid=0;if(w)GetWindowThreadProcessId(w,&pid);
        const auto process=w?process_name(pid):std::wstring();
        if(const auto reason=privacy_block(w,config,process,title);!reason.empty()) {
            ++skipped[reason];next_check=now+ms(config.min_interval_ms);continue;
        }
        auto& ws=state_for(w,process);
        // While content is settling, poll at a third of the settle time (slower for windows that keep changing).
        const int settle_poll=std::max(config.min_interval_ms,config.settle_ms/3)*(1+std::min(ws.churn,3));
        const auto t0=clock::now();const auto cpu0=thread_cpu_ms();
        const auto text=lens::observe::extract_window_text(w,budget);
        const auto elapsed=std::chrono::duration_cast<ms>(clock::now()-t0).count();last_work_ms=static_cast<long long>(thread_cpu_ms()-cpu0);
        last_extract={{"available",text.available},{"nodes",text.nodes},{"offscreen",text.offscreen},{"pruned",text.pruned},
                      {"visible_ranges",text.visible_ranges},{"password_skipped",text.password_skipped},{"chars",text.text.size()},{"ms",elapsed},{"cpu_ms",last_work_ms}};  // counts only, never content
        const auto body=utf8(text.text);
        const long long uia_chars=static_cast<long long>(text.text.size())-static_cast<long long>(title.size());
        bool fresh=false;
        if(!config.ocr.is_null()&&(!text.available||uia_chars<config.min_uia_chars)) {
            // OCR fallback: capture in memory; once the frame has settled, OCR only what changed since the last OCR.
            const auto frame=lens::observe::capture_window(w);
            if(frame.bgr.empty()){++skipped["capture_failed"];}
            else {
                if(settle_frame_window!=w||lens::observe::changed_region(settle_frame,frame))++frame_generation;
                settle_frame=frame;settle_frame_window=w;
                std::optional<lens::observe::Rect> region=previous_frame_window==w?lens::observe::changed_region(previous_frame,frame)
                                                                                 :lens::observe::Rect{0,0,frame.w,frame.h};
                if(!region)pending.active=false;
                else if(!settled(static_cast<uint64_t>(frame_generation),ws)){schedule(settle_poll);continue;}
                if(previous_frame_window!=w)ocr_lines.clear();
                if(region) {
                    previous_frame=frame;previous_frame_window=w;
                    // A change OCRs a full-width band (change ± 32 px); lines cut by the band edges are dropped and the
                    // window's cached lines inside the band are replaced, so each capture holds the whole window text.
                    json req=config.ocr;req["consent"]=true;req["mode"]="screen";req["image_base64"]=lens::observe::bmp_base64(frame);
                    const int band_y=std::max(0,region->y-32),band_h=std::min(frame.h,region->y+region->h+32)-band_y;
                    const bool partial=!ocr_lines.empty()&&band_h<0.6*frame.h;
                    if(partial){req["region"]={0,band_y,frame.w,band_h};req["drop_edge_boxes"]=true;}
                    const auto t1=clock::now();
                    const auto out=ocr_worker.request(req.dump(),30000);
                    const auto ocr_ms=std::chrono::duration_cast<ms>(clock::now()-t1).count();
                    const auto result=out?json::parse(*out,nullptr,false):json();
                    if(!result.is_object()||!result.value("ok",false)){++skipped["ocr_failed"];}
                    else {
                        const int offset=partial?band_y:0;
                        if(partial)std::erase_if(ocr_lines,[&](const OcrLine& l){return l.y0>=band_y&&l.y1<=band_y+band_h;});
                        else ocr_lines.clear();
                        double conf=0;json recognizers=json::array();
                        for(const auto& l:result.at("lines")) {
                            const auto& b=l.at("box");
                            ocr_lines.push_back({l.at("text").get<std::string>(),b[0].get<int>(),b[1].get<int>()+offset,b[3].get<int>()+offset});
                            conf+=l.at("confidence").get<double>();
                            if(std::find(recognizers.begin(),recognizers.end(),l.at("recognizer"))==recognizers.end())recognizers.push_back(l.at("recognizer"));
                        }
                        std::sort(ocr_lines.begin(),ocr_lines.end(),[](const OcrLine& a,const OcrLine& b){
                            return std::abs(a.y0-b.y0)<10?a.x0<b.x0:a.y0<b.y0;});
                        std::string joined;for(const auto& l:ocr_lines)joined+=l.text+"\n";
                        const auto n=result.at("lines").size();
                        fresh=store(ws,joined,false,process,title,{{"capture","ocr"},{"region",partial?req["region"]:json(nullptr)},{"lines_read",n},
                            {"lines",ocr_lines.size()},{"mean_confidence",n?conf/n:0.0},{"recognizers",recognizers},{"ocr_ms",ocr_ms},
                            {"ocr_peak_working_set_bytes",result.value("peak_working_set_bytes",0)},{"uia_chars",uia_chars}});
                    }
                }
            }
        } else {
            const auto hash=lens::observe::line_hash(utf8(document_identity(title))+"\n"+body);  // a new document is new content
            if(text.timed_out){++counts["timed_out_extracts"];schedule(settle_poll);continue;}  // a stalled target app: retry later
            if(hash!=ws.considered) {
                if(!settled(hash,ws)){schedule(settle_poll);continue;}
                ws.considered=hash;
                fresh=store(ws,body,text.truncated,process,title,{{"capture","uia"},{"elements",text.nodes},{"password_elements_skipped",text.password_skipped},
                                                                    {"offscreen_elements",text.offscreen},{"extract_ms",elapsed}});
            } else pending.active=false;
        }
        if(fresh)interval=config.min_interval_ms;
        else {++counts["unchanged"];interval=std::min(interval*2,config.max_interval_ms);}
        schedule(interval);
    }
    json c=json::object();for(const auto& [k,v]:counts)c[k]=v;
    status({{"event","stopped"},{"records",counts["records"]},{"unchanged",counts["unchanged"]},{"counts",c},{"skipped",skipped}});
    CoUninitialize();
    return 0;
}
