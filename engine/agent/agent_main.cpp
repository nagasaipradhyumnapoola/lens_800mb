// lens-agent: the always-on Lens background process (docs/LENS_V1_SPEC.md §3–4, §15–17).
// Owns the encrypted memory engine, runs the screen observer only after the user has consented (config), relays its
// observations into memory, consolidates episodes periodically, and serves local clients (the Lens app, CLI) over a
// named pipe that only the current user can open and that rejects remote clients. JSON lines in both directions.
//
// Client ops: status | set_consent {"observe_screen","microphone","phone_link","onboarded": bool} |
// set_exclusions {"excluded_processes","private_title_markers": [string]} | set_autostart {"enabled":bool} |
// diagnostics | import_preview|import_start|import_status|import_cancel|import_delete (imports.hpp) |
// pause | resume | engine ops passed through (recall, search, timeline, retrieve_context, find_source, episodes,
// episode_context, stats, consolidate, delete, add, import_batch, ingest_audio, unload_models). Anything else is rejected.
// Pause stops all capture (screen and microphone) at once and holds until resume, whatever else changes meanwhile.
// --tray adds a notification-area icon (status, Pause/Resume, Open Lens, Quit) on a thread of this process, so the
// resident system stays one process; --tray-hidden runs the same commands without the icon (tests).
#include "child_process.hpp"
#include "actions.hpp"
#include "imports.hpp"
#include <windows.h>
#include <bcrypt.h>
#include <sddl.h>
#include <shellapi.h>
#include <shlobj.h>
#include <tlhelp32.h>
#include <psapi.h>
#include <nlohmann/json.hpp>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <map>
#include <mutex>
#include <set>
#include <string>
#include <thread>

namespace fs=std::filesystem;
using json=nlohmann::json;
using lens::agent::Child;

namespace {
std::string utf8(const std::wstring& w) {
    if(w.empty())return {};
    const int n=WideCharToMultiByte(CP_UTF8,0,w.data(),static_cast<int>(w.size()),nullptr,0,nullptr,nullptr);
    std::string s(n,'\0');WideCharToMultiByte(CP_UTF8,0,w.data(),static_cast<int>(w.size()),s.data(),n,nullptr,nullptr);return s;
}
std::wstring wide(const std::string& s) {
    const int n=MultiByteToWideChar(CP_UTF8,0,s.data(),static_cast<int>(s.size()),nullptr,0);
    std::wstring w(n,L'\0');MultiByteToWideChar(CP_UTF8,0,s.data(),static_cast<int>(s.size()),w.data(),n);return w;
}
std::string file_sha256(const fs::path& p) {
    std::ifstream f(p,std::ios::binary);if(!f)return {};
    BCRYPT_ALG_HANDLE alg=nullptr;BCRYPT_HASH_HANDLE h=nullptr;unsigned char d[32]{};
    BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,nullptr,0);BCryptCreateHash(alg,&h,nullptr,0,nullptr,0,0);
    std::vector<char> buf(1<<20);
    while(f){f.read(buf.data(),buf.size());const auto n=f.gcount();if(n>0)BCryptHashData(h,reinterpret_cast<PUCHAR>(buf.data()),static_cast<ULONG>(n),0);}
    BCryptFinishHash(h,d,32,0);BCryptDestroyHash(h);BCryptCloseAlgorithmProvider(alg,0);
    static const char* hex="0123456789abcdef";std::string out;for(unsigned char b:d){out+=hex[b>>4];out+=hex[b&15];}return out;
}
json read_json(const fs::path& p){std::ifstream f(p);if(!f)throw std::runtime_error("unreadable:"+utf8(p.wstring()));return json::parse(f);}
std::mutex log_lock;
void log(const json& j){std::lock_guard g(log_lock);std::cerr<<j.dump()<<'\n';std::cerr.flush();}  // never memory content

struct Engine {
    Child child;std::mutex lock;std::function<void(const json&)> before;  // resource governor hook (spec §15)
    std::optional<json> ask(const json& req) {
        if(before)before(req);
        std::lock_guard g(lock);const auto line=child.request(req.dump());
        if(!line)return std::nullopt;
        return json::parse(*line,nullptr,false);
    }
};

// Spoken replies (lens-tts): one worker, started on first use and stopped when idle so Kokoro is never resident for
// long (spec §15). Every file it reads is hash-verified against the lock files once, before the first start.
struct Speech {
    Child child;std::mutex lock;std::chrono::steady_clock::time_point last{};json paths;std::string status="not_checked";
    // Kokoro (~394 MB) never shares RAM with another heavy model: on_start frees the others, on_stop lets them back.
    std::function<void()> on_start,on_stop;
    static inline const std::set<std::string> voices{"af_heart","af_bella","am_michael","bf_emma","bm_george"};
    bool verify(const fs::path& root) {
        if(status=="verified")return true;
        try {
            json pinned;for(const auto& r:read_json(root/"third_party/model-lock.json"))pinned[r.at("path").get<std::string>()]=r.at("sha256");
            const auto o=read_json(root/"third_party/ocr-runtime-lock.json");
            for(const auto& a:o.at("runtime_artifacts"))if(a.at("path").get<std::string>().ends_with("/onnxruntime.dll"))pinned[a.at("path").get<std::string>()]=a.at("sha256");
            const std::string k="models/onnx-community--Kokoro-82M-v1.0-ONNX/",m="models/hexgrad--misaki/";
            json p={{"runtime",".tools/ocr-runtime/onnxruntime.dll"},{"model","models/Lens--kokoro-82m-mixed-int8/model.onnx"},{"tokenizer",k+"tokenizer.json"},
                    {"lexicon",{m+"us_gold.json",m+"us_silver.json"}}};
            std::vector<std::string> files{p["runtime"],p["model"],p["tokenizer"],p["lexicon"][0],p["lexicon"][1]};
            for(const auto& v:voices)files.push_back(k+"voices/"+v+".bin");
            for(const auto& f:files)
                if(!pinned.contains(f)||file_sha256(root/wide(f))!=pinned[f].get<std::string>())throw std::runtime_error("hash_mismatch:"+f);
            auto abs=[&](const std::string& f){return utf8((root/wide(f)).make_preferred().wstring());};
            paths={{"runtime",abs(p["runtime"])},{"model",abs(p["model"])},{"tokenizer",abs(p["tokenizer"])},
                   {"lexicon",{abs(p["lexicon"][0]),abs(p["lexicon"][1])}},{"voices_dir",abs(k+"voices")}};
            status="verified";return true;
        } catch(const std::exception& ex){status=std::string("unavailable: ")+ex.what();return false;}
    }
    json speak(const fs::path& root,const fs::path& exe_dir,const json& req) {
        std::lock_guard g(lock);
        if(!req.contains("text")||!req["text"].is_string())return {{"ok",false},{"error","invalid_request"}};
        const auto voice=req.value("voice",std::string("af_heart"));if(!voices.count(voice))return {{"ok",false},{"error","unsupported_voice"}};
        if(!verify(root))return {{"ok",false},{"error","speech_unavailable"},{"reason",status}};
        json r={{"text",req["text"]},{"voice",paths["voices_dir"].get<std::string>()+"\\"+voice+".bin"},{"speed",req.value("speed",1.0)},{"threads",4},
                {"runtime",paths["runtime"]},{"model",paths["model"]},{"tokenizer",paths["tokenizer"]},{"lexicon",paths["lexicon"]}};
        if(!child.running()) {
            if(on_start)on_start();
            if(!child.start((exe_dir/L"lens-tts.exe").wstring(),{})){if(on_stop)on_stop();return {{"ok",false},{"error","speech_unavailable"}};}
        }
        const auto line=child.request(r.dump());last=std::chrono::steady_clock::now();
        if(!line){stop_locked();return {{"ok",false},{"error","speech_unavailable"}};}
        auto out=json::parse(*line,nullptr,false);return out.is_object()?out:json{{"ok",false},{"error","speech_unavailable"}};
    }
    void stop_if_idle(std::chrono::seconds idle) {
        std::lock_guard g(lock);if(child.running()&&std::chrono::steady_clock::now()-last>idle)stop_locked();
    }
    void stop(){std::lock_guard g(lock);if(child.running())stop_locked();}
private:
    void stop_locked(){child.stop();if(on_stop)on_stop();}
};

// Engine arguments from the pinned lock files (same model id convention as scripts/lens.ps1). Every artifact is
// hash-verified; on any mismatch the engine runs keyword-only and the reason is reported in status.
std::vector<std::wstring> engine_args(const fs::path& root,const fs::path& db,std::string& semantic_status) {
    std::vector<std::wstring> args{L"--db",db.wstring()};
    try {
        const auto e=read_json(root/"third_party/embedding-lock.json"),r=read_json(root/"third_party/reranker-lock.json"),o=read_json(root/"third_party/ocr-runtime-lock.json");
        auto pick=[](const json& lock,const char* name)->const json&{for(const auto& f:lock.at("files"))if(f.at("filename")==name)return f;throw std::runtime_error("missing");};
        const auto& model=pick(e,"onnx/model_qint8_avx512_vnni.onnx");const auto& tok=pick(e,"onnx/tokenizer.json");
        const auto& rmodel=pick(r,"onnx/model_qint8_avx512_vnni.onnx");const auto& rtok=pick(r,"tokenizer.json");
        json ort;for(const auto& a:o.at("runtime_artifacts"))if(a.at("path").get<std::string>().ends_with("/onnxruntime.dll"))ort=a;
        for(const json* a:std::initializer_list<const json*>{&model,&tok,&rmodel,&rtok,&ort})
            if(file_sha256(root/wide(a->at("path").get<std::string>()))!=a->at("sha256").get<std::string>())throw std::runtime_error("hash_mismatch:"+a->at("path").get<std::string>());
        const auto id="intfloat/multilingual-e5-small@"+e.at("revision").get<std::string>().substr(0,12)+"/onnx/model_qint8_avx512_vnni.onnx#sha256:"+model.at("sha256").get<std::string>().substr(0,16);
        for(const auto& a:std::vector<std::wstring>{L"--ort",(root/wide(ort.at("path").get<std::string>())).wstring(),L"--embedding-model",(root/wide(model.at("path").get<std::string>())).wstring(),
            L"--embedding-tokenizer",(root/wide(tok.at("path").get<std::string>())).wstring(),L"--embedding-id",wide(id),
            L"--reranker-model",(root/wide(rmodel.at("path").get<std::string>())).wstring(),L"--reranker-tokenizer",(root/wide(rtok.at("path").get<std::string>())).wstring()})args.push_back(a);
        semantic_status="verified";
    } catch(const std::exception& ex){semantic_status=std::string("keyword_only: ")+ex.what();}
    return args;
}

// Security descriptor: full access for the current user only (plus SYSTEM); remote clients are rejected separately.
bool user_only_security(SECURITY_ATTRIBUTES& sa) {
    HANDLE token=nullptr;if(!OpenProcessToken(GetCurrentProcess(),TOKEN_QUERY,&token))return false;
    DWORD n=0;GetTokenInformation(token,TokenUser,nullptr,0,&n);std::vector<BYTE> buf(n);
    if(!GetTokenInformation(token,TokenUser,buf.data(),n,&n)){CloseHandle(token);return false;}CloseHandle(token);
    LPWSTR sid=nullptr;if(!ConvertSidToStringSidW(reinterpret_cast<TOKEN_USER*>(buf.data())->User.Sid,&sid))return false;
    const std::wstring sddl=L"D:P(A;;GA;;;"+std::wstring(sid)+L")(A;;GA;;;SY)";LocalFree(sid);
    PSECURITY_DESCRIPTOR sd=nullptr;
    if(!ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl.c_str(),SDDL_REVISION_1,&sd,nullptr))return false;
    sa.nLength=sizeof sa;sa.lpSecurityDescriptor=sd;sa.bInheritHandle=FALSE;return true;
}

const std::set<std::string> passthrough={"recall","search","timeline","retrieve_context","find_source","episodes","episode_context","stats",
    "consolidate","index","delete","add","import_batch","ingest_audio","unload_models","entities","entity_context","facts","projects","project_context",
    "delete_sources","export","imports","backup","restore","rotate_key","retention_set","retention_list","retention_remove",
    "pin","unpin","pins","feedback","correct_fact"};

// The agent and every process it started (engine, observer and its OCR worker, voice, mesh), with real memory use.
json process_tree() {
    json out=json::array();HANDLE snap=CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS,0);if(snap==INVALID_HANDLE_VALUE)return out;
    std::vector<PROCESSENTRY32W> all;PROCESSENTRY32W e{};e.dwSize=sizeof e;
    if(Process32FirstW(snap,&e))do all.push_back(e);while(Process32NextW(snap,&e));
    CloseHandle(snap);
    std::vector<DWORD> tree{GetCurrentProcessId()};
    for(size_t i=0;i<tree.size();++i)for(const auto& p:all)
        if(p.th32ParentProcessID==tree[i]&&std::find(tree.begin(),tree.end(),p.th32ProcessID)==tree.end())tree.push_back(p.th32ProcessID);
    for(const DWORD pid:tree) {
        std::wstring name;for(const auto& p:all)if(p.th32ProcessID==pid)name=p.szExeFile;
        HANDLE h=OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,FALSE,pid);if(!h)continue;
        PROCESS_MEMORY_COUNTERS_EX m{};m.cb=sizeof m;
        if(GetProcessMemoryInfo(h,reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&m),sizeof m))
            out.push_back({{"name",utf8(name)},{"pid",pid},{"working_set",m.WorkingSetSize},{"private",m.PrivateUsage}});
        CloseHandle(h);
    }
    return out;
}

// Notification-area icon. The window is never shown; it only receives the icon's mouse messages and menu commands
// (tests send the same WM_COMMANDs to the window found by class "LensAgentTray" and the pipe name as its title).
struct TrayHooks{std::function<json()> status;std::function<void(bool)> pause;std::function<void()> open,quit;};
constexpr UINT WM_TRAY=WM_APP+1;
constexpr UINT_PTR ID_PAUSE=1001,ID_RESUME=1002,ID_OPEN=1003,ID_QUIT=1004;
TrayHooks* tray_hooks=nullptr;bool tray_icon=false;UINT taskbar_created=0;HICON icon_on=nullptr,icon_off=nullptr;

HICON dot_icon(COLORREF rgb) {  // 16x16 filled circle, drawn here so the agent needs no resource file
    BITMAPINFO bi{};bi.bmiHeader.biSize=sizeof bi.bmiHeader;bi.bmiHeader.biWidth=16;bi.bmiHeader.biHeight=-16;
    bi.bmiHeader.biPlanes=1;bi.bmiHeader.biBitCount=32;bi.bmiHeader.biCompression=BI_RGB;
    void* bits=nullptr;HBITMAP color=CreateDIBSection(nullptr,&bi,DIB_RGB_COLORS,&bits,nullptr,0);if(!color)return LoadIconW(nullptr,MAKEINTRESOURCEW(32512));  // IDI_APPLICATION
    auto* px=static_cast<DWORD*>(bits);
    const DWORD argb=0xFF000000u|(static_cast<DWORD>(GetRValue(rgb))<<16)|(static_cast<DWORD>(GetGValue(rgb))<<8)|GetBValue(rgb);
    for(int y=0;y<16;++y)for(int x=0;x<16;++x){const double dx=x-7.5,dy=y-7.5;px[y*16+x]=dx*dx+dy*dy<=42.25?argb:0;}
    const BYTE zeros[32]{};HBITMAP mask=CreateBitmap(16,16,1,1,zeros);
    ICONINFO ii{TRUE,0,0,mask,color};HICON icon=CreateIconIndirect(&ii);DeleteObject(mask);DeleteObject(color);return icon;
}
std::wstring capture_state(const json& s) {
    if(!s.value("ok",false))return L"Lens is starting";
    if(s.value("paused",false))return L"Paused";
    if(s.value("observer_running",false)||s.value("voice_running",false))return L"Observing";
    return L"Observation off";
}
void tray_update(HWND w,DWORD message) {
    if(!tray_icon)return;
    const auto state=capture_state(tray_hooks->status());
    NOTIFYICONDATAW nid{};nid.cbSize=sizeof nid;nid.hWnd=w;nid.uID=1;nid.uFlags=NIF_MESSAGE|NIF_ICON|NIF_TIP;nid.uCallbackMessage=WM_TRAY;
    nid.hIcon=state==L"Observing"?icon_on:icon_off;wcsncpy_s(nid.szTip,(L"Lens: "+state).c_str(),_TRUNCATE);
    Shell_NotifyIconW(message,&nid);
}
LRESULT CALLBACK tray_proc(HWND w,UINT m,WPARAM wp,LPARAM lp) {
    if(m==taskbar_created&&taskbar_created){tray_update(w,NIM_ADD);return 0;}  // Explorer restarted
    switch(m) {
    case WM_TRAY:
        if(lp==WM_LBUTTONDBLCLK)tray_hooks->open();
        else if(lp==WM_RBUTTONUP||lp==WM_CONTEXTMENU) {  // double-click opens Lens; right-click shows the menu
            const auto s=tray_hooks->status();const bool paused=s.value("paused",false);
            const bool capturing=s.value("observer_running",false)||s.value("voice_running",false);
            HMENU menu=CreatePopupMenu();
            AppendMenuW(menu,MF_STRING|MF_GRAYED,0,(L"Lens: "+capture_state(s)).c_str());AppendMenuW(menu,MF_SEPARATOR,0,nullptr);
            if(paused)AppendMenuW(menu,MF_STRING,ID_RESUME,L"Resume capture");
            else AppendMenuW(menu,MF_STRING|(capturing?0u:MF_GRAYED),ID_PAUSE,L"Pause capture");
            AppendMenuW(menu,MF_STRING,ID_OPEN,L"Open Lens");AppendMenuW(menu,MF_SEPARATOR,0,nullptr);AppendMenuW(menu,MF_STRING,ID_QUIT,L"Quit Lens");
            POINT p;GetCursorPos(&p);SetForegroundWindow(w);  // required so the menu closes when the user clicks elsewhere
            TrackPopupMenu(menu,TPM_RIGHTBUTTON,p.x,p.y,0,w,nullptr);PostMessageW(w,WM_NULL,0,0);DestroyMenu(menu);
        }
        return 0;
    case WM_COMMAND:
        switch(LOWORD(wp)) {
        case ID_PAUSE:tray_hooks->pause(true);break;
        case ID_RESUME:tray_hooks->pause(false);break;
        case ID_OPEN:tray_hooks->open();break;
        case ID_QUIT:tray_hooks->quit();break;
        }
        tray_update(w,NIM_MODIFY);return 0;
    case WM_TIMER:tray_update(w,NIM_MODIFY);return 0;
    case WM_CLOSE:DestroyWindow(w);return 0;
    case WM_DESTROY:{if(tray_icon){NOTIFYICONDATAW nid{};nid.cbSize=sizeof nid;nid.hWnd=w;nid.uID=1;Shell_NotifyIconW(NIM_DELETE,&nid);}PostQuitMessage(0);return 0;}
    }
    return DefWindowProcW(w,m,wp,lp);
}
void run_tray(TrayHooks* hooks,bool icon,const std::wstring& title,std::atomic<HWND>& window,std::atomic<bool>& ready) {
    tray_hooks=hooks;tray_icon=icon;taskbar_created=RegisterWindowMessageW(L"TaskbarCreated");
    icon_on=dot_icon(RGB(76,194,120));icon_off=dot_icon(RGB(140,140,150));
    WNDCLASSW wc{};wc.lpfnWndProc=tray_proc;wc.hInstance=GetModuleHandleW(nullptr);wc.lpszClassName=L"LensAgentTray";RegisterClassW(&wc);
    HWND w=CreateWindowExW(0,wc.lpszClassName,title.c_str(),WS_POPUP,0,0,0,0,nullptr,nullptr,wc.hInstance,nullptr);  // never shown
    if(!w){ready=true;return;}
    tray_update(w,NIM_ADD);SetTimer(w,1,3000,nullptr);window=w;ready=true;
    MSG msg;while(GetMessageW(&msg,nullptr,0,0)>0){TranslateMessage(&msg);DispatchMessageW(&msg);}
    window=nullptr;DestroyIcon(icon_on);DestroyIcon(icon_off);
}
}

int wmain(int argc,wchar_t** argv) {
    fs::path data_dir,root;std::wstring pipe_name,follow,voice_input,explicit_args;bool test_capabilities=false;
    std::wstring autostart_key=L"Software\\Microsoft\\Windows\\CurrentVersion\\Run";  // HKCU; tests pass a scratch key
    enum class Tray{none,icon,hidden} tray=Tray::none;
    {wchar_t* local=nullptr;if(SUCCEEDED(SHGetKnownFolderPath(FOLDERID_LocalAppData,0,nullptr,&local))){data_dir=fs::path(local)/L"Lens";CoTaskMemFree(local);}}
    {  // install root: nearest ancestor of the executable holding the pinned lock files (installed: <root>\bin; repo: build\engine\Release)
        std::wstring self(32768,L'\0');self.resize(GetModuleFileNameW(nullptr,self.data(),32768));
        for(auto p=fs::path(self).parent_path();!p.empty()&&p!=p.parent_path();p=p.parent_path())
            if(fs::exists(p/L"third_party"/L"embedding-lock.json")){root=p;break;}
    }
    for(int i=1;i<argc;++i) {
        const std::wstring a=argv[i];auto next=[&]{return i+1<argc?std::wstring(argv[++i]):std::wstring();};
        if(a==L"--data-dir"){data_dir=next();explicit_args+=L" --data-dir \""+data_dir.wstring()+L"\"";}
        else if(a==L"--root")root=next();
        else if(a==L"--pipe-name"){pipe_name=next();explicit_args+=L" --pipe-name \""+pipe_name+L"\"";}
        else if(a==L"--observer-follow")follow=next();
        else if(a==L"--voice-input-wav")voice_input=next();  // tests: a file instead of the microphone
        else if(a==L"--autostart-key")autostart_key=next();
        else if(a==L"--tray")tray=Tray::icon;else if(a==L"--tray-hidden")tray=Tray::hidden;
        else if(a==L"--test-capabilities")test_capabilities=true;
        else {std::cerr<<"usage: lens-agent [--data-dir <dir>] [--root <install root>] [--pipe-name <name>] [--tray]\n";return 2;}
    }
    if(pipe_name.empty()) {  // per-user pipe name; the ACL is what enforces access
        wchar_t user[256];DWORD n=256;GetUserNameW(user,&n);pipe_name=L"lens-agent-"+std::wstring(user);
    }
    fs::create_directories(data_dir);
    HANDLE single=CreateMutexW(nullptr,TRUE,(L"Local\\"+pipe_name).c_str());
    if(GetLastError()==ERROR_ALREADY_EXISTS){log({{"event","refused"},{"reason","already_running"}});return 3;}
    const auto exe_dir=fs::path([]{std::wstring s(32768,L'\0');s.resize(GetModuleFileNameW(nullptr,s.data(),32768));return s;}()).parent_path();
    const auto config_path=data_dir/L"config.json";
    // Every consent defaults to off; "onboarded" records that the user has been through the first-run choices.
    json config={{"observe_screen",false},{"microphone",false},{"phone_link",false},{"onboarded",false},{"observer",json::object()},{"consolidate_minutes",10}};
    if(fs::exists(config_path))config.update(read_json(config_path));
    std::recursive_mutex config_lock;  // clients, the tray and child callbacks read the config concurrently
    auto save_config=[&]{std::lock_guard g(config_lock);std::ofstream f(config_path);f<<config.dump(1);};
    auto consent=[&](const char* key){std::lock_guard g(config_lock);return config.value(key,false);};

    std::string semantic;Engine engine;Speech speech;lens::agent::Actions actions(test_capabilities);
    if(!engine.child.start((exe_dir/L"lens-engine.exe").wstring(),engine_args(root,data_dir/L"memory.db",semantic))){log({{"event","refused"},{"reason","engine_start_failed"}});return 1;}
    const auto stats=engine.ask({{"op","stats"}});
    if(!stats||!stats->value("ok",false)){log({{"event","refused"},{"reason","database_open_failed"}});return 1;}

    // Capture telemetry for Diagnostics: when and how the last record was captured and stored. Never content.
    std::mutex telemetry_lock;json telemetry={{"screen",nullptr},{"voice",nullptr}};const auto started_at=std::chrono::steady_clock::now();
    auto note_capture=[&](const char* channel,const json& req,const std::optional<json>& r,long long store_ms) {
        const auto meta=req.value("metadata",json::object());json t={{"at",req.value("timestamp",std::string())},{"store_ms",store_ms},
            {"ok",r&&r->value("ok",false)},{"language",req.value("language",std::string())}};
        if(!t["ok"].get<bool>())t["error"]=r?r->value("error",std::string("engine_error")):std::string("engine_unavailable");
        if(meta.is_object()) {
            t["path"]=meta.value("capture",std::string(std::string(channel)=="voice"?"microphone":"uia"));
            for(const char* k:{"extract_ms","ocr_ms","recognizers","mean_confidence","duration_ms","speech_ms"})if(meta.contains(k))t[k]=meta[k];
        }
        std::lock_guard g(telemetry_lock);telemetry[channel]=t;
    };
    auto timed_ask=[&](const json& req,long long& ms){const auto t0=std::chrono::steady_clock::now();auto r=engine.ask(req);
        ms=std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-t0).count();return r;};

    // Observer: started only while consent is recorded in the config; its records go straight into memory.
    Child observer;std::mutex observer_lock;std::atomic<long long> observed=0,stored=0,failed=0;std::atomic<bool> paused=false;
    auto start_observer=[&]{
        std::lock_guard g(observer_lock);if(observer.running()||paused)return;  // paused: starts on resume
        observer.stop();  // reap a previous run that ended by itself (its reader thread must be joined before reuse)
        json ocfg;{std::lock_guard c(config_lock);ocfg=config.at("observer");}
        if(!ocfg.contains("ocr")) {  // default OCR fallback from the installed models (docs/VERIFICATION.md, Milestone 4)
            const auto m=root/L"models";
            auto rec=[&](const wchar_t* dir){return json{{"model",utf8((m/dir/L"inference.onnx").wstring())},{"dictionary",utf8((m/dir/L"ctc-dictionary.json").wstring())}};};
            json t={{"runtime",utf8((root/L".tools/ocr-runtime/onnxruntime.dll").wstring())},{"detector",utf8((m/L"PaddlePaddle--PP-OCRv5_mobile_det/inference.onnx").wstring())},
                    {"route","auto"},{"threads",2},{"recognizers",{{"general",rec(L"PaddlePaddle--PP-OCRv6_tiny_rec")},{"hi",rec(L"PaddlePaddle--devanagari_PP-OCRv5_mobile_rec")},
                    {"ta",rec(L"PaddlePaddle--ta_PP-OCRv5_mobile_rec")},{"te",rec(L"PaddlePaddle--te_PP-OCRv5_mobile_rec")}}}};
            if(fs::exists(root/L".tools/ocr-runtime/onnxruntime.dll")&&fs::exists(m/L"PaddlePaddle--PP-OCRv5_mobile_det/inference.onnx"))ocfg["ocr"]=t;
        }
        const auto cfg=data_dir/L"observer.json";{std::ofstream f(cfg);f<<ocfg.dump();}
        std::vector<std::wstring> args{L"--consent",L"--config",cfg.wstring()};if(!follow.empty()){args.push_back(L"--follow");args.push_back(follow);}
        observer.start((exe_dir/L"lens-observer.exe").wstring(),args,[&](const std::string& line){
            ++observed;const auto req=json::parse(line,nullptr,false);if(!req.is_object()){++failed;return;}
            long long ms=0;const auto r=timed_ask(req,ms);if(r&&r->value("ok",false))++stored;else ++failed;
            note_capture("screen",req,r,ms);
        });
        if(speech.child.running())observer.send("hold_ocr");  // a spoken reply is using the heavy-model budget
        log({{"event","observer_started"}});
    };
    auto stop_observer=[&]{std::lock_guard g(observer_lock);if(observer.running()){observer.stop();log({{"event","observer_stopped"}});}};
    // Resource governor (spec §15, 500 MB for the whole tree): the TTS worker never runs beside the engine's retrieval
    // models or the OCR worker. Speaking unloads the first and holds the second; any engine request that loads a model
    // stops the TTS worker first, which releases the OCR hold.
    speech.on_start=[&]{
        engine.ask({{"op","unload_models"}});
        std::lock_guard g(observer_lock);if(observer.running())observer.send("hold_ocr");
    };
    speech.on_stop=[&]{std::lock_guard g(observer_lock);if(observer.running())observer.send("release_ocr");};
    engine.before=[&](const json& r){
        static const std::set<std::string> loads_models{"recall","search","retrieve_context","index","ingest_audio"};
        if(r.is_object()&&loads_models.count(r.value("op",std::string())))speech.stop();
    };
    if(consent("observe_screen"))start_observer();

    // Voice capture (lens-voice): the default microphone, only while microphone consent is on and not paused. Speech
    // segments go to the engine as ingest_audio requests (transcribed on device, then the audio is discarded).
    Child voice;std::mutex voice_lock;std::atomic<long long> voiced=0;
    auto voice_running=[&]{std::lock_guard g(voice_lock);return voice.running();};
    auto start_voice=[&]{
        std::lock_guard g(voice_lock);if(voice.running()||paused)return;
        voice.stop();  // reap a previous run (e.g. the microphone went away) before reusing the child
        const auto model=root/L"models"/L"ggerganov--whisper.cpp"/L"ggml-base-q5_1.bin";
        if(!fs::exists(model)){log({{"event","voice_unavailable"},{"reason","model_missing"}});return;}
        std::vector<std::wstring> args{L"--consent",L"--model",model.wstring()};
        if(!voice_input.empty()){args.push_back(L"--input-wav");args.push_back(voice_input);}
        voice.start((exe_dir/L"lens-voice.exe").wstring(),args,[&](const std::string& line){
            const auto req=json::parse(line,nullptr,false);if(!req.is_object()){++failed;return;}
            long long ms=0;const auto r=timed_ask(req,ms);if(r&&r->value("ok",false))++voiced;else ++failed;
            note_capture("voice",req,r,ms);
        });
        log({{"event","voice_started"}});
    };
    auto stop_voice=[&]{std::lock_guard g(voice_lock);if(voice.running()){voice.stop();log({{"event","voice_stopped"}});}};
    if(consent("microphone"))start_voice();

    // Paired-device link (lens-mesh): a separate network-facing process, started only while phone_link consent is on.
    Child mesh;std::mutex mesh_lock;
    auto mesh_running=[&]{std::lock_guard g(mesh_lock);return mesh.running();};
    auto start_mesh=[&]{
        std::lock_guard g(mesh_lock);if(mesh.running())return;
        mesh.stop();
        mesh.start((exe_dir/L"lens-mesh.exe").wstring(),{L"--data-dir",data_dir.wstring(),L"--pipe-name",pipe_name,
                   L"--port",std::to_wstring(config.value("mesh_port",47821)),L"--bind",wide(config.value("mesh_bind",std::string("0.0.0.0")))});
        log({{"event","mesh_started"}});
    };
    auto stop_mesh=[&]{std::lock_guard g(mesh_lock);if(mesh.running()){mesh.stop();log({{"event","mesh_stopped"}});}};
    if(consent("phone_link"))start_mesh();

    std::atomic<bool> stopping=false;std::mutex wake_lock;std::condition_variable wake;
    std::thread consolidator([&]{  // periodic episode consolidation (derived memory; rebuildable)
        std::unique_lock l(wake_lock);
        while(!stopping) {
            wake.wait_for(l,std::chrono::minutes(std::max(1,config.value("consolidate_minutes",10))));
            if(stopping)break;
            if(const auto r=engine.ask({{"op","consolidate"}}))log({{"event","consolidated"},{"episodes",r->value("episodes",0)}});
            // Embed new observations for semantic recall (models load lazily and unload again when idle).
            if(semantic=="verified")for(int k=0;k<20&&!stopping;++k){const auto r=engine.ask({{"op","index"},{"limit",256}});if(!r||r->value("pending_sources",0)==0)break;}
        }
    });
    std::thread speech_idle([&]{  // the TTS worker exits after 60 s without a spoken reply
        std::unique_lock l(wake_lock);
        while(!stopping){
            wake.wait_for(l,std::chrono::seconds(5));
            int idle=60;{std::lock_guard g(config_lock);idle=std::max(1,config.value("speech_idle_seconds",60));}
            speech.stop_if_idle(std::chrono::seconds(idle));
        }
    });

    // Autostart at sign-in: a per-user Run value (no administrator rights, no service). It starts lens-app --background,
    // a GUI-subsystem launcher, so no console window appears; that starts this agent with its tray icon and exits.
    auto autostart_enabled=[&]{DWORD n=0;return RegGetValueW(HKEY_CURRENT_USER,autostart_key.c_str(),L"LensAgent",RRF_RT_REG_SZ,nullptr,nullptr,&n)==ERROR_SUCCESS;};
    auto set_autostart=[&](bool on)->bool {
        if(!on){const auto r=RegDeleteKeyValueW(HKEY_CURRENT_USER,autostart_key.c_str(),L"LensAgent");return r==ERROR_SUCCESS||r==ERROR_FILE_NOT_FOUND;}
        const std::wstring cmd=L"\""+(exe_dir/L"lens-app.exe").wstring()+L"\" --background"+explicit_args;
        return RegSetKeyValueW(HKEY_CURRENT_USER,autostart_key.c_str(),L"LensAgent",REG_SZ,cmd.c_str(),static_cast<DWORD>((cmd.size()+1)*sizeof(wchar_t)))==ERROR_SUCCESS;
    };
    // Pause holds every capture (screen and microphone) until resume; turning all capture consents off ends it.
    auto set_paused=[&](bool on)->json {
        if(on&&!paused&&!observer.running()&&!voice_running())return {{"ok",false},{"error","observer_not_running"}};
        paused=on;
        {std::lock_guard g(observer_lock);if(observer.running())observer.send(on?"pause":"resume");}
        if(on)stop_voice();
        else{if(consent("observe_screen"))start_observer();if(consent("microphone"))start_voice();}
        log({{"event",on?"paused":"resumed"}});
        return {{"ok",true},{"paused",paused.load()}};
    };

    lens::agent::imports::Jobs imports(data_dir/L"imports.json",[&](const json& r){return engine.ask(r);});

    auto handle=[&](const json& req)->json {
        const auto op=req.value("op",std::string());
        if(op=="status") {
            json observer_cfg;{std::lock_guard g(config_lock);observer_cfg=config.at("observer");}
            return {{"ok",true},{"observe_screen",consent("observe_screen")},{"observer_running",observer.running()},
            {"paused",paused.load()},{"observed",observed.load()},{"stored",stored.load()},{"failed",failed.load()},{"semantic",semantic},
            {"microphone",consent("microphone")},{"voice_running",voice_running()},{"voiced",voiced.load()},
            {"phone_link",consent("phone_link")},{"mesh_running",mesh_running()},{"onboarded",consent("onboarded")},
            {"exclusions",{{"excluded_processes",observer_cfg.value("excluded_processes",json::array())},
                           {"private_title_markers",observer_cfg.value("private_title_markers",json::array())}}},
            {"autostart",autostart_enabled()},{"tray",tray==Tray::icon?"icon":tray==Tray::hidden?"hidden":"none"},{"data_dir",utf8(data_dir.wstring())}};
        }
        if(op=="set_consent") {  // each consent is independent: screen observation, microphone, the paired-device link
            static const char* keys[]={"observe_screen","microphone","phone_link","onboarded"};
            bool any=false;for(const char* k:keys)if(req.contains(k)){any=true;if(!req[k].is_boolean())return {{"ok",false},{"error","invalid_request"}};}
            if(!any)return {{"ok",false},{"error","invalid_request"}};
            {std::lock_guard g(config_lock);for(const char* k:keys)if(req.contains(k))config[k]=req[k];}
            save_config();
            if(req.contains("observe_screen")){if(consent("observe_screen"))start_observer();else stop_observer();}
            if(req.contains("microphone")){if(consent("microphone"))start_voice();else stop_voice();}
            if(req.contains("phone_link")){if(consent("phone_link"))start_mesh();else stop_mesh();}
            if(!consent("observe_screen")&&!consent("microphone"))paused=false;
            return {{"ok",true},{"observe_screen",consent("observe_screen")},{"microphone",consent("microphone")},
                    {"phone_link",consent("phone_link")},{"onboarded",consent("onboarded")}};
        }
        if(op=="set_exclusions") {  // the user's additions; the observer's built-in exclusions always apply as well
            json lists=json::object();
            for(const char* k:{"excluded_processes","private_title_markers"}) {
                if(!req.contains(k))continue;const auto& v=req[k];
                if(!v.is_array()||v.size()>200)return {{"ok",false},{"error","invalid_request"}};
                json out=json::array();
                for(const auto& item:v) {
                    if(!item.is_string())return {{"ok",false},{"error","invalid_request"}};
                    auto t=item.get<std::string>();t.erase(0,t.find_first_not_of(" \t"));t.erase(t.find_last_not_of(" \t")+1);
                    if(t.empty()||t.size()>260||t.find_first_of("\r\n")!=std::string::npos)return {{"ok",false},{"error","invalid_request"}};
                    out.push_back(t);
                }
                lists[k]=out;
            }
            if(lists.empty())return {{"ok",false},{"error","invalid_request"}};
            {std::lock_guard g(config_lock);for(const auto& [k,v]:lists.items())config["observer"][k]=v;}
            save_config();
            bool restart=false;{std::lock_guard g(observer_lock);restart=observer.running();}
            if(restart){stop_observer();start_observer();}  // the new exclusions apply from the next capture
            json cfg;{std::lock_guard g(config_lock);cfg=config.at("observer");}
            return {{"ok",true},{"excluded_processes",cfg.value("excluded_processes",json::array())},{"private_title_markers",cfg.value("private_title_markers",json::array())}};
        }
        if(op=="set_autostart") {
            if(!req.contains("enabled")||!req["enabled"].is_boolean())return {{"ok",false},{"error","invalid_request"}};
            if(!set_autostart(req["enabled"].get<bool>()))return {{"ok",false},{"error","autostart_failed"}};
            return {{"ok",true},{"autostart",autostart_enabled()}};
        }
        if(op=="mesh_pair_begin"||op=="mesh_devices"||op=="mesh_unpair"||op=="mesh_status") {
            std::lock_guard g(mesh_lock);if(!mesh.running())return {{"ok",false},{"error","phone_link_off"}};
            json control={{"op",op.substr(5)}};if(op=="mesh_unpair")control["fingerprint"]=req.value("fingerprint",std::string());
            const auto r=mesh.request(control.dump());return r?json::parse(*r,nullptr,false):json{{"ok",false},{"error","mesh_unavailable"}};
        }
        if(op=="pause"||op=="resume")return set_paused(op=="pause");
        if(op=="action_capabilities")return actions.capabilities();
        if(op=="action_pending")return actions.pending();
        if(op=="action_status")return actions.status(req.value("id",std::string()));
        if(op=="action_request"||op=="action_decide") {
            // Requests only create pending actions; approval comes from the user in the app (lens-mesh never forwards it).
            auto r=op=="action_request"?actions.request(req):actions.decide(req.value("id",std::string()),req.value("approve",false));
            if(r.value("ok",false)&&r.contains("action")) {
                const auto& a=r["action"];
                if(a.value("status","")=="executed"&&a["capability"]=="laptop.remember")
                    engine.ask({{"op","add"},{"consent",true},{"id",a["id"].get<std::string>()+"-memory"},{"text",a["params"]["text"]},{"language","und"},
                                {"timestamp",a.value("finished_utc",std::string())},{"device","laptop"},{"kind","note"},{"provenance","lens action "+a["id"].get<std::string>()}});
                engine.ask({{"op","add"},{"consent",true},{"id",a["id"].get<std::string>()+"-"+a["status"].get<std::string>()},{"language","en"},
                            {"text","Lens action "+a["capability"].get<std::string>()+" requested by "+a.value("requested_by",std::string())+": "+a["status"].get<std::string>()},
                            {"timestamp",a.contains("decided_utc")?a["decided_utc"]:a["requested_utc"]},{"device","laptop"},{"kind","action_audit"},
                            {"provenance","lens-agent action registry"},{"metadata",{{"action",a}}}});
            }
            return r;
        }
        if(op=="diagnostics") {  // real measurements only: process memory, capture telemetry, data folder sizes
            const auto procs=process_tree();unsigned long long ws=0,pv=0;
            for(const auto& p:procs){ws+=p["working_set"].get<unsigned long long>();pv+=p["private"].get<unsigned long long>();}
            json files=json::array();unsigned long long total=0;std::error_code ec;
            for(const auto& e:fs::directory_iterator(data_dir,ec)) {
                if(!e.is_regular_file(ec))continue;const auto b=e.file_size(ec);if(ec)continue;
                total+=b;files.push_back({{"name",utf8(e.path().filename().wstring())},{"bytes",b}});
            }
            json t;{std::lock_guard g(telemetry_lock);t=telemetry;}
            const auto up=std::chrono::duration_cast<std::chrono::seconds>(std::chrono::steady_clock::now()-started_at).count();
            return {{"ok",true},{"uptime_seconds",up},{"processes",procs},{"memory",{{"working_set",ws},{"private",pv},{"ceiling",500000000}}},
                    {"capture",t},{"observer_running",observer.running()},{"voice_running",voice_running()},{"mesh_running",mesh_running()},
                    {"paused",paused.load()},{"observed",observed.load()},{"stored",stored.load()},{"failed",failed.load()},{"voiced",voiced.load()},
                    {"semantic",semantic},{"storage",{{"data_dir",utf8(data_dir.wstring())},{"files",files},{"total_bytes",total}}}};
        }
        if(op=="import_preview")return imports.preview(req);
        if(op=="import_start")return imports.start(req);
        if(op=="import_status")return imports.status(req);
        if(op=="import_cancel")return imports.cancel(req);
        if(op=="import_delete")return imports.remove(req);
        if(op=="speak")return speech.speak(root,exe_dir,req);
        if(op=="shutdown"){stopping=true;wake.notify_all();return {{"ok",true}};}
        if(!passthrough.count(op))return {{"ok",false},{"error","unsupported_operation"}};
        const auto r=engine.ask(req);return r?*r:json{{"ok",false},{"error","engine_unavailable"}};
    };

    SECURITY_ATTRIBUTES sa{};if(!user_only_security(sa)){log({{"event","refused"},{"reason","security_descriptor_failed"}});return 1;}
    const std::wstring path=L"\\\\.\\pipe\\"+pipe_name;
    log({{"event","started"},{"pipe",utf8(path)},{"semantic",semantic},{"observe_screen",consent("observe_screen")}});
    auto poke_pipe=[&]{HANDLE poke=CreateFileW(path.c_str(),GENERIC_READ|GENERIC_WRITE,0,nullptr,OPEN_EXISTING,0,nullptr);if(poke!=INVALID_HANDLE_VALUE)CloseHandle(poke);};
    TrayHooks hooks{[&]{return handle({{"op","status"}});},[&](bool on){set_paused(on);},
        [&]{  // Open Lens: the app is a separate, short-lived process; closing it frees its WebView2 memory
            std::wstring cmd=L"\""+(exe_dir/L"lens-app.exe").wstring()+L"\" --pipe-name \""+pipe_name+L"\"";
            STARTUPINFOW si{};si.cb=sizeof si;PROCESS_INFORMATION pi{};
            if(CreateProcessW(nullptr,cmd.data(),nullptr,nullptr,FALSE,0,nullptr,nullptr,&si,&pi)){CloseHandle(pi.hThread);CloseHandle(pi.hProcess);}
        },
        [&]{handle({{"op","shutdown"}});poke_pipe();}};
    std::atomic<HWND> tray_window=nullptr;std::atomic<bool> tray_ready=false;std::thread tray_thread;
    if(tray!=Tray::none)tray_thread=std::thread([&]{run_tray(&hooks,tray==Tray::icon,pipe_name,tray_window,tray_ready);});
    std::vector<std::thread> clients;
    while(!stopping) {
        HANDLE pipe=CreateNamedPipeW(path.c_str(),PIPE_ACCESS_DUPLEX,PIPE_TYPE_BYTE|PIPE_READMODE_BYTE|PIPE_WAIT|PIPE_REJECT_REMOTE_CLIENTS,
                                     PIPE_UNLIMITED_INSTANCES,1<<16,1<<16,0,&sa);
        if(pipe==INVALID_HANDLE_VALUE){log({{"event","pipe_failed"},{"error",static_cast<int>(GetLastError())}});break;}
        const BOOL connected=ConnectNamedPipe(pipe,nullptr)?TRUE:(GetLastError()==ERROR_PIPE_CONNECTED);
        if(!connected||stopping){CloseHandle(pipe);continue;}
        clients.emplace_back([&,pipe]{
            std::string pending;char buf[65536];DWORD n=0;
            while(!stopping&&ReadFile(pipe,buf,sizeof buf,&n,nullptr)&&n) {
                pending.append(buf,n);size_t pos;
                while((pos=pending.find('\n'))!=std::string::npos) {
                    const auto line=pending.substr(0,pos);pending.erase(0,pos+1);
                    const auto req=json::parse(line,nullptr,false);
                    json res;  // hostile or mistyped requests (e.g. a non-string "op") must never end the agent
                    try{res=req.is_object()?handle(req):json{{"ok",false},{"error","invalid_request"}};}
                    catch(...){res={{"ok",false},{"error","invalid_request"}};}
                    const auto out=res.dump()+"\n";DWORD w=0;WriteFile(pipe,out.data(),static_cast<DWORD>(out.size()),&w,nullptr);
                }
            }
            FlushFileBuffers(pipe);DisconnectNamedPipe(pipe);CloseHandle(pipe);
            if(stopping)poke_pipe();
        });
    }
    stopping=true;wake.notify_all();
    if(tray_thread.joinable()){while(!tray_ready)Sleep(10);if(HWND w=tray_window)PostMessageW(w,WM_CLOSE,0,0);tray_thread.join();}
    stop_mesh();stop_observer();stop_voice();  // the mesh holds a pipe connection of its own; stop children before joining clients
    for(auto& t:clients)if(t.joinable()){CancelSynchronousIo(t.native_handle());t.join();}  // unblock idle clients (e.g. an open app)
    consolidator.join();speech_idle.join();speech.child.stop();imports.cancel_all();engine.child.stop();
    LocalFree(sa.lpSecurityDescriptor);ReleaseMutex(single);CloseHandle(single);
    log({{"event","stopped"}});
    return 0;
}
