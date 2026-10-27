// A UTF-8 JSON adapter around Needle's published native C API. No action execution.
#include <windows.h>
#include <nlohmann/json.hpp>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <vector>
#include "input.hpp"
#include "tool_policy.hpp"
using json=nlohmann::json;
using Load=int(*)(const unsigned char*,unsigned long long);
using Init=int(*)(const char*,const char*,const char*);
using Complete=int(*)(const char*,const float*,int,int,char*,int);
struct Module {
    HMODULE handle{};
    ~Module(){if(handle)FreeLibrary(handle);}
};
int main() {
    SetEnvironmentVariableW(L"NEEDLE_TELEMETRY",L"0");SetEnvironmentVariableW(L"DO_NOT_TRACK",L"1");
    try {
        std::string input;
        if(lens::read_line(std::cin,input,262144)!=lens::Line::ready)throw lens::Error("invalid_request");
        const auto request=json::parse(input);
        const auto text=lens::validated_string(request.at("text").get<std::string>(),131072);
        const auto system=lens::validated_string(request.value("system",std::string{}),8192,true);
        const lens::ToolPolicy policy(request.at("tools"));
        const auto dll=lens::utf8_path(request.at("library").get<std::string>());
        const auto path=lens::utf8_path(request.at("weights").get<std::string>());
        Module module{LoadLibraryExW(dll.c_str(),nullptr,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_DEFAULT_DIRS)};
        if(!module.handle)throw std::runtime_error("native_library_unavailable");
        auto load=reinterpret_cast<Load>(GetProcAddress(module.handle,"needle_load"));
        auto init=reinterpret_cast<Init>(GetProcAddress(module.handle,"needle_init"));
        auto complete=reinterpret_cast<Complete>(GetProcAddress(module.handle,"needle_complete"));
        if(!load||!init||!complete)throw std::runtime_error("native_api_unavailable");
        const auto weights=lens::read_file(path,256000000);
        if(load(reinterpret_cast<const unsigned char*>(weights.data()),weights.size())<0)throw lens::Error("model_load_failed");
        const auto tools=request.at("tools").dump();
        if(init(system.c_str(),tools.c_str(),nullptr)<0)throw std::runtime_error("model_init_failed");
        std::vector<char> output(131072);
        if(complete(text.c_str(),nullptr,0,512,output.data(),static_cast<int>(output.size()))<0)
            throw std::runtime_error("inference_failed");
        auto response=json::parse(output.data());
        std::cout<<policy.evaluate(response).dump()<<'\n';
    } catch(const lens::Error& e) {std::cerr<<e.what()<<'\n';return 1;}
    catch(...) {std::cerr<<"needle_request_failed\n";return 1;}
}
