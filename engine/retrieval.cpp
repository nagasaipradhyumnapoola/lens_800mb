#include "retrieval.hpp"
#include "memory_query.hpp"
#include "sql.hpp"
#include "temporal.hpp"
#include "query_understanding.hpp"
#include <optional>
#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <map>
#include <set>
#include <unordered_map>
namespace lens {
using json=nlohmann::json;using namespace sql;
namespace {
constexpr std::size_t single_chunk_bytes=1500,chunk_bytes=1200,chunk_overlap=200;
constexpr double rrf_k=60.0;
// Keyword evidence joins the fusion only when it covers most query units (chosen on the dev split).
constexpr double min_keyword_coverage=0.5;
// Hybrid abstention threshold on the best passage cosine, chosen on the dev split only
// at 10,000 events (reports/retrieval-nl/calibration/); test-split results never feed back into it.
constexpr double default_min_similarity=0.8309;
// Second-stage reranking defaults; decided by the dev-split benchmark (docs/retrieval.md).
constexpr bool default_center=true; // language-identity centering (10k v1: R@10 0.878 -> 0.969, English 0.79 -> 0.98)
// Abstention with centering, fitted on v1 dev + inspected split with 2-fold cross-validation
// (scripts/calibrate_abstention.py, reports/retrieval-nl/dev-experiments/abstention-cv.json); never on the holdout.
constexpr double default_min_centered_similarity=0.37;       // with reranker: answer if rerank or centered cosine clears
constexpr double default_min_rerank_centered=0.4;
constexpr double default_min_centered_similarity_no_rerank=0.35;
constexpr const char* default_rerank_fusion="replace"; // "rrf" pending benchmark on v1 + expansion
constexpr bool default_rerank=true;   // when a reranker is configured; hybrid alone otherwise
constexpr double default_min_rerank=-1.8282; // dev-split calibration, reports/retrieval-nl/m2-rerank/
bool continuation(unsigned char b){return (b&0xC0)==0x80;}
std::size_t char_start(const std::string& s,std::size_t i){while(i>0&&i<s.size()&&continuation(static_cast<unsigned char>(s[i])))--i;return i;}
std::size_t utf8_len(unsigned char b){return b<0x80?1:(b>>5)==6?2:(b>>4)==14?3:4;}
std::uint32_t code_point(const std::string& s,std::size_t i,std::size_t n){
    std::uint32_t cp=static_cast<unsigned char>(s[i])&(n==1?0x7F:n==2?0x1F:n==3?0x0F:0x07);
    for(std::size_t k=1;k<n&&i+k<s.size();++k)cp=(cp<<6)|(static_cast<unsigned char>(s[i+k])&0x3F);return cp;
}
bool unspaced_script(std::uint32_t cp){ // Han, kana, Hangul and Thai do not separate words with spaces
    return (cp>=0x4E00&&cp<=0x9FFF)||(cp>=0x3400&&cp<=0x4DBF)||(cp>=0x3040&&cp<=0x30FF)||(cp>=0xAC00&&cp<=0xD7AF)||
           (cp>=0x0E00&&cp<=0x0E7F)||(cp>=0x20000&&cp<=0x2FFFF)||(cp>=0xF900&&cp<=0xFAFF);
}
bool separator(std::uint32_t cp){
    if(cp<128)return !std::isalnum(static_cast<int>(cp));
    return cp==0x3000||cp==0x3001||cp==0x3002||cp==0xFF0C||cp==0xFF01||cp==0xFF1F||cp==0x0964||cp==0x0965||cp==0x00A0||
           cp==0x2014||cp==0x2013||cp==0x201C||cp==0x201D||cp==0x2018||cp==0x2019||cp==0xFF1A||cp==0xFF1B||cp==0x00BF||cp==0x00A1;
}
// Lexical units of a query: lowercase ASCII words (English stopwords removed), whole words of spaced
// scripts, and character bigrams of unspaced scripts so Chinese/Japanese/Korean/Thai can match substrings.
std::vector<std::string> units(const std::string& query){
    static const std::set<std::string> stop={"what","did","does","do","i","we","you","the","a","an","was","were","is","are","about",
        "say","said","tell","told","me","my","our","please","find","show","remember","that","which","where","when","wanted","want",
        "of","in","on","to","for","and","it","last","who","how","with","at","by","from","be","been","this","there","any","have","has",
        "de","la","el","en","y","que","los","las","del","un","una","por","con","se","es","mi","qué","cuándo","dónde"};
    std::vector<std::string> out;auto add=[&](const std::string& u){if(!u.empty()&&!stop.contains(u)&&std::find(out.begin(),out.end(),u)==out.end())out.push_back(u);};
    std::string word;std::vector<std::string> run;
    auto flush=[&]{
        if(!word.empty()){add(word);word.clear();}
        if(run.size()==1)add(run[0]);
        for(std::size_t i=0;i+1<run.size();++i)add(run[i]+run[i+1]);
        run.clear();
    };
    for(std::size_t i=0;i<query.size();){
        const auto n=std::min(utf8_len(static_cast<unsigned char>(query[i])),query.size()-i);const auto cp=code_point(query,i,n);
        if(separator(cp)){flush();}
        else if(unspaced_script(cp)){if(!word.empty()){add(word);word.clear();}run.push_back(query.substr(i,n));}
        else {if(!run.empty())flush();
            if(cp<128)word.push_back(static_cast<char>(std::tolower(static_cast<int>(cp))));else word+=query.substr(i,n);}
        i+=n;
    }
    flush();
    if(out.size()>32)out.resize(32);
    return out;
}
std::string excerpt(const std::string& text,std::size_t anchor,std::size_t& start,std::size_t& end){
    if(text.size()<=single_chunk_bytes){start=0;end=text.size();return text;}
    start=char_start(text,anchor>600?anchor-600:0);end=char_start(text,std::min(text.size(),start+single_chunk_bytes));
    if(end<=start)end=text.size();
    return text.substr(start,end-start);
}
// Decrypted vectors of one model, kept for the life of the engine process so repeated questions do not
// re-read and re-decrypt every vector page. Invalidated whenever the chunk count or newest chunk id changes
// (any index, delete or cascade). The cache is process memory only; nothing is written outside SQLCipher.
// Script groups for language-identity centering. Multilingual e5 embeddings carry a strong per-language
// component that makes unrelated text in another script outrank the right answer (docs/retrieval.md,
// reports/retrieval-nl/dev-experiments/embedding-centering.json). Centering each vector on its script group's
// mean removes that component; groups with too few stored vectors fall back to the global mean.
enum ScriptGroup:unsigned char {g_other,g_latn,g_han,g_kana,g_hang,g_deva,g_beng,g_guru,g_gujr,g_orya,g_taml,g_telu,g_knda,g_mlym,
                                g_thai,g_arab,g_cyrl,g_count};
constexpr std::size_t min_group_vectors=50;
unsigned char script_group(const std::string& s,std::size_t a,std::size_t b){
    std::array<std::size_t,g_count> counts{};
    for(std::size_t i=a;i<b&&i<s.size();){
        const auto n=std::min(utf8_len(static_cast<unsigned char>(s[i])),s.size()-i);const auto cp=code_point(s,i,n);i+=n;
        unsigned char g=g_other;
        if((cp<128&&std::isalpha(static_cast<int>(cp)))||(cp>=0xC0&&cp<=0x24F))g=g_latn;
        else if((cp>=0x4E00&&cp<=0x9FFF)||(cp>=0x3400&&cp<=0x4DBF))g=g_han;
        else if(cp>=0x3040&&cp<=0x30FF)g=g_kana;else if(cp>=0xAC00&&cp<=0xD7AF)g=g_hang;
        else if(cp>=0x0900&&cp<=0x097F)g=g_deva;else if(cp>=0x0980&&cp<=0x09FF)g=g_beng;else if(cp>=0x0A00&&cp<=0x0A7F)g=g_guru;
        else if(cp>=0x0A80&&cp<=0x0AFF)g=g_gujr;else if(cp>=0x0B00&&cp<=0x0B7F)g=g_orya;else if(cp>=0x0B80&&cp<=0x0BFF)g=g_taml;
        else if(cp>=0x0C00&&cp<=0x0C7F)g=g_telu;else if(cp>=0x0C80&&cp<=0x0CFF)g=g_knda;else if(cp>=0x0D00&&cp<=0x0D7F)g=g_mlym;
        else if(cp>=0x0E00&&cp<=0x0E7F)g=g_thai;else if(cp>=0x0600&&cp<=0x06FF)g=g_arab;else if(cp>=0x0400&&cp<=0x04FF)g=g_cyrl;
        if(g!=g_other)++counts[g];
    }
    unsigned char best=g_other;for(unsigned char g=1;g<g_count;++g)if(counts[g]>counts[best])best=g;
    return best;
}
struct VectorCache {
    sqlite3* db=nullptr;std::string model;std::int64_t count=-1,max_id=-1;
    std::vector<std::string> ids;std::vector<signed char> vectors;std::vector<float> scales;std::vector<std::size_t> starts,ends;
    // Centering: per-vector mean index (g_count = global mean) and 1/||p - mean||; means are float, one per group.
    std::vector<unsigned char> mean_of;std::vector<float> inv_centered_norm;
    std::vector<Embedding> means;std::array<std::size_t,g_count> group_size{};
};
const VectorCache& vector_cache(sqlite3* db,const std::string& model){
    static VectorCache cache;
    std::int64_t count,max_id;
    {Statement s(db,"SELECT count(*),coalesce(max(id),0) FROM embedding_chunks;");s.step();count=sqlite3_column_int64(s.p,0);max_id=sqlite3_column_int64(s.p,1);}
    if(cache.db==db&&cache.model==model&&cache.count==count&&cache.max_id==max_id)return cache;
    VectorCache fresh;fresh.db=db;fresh.model=model;fresh.count=count;fresh.max_id=max_id;
    Statement s(db,"SELECT e.source_id,e.byte_start,e.byte_end,e.scale,e.vector,lens_text(o.text,o.text_codec,o.text_zstd) FROM embedding_chunks e JOIN observations o ON o.id=e.source_id WHERE e.model=?;");s.text(1,model);
    std::vector<unsigned char> groups;
    while(s.step()==SQLITE_ROW){
        const auto text=s.text(5);groups.push_back(script_group(text,static_cast<std::size_t>(sqlite3_column_int64(s.p,1)),static_cast<std::size_t>(sqlite3_column_int64(s.p,2))));
        const auto* blob=static_cast<const signed char*>(sqlite3_column_blob(s.p,4));
        if(!blob||sqlite3_column_bytes(s.p,4)!=static_cast<int>(embedding_dim))throw Error("vector_corrupt");
        fresh.ids.push_back(s.text(0));fresh.starts.push_back(static_cast<std::size_t>(sqlite3_column_int64(s.p,1)));
        fresh.ends.push_back(static_cast<std::size_t>(sqlite3_column_int64(s.p,2)));fresh.scales.push_back(static_cast<float>(sqlite3_column_double(s.p,3)));
        fresh.vectors.insert(fresh.vectors.end(),blob,blob+embedding_dim);
    }
    const auto n=fresh.ids.size();
    std::vector<std::array<double,embedding_dim>> sums(g_count+1);
    for(auto& x:sums)x.fill(0);
    for(std::size_t i=0;i<n;++i){
        ++fresh.group_size[groups[i]];
        for(std::size_t d=0;d<embedding_dim;++d){const double v=static_cast<double>(fresh.vectors[i*embedding_dim+d])*fresh.scales[i];sums[groups[i]][d]+=v;sums[g_count][d]+=v;}
    }
    fresh.means.assign(g_count+1,Embedding{});
    for(std::size_t g=0;g<=g_count;++g){
        const double size=g==g_count?static_cast<double>(n):static_cast<double>(fresh.group_size[g]);
        if(size>0)for(std::size_t d=0;d<embedding_dim;++d)fresh.means[g][d]=static_cast<float>(sums[g][d]/size);
    }
    fresh.mean_of.resize(n);fresh.inv_centered_norm.resize(n);
    for(std::size_t i=0;i<n;++i){
        const unsigned char m=fresh.group_size[groups[i]]>=min_group_vectors&&groups[i]!=g_other?groups[i]:static_cast<unsigned char>(g_count);
        double norm=0;for(std::size_t d=0;d<embedding_dim;++d){const double v=static_cast<double>(fresh.vectors[i*embedding_dim+d])*fresh.scales[i]-fresh.means[m][d];norm+=v*v;}
        fresh.mean_of[i]=m;fresh.inv_centered_norm[i]=norm>0?static_cast<float>(1.0/std::sqrt(norm)):0.0f;
    }
    cache=std::move(fresh);return cache;
}
struct Candidate {
    std::string id;double cosine=-2;std::size_t chunk_start=0,chunk_end=0;
    int hits=0;int keyword_rank=-1,semantic_rank=-1;double fused=0;
};
}

std::vector<Chunk> chunk_text(const std::string& text){
    std::vector<Chunk> chunks;
    if(text.size()<=single_chunk_bytes){chunks.push_back({0,text.size()});return chunks;}
    std::size_t start=0;
    while(start<text.size()){
        std::size_t end=std::min(text.size(),start+chunk_bytes);
        if(end<text.size()){
            // Prefer a boundary after whitespace or sentence punctuation in the last third of the window.
            std::size_t cut=std::string::npos;
            for(std::size_t i=end;i>start+chunk_bytes*2/3;--i){
                const unsigned char c=static_cast<unsigned char>(text[i-1]);
                if(c==' '||c=='\n'||c=='.'||c==','||text.compare(i-3,3,"\xE3\x80\x82")==0||text.compare(i-3,3,"\xE0\xA5\xA4")==0){cut=i;break;}
            }
            end=cut!=std::string::npos?cut:char_start(text,end);
            if(end<=start)end=char_start(text,std::min(text.size(),start+chunk_bytes+4));
        }
        chunks.push_back({start,end});
        if(end>=text.size())break;
        start=char_start(text,end>chunk_overlap?end-chunk_overlap:0);
        if(start<=chunks.back().start)start=end;
    }
    return chunks;
}

json index_sources(sqlite3* db,Embedder& embedder,const json& j){
    const int limit=j.value("limit",256);if(limit<1||limit>4096)throw Error("invalid_limit");
    std::vector<std::pair<std::string,std::string>> pending;
    {Statement s(db,"SELECT o.id,lens_text(o.text,o.text_codec,o.text_zstd) FROM observations o WHERE NOT EXISTS(SELECT 1 FROM embedding_chunks e WHERE e.source_id=o.id AND e.model=?) ORDER BY o.rowid LIMIT ?;");
     s.text(1,embedder.model_id());check(sqlite3_bind_int(s.p,2,limit));
     while(s.step()==SQLITE_ROW)pending.emplace_back(s.text(0),s.text(1));}
    std::size_t chunk_count=0;
    for(const auto& [id,text]:pending){
        const auto chunks=chunk_text(text);std::vector<std::string> passages;
        for(const auto& c:chunks)passages.push_back("passage: "+text.substr(c.start,c.end-c.start));
        const auto vectors=embedder.embed(passages);
        Transaction tx(db);
        for(std::size_t k=0;k<chunks.size();++k){
            // Symmetric per-vector int8 quantization; the scale restores magnitude at scoring time.
            float peak=0;for(float x:vectors[k])peak=std::max(peak,std::fabs(x));
            const float scale=peak>0?peak/127.0f:1.0f;std::string blob(embedding_dim,'\0');
            for(std::size_t d=0;d<embedding_dim;++d)blob[d]=static_cast<char>(static_cast<signed char>(std::lround(vectors[k][d]/scale)));
            Statement ins(db,"INSERT INTO embedding_chunks(source_id,chunk,byte_start,byte_end,model,scale,vector) VALUES(?,?,?,?,?,?,?);");
            ins.text(1,id);check(sqlite3_bind_int64(ins.p,2,static_cast<sqlite3_int64>(k)));
            check(sqlite3_bind_int64(ins.p,3,static_cast<sqlite3_int64>(chunks[k].start)));check(sqlite3_bind_int64(ins.p,4,static_cast<sqlite3_int64>(chunks[k].end)));
            ins.text(5,embedder.model_id());check(sqlite3_bind_double(ins.p,6,scale));
            check(sqlite3_bind_blob(ins.p,7,blob.data(),static_cast<int>(blob.size()),SQLITE_TRANSIENT));ins.step();
        }
        tx.commit();chunk_count+=chunks.size();
    }
    Statement remaining(db,"SELECT count(*) FROM observations o WHERE NOT EXISTS(SELECT 1 FROM embedding_chunks e WHERE e.source_id=o.id AND e.model=?);");
    remaining.text(1,embedder.model_id());remaining.step();
    return {{"ok",true},{"indexed_sources",pending.size()},{"chunks",chunk_count},{"pending_sources",sqlite3_column_int64(remaining.p,0)},{"model",embedder.model_id()}};
}

json recall_once(sqlite3* db,const EmbedderAccess& access,const RerankerAccess& reranker_access,const std::string& model_id,const json& j){
    const auto query_text=required(j,"query",1024);
    const auto mode=j.value("mode",std::string("hybrid"));
    if(mode!="hybrid"&&mode!="semantic"&&mode!="keyword")throw Error("invalid_mode");
    const int limit=j.value("limit",10),pool=j.value("candidates",50);
    if(limit<1||limit>20||pool<limit||pool>200)throw Error("invalid_limit");
    const bool abstain=j.value("abstain",true);
    const double min_similarity=j.value("min_similarity",default_min_similarity);
    if(!std::isfinite(min_similarity)||min_similarity<-1||min_similarity>1)throw Error("invalid_threshold");
    const bool rerank=j.value("rerank",default_rerank&&static_cast<bool>(reranker_access))&&mode!="keyword";
    if(rerank&&!reranker_access)throw Error("reranker_not_configured");
    const bool center=j.value("center",default_center);
    const auto rerank_fusion=j.value("rerank_fusion",std::string(default_rerank_fusion));
    if(rerank_fusion!="replace"&&rerank_fusion!="rrf")throw Error("invalid_rerank_fusion");
    const int rerank_candidates=j.value("rerank_candidates",20);
    if(rerank_candidates<1||rerank_candidates>50)throw Error("invalid_limit");
    const double min_rerank=j.value("min_rerank_score",default_min_rerank);
    if(!std::isfinite(min_rerank))throw Error("invalid_threshold");
    const auto f=query::filters(j);
    const std::string& text=query_text;
    std::unordered_map<std::string,Candidate> by_id;std::vector<std::string> keyword_order,semantic_order;
    const auto query_units=units(text);bool full_keyword_match=false;
    if(mode!="semantic"&&!query_units.empty()){
        // Candidates come from indexes, not full scans: FTS5 (bm25) for tokenizable units, plus a literal scan
        // only for unspaced-script bigrams, which unicode61 cannot index. Unit hits (case-folded ASCII, exact
        // other scripts) are then counted on the candidate rows only and rank first; bm25 breaks ties.
        std::map<std::string,int> fts_rank;std::string match;std::vector<std::string> bigrams;
        for(const auto& u:query_units){
            const auto cp=code_point(u,0,std::min(utf8_len(static_cast<unsigned char>(u[0])),u.size()));
            if(unspaced_script(cp)){bigrams.push_back(u);continue;}
            if(!match.empty())match+=" OR ";match+=query::quote(u);
        }
        if(!match.empty()){
            Statement s(db,("SELECT o.id FROM memory_fts JOIN observations o ON o.rowid=memory_fts.rowid JOIN source_metadata m ON m.source_id=o.id WHERE memory_fts MATCH ?"+f.where+" ORDER BY bm25(memory_fts) LIMIT "+std::to_string(pool)).c_str());
            s.text(1,match);query::bind_values(s,f.values,2);int r=0;while(s.step()==SQLITE_ROW)fts_rank.emplace(s.text(0),r++);
        }
        std::set<std::string> candidates;for(const auto& [id,r]:fts_rank)candidates.insert(id);
        if(!bigrams.empty()){
            std::string any="0";for(std::size_t i=0;i<bigrams.size();++i)any+="+(instr(lens_text(o.text,o.text_codec,o.text_zstd),?)>0)";
            std::vector<std::string> values=bigrams;values.insert(values.end(),f.values.begin(),f.values.end());
            Statement s(db,("SELECT o.id,"+any+" AS hits"+tables+"WHERE hits>0"+f.where+" ORDER BY hits DESC,m.event_key DESC LIMIT "+std::to_string(pool)).c_str());
            query::bind_values(s,values);while(s.step()==SQLITE_ROW)candidates.insert(s.text(0));
        }
        std::map<std::string,int> hits;
        if(!candidates.empty()){
            std::string hits_sql="0";for(std::size_t i=0;i<query_units.size();++i)hits_sql+="+(instr(lower(lens_text(o.text,o.text_codec,o.text_zstd)),?)>0)";
            std::string in;for(std::size_t i=0;i<candidates.size();++i)in+=i?",?":"?";
            std::vector<std::string> values=query_units;values.insert(values.end(),candidates.begin(),candidates.end());
            Statement s(db,("SELECT o.id,"+hits_sql+" FROM observations o WHERE o.id IN ("+in+");").c_str());
            query::bind_values(s,values);while(s.step()==SQLITE_ROW)hits[s.text(0)]=sqlite3_column_int(s.p,1);
        }
        std::vector<std::string> ids;for(const auto& [id,h]:hits)if(h>0||fts_rank.contains(id))ids.push_back(id);
        std::sort(ids.begin(),ids.end(),[&](const auto& a,const auto& b){
            if(hits[a]!=hits[b])return hits[a]>hits[b];
            const int ra=fts_rank.contains(a)?fts_rank[a]:pool,rb=fts_rank.contains(b)?fts_rank[b]:pool;
            return ra!=rb?ra<rb:a<b;});
        if(ids.size()>static_cast<std::size_t>(pool))ids.resize(pool);
        for(std::size_t r=0;r<ids.size();++r){auto& c=by_id[ids[r]];c.id=ids[r];c.hits=hits[ids[r]];c.keyword_rank=static_cast<int>(r);
            if(c.hits==static_cast<int>(query_units.size()))full_keyword_match=true;}
        keyword_order=ids;
    }
    double best_cosine=-2;std::int64_t unindexed=0;
    if(mode!="keyword"){
        auto& embedder=access();
        if(embedder.model_id()!=model_id)throw Error("embedding_model_mismatch");
        const auto q=embedder.embed({"query: "+text}).front();
        const auto& cache=vector_cache(db,model_id);
        std::vector<char> allowed;
        if(!f.where.empty()){ // filters are resolved on metadata only, then applied to the cached vectors
            allowed.assign(cache.ids.size(),0);std::unordered_map<std::string,std::vector<std::size_t>> rows;
            for(std::size_t i=0;i<cache.ids.size();++i)rows[cache.ids[i]].push_back(i);
            Statement s(db,("SELECT o.id FROM observations o JOIN source_metadata m ON m.source_id=o.id WHERE 1=1"+f.where).c_str());
            query::bind_values(s,f.values);
            while(s.step()==SQLITE_ROW)if(auto it=rows.find(s.text(0));it!=rows.end())for(auto i:it->second)allowed[i]=1;
        }
        // Centered scoring: cos(q - m_q, p - m_p) = (q_c . p - q_c . m_p) / ||p - m_p|| with q_c unit length,
        // computed on the stored int8 vectors without materialising centered copies.
        Embedding qc=q;std::vector<float> q_dot_mean;
        if(center&&!cache.ids.empty()){
            const auto gq=script_group(text,0,text.size());
            const auto mq=cache.group_size[gq]>=min_group_vectors&&gq!=g_other?gq:static_cast<unsigned char>(g_count);
            double norm=0;for(std::size_t d=0;d<embedding_dim;++d){qc[d]=q[d]-cache.means[mq][d];norm+=static_cast<double>(qc[d])*qc[d];}
            norm=std::sqrt(norm);if(norm>0)for(auto& x:qc)x=static_cast<float>(x/norm);
            q_dot_mean.assign(g_count+1,0.0f);
            for(std::size_t g=0;g<=g_count;++g){float dm=0;for(std::size_t d=0;d<embedding_dim;++d)dm+=qc[d]*cache.means[g][d];q_dot_mean[g]=dm;}
        }
        std::unordered_map<std::string,Candidate> semantic;
        for(std::size_t i=0;i<cache.ids.size();++i){
            if(!allowed.empty()&&!allowed[i])continue;
            const signed char* v=cache.vectors.data()+i*embedding_dim;
            float dot=0;for(std::size_t d=0;d<embedding_dim;++d)dot+=static_cast<float>(v[d])*qc[d];
            const double score=q_dot_mean.empty()?static_cast<double>(dot)*cache.scales[i]
                :(static_cast<double>(dot)*cache.scales[i]-q_dot_mean[cache.mean_of[i]])*cache.inv_centered_norm[i];
            auto& c=semantic[cache.ids[i]];
            if(score>c.cosine){c.id=cache.ids[i];c.cosine=score;c.chunk_start=cache.starts[i];c.chunk_end=cache.ends[i];}
        }
        std::vector<Candidate> ranked;for(auto& [id,c]:semantic)ranked.push_back(c);
        const auto keep=std::min(ranked.size(),static_cast<std::size_t>(pool));
        std::partial_sort(ranked.begin(),ranked.begin()+static_cast<std::ptrdiff_t>(keep),ranked.end(),
            [](const auto& a,const auto& b){return a.cosine!=b.cosine?a.cosine>b.cosine:a.id<b.id;});
        ranked.resize(keep);
        for(std::size_t r=0;r<ranked.size();++r){
            auto& c=by_id[ranked[r].id];c.id=ranked[r].id;c.cosine=ranked[r].cosine;c.chunk_start=ranked[r].chunk_start;c.chunk_end=ranked[r].chunk_end;
            c.semantic_rank=static_cast<int>(r);semantic_order.push_back(c.id);
        }
        if(!ranked.empty())best_cosine=ranked.front().cosine;
        Statement u(db,"SELECT (SELECT count(*) FROM observations)-(SELECT count(DISTINCT source_id) FROM embedding_chunks WHERE model=?);");
        u.text(1,model_id);u.step();unindexed=sqlite3_column_int64(u.p,0);
    }
    std::vector<std::string> order;
    if(mode=="keyword")order=keyword_order;
    else if(mode=="semantic")order=semantic_order;
    else {
        // Reciprocal-rank fusion; a keyword candidate counts in proportion to the squared share of query
        // units it contains (and only from a majority of units), so one shared name cannot outrank a strong semantic match (chosen on dev split).
        for(auto& [id,c]:by_id){
            const double coverage=query_units.empty()?0.0:static_cast<double>(c.hits)/static_cast<double>(query_units.size());
            c.fused=(c.keyword_rank>=0&&coverage>=min_keyword_coverage?coverage*coverage/(rrf_k+c.keyword_rank+1):0)+(c.semantic_rank>=0?1.0/(rrf_k+c.semantic_rank+1):0);
            order.push_back(id);
        }
        std::sort(order.begin(),order.end(),[&](const auto& a,const auto& b){
            const auto& x=by_id[a];const auto& y=by_id[b];return x.fused!=y.fused?x.fused>y.fused:(x.cosine!=y.cosine?x.cosine>y.cosine:a<b);});
    }
    // Evidence for a candidate: its best semantic chunk, else a keyword-anchored excerpt (exact byte range).
    struct Evidence {json source;std::string quote;std::size_t start=0,end=0,size=0;};
    auto evidence=[&](const Candidate& c,Evidence& e)->bool{
        Statement s(db,(columns+tables+"WHERE o.id=?;").c_str());s.text(1,c.id);if(s.step()!=SQLITE_ROW)return false;
        e.source=source(s);const auto body=e.source.at("text").get<std::string>();e.size=body.size();e.start=0;e.end=body.size();
        if(c.semantic_rank>=0&&c.chunk_end<=body.size()&&c.chunk_start<c.chunk_end){e.start=c.chunk_start;e.end=c.chunk_end;e.quote=body.substr(e.start,e.end-e.start);}
        else {std::size_t anchor=std::string::npos;std::string folded=body;
            for(char& ch:folded)if(static_cast<unsigned char>(ch)<128)ch=static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
            for(const auto& u:query_units)anchor=std::min(anchor,folded.find(u));
            e.quote=excerpt(body,anchor==std::string::npos?0:anchor,e.start,e.end);}
        return true;
    };
    std::unordered_map<std::string,Evidence> found;std::unordered_map<std::string,double> rerank_score;double best_rerank=-1e9;
    if(rerank&&!order.empty()){
        // Second stage: the cross-encoder re-scores the top fused candidates on their evidence passages.
        std::vector<std::string> head(order.begin(),order.begin()+std::min(order.size(),static_cast<std::size_t>(rerank_candidates)));
        std::vector<std::string> ids,passages;
        for(const auto& id:head){Evidence e;if(evidence(by_id[id],e)){ids.push_back(id);passages.push_back(e.quote);found.emplace(id,std::move(e));}}
        const auto scores=reranker_access().score(text,passages);
        for(std::size_t i=0;i<ids.size();++i){rerank_score[ids[i]]=scores[i];best_rerank=std::max(best_rerank,static_cast<double>(scores[i]));}
        // A source containing every query unit verbatim is direct evidence; the cross-encoder orders within
        // that group and within the rest, but cannot push literal matches below partial ones.
        const auto full=[&](const std::string& id){return !query_units.empty()&&by_id[id].hits==static_cast<int>(query_units.size());};
        // "replace": order by the cross-encoder alone. "rrf": reciprocal-rank fusion of the cross-encoder order and
        // the first-stage (hybrid) order — their errors are complementary (docs/retrieval.md).
        std::unordered_map<std::string,double> final_score;
        {std::vector<std::string> by_rerank=ids;
         std::stable_sort(by_rerank.begin(),by_rerank.end(),[&](const auto& a,const auto& b){return rerank_score[a]>rerank_score[b];});
         for(std::size_t r=0;r<by_rerank.size();++r)final_score[by_rerank[r]]=rerank_fusion=="rrf"?1.0/(rrf_k+r+1):-static_cast<double>(r);
         if(rerank_fusion=="rrf")for(std::size_t r=0;r<ids.size();++r)final_score[ids[r]]+=1.0/(rrf_k+r+1);} // ids are in first-stage order
        std::stable_sort(ids.begin(),ids.end(),[&](const auto& a,const auto& b){
            if(full(a)!=full(b))return full(a);return final_score[a]>final_score[b];});
        std::vector<std::string> rest(order.begin()+static_cast<std::ptrdiff_t>(head.size()),order.end());
        order=ids;order.insert(order.end(),rest.begin(),rest.end());
    }
    bool not_found=order.empty();
    if(abstain&&!not_found){
        if(mode=="keyword")not_found=!full_keyword_match;
        else if(center&&rerank)not_found=!full_keyword_match&&best_rerank<j.value("min_rerank_score",default_min_rerank_centered)
                                         &&best_cosine<j.value("min_similarity",default_min_centered_similarity);
        else if(center)not_found=(mode=="semantic"||!full_keyword_match)&&best_cosine<j.value("min_similarity",default_min_centered_similarity_no_rerank);
        else if(rerank)not_found=!full_keyword_match&&best_rerank<min_rerank;
        else if(mode=="semantic")not_found=best_cosine<min_similarity;
        else not_found=!full_keyword_match&&best_cosine<min_similarity;
    }
    json results=json::array();
    if(!not_found)for(std::size_t r=0;r<order.size()&&results.size()<static_cast<std::size_t>(limit);++r){
        const auto& c=by_id[order[r]];Evidence e;
        if(auto it=found.find(c.id);it!=found.end())e=it->second;else if(!evidence(c,e))continue;
        const auto rs=rerank_score.find(c.id);
        results.push_back({{"source",e.source},{"evidence",{{"source_id",c.id},{"quote",e.quote},{"byte_offset",e.start},{"byte_end",e.end},
            {"truncated",e.start>0||e.end<e.size}}},
            {"scores",{{"semantic",c.semantic_rank>=0?json(c.cosine):json(nullptr)},{"keyword_hits",c.hits},{"keyword_units",query_units.size()},
                       {"keyword_rank",c.keyword_rank>=0?json(c.keyword_rank+1):json(nullptr)},{"semantic_rank",c.semantic_rank>=0?json(c.semantic_rank+1):json(nullptr)},
                       {"fused",c.fused},{"rerank",rs!=rerank_score.end()?json(rs->second):json(nullptr)}}}});
    }
    return {{"ok",true},{"not_found",not_found},{"mode",mode},{"results",results},{"best_semantic",best_cosine>-2?json(best_cosine):json(nullptr)},
            {"full_keyword_match",full_keyword_match},{"unindexed_sources",unindexed},{"reranked",rerank},{"centered",center&&mode!="keyword"},
            {"best_rerank",rerank&&best_rerank>-1e9?json(best_rerank):json(nullptr)},{"model",mode=="keyword"?json(nullptr):json(model_id)},
            {"answer_kind","source_evidence"},{"generated_claims",false}};
}

json recall(sqlite3* db,const EmbedderAccess& access,const RerankerAccess& reranker_access,const std::string& model_id,const json& j){
    // Interpreted constraints from the question itself: a time window ("last week", "昨天") and application
    // hints ("in Chrome", "on WhatsApp", "邮件"). Explicit API filters always win and are strict. Interpreted
    // constraints are applied first; a phrase may describe content instead ("the October bill"), so when no
    // evidence satisfies them the question is retried without them and the response says so.
    const auto question=required(j,"query",1024);
    const json given=j.contains("filters")&&j["filters"].is_object()?j["filters"]:json::object();
    const bool explicit_time=given.contains("from")||given.contains("to");
    const bool explicit_app=given.contains("application")||given.contains("application_contains");
    std::optional<TimeWindow> w;json window=nullptr;
    if(j.value("interpret_time",true)&&!explicit_time){
        const auto now=j.contains("now")?std::chrono::sys_seconds{std::chrono::seconds{epoch(required(j,"now",64))}}
                                         :std::chrono::floor<std::chrono::seconds>(std::chrono::system_clock::now());
        const int offset=j.value("utc_offset_minutes",0);if(offset<-14*60||offset>14*60)throw Error("invalid_utc_offset");
        w=interpret_time(question,now,offset);
        if(w)window={{"from",iso_utc(w->from)},{"to",iso_utc(w->to)},{"phrase",w->phrase},{"kind",w->kind},{"utc_offset_minutes",offset}};
    }
    const auto interpretation=j.value("interpret_query",true)?interpret_query(question):QueryInterpretation{};
    json app_matches=json::array(),app_phrases=json::array();
    if(!explicit_app)for(const auto& a:interpretation.applications){
        app_phrases.push_back(a.phrase);for(const auto& m:a.matches)if(std::find(app_matches.begin(),app_matches.end(),m)==app_matches.end())app_matches.push_back(m);
    }
    json trace={{"time_window",window},{"applications",app_phrases},{"application_filter",app_matches},
                {"action",interpretation.action.empty()?json(nullptr):json(interpretation.action)},
                {"action_note","reported only; observers do not yet record action kinds"}};
    if(!w&&app_matches.empty()){auto result=recall_once(db,access,reranker_access,model_id,j);result["interpretation"]=trace;return result;}
    json filtered=j;filtered["filters"]=given;
    if(w){
        filtered["filters"]["from"]=iso_utc(w->from);filtered["filters"]["to"]=iso_utc(w->to);
        // The time words are a filter now; removing them keeps them from diluting keyword/semantic matching.
        std::string lowered=question;for(char& c:lowered)if(static_cast<unsigned char>(c)<128)c=static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        if(const auto at=lowered.find(w->phrase);at!=std::string::npos){
            const auto stripped=question.substr(0,at)+question.substr(at+w->phrase.size());
            if(stripped.find_first_not_of(" \t?.,!")!=std::string::npos)filtered["query"]=stripped;
        }
    }
    if(!app_matches.empty())filtered["filters"]["application_contains"]=app_matches;
    auto result=recall_once(db,access,reranker_access,model_id,filtered);
    std::string state="applied";
    if(result.at("not_found").get<bool>()){result=recall_once(db,access,reranker_access,model_id,j);state="relaxed_no_evidence_with_interpreted_constraints";}
    trace["constraints"]=state;result["interpretation"]=trace;
    if(w){result["time_window"]=window;result["time_filter"]=state=="applied"?"applied":"relaxed_no_evidence_in_window";}
    return result;
}
}
