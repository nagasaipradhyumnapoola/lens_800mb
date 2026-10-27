#pragma once
// Delta storage for screen observations (docs/LENS_V1_SPEC.md §5, §15): per window, a compact fingerprint of the
// lines already stored (64-bit hashes of whitespace-normalised lines, bounded), so a new capture stores only the lines
// that are new since the window's last stored capture. Near-duplicate re-renders (almost every line already seen and
// only a few characters new) are not stored at all. Fingerprints hold hashes only, never text.
#include <cstdint>
#include <deque>
#include <string>
#include <string_view>
#include <unordered_set>
#include <vector>

namespace lens::observe {
inline std::string normalise_line(std::string_view s) {  // collapse runs of whitespace; trim
    std::string out;bool space=false;
    for(char c:s) {
        if(c==' '||c=='\t'||c=='\r'||c=='\n'||c=='\f'||c=='\v'){space=!out.empty();continue;}
        if(space){out+=' ';space=false;}
        out+=c;
    }
    return out;
}
inline uint64_t line_hash(std::string_view s) {  // FNV-1a 64
    uint64_t h=1469598103934665603ull;for(unsigned char c:s){h^=c;h*=1099511628211ull;}return h;
}
inline std::vector<std::string> split_lines(const std::string& text) {
    std::vector<std::string> out;size_t start=0;
    while(start<text.size()) {
        auto end=text.find('\n',start);if(end==std::string::npos)end=text.size();
        auto line=normalise_line(std::string_view(text).substr(start,end-start));
        if(!line.empty())out.push_back(std::move(line));
        start=end+1;
    }
    return out;
}
// Keeps at most max_bytes of UTF-8, cutting at the last line break that fits (or at a character boundary).
inline std::string cap_utf8(const std::string& s,size_t max_bytes,bool& truncated) {
    if(s.size()<=max_bytes)return s;
    truncated=true;
    size_t cut=max_bytes;while(cut>0&&(static_cast<unsigned char>(s[cut])&0xC0)==0x80)--cut;
    const auto nl=s.rfind('\n',cut);
    if(nl!=std::string::npos&&nl>=max_bytes/2)cut=nl+1;
    return s.substr(0,cut);
}

class LineFingerprint {
public:
    LineFingerprint()=default;
    explicit LineFingerprint(size_t capacity):capacity_(capacity) {}
    bool contains(uint64_t h) const {return set_.count(h)>0;}
    void add(uint64_t h) {
        if(!set_.insert(h).second)return;
        order_.push_back(h);
        if(order_.size()>capacity_){set_.erase(order_.front());order_.pop_front();}
    }
    void clear(){set_.clear();order_.clear();}
    size_t size() const {return set_.size();}
private:
    size_t capacity_=4096;std::unordered_set<uint64_t> set_;std::deque<uint64_t> order_;
};

struct LineDelta {
    std::vector<std::string> new_lines;  // lines not in the fingerprint, in screen order
    size_t new_chars=0,lines=0;
    double overlap=0;                    // share of the capture's lines already in the fingerprint
};
inline LineDelta diff_lines(const std::vector<std::string>& lines,const LineFingerprint& seen) {
    LineDelta d;d.lines=lines.size();size_t known=0;std::unordered_set<uint64_t> here;
    for(const auto& l:lines) {
        const auto h=line_hash(l);
        if(seen.contains(h)){++known;continue;}
        if(!here.insert(h).second)continue;  // a new line repeated on screen is stored once
        d.new_chars+=l.size();d.new_lines.push_back(l);
    }
    d.overlap=lines.empty()?1.0:static_cast<double>(known)/static_cast<double>(lines.size());
    return d;
}
inline std::string join_lines(const std::vector<std::string>& lines) {
    std::string out;for(const auto& l:lines){out+=l;out+='\n';}return out;
}
}
