// lens-mesh: authenticated, encrypted link between the laptop's Lens memory and paired devices (docs/LENS_V1_SPEC.md
// §13 PAP mesh; Milestone 12). Network-facing code lives in this separate process; it reaches memory only through the
// agent's user-only pipe and only with a small allow-list of operations.
//
// Transport: TLS 1.3 only (OpenSSL), mutual authentication with self-signed P-256 certificates pinned by SHA-256
// fingerprint. Pairing: the laptop shows a QR payload {host, port, fingerprint, one-time token}; the phone connects
// pinned to that fingerprint, presents its own certificate and the token (valid 5 minutes, single use, compared in
// constant time). The device then waits until the user approves it on the laptop, where the same 8-digit verification
// code is shown as on the phone; only then is its fingerprint authorised. Unpaired peers can only pair. The private key
// is DPAPI-protected.
// Accounts: this laptop belongs to one Lens account (account.json, created with the identity). A device joins that
// account only by pairing; a device that already belongs to another account is refused, so no data ever passes
// between devices of different accounts. Paired status is checked on every request: revoking cuts open connections.
//
// Control (stdin/stdout JSON lines, from lens-agent): pair_begin | pending | approve {fingerprint} |
// deny {fingerprint} | devices | unpair {fingerprint} | status.
// Windows: the identity is DPAPI-protected and the agent is reached over its named pipe. macOS and Linux: the identity is
// sealed (AES-256-GCM) with a key derived from the per-user master key in the Keychain / Secret Service, and the agent is
// reached over its user-only Unix socket (agent/os.cpp).
#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#include <iphlpapi.h>
#include <windows.h>
#include <wincrypt.h>
#else
#include "../agent/os.hpp"
#include "../../adapters/posix/master_key.hpp"
#include <arpa/inet.h>
#include <ifaddrs.h>
#include <net/if.h>
#include <netinet/in.h>
#include <openssl/hmac.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>
#include <csignal>
using SOCKET=int;
constexpr SOCKET INVALID_SOCKET=-1;
inline int closesocket(SOCKET s){return ::close(s);}
#endif
#include <openssl/err.h>
#include <openssl/evp.h>
#include <openssl/pem.h>
#include <openssl/rand.h>
#include <openssl/ssl.h>
#include <openssl/x509.h>
#include <nlohmann/json.hpp>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <ctime>
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
std::string now_iso() {
    const auto t=std::time(nullptr);std::tm u{};
#ifdef _WIN32
    gmtime_s(&u,&t);
#else
    gmtime_r(&t,&u);
#endif
    char b[40];std::strftime(b,sizeof b,"%Y-%m-%dT%H:%M:%SZ",&u);return b;
}
fs::path from_utf8(const std::string& s){return fs::path(std::u8string(reinterpret_cast<const char8_t*>(s.data()),s.size()));}

// --- protected identity ----------------------------------------------------------------------------------------------
#ifdef _WIN32
const char* const IDENTITY_FILE="identity.dpapi";
std::string protect_identity(const std::string& in,bool protect) {  // DPAPI, this user only
    DATA_BLOB src{static_cast<DWORD>(in.size()),reinterpret_cast<BYTE*>(const_cast<char*>(in.data()))},out{};
    static const char entropy_text[]="Lens mesh identity v1";DATA_BLOB entropy{sizeof entropy_text,reinterpret_cast<BYTE*>(const_cast<char*>(entropy_text))};
    const BOOL ok=protect?CryptProtectData(&src,L"Lens mesh identity",&entropy,nullptr,nullptr,CRYPTPROTECT_UI_FORBIDDEN,&out)
                         :CryptUnprotectData(&src,nullptr,&entropy,nullptr,nullptr,CRYPTPROTECT_UI_FORBIDDEN,&out);
    if(!ok)throw std::runtime_error("dpapi_failed");
    std::string r(reinterpret_cast<char*>(out.pbData),out.cbData);SecureZeroMemory(out.pbData,out.cbData);LocalFree(out.pbData);return r;
}
#else
const char* const IDENTITY_FILE="identity.sealed";
// AES-256-GCM under HMAC-SHA256(per-user master key, "Lens mesh identity v1"); file = "LMI1" | IV (12) | ciphertext | tag (16).
std::string protect_identity(const std::string& in,bool protect) {
    auto master=lens::master_key(true);unsigned char k[EVP_MAX_MD_SIZE];unsigned klen=0;
    static const char info[]="Lens mesh identity v1";
    HMAC(EVP_sha256(),master.data(),static_cast<int>(master.size()),reinterpret_cast<const unsigned char*>(info),sizeof info-1,k,&klen);
    OPENSSL_cleanse(master.data(),master.size());
    std::string out;bool ok=false;EVP_CIPHER_CTX* c=EVP_CIPHER_CTX_new();
    auto u=[](std::string& s,size_t at){return reinterpret_cast<unsigned char*>(s.data())+at;};
    auto cu=[](const std::string& s,size_t at){return reinterpret_cast<const unsigned char*>(s.data())+at;};
    int n=0,m=0;
    if(protect) {
        unsigned char iv[12];RAND_bytes(iv,sizeof iv);
        out.assign("LMI1");out.append(reinterpret_cast<const char*>(iv),sizeof iv);out.resize(16+in.size()+16);
        ok=c&&EVP_EncryptInit_ex(c,EVP_aes_256_gcm(),nullptr,k,iv)==1&&EVP_EncryptUpdate(c,u(out,16),&n,cu(in,0),static_cast<int>(in.size()))==1
           &&EVP_EncryptFinal_ex(c,u(out,16+static_cast<size_t>(n)),&m)==1&&EVP_CIPHER_CTX_ctrl(c,EVP_CTRL_GCM_GET_TAG,16,u(out,16+in.size()))==1;
    } else if(in.size()>=32&&in.compare(0,4,"LMI1")==0) {
        const size_t len=in.size()-32;std::string tag=in.substr(in.size()-16);out.resize(len);
        ok=c&&EVP_DecryptInit_ex(c,EVP_aes_256_gcm(),nullptr,k,cu(in,4))==1&&EVP_DecryptUpdate(c,u(out,0),&n,cu(in,16),static_cast<int>(len))==1
           &&EVP_CIPHER_CTX_ctrl(c,EVP_CTRL_GCM_SET_TAG,16,tag.data())==1&&EVP_DecryptFinal_ex(c,u(out,static_cast<size_t>(n)),&m)==1;
    }
    EVP_CIPHER_CTX_free(c);OPENSSL_cleanse(k,sizeof k);
    if(!ok){OPENSSL_cleanse(out.data(),out.size());throw std::runtime_error("identity_unreadable");}
    return out;
}
#endif
struct Identity {EVP_PKEY* key=nullptr;X509* cert=nullptr;std::string fingerprint;};
std::string cert_fingerprint(X509* c){unsigned char d[EVP_MAX_MD_SIZE];unsigned n=0;X509_digest(c,EVP_sha256(),d,&n);return hex(d,n);}
Identity load_identity(const fs::path& dir) {
    const auto path=dir/IDENTITY_FILE;std::string pem;
    if(fs::exists(path)){std::ifstream f(path,std::ios::binary);std::string blob((std::istreambuf_iterator<char>(f)),{});pem=protect_identity(blob,false);}
    else {
        EVP_PKEY* key=EVP_PKEY_Q_keygen(nullptr,nullptr,"EC","P-256");X509* x=X509_new();
        X509_set_version(x,2);unsigned char serial[16];RAND_bytes(serial,16);BIGNUM* bn=BN_bin2bn(serial,16,nullptr);BN_to_ASN1_INTEGER(bn,X509_get_serialNumber(x));BN_free(bn);
        X509_gmtime_adj(X509_getm_notBefore(x),-3600);X509_gmtime_adj(X509_getm_notAfter(x),60L*60*24*365*20);X509_set_pubkey(x,key);
        X509_NAME* name=X509_get_subject_name(x);X509_NAME_add_entry_by_txt(name,"CN",MBSTRING_ASC,reinterpret_cast<const unsigned char*>("Lens laptop"),-1,-1,0);
        X509_set_issuer_name(x,name);X509_sign(x,key,EVP_sha256());
        BIO* b=BIO_new(BIO_s_mem());PEM_write_bio_PrivateKey(b,key,nullptr,nullptr,0,nullptr,nullptr);PEM_write_bio_X509(b,x);
        char* data=nullptr;const long n=BIO_get_mem_data(b,&data);pem.assign(data,static_cast<size_t>(n));BIO_free(b);EVP_PKEY_free(key);X509_free(x);
        const auto blob=protect_identity(pem,true);fs::create_directories(dir);
        {std::ofstream f(path,std::ios::binary);f.write(blob.data(),static_cast<std::streamsize>(blob.size()));}
        std::error_code ec;fs::permissions(path,fs::perms::owner_read|fs::perms::owner_write,ec);
    }
    Identity id;BIO* b=BIO_new_mem_buf(pem.data(),static_cast<int>(pem.size()));
    id.key=PEM_read_bio_PrivateKey(b,nullptr,nullptr,nullptr);id.cert=PEM_read_bio_X509(b,nullptr,nullptr,nullptr);BIO_free(b);
    OPENSSL_cleanse(pem.data(),pem.size());
    if(!id.key||!id.cert)throw std::runtime_error("identity_unreadable");
    id.fingerprint=cert_fingerprint(id.cert);return id;
}

// --- Lens account ---------------------------------------------------------------------------------------------------
bool is_hex(const std::string& s,size_t n){return s.size()==n&&std::all_of(s.begin(),s.end(),[](char c){return (c>='0'&&c<='9')||(c>='a'&&c<='f');});}
std::string load_account(const fs::path& dir) {
    const auto path=dir/"account.json";
    if(fs::exists(path)){std::ifstream f(path);const auto j=json::parse(f,nullptr,false);if(j.is_object()&&is_hex(j.value("account_id",std::string()),32))return j["account_id"];throw std::runtime_error("account_unreadable");}
    unsigned char r[16];RAND_bytes(r,16);const auto id=hex(r,16);
    fs::create_directories(dir);std::ofstream f(path);f<<json{{"account_id",id},{"created_utc",now_iso()}}.dump(1);return id;
}
// 8 digits shown on both screens before the user approves a new device: SHA-256(laptop fingerprint ":" device fingerprint).
std::string verification_code(const std::string& laptop,const std::string& device) {
    const auto text=laptop+":"+device;unsigned char d[32];unsigned n=0;EVP_Digest(text.data(),text.size(),d,&n,EVP_sha256(),nullptr);
    const unsigned long v=((static_cast<unsigned long>(d[0])<<24)|(static_cast<unsigned long>(d[1])<<16)|(static_cast<unsigned long>(d[2])<<8)|d[3])%100000000UL;
    char b[16];snprintf(b,sizeof b,"%04lu %04lu",v/10000,v%10000);return b;
}

// --- paired devices -------------------------------------------------------------------------------------------------
struct Devices {
    fs::path path;std::string account;std::mutex lock;json list=json::array();
    void load() {
        if(fs::exists(path)){std::ifstream f(path);list=json::parse(f,nullptr,false);if(!list.is_array())list=json::array();}
        for(auto& d:list)if(!d.contains("account_id"))d["account_id"]=account;  // paired to this laptop before accounts were recorded
    }
    void save(){std::ofstream f(path);f<<list.dump(1);}
    std::optional<json> find(const std::string& fp) {  // paired and in this laptop's account
        std::lock_guard g(lock);
        for(const auto& d:list)if(d.value("fingerprint","")==fp&&d.value("account_id","")==account)return std::optional<json>(d);
        return std::nullopt;
    }
    void add(const std::string& fp,const std::string& name){std::lock_guard g(lock);list.push_back({{"fingerprint",fp},{"name",name},{"account_id",account},{"paired_utc",now_iso()}});save();}
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
// Devices that presented a valid token and wait for the user's approval on the laptop (5 minutes), and those denied.
struct Approvals {
    struct Request {std::string name,code,requested_utc;std::chrono::steady_clock::time_point expires;};
    std::mutex lock;std::map<std::string,Request> pending;std::set<std::string> denied;
    void add(const std::string& fp,const std::string& name,const std::string& code) {
        std::lock_guard g(lock);denied.erase(fp);pending[fp]={name,code,now_iso(),std::chrono::steady_clock::now()+std::chrono::minutes(5)};
    }
    std::optional<Request> take(const std::string& fp) {  // removes and returns a live request
        std::lock_guard g(lock);expire();const auto it=pending.find(fp);if(it==pending.end())return std::nullopt;
        auto r=it->second;pending.erase(it);return r;
    }
    bool waiting(const std::string& fp){std::lock_guard g(lock);expire();return pending.count(fp)>0;}
    json list() {
        std::lock_guard g(lock);expire();json out=json::array();
        for(const auto& [fp,r]:pending)out.push_back({{"fingerprint",fp},{"name",r.name},{"verification_code",r.code},{"requested_utc",r.requested_utc}});
        return out;
    }
private:
    void expire(){const auto now=std::chrono::steady_clock::now();for(auto it=pending.begin();it!=pending.end();)it=it->second.expires<now?pending.erase(it):std::next(it);}
};

// --- agent pipe -----------------------------------------------------------------------------------------------------
#ifdef _WIN32
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
#else
struct Agent {  // the agent's user-only Unix socket (agent/os.cpp checks the peer's user id)
    std::string name;std::mutex lock;std::unique_ptr<lens::agent::os::Connection> c;std::string buf;
    json ask(const json& req) {
        std::lock_guard g(lock);
        for(int attempt=0;attempt<2;++attempt) {
            if(!c)c=lens::agent::os::connect(name);
            if(!c)return {{"ok",false},{"error","agent_unavailable"}};
            if(c->write(req.dump()+"\n")) {
                size_t pos;
                while((pos=buf.find('\n'))==std::string::npos)if(!c->read_some(buf))break;
                if((pos=buf.find('\n'))!=std::string::npos){auto out=buf.substr(0,pos);buf.erase(0,pos+1);return json::parse(out,nullptr,false);}
            }
            c.reset();buf.clear();
        }
        return {{"ok",false},{"error","agent_unavailable"}};
    }
};
#endif

const std::set<std::string> remote_read={"ping","recall","search","episodes","episode_context","find_source","timeline","entities","entity_context","facts","projects","project_context"};
const std::set<std::string> remote_kinds={"note","voice_note","share","reminder","screen_observation"};  // screen: the phone's own
                                                                                                         // opt-in observer

#ifndef _WIN32
std::vector<std::string> local_ipv4() {  // up, non-loopback IPv4 addresses for the pairing code
    std::vector<std::string> out;ifaddrs* all=nullptr;
    if(getifaddrs(&all))return out;
    for(auto* a=all;a;a=a->ifa_next) {
        if(!a->ifa_addr||a->ifa_addr->sa_family!=AF_INET||!(a->ifa_flags&IFF_UP)||(a->ifa_flags&IFF_LOOPBACK))continue;
        char s[64];inet_ntop(AF_INET,&reinterpret_cast<sockaddr_in*>(a->ifa_addr)->sin_addr,s,sizeof s);out.push_back(s);
    }
    freeifaddrs(all);return out;
}
#else
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
#endif

int accept_any_peer(int,X509_STORE_CTX*){return 1;}  // self-signed peers; authorisation is by pinned fingerprint below

void receive_timeout(SOCKET s,int ms) {
#ifdef _WIN32
    const DWORD t=static_cast<DWORD>(ms);setsockopt(s,SOL_SOCKET,SO_RCVTIMEO,reinterpret_cast<const char*>(&t),sizeof t);
#else
    const timeval t{ms/1000,(ms%1000)*1000};setsockopt(s,SOL_SOCKET,SO_RCVTIMEO,&t,sizeof t);
#endif
}

int run(const std::vector<std::string>& argv);
}

#ifdef _WIN32
int wmain(int argc,wchar_t** argv) {  // arguments as UTF-8
    std::vector<std::string> args;
    for(int i=0;i<argc;++i){const auto u=fs::path(argv[i]).u8string();args.emplace_back(reinterpret_cast<const char*>(u.data()),u.size());}
    return run(args);
}
#else
int main(int argc,char** argv){return run(std::vector<std::string>(argv,argv+argc));}
#endif

namespace {
int run(const std::vector<std::string>& argv) {
    fs::path data_dir;std::string pipe,bind="0.0.0.0";int port=0;
    for(size_t i=1;i<argv.size();++i) {
        const auto& a=argv[i];auto next=[&]{return i+1<argv.size()?argv[++i]:std::string();};
        if(a=="--data-dir")data_dir=from_utf8(next());else if(a=="--pipe-name")pipe=next();else if(a=="--port")port=std::stoi(next());
        else if(a=="--bind")bind=next();
        else {std::cerr<<"usage: lens-mesh --data-dir <dir> --pipe-name <agent pipe> [--port N] [--bind addr]\n";return 2;}
    }
    if(data_dir.empty()||pipe.empty())return 2;
#ifdef _WIN32
    WSADATA wsa;WSAStartup(MAKEWORD(2,2),&wsa);
#else
    std::signal(SIGPIPE,SIG_IGN);  // a phone that disconnects mid-reply must not end the service
#endif
    Identity id;std::string account;
    try{id=load_identity(data_dir/"mesh");account=load_account(data_dir/"mesh");}catch(const std::exception& e){log({{"event","refused"},{"reason",e.what()}});return 1;}
    Devices devices;devices.path=data_dir/"mesh"/"devices.json";devices.account=account;devices.load();
    Pairing pairing;Approvals approvals;Agent agent;
#ifdef _WIN32
    agent.name=from_utf8(pipe).wstring();
#else
    agent.name=pipe;
#endif

    SSL_CTX* ctx=SSL_CTX_new(TLS_server_method());
    SSL_CTX_set_min_proto_version(ctx,TLS1_3_VERSION);SSL_CTX_use_certificate(ctx,id.cert);SSL_CTX_use_PrivateKey(ctx,id.key);
    SSL_CTX_set_verify(ctx,SSL_VERIFY_PEER|SSL_VERIFY_FAIL_IF_NO_PEER_CERT,accept_any_peer);

    SOCKET listener=socket(AF_INET,SOCK_STREAM,IPPROTO_TCP);sockaddr_in addr{};addr.sin_family=AF_INET;addr.sin_port=htons(static_cast<std::uint16_t>(port));
    inet_pton(AF_INET,bind.c_str(),&addr.sin_addr);
#ifdef _WIN32
    BOOL exclusive=TRUE;setsockopt(listener,SOL_SOCKET,SO_EXCLUSIVEADDRUSE,reinterpret_cast<const char*>(&exclusive),sizeof exclusive);
    int alen=sizeof addr;
#else
    socklen_t alen=sizeof addr;
#endif
    if(::bind(listener,reinterpret_cast<sockaddr*>(&addr),sizeof addr)||listen(listener,16)){log({{"event","refused"},{"reason","listen_failed"}});return 1;}
    getsockname(listener,reinterpret_cast<sockaddr*>(&addr),&alen);port=ntohs(addr.sin_port);
    log({{"event","listening"},{"port",port},{"fingerprint",id.fingerprint}});
    std::atomic<bool> stopping=false;std::atomic<int> connections=0;

    auto serve=[&](SOCKET s) {
        ++connections;receive_timeout(s,120000);
        SSL* ssl=SSL_new(ctx);SSL_set_fd(ssl,static_cast<int>(s));
        if(SSL_accept(ssl)==1) {
            X509* peer=SSL_get1_peer_certificate(ssl);const std::string fp=peer?cert_fingerprint(peer):"";X509_free(peer);
            std::string pending;char buf[16384];int n=0;
            auto send=[&](const json& j){const auto t=j.dump()+"\n";SSL_write(ssl,t.data(),static_cast<int>(t.size()));};
            while(!stopping&&(n=SSL_read(ssl,buf,sizeof buf))>0) {
                pending.append(buf,static_cast<size_t>(n));
                if(pending.size()>(1u<<20)){send({{"ok",false},{"error","request_too_large"}});break;}
                size_t pos;
                while((pos=pending.find('\n'))!=std::string::npos) {
                    const auto req=json::parse(pending.substr(0,pos),nullptr,false);pending.erase(0,pos+1);
                    try {  // mistyped fields from any peer (paired or not) must never end the service
                    const auto op=req.is_object()&&req.contains("op")&&req["op"].is_string()?req["op"].get<std::string>():std::string();
                    const auto device=devices.find(fp);  // every request: a revoked device loses an open connection too
                    if(op=="pair") {
                        const auto name=req.value("name",std::string("Phone")).substr(0,64);
                        const auto device_account=req.value("account_id",std::string());
                        if(fp.empty()||!pairing.consume(req.value("token",std::string()))){send({{"ok",false},{"error","pairing_refused"}});log({{"event","pairing_refused"}});continue;}
                        if(!device_account.empty()&&device_account!=account){send({{"ok",false},{"error","account_mismatch"}});log({{"event","pairing_refused"},{"reason","account_mismatch"}});continue;}
                        if(device){send({{"ok",true},{"paired",true},{"account_id",account},{"laptop_fingerprint",id.fingerprint}});continue;}
                        const auto code=verification_code(id.fingerprint,fp);approvals.add(fp,name,code);
                        send({{"ok",true},{"paired",false},{"awaiting_approval",true},{"verification_code",code},{"expires_in_seconds",300},{"laptop_fingerprint",id.fingerprint}});
                        log({{"event","pairing_awaiting_approval"}});continue;
                    }
                    if(op=="pair_status") {  // the phone waits here while the user decides on the laptop
                        if(device)send({{"ok",true},{"paired",true},{"account_id",account},{"laptop_fingerprint",id.fingerprint}});
                        else if(approvals.waiting(fp))send({{"ok",true},{"paired",false},{"awaiting_approval",true}});
                        else {bool denied=false;{std::lock_guard g(approvals.lock);denied=approvals.denied.count(fp)>0;}send({{"ok",false},{"error",denied?"pairing_denied":"not_paired"}});}
                        continue;
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
                        a["consent_context"]={{"mode",kind=="screen_observation"?"paired_device_screen":"paired_device"},{"device_fingerprint",fp}};
                        a["source_application"]="lens-companion";
                        if(kind=="screen_observation") {  // the observed Android app, when it is a plausible package name
                            const auto meta=a.value("metadata",json::object());const auto pkg=meta.is_object()?meta.value("package",std::string()):std::string();
                            if(!pkg.empty()&&pkg.size()<=128&&std::all_of(pkg.begin(),pkg.end(),[](char c){return std::isalnum(static_cast<unsigned char>(c))||c=='.'||c=='_';}))
                                a["source_application"]="android:"+pkg;
                        }
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
        else if(op=="pending")reply({{"ok",true},{"pending",approvals.list()}});
        else if(op=="approve"||op=="deny") {  // the user's decision in the Lens app; never available to a device
            const auto fp=req.value("fingerprint",std::string());const auto r=approvals.take(fp);
            if(!r){reply({{"ok",false},{"error","no_pending_request"}});continue;}
            if(op=="approve"){devices.add(fp,r->name);log({{"event","paired"}});}
            else {std::lock_guard g(approvals.lock);approvals.denied.insert(fp);log({{"event","pairing_denied"}});}
            reply({{"ok",true},{"fingerprint",fp},{"paired",op=="approve"}});
        }
        else if(op=="devices"){std::lock_guard g(devices.lock);reply({{"ok",true},{"devices",devices.list}});}
        else if(op=="unpair")reply({{"ok",true},{"removed",devices.remove(req.value("fingerprint",std::string()))}});
        else if(op=="status")reply({{"ok",true},{"port",port},{"fingerprint",id.fingerprint},{"account_id",account},{"connections",connections.load()}});
        else reply({{"ok",false},{"error","unsupported_operation"}});
    }
    stopping=true;
#ifdef _WIN32
    closesocket(listener);acceptor.join();
    SSL_CTX_free(ctx);EVP_PKEY_free(id.key);X509_free(id.cert);WSACleanup();
#else
    shutdown(listener,SHUT_RDWR);closesocket(listener);acceptor.detach();  // closing does not always wake accept(); exiting does
#endif
    return 0;
}
}
