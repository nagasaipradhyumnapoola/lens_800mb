#pragma once
#include <array>
#include <filesystem>
#include <fstream>
#include <istream>
#include <stdexcept>
#include <string>
#include <vector>
namespace lens {
class Error:public std::runtime_error {public:explicit Error(const char* code):std::runtime_error(code){}};
enum class Line { end, ready, too_large };
inline Line read_line(std::istream& in,std::string& text,std::size_t limit) {
    text.clear();char c{};
    while(in.get(c)) {
        if(c=='\n')return Line::ready;
        if(text.size()>=limit)return Line::too_large;
        text.push_back(c);
    }
    return text.empty()?Line::end:Line::ready;
}
inline std::string validated_string(const std::string& s,std::size_t max,bool allow_empty=false) {
    if((s.empty()&&!allow_empty)||s.size()>max||s.find('\0')!=std::string::npos)throw Error("invalid_request");return s;
}
inline std::filesystem::path utf8_path(const std::string& s) {
    validated_string(s,32768);return std::filesystem::path(std::u8string(s.begin(),s.end()));
}
inline std::vector<char> read_file(const std::filesystem::path& path,std::size_t limit) {
    std::error_code ec;
    if(!std::filesystem::is_regular_file(path,ec)||ec)throw Error("file_unavailable");
    const auto size=std::filesystem::file_size(path,ec);
    if(ec)throw Error("file_unavailable");
    if(size>limit)throw Error("file_too_large");
    std::ifstream file(path,std::ios::binary);if(!file)throw Error("file_unavailable");
    std::vector<char> result;result.reserve(static_cast<size_t>(size));std::array<char,65536> buffer{};
    while(file) {
        file.read(buffer.data(),buffer.size());const auto n=static_cast<size_t>(file.gcount());
        if(n>limit-result.size())throw Error("file_too_large");
        result.insert(result.end(),buffer.data(),buffer.data()+n);
    }
    if(file.bad())throw Error("file_read_failed");return result;
}
}
