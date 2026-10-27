// lens-observer: consent-gated Windows screen-text observer (docs/LENS_V1_SPEC.md §3–5, §15; Milestone 3).
// Emits one engine `add` request (JSON line) on stdout per new piece of window content, so
// `lens-observer --consent | lens-engine --db ...` stores observations in the encrypted memory. UI Automation text only
// (OCR fallback is a later stage). Never reads password elements, excluded processes, private-browsing windows or
// capture-protected windows. Control on stdin: pause | resume | status | stop (or {"op":...}); EOF stops.
// Diagnostics go to stderr as JSON and never contain window text or titles.
#include "uia_text.hpp"
#include "screen_capture.hpp"
#include <windows.h>
#include <bcrypt.h>
#include <dwmapi.h>
#include <nlohmann/json.hpp>
#include <psapi.h>
#include <algorithm>
#include <atomic>
#include <chrono>
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
// Dominant-script language guess: a label for retrieval metadata, not a language identifier.
std::string script_language(const std::wstring& s) {
    std::map<std::string,int> n;
    for(wchar_t c:s) {
        if(c>=0x0900&&c<=0x097F)++n["hi"];else if(c>=0x0B80&&c<=0x0BFF)++n["ta"];else if(c>=0x0C00&&c<=0x0C7F)++n["te"];
        else if((c>=0x4E00&&c<=0x9FFF)||(c>=0x3400&&c<=0x4DBF))++n["zh"];else if(iswalpha(c)&&c<0x0250)++n["und-Latn"];
    }
    std::string best="und";int top=0;for(auto& [k,v]:n)if(v>top){best=k;top=v;}return best;
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

int wmain(int argc,wchar_t** argv) {
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
    if(FAILED(CoInitializeEx(nullptr,COINIT_MULTITHREADED)))return 1;
    SetConsoleOutputCP(CP_UTF8);

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

    status({{"event","started"},{"follow",follow_pid?"pid":"foreground"},{"capture","uia"}});
    std::map<std::string,int> skipped;long long records=0,unchanged=0;json last_extract=json::object();
    std::deque<std::string> recent;HWND last_window=nullptr;std::wstring last_title;
    int interval=config.min_interval_ms;auto next_check=std::chrono::steady_clock::now();
    lens::observe::UiaBudget budget;
    lens::observe::Frame previous_frame;HWND previous_frame_window=nullptr;
    std::wstring ocr_exe;
    {std::wstring self(32768,L'\0');self.resize(GetModuleFileNameW(nullptr,self.data(),32768));ocr_exe=self.substr(0,self.find_last_of(L"\\/")+1)+L"lens-ocr.exe";}
    lens::observe::ServeWorker ocr_worker(ocr_exe);
    struct OcrLine {std::string text;int x0,y0,y1;};std::vector<OcrLine> ocr_lines;  // last OCR text of the followed window
    auto emit=[&](const std::string& body,const std::wstring& wide_text,const std::wstring& process,const std::wstring& title,const json& capture)->bool {
        const auto digest=sha256_hex(utf8(process)+"\n"+utf8(title)+"\n"+body);
        if(body.size()<3||std::find(recent.begin(),recent.end(),digest)!=recent.end())return false;
        recent.push_back(digest);if(recent.size()>256)recent.pop_front();
        json metadata={{"window_title",utf8(title)}};metadata.update(capture);
        json request={{"op","add"},{"consent",true},{"id","obs-"+digest.substr(0,32)},{"text",body},{"language",script_language(wide_text)},
            {"timestamp",utc_now()},{"device",config.device},{"kind","screen_observation"},{"provenance","lens-observer "+capture.value("capture",std::string("uia"))},
            {"source_application",utf8(process)},{"source_locator","window:"+utf8(title)},
            {"consent_context",{{"mode","observer_explicit_consent"}}},{"metadata",metadata}};
        {std::lock_guard g(out_lock);std::cout<<request.dump()<<'\n';std::cout.flush();}
        ++records;return true;
    };
    while(!stopping) {
        std::this_thread::sleep_for(std::chrono::milliseconds(250));
        if(status_requested.exchange(false))
            status({{"event","status"},{"paused",paused.load()},{"records",records},{"unchanged",unchanged},{"skipped",skipped},{"interval_ms",interval},
                    {"last_extract",last_extract}});
        // Release the OCR worker (and its models) after a quiet period; it restarts on the next OCR need.
        if(ocr_worker.running()&&GetTickCount64()-ocr_worker.last_used()>static_cast<ULONGLONG>(config.ocr_idle_ms))ocr_worker.stop();
        if(paused)continue;
        HWND w=nullptr;
        if(follow_pid){FindPid f{follow_pid};EnumWindows(find_pid_window,reinterpret_cast<LPARAM>(&f));w=f.found;}
        else w=GetForegroundWindow();
        const auto title=w?window_title(w):std::wstring();
        const auto now=std::chrono::steady_clock::now();
        if(w!=last_window||title!=last_title){last_window=w;last_title=title;interval=config.min_interval_ms;next_check=now;}
        if(now<next_check)continue;
        DWORD pid=0;if(w)GetWindowThreadProcessId(w,&pid);
        const auto process=w?process_name(pid):std::wstring();
        if(const auto reason=privacy_block(w,config,process,title);!reason.empty()) {
            ++skipped[reason];next_check=now+std::chrono::milliseconds(config.min_interval_ms);continue;
        }
        const auto t0=std::chrono::steady_clock::now();
        const auto text=lens::observe::extract_window_text(w,budget);
        const auto elapsed=std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-t0).count();
        last_extract={{"available",text.available},{"nodes",text.nodes},{"offscreen",text.offscreen},{"password_skipped",text.password_skipped},
                      {"chars",text.text.size()},{"ms",elapsed}};  // counts only, never content
        const auto body=utf8(text.text);
        const long long uia_chars=static_cast<long long>(text.text.size())-static_cast<long long>(title.size());
        bool fresh=false;
        if(!config.ocr.is_null()&&(!text.available||uia_chars<config.min_uia_chars)) {
            // OCR fallback: capture in memory, OCR only what changed since the previous frame of this window.
            const auto frame=lens::observe::capture_window(w);
            if(frame.bgr.empty()){++skipped["capture_failed"];}
            else {
                std::optional<lens::observe::Rect> region=previous_frame_window==w?lens::observe::changed_region(previous_frame,frame)
                                                                                 :lens::observe::Rect{0,0,frame.w,frame.h};
                if(previous_frame_window!=w)ocr_lines.clear();
                previous_frame=frame;previous_frame_window=w;
                if(region) {
                    // A change OCRs a full-width band (change ± 32 px); lines cut by the band edges are dropped and the
                    // window's cached lines inside the band are replaced, so each record holds the whole window text.
                    json req=config.ocr;req["consent"]=true;req["mode"]="screen";req["image_base64"]=lens::observe::bmp_base64(frame);
                    const int band_y=std::max(0,region->y-32),band_h=std::min(frame.h,region->y+region->h+32)-band_y;
                    const bool partial=!ocr_lines.empty()&&band_h<0.6*frame.h;
                    if(partial){req["region"]={0,band_y,frame.w,band_h};req["drop_edge_boxes"]=true;}
                    const auto t1=std::chrono::steady_clock::now();
                    const auto out=ocr_worker.request(req.dump(),30000);
                    const auto ocr_ms=std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-t1).count();
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
                        fresh=emit(joined,wide(joined),process,title,{{"capture","ocr"},{"region",partial?req["region"]:json(nullptr)},{"lines_read",n},
                            {"lines",ocr_lines.size()},{"mean_confidence",n?conf/n:0.0},{"recognizers",recognizers},{"ocr_ms",ocr_ms},
                            {"ocr_peak_working_set_bytes",result.value("peak_working_set_bytes",0)},{"uia_chars",uia_chars}});
                    }
                }
            }
        } else {
            fresh=emit(body,text.text,process,title,{{"capture","uia"},{"elements",text.nodes},{"password_elements_skipped",text.password_skipped},
                                                     {"truncated",text.truncated},{"extract_ms",elapsed}});
        }
        if(fresh)interval=config.min_interval_ms;
        else {++unchanged;interval=std::min(interval*2,config.max_interval_ms);}
        next_check=std::chrono::steady_clock::now()+std::chrono::milliseconds(interval);
    }
    status({{"event","stopped"},{"records",records},{"unchanged",unchanged},{"skipped",skipped}});
    CoUninitialize();
    return 0;
}
