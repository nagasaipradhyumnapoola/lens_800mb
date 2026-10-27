// lens-mesh: authenticated, encrypted link between the laptop's Lens memory and paired devices (docs/LENS_V1_SPEC.md
// §13 PAP mesh; Milestone 12). Network-facing code lives in this separate process; it reaches memory only through the
// agent's user-only pipe and only with a small allow-list of operations.
//
// Transport: TLS 1.3 only (OpenSSL), mutual authentication with self-signed P-256 certificates pinned by SHA-256
// fingerprint. Pairing: the laptop shows a QR payload {host, port, fingerprint, one-time token}; the phone connects
// pinned to that fingerprint, presents its own certificate and the token (valid 5 minutes, single use, compared in
// constant time); its fingerprint is then authorised. Unpaired peers can only pair. The private key is DPAPI-protected.
//
// Control (stdin/stdout JSON lines, from lens-agent): pair_begin | devices | unpair {fingerprint} | status.
#include <winsock2.h>
#include <ws2tcpip.h>
#include <iphlpapi.h>
#include <windows.h>
#include <wincrypt.h>
#include <openssl/err.h>
#include <openssl/evp.h>
#include <openssl/pem.h>
#include <openssl/rand.h>
#include <openssl/ssl.h>
#include <openssl/x509.h>
#include <nlohmann/json.hpp>
#include <atomic>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <optional>
#include <mutex>
#include <set>
#include <string>
#include <thread>
#include <vector>

namespace fs=std::filesystem;
using json=nlohmann::json;

namespace {
std::mutex io_lock;
void log(const json& j){std::lock_guard g(io_lock);std::cerr<<j.dump()<<'\n';std::cerr.flush();}
void reply(const json& j){std::lock_guard g(io_lock);std::cout<<j.dump()<<'\n';std::cout.flush();}
std::string hex(const unsigned char* d,size_t n){static const char* h="0123456789abcdef";std::string s;for(size_t i=0;i<n;++i){s+=h[d[i]>>4];s+=h[d[i]&15];}return s;}
std::string now_iso(){SYSTEMTIME t;GetSystemTime(&t);char b[40];snprintf(b,sizeof b,"%04u-%02u-%02uT%02u:%02u:%02uZ",t.wYear,t.wMonth,t.wDay,t.wHour,t.wMinute,t.wSecond);return b;}

// --- DPAPI-protected identity -------------------------------------------------------------------------------------
std::string dpapi(const std::string& in,bool protect) {
    DATA_BLOB src{static_cast<DWORD>(in.size()),reinterpret_cast<BYTE*>(const_cast<char*>(in.data()))},out{};
    static const char entropy_text[]="Lens mesh identity v1";DATA_BLOB entropy{sizeof entropy_text,reinterpret_cast<BYTE*>(const_cast<char*>(entropy_text))};
    const BOOL ok=protect?CryptProtectData(&src,L"Lens mesh identity",&entropy,nullptr,nullptr,CRYPTPROTECT_UI_FORBIDDEN,&out)
                         :CryptUnprotectData(&src,nullptr,&entropy,nullptr,nullptr,CRYPTPROTECT_UI_FORBIDDEN,&out);
    if(!ok)throw std::runtime_error("dpapi_failed");
    std::string r(reinterpret_cast<char*>(out.pbData),out.cbData);SecureZeroMemory(out.pbData,out.cbData);LocalFree(out.pbData);return r;
}
struct Identity {EVP_PKEY* key=nullptr;X509* cert=nullptr;std::string fingerprint;};
std::string cert_fingerprint(X509* c){unsigned char d[EVP_MAX_MD_SIZE];unsigned n=0;X509_digest(c,EVP_sha256(),d,&n);return hex(d,n);}
Identity load_identity(const fs::path& dir) {
    const auto path=dir/L"identity.dpapi";std::string pem;
    if(fs::exists(path)){std::ifstream f(path,std::ios::binary);std::string blob((std::istreambuf_iterator<char>(f)),{});pem=dpapi(blob,false);}
    else {
        EVP_PKEY* key=EVP_PKEY_Q_keygen(nullptr,nullptr,"EC","P-256");X509* x=X509_new();
        X509_set_version(x,2);unsigned char serial[16];RAND_bytes(serial,16);BIGNUM* bn=BN_bin2bn(serial,16,nullptr);BN_to_ASN1_INTEGER(bn,X509_get_serialNumber(x));BN_free(bn);
        X509_gmtime_adj(X509_getm_notBefore(x),-3600);X509_gmtime_adj(X509_getm_notAfter(x),60L*60*24*365*20);X509_set_pubkey(x,key);
        X509_NAME* name=X509_get_subject_name(x);X509_NAME_add_entry_by_txt(name,"CN",MBSTRING_ASC,reinterpret_cast<const unsigned char*>("Lens laptop"),-1,-1,0);
        X509_set_issuer_name(x,name);X509_sign(x,key,EVP_sha256());
        BIO* b=BIO_new(BIO_s_mem());PEM_write_bio_PrivateKey(b,key,nullptr,nullptr,0,nullptr,nullptr);PEM_write_bio_X509(b,x);
        char* data=nullptr;const long n=BIO_get_mem_data(b,&data);pem.assign(data,static_cast<size_t>(n));BIO_free(b);EVP_PKEY_free(key);X509_free(x);
        const auto blob=dpapi(pem,true);fs::create_directories(dir);std::ofstream f(path,std::ios::binary);f.write(blob.data(),static_cast<std::streamsize>(blob.size()));
    }
    Identity id;BIO* b=BIO_new_mem_buf(pem.data(),static_cast<int>(pem.size()));
    id.key=PEM_read_bio_PrivateKey(b,nullptr,nullptr,nullptr);id.cert=PEM_read_bio_X509(b,nullptr,nullptr,nullptr);BIO_free(b);
    OPENSSL_cleanse(pem.data(),pem.size());
    if(!id.key||!id.cert)throw std::runtime_error("identity_unreadable");
    id.fingerprint=cert_fingerprint(id.cert);return id;
}

// --- paired devices -------------------------------------------------------------------------------------------------
struct Devices {
    fs::path path;std::mutex lock;json list=json::array();
    void load(){if(fs::exists(path)){std::ifstream f(path);list=json::parse(f,nullptr,false);if(!list.is_array())list=json::array();}}
    void save(){std::ofstream f(path);f<<list.dump(1);}
    std::optional<json> find(const std::string& fp){std::lock_guard g(lock);for(const auto& d:list)if(d.value("fingerprint","")==fp)return std::optional<json>(d);return std::nullopt;}
    void add(const std::string& fp,const std::string& name){std::lock_guard g(lock);list.push_back({{"fingerprint",fp},{"name",name},{"paired_utc",now_iso()}});save();}
    bool remove(const std::string& fp){std::lock_guard g(lock);const auto n=list.size();
        list.erase(std::remove_if(list.begin(),list.end(),[&](const json& d){return d.value("fingerprint","")==fp;}),list.end());save();return list.size()!=n;}
};

// --- pairing token --------------------------------------------------------------------------------------------------
struct Pairing {std::mutex lock;std::string token;std::chrono::steady_clock::time_point expires{};
    std::string begin(){std::lock_guard g(lock);unsigned char r[16];RAND_bytes(r,16);token=hex(r,16);expires=std::chrono::steady_clock::now()+std::chrono::minutes(5);return token;}
    bool consume(const std::string& offered){
        std::lock_guard g(lock);
        const bool live=!token.empty()&&std::chrono::steady_clock::now()<expires&&offered.size()==token.size()&&CRYPTO_memcmp(offered.data(),token.data(),token.size())==0;
        if(live)token.clear();return live;}  // single use
};

// --- agent pipe -----------------------------------------------------------------------------------------------------
struct Agent {
    std::wstring name;std::mutex lock;HANDLE h=INVALID_HANDLE_VALUE;std::string buf;
    json ask(const json& req) {
        std::lock_guard g(lock);
        for(int attempt=0;attempt<2;++attempt) {
            if(h==INVALID_HANDLE_VALUE)h=CreateFileW((L"\\\\.\\pipe\\"+name).c_str(),GENERIC_READ|GENERIC_WRITE,0,nullptr,OPEN_EXISTING,0,nullptr);
            if(h==INVALID_HANDLE_VALUE)return {{"ok",false},{"error","agent_unavailable"}};
            const auto line=req.dump()+"\n";DWORD n=0;bool ok=WriteFile(h,line.data(),static_cast<DWORD>(line.size()),&n,nullptr);
            while(ok) {
                const auto pos=buf.find('\n');if(pos!=std::string::npos){auto out=buf.substr(0,pos);buf.erase(0,pos+1);return json::parse(out,nullptr,false);}
                char b[65536];ok=ReadFile(h,b,sizeof b,&n,nullptr)&&n;if(ok)buf.append(b,n);
            }
            CloseHandle(h);h=INVALID_HANDLE_VALUE;buf.clear();
        }
        return {{"ok",false},{"error","agent_unavailable"}};
    }
};

const std::set<std::string> remote_read={"ping","recall","search","episodes","episode_context","find_source","timeline","entities","entity_context","facts","projects","project_context"};
const std::set<std::string> remote_kinds={"note","voice_note","share","reminder"};

std::vector<std::string> local_ipv4() {
    std::vector<std::string> out;ULONG size=15000;std::vector<BYTE> buf(size);
    auto* a=reinterpret_cast<IP_ADAPTER_ADDRESSES*>(buf.data());
    if(GetAdaptersAddresses(AF_INET,GAA_FLAG_SKIP_ANYCAST|GAA_FLAG_SKIP_MULTICAST|GAA_FLAG_SKIP_DNS_SERVER,nullptr,a,&size)!=NO_ERROR)return out;
    for(;a;a=a->Next) {
        if(a->OperStatus!=IfOperStatusUp||a->IfType==IF_TYPE_SOFTWARE_LOOPBACK)continue;
        for(auto* u=a->FirstUnicastAddress;u;u=u->Next){char s[64];inet_ntop(AF_INET,&reinterpret_cast<sockaddr_in*>(u->Address.lpSockaddr)->sin_addr,s,sizeof s);out.push_back(s);}
    }
    return out;
}

int accept_any_peer(int,X509_STORE_CTX*){return 1;}  // self-signed peers; authorisation is by pinned fingerprint below
}

int wmain(int argc,wchar_t** argv) {
    fs::path data_dir;std::wstring pipe=L"";std::string bind="0.0.0.0";int port=0;
    for(int i=1;i<argc;++i) {
        const std::wstring a=argv[i];auto next=[&]{return i+1<argc?std::wstring(argv[++i]):std::wstring();};
        if(a==L"--data-dir")data_dir=next();else if(a==L"--pipe-name")pipe=next();else if(a==L"--port")port=std::stoi(next());
        else if(a==L"--bind"){const auto w=next();bind.assign(w.begin(),w.end());}
        else {std::cerr<<"usage: lens-mesh --data-dir <dir> --pipe-name <agent pipe> [--port N] [--bind addr]\n";return 2;}
    }
    if(data_dir.empty()||pipe.empty())return 2;
    WSADATA wsa;WSAStartup(MAKEWORD(2,2),&wsa);
    Identity id;try{id=load_identity(data_dir/L"mesh");}catch(const std::exception& e){log({{"event","refused"},{"reason",e.what()}});return 1;}
    Devices devices;devices.path=data_dir/L"mesh"/L"devices.json";devices.load();
    Pairing pairing;Agent agent;agent.name=pipe;

    SSL_CTX* ctx=SSL_CTX_new(TLS_server_method());
    SSL_CTX_set_min_proto_version(ctx,TLS1_3_VERSION);SSL_CTX_use_certificate(ctx,id.cert);SSL_CTX_use_PrivateKey(ctx,id.key);
    SSL_CTX_set_verify(ctx,SSL_VERIFY_PEER|SSL_VERIFY_FAIL_IF_NO_PEER_CERT,accept_any_peer);

    SOCKET listener=socket(AF_INET,SOCK_STREAM,IPPROTO_TCP);sockaddr_in addr{};addr.sin_family=AF_INET;addr.sin_port=htons(static_cast<u_short>(port));
    inet_pton(AF_INET,bind.c_str(),&addr.sin_addr);
    BOOL exclusive=TRUE;setsockopt(listener,SOL_SOCKET,SO_EXCLUSIVEADDRUSE,reinterpret_cast<const char*>(&exclusive),sizeof exclusive);
    if(::bind(listener,reinterpret_cast<sockaddr*>(&addr),sizeof addr)||listen(listener,16)){log({{"event","refused"},{"reason","listen_failed"}});return 1;}
    int alen=sizeof addr;getsockname(listener,reinterpret_cast<sockaddr*>(&addr),&alen);port=ntohs(addr.sin_port);
    log({{"event","listening"},{"port",port},{"fingerprint",id.fingerprint}});
    std::atomic<bool> stopping=false;std::atomic<int> connections=0;

    auto serve=[&](SOCKET s) {
        ++connections;DWORD timeout=120000;setsockopt(s,SOL_SOCKET,SO_RCVTIMEO,reinterpret_cast<const char*>(&timeout),sizeof timeout);
        SSL* ssl=SSL_new(ctx);SSL_set_fd(ssl,static_cast<int>(s));
        if(SSL_accept(ssl)==1) {
            X509* peer=SSL_get1_peer_certificate(ssl);const std::string fp=peer?cert_fingerprint(peer):"";X509_free(peer);
            auto device=devices.find(fp);std::string pending;char buf[16384];int n=0;
            auto send=[&](const json& j){const auto t=j.dump()+"\n";SSL_write(ssl,t.data(),static_cast<int>(t.size()));};
            while(!stopping&&(n=SSL_read(ssl,buf,sizeof buf))>0) {
                pending.append(buf,static_cast<size_t>(n));
                if(pending.size()>(1u<<20)){send({{"ok",false},{"error","request_too_large"}});break;}
                size_t pos;
                while((pos=pending.find('\n'))!=std::string::npos) {
                    const auto req=json::parse(pending.substr(0,pos),nullptr,false);pending.erase(0,pos+1);
                    try {  // mistyped fields from any peer (paired or not) must never end the service
                    const auto op=req.is_object()&&req.contains("op")&&req["op"].is_string()?req["op"].get<std::string>():std::string();
                    if(op=="pair") {
                        const auto name=req.value("name",std::string("Phone")).substr(0,64);
                        if(fp.empty()||!pairing.consume(req.value("token",std::string()))){send({{"ok",false},{"error","pairing_refused"}});log({{"event","pairing_refused"}});continue;}
                        if(!devices.find(fp))devices.add(fp,name);device=devices.find(fp);
                        send({{"ok",true},{"paired",true},{"laptop_fingerprint",id.fingerprint}});log({{"event","paired"},{"device",name}});continue;
                    }
                    if(!device){send({{"ok",false},{"error","not_paired"}});continue;}
                    if(op=="ping"){send({{"ok",true},{"device",device->at("name")}});continue;}
                    if(remote_read.count(op)){send(agent.ask(req));continue;}
                    if(op=="action_request"||op=="action_status") {  // devices may ask; only the user on the laptop approves
                        auto a=req;if(op=="action_request")a["requested_by"]="paired device "+device->at("name").get<std::string>();
                        send(agent.ask(a));continue;
                    }
                    if(op=="add") {  // phone contributions: provenance and device are set here, never by the phone
                        auto a=req;const auto kind=a.value("kind",std::string());
                        if(!a.value("consent",false)||!remote_kinds.count(kind)){send({{"ok",false},{"error","not_allowed"}});continue;}
                        a["device"]=device->at("name");a["provenance"]="lens-mesh paired device "+fp.substr(0,16);
                        a["consent_context"]={{"mode","paired_device"},{"device_fingerprint",fp}};a["source_application"]="lens-companion";
                        send(agent.ask(a));continue;
                    }
                    send({{"ok",false},{"error","unsupported_operation"}});
                    } catch(...) {send({{"ok",false},{"error","invalid_request"}});}
                }
            }
        }
        SSL_shutdown(ssl);SSL_free(ssl);closesocket(s);--connections;
    };
    std::thread acceptor([&]{
        while(!stopping) {
            SOCKET s=accept(listener,nullptr,nullptr);
            if(s==INVALID_SOCKET){if(stopping)break;continue;}
            std::thread(serve,s).detach();
        }
    });

    std::string line;  // control channel from the agent
    while(std::getline(std::cin,line)) {
        const auto req=json::parse(line,nullptr,false);const auto op=req.is_object()&&req.contains("op")&&req["op"].is_string()?req["op"].get<std::string>():std::string();
        if(op=="pair_begin") {
            const auto token=pairing.begin();const auto hosts=local_ipv4();
            reply({{"ok",true},{"qr",{{"v",1},{"hosts",hosts},{"port",port},{"fp",id.fingerprint},{"token",token}}},{"expires_in_seconds",300}});
        }
        else if(op=="devices"){std::lock_guard g(devices.lock);reply({{"ok",true},{"devices",devices.list}});}
        else if(op=="unpair")reply({{"ok",true},{"removed",devices.remove(req.value("fingerprint",std::string()))}});
        else if(op=="status")reply({{"ok",true},{"port",port},{"fingerprint",id.fingerprint},{"connections",connections.load()}});
        else reply({{"ok",false},{"error","unsupported_operation"}});
    }
    stopping=true;closesocket(listener);acceptor.join();
    SSL_CTX_free(ctx);EVP_PKEY_free(id.key);X509_free(id.cert);WSACleanup();
    return 0;
}
