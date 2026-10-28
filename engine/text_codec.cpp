#include "text_codec.hpp"
#include "input.hpp"
#include "sql.hpp"
#include <sqlcipher/sqlite3.h>
#include <zstd.h>
#include <zdict.h>
#include <openssl/evp.h>
#include <iomanip>
#include <sstream>
#include <vector>

namespace lens {
namespace {
constexpr size_t min_bytes=256;constexpr int level=3;

void lens_text(sqlite3_context* ctx,int,sqlite3_value** argv) {
    if(sqlite3_value_type(argv[1])==SQLITE_NULL){sqlite3_result_value(ctx,argv[0]);return;}
    try {
        const auto* codec=static_cast<const TextCodec*>(sqlite3_user_data(ctx));
        const auto text=codec->decode(sqlite3_value_int(argv[1]),sqlite3_value_blob(argv[2]),static_cast<size_t>(sqlite3_value_bytes(argv[2])));
        sqlite3_result_text64(ctx,text.data(),text.size(),SQLITE_TRANSIENT,SQLITE_UTF8);
    } catch(...) {sqlite3_result_error(ctx,"text_decode_failed",-1);}
}

std::string sha256(const void* data,size_t n) {
    unsigned char out[EVP_MAX_MD_SIZE]{};size_t len{};
    if(!EVP_Q_digest(nullptr,"SHA256",nullptr,data,n,out,&len))throw Error("hash_failed");
    std::ostringstream s;for(size_t i=0;i<len;++i)s<<std::hex<<std::setfill('0')<<std::setw(2)<<static_cast<unsigned>(out[i]);return s.str();
}
}

TextCodec::~TextCodec() {
    for(auto& [_,c]:cdicts_)ZSTD_freeCDict(c);
    for(auto& [_,d]:ddicts_)ZSTD_freeDDict(d);
}

void TextCodec::register_sql(sqlite3* db) {
    sql::check(sqlite3_create_function_v2(db,"lens_text",3,SQLITE_UTF8|SQLITE_DETERMINISTIC|SQLITE_INNOCUOUS,this,lens_text,nullptr,nullptr,nullptr));
}

void TextCodec::load_dictionaries(sqlite3* db) {
    std::lock_guard g(lock_);
    sql::Statement s(db,"SELECT id,data FROM text_dictionaries ORDER BY id;");
    while(s.step()==SQLITE_ROW) {
        const int id=sqlite3_column_int(s.p,0);if(ddicts_.count(id))continue;
        const void* data=sqlite3_column_blob(s.p,1);const size_t n=static_cast<size_t>(sqlite3_column_bytes(s.p,1));
        ddicts_[id]=ZSTD_createDDict(data,n);cdicts_[id]=ZSTD_createCDict(data,n,level);latest_=std::max(latest_,id);
        if(!ddicts_[id]||!cdicts_[id])throw Error("dictionary_load_failed");
    }
}

std::optional<TextCodec::Encoded> TextCodec::encode(const std::string& text) const {
    if(text.size()<min_bytes)return std::nullopt;
    std::lock_guard g(lock_);
    std::string out(ZSTD_compressBound(text.size()),'\0');size_t n=0;
    std::unique_ptr<ZSTD_CCtx,decltype(&ZSTD_freeCCtx)> cctx(ZSTD_createCCtx(),ZSTD_freeCCtx);
    if(latest_>0)n=ZSTD_compress_usingCDict(cctx.get(),out.data(),out.size(),text.data(),text.size(),cdicts_.at(latest_));
    else n=ZSTD_compressCCtx(cctx.get(),out.data(),out.size(),text.data(),text.size(),level);
    if(ZSTD_isError(n)||n>text.size()*85/100)return std::nullopt;
    out.resize(n);return Encoded{latest_,std::move(out)};
}

std::string TextCodec::decode(int codec,const void* data,size_t size) const {
    const auto content=ZSTD_getFrameContentSize(data,size);
    if(content==ZSTD_CONTENTSIZE_ERROR||content==ZSTD_CONTENTSIZE_UNKNOWN||content>(64u<<20))throw Error("text_decode_failed");
    std::string out(static_cast<size_t>(content),'\0');size_t n=0;
    std::unique_ptr<ZSTD_DCtx,decltype(&ZSTD_freeDCtx)> dctx(ZSTD_createDCtx(),ZSTD_freeDCtx);
    if(codec==0)n=ZSTD_decompressDCtx(dctx.get(),out.data(),out.size(),data,size);
    else {
        std::lock_guard g(lock_);const auto it=ddicts_.find(codec);if(it==ddicts_.end())throw Error("dictionary_missing");
        n=ZSTD_decompress_usingDDict(dctx.get(),out.data(),out.size(),data,size,it->second);
    }
    if(ZSTD_isError(n)||n!=out.size())throw Error("text_decode_failed");
    return out;
}

int TextCodec::train(sqlite3* db,int samples,int dictionary_bytes) {
    std::string buffer;std::vector<size_t> sizes;
    {sql::Statement s(db,"SELECT lens_text(text,text_codec,text_zstd) FROM observations ORDER BY rowid DESC LIMIT ?;");
     sql::check(sqlite3_bind_int(s.p,1,samples));
     while(s.step()==SQLITE_ROW){const auto t=s.text(0);if(t.size()<64)continue;buffer+=t;sizes.push_back(t.size());}}
    if(sizes.size()<100)throw Error("insufficient_samples");
    std::string dict(static_cast<size_t>(dictionary_bytes),'\0');
    const size_t n=ZDICT_trainFromBuffer(dict.data(),dict.size(),buffer.data(),sizes.data(),static_cast<unsigned>(sizes.size()));
    if(ZDICT_isError(n))throw Error("dictionary_training_failed");
    dict.resize(n);
    sql::Statement ins(db,"INSERT INTO text_dictionaries(created_at,sha256,data) VALUES(strftime('%Y-%m-%dT%H:%M:%fZ','now'),?,?);");
    ins.text(1,sha256(dict.data(),dict.size()));sql::check(sqlite3_bind_blob(ins.p,2,dict.data(),static_cast<int>(dict.size()),SQLITE_TRANSIENT));ins.step();
    const int id=static_cast<int>(sqlite3_last_insert_rowid(db));
    load_dictionaries(db);return id;
}

long long TextCodec::retire_dictionaries(sqlite3* db) {
    {sql::Statement any(db,"SELECT count(*) FROM text_dictionaries;");any.step();if(sqlite3_column_int64(any.p,0)==0)return 0;}
    {std::lock_guard g(lock_);latest_=0;}
    // Originals are immutable (trigger observations_immutable). This storage-only rewrite is the one exception: it runs
    // inside the deleting transaction and writes a new encoding only after it decodes to exactly the stored text.
    sql::exec(db,"DROP TRIGGER observations_immutable;");
    long long moved=0;
    sql::Statement up(db,"UPDATE observations SET text=?,text_codec=?,text_zstd=? WHERE rowid=?;");
    for(;;) {  // bounded batches keep memory flat however many rows used a dictionary
        std::vector<std::pair<long long,std::string>> batch;
        {sql::Statement s(db,"SELECT rowid,lens_text(text,text_codec,text_zstd) FROM observations WHERE text_codec>0 LIMIT 256;");
         while(s.step()==SQLITE_ROW){const auto* t=reinterpret_cast<const char*>(sqlite3_column_text(s.p,1));
             batch.emplace_back(sqlite3_column_int64(s.p,0),std::string(t?t:"",static_cast<size_t>(sqlite3_column_bytes(s.p,1))));}}
        if(batch.empty())break;
        for(const auto& [rowid,text]:batch) {
            sqlite3_reset(up.p);
            if(const auto e=encode(text)) {
                if(e->codec!=0||decode(0,e->blob.data(),e->blob.size())!=text)throw Error("text_reencode_failed");
                up.text(1,std::string());sql::check(sqlite3_bind_int(up.p,2,0));
                sql::check(sqlite3_bind_blob(up.p,3,e->blob.data(),static_cast<int>(e->blob.size()),SQLITE_TRANSIENT));
            } else {up.text(1,text);sql::check(sqlite3_bind_null(up.p,2));sql::check(sqlite3_bind_null(up.p,3));}
            sql::check(sqlite3_bind_int64(up.p,4,rowid));up.step();++moved;
        }
    }
    sql::exec(db,"CREATE TRIGGER observations_immutable BEFORE UPDATE ON observations BEGIN SELECT RAISE(ABORT,'immutable'); END;"
                 "DELETE FROM text_dictionaries;");
    return moved;
}
}
