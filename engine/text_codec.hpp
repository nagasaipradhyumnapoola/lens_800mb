#pragma once
// Lossless observation-text compression (docs/LENS_V1_SPEC.md §9; schema v6).
// Texts of at least 256 bytes are stored as an independent zstd frame (level 3), optionally with a trained dictionary,
// when that saves at least 15%; shorter or incompressible texts stay plain. Every row decodes on its own: no row
// depends on another, so deletion and sync never break other memories. SQL reads text through lens_text(text,
// text_codec,text_zstd), registered on the connection; content hashes are always computed on the original text.
#include <map>
#include <mutex>
#include <optional>
#include <string>
struct sqlite3;
struct ZSTD_CDict_s;struct ZSTD_DDict_s;

namespace lens {
class TextCodec {
public:
    TextCodec()=default;
    ~TextCodec();
    TextCodec(const TextCodec&)=delete;TextCodec& operator=(const TextCodec&)=delete;
    void register_sql(sqlite3* db);                   // lens_text(text,codec,blob)
    void load_dictionaries(sqlite3* db);              // after schema v6 exists
    struct Encoded {int codec;std::string blob;};     // codec 0 = zstd without dictionary, n = dictionary id
    std::optional<Encoded> encode(const std::string& text) const;
    std::string decode(int codec,const void* data,size_t size) const;
    int train(sqlite3* db,int samples,int dictionary_bytes);  // returns the new dictionary id
private:
    mutable std::mutex lock_;
    std::map<int,ZSTD_CDict_s*> cdicts_;std::map<int,ZSTD_DDict_s*> ddicts_;int latest_=0;
};
}
