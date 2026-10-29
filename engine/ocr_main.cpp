// Native runtime/image adapter; no Python is loaded by this executable.
// Resize/normalize and CTC selection follow PaddleX 3.7.2 text_recognition/processors.py; detection pre/post-processing
// follows PaddleOCR 3.x DBPostProcess for screens (axis-aligned boxes; screen text is horizontal):
// Copyright (c) PaddlePaddle Authors, Apache License 2.0 (see third_party/licenses).
// Inference is performed by Microsoft's unmodified ONNX Runtime and PaddleOCR weights.
//
// One JSON request per process on stdin (or, with --serve, one per line until stdin closes, models kept loaded):
//   crop mode   {"consent":true,"runtime":dll,"model":onnx,"dictionary":json,"image":path}  -> {"text","confidence",...}
//   screen mode {"consent":true,"runtime":dll,"mode":"screen","detector":onnx,"recognizers":{"general":{"model","dictionary"},
//               "hi":{...},...},"route":"auto"|<key>,"image":path | "image_base64":<encoded image>,"region":[x,y,w,h],
//               "det_pixels":409600 (detector input pixels per run; larger screens run as bands),"max_recognizers":2,
//               "max_probe_misses":2,"merge_lines":true}; a recogniser spec may carry "rtl":true (arabic_*: visual to logical)
//               -> {"lines":[{"text","confidence","box":[x0,y0,x1,y1],"recognizer"}],"timing_ms":{...},"peak_working_set_bytes"}
// Images are decoded in memory and never written to disk.
#define ORT_API_MANUAL_INIT
#include "onnxruntime_cxx_api.h"
#include "input.hpp"
#include <windows.h>
#include <psapi.h>
#include <wincodec.h>
#include <wincrypt.h>
#include <wrl/client.h>
#include <nlohmann/json.hpp>
#include <algorithm>
#include <cctype>
#include <array>
#include <chrono>
#include <cmath>
#include <iostream>
#include <map>
#include <memory>
#include <vector>
using json=nlohmann::json;
using Microsoft::WRL::ComPtr;
struct Module {HMODULE h{};~Module(){if(h)FreeLibrary(h);}};
struct Com {HRESULT result=CoInitializeEx(nullptr,COINIT_MULTITHREADED);~Com(){if(SUCCEEDED(result))CoUninitialize();}};
void checked(HRESULT h){if(FAILED(h))throw lens::Error("image_decode_failed");}
void quiet_ort(void*,OrtLoggingLevel,const char*,const char*,const char*,const char*){}

namespace {
struct Image {int w=0,h=0;std::vector<BYTE> bgr;};  // 8-bit BGR, row-major

Image decode(const std::vector<char>& bytes) {
    ComPtr<IWICImagingFactory> factory;
    checked(CoCreateInstance(CLSID_WICImagingFactory,nullptr,CLSCTX_INPROC_SERVER,IID_PPV_ARGS(&factory)));
    ComPtr<IWICStream> stream;checked(factory->CreateStream(&stream));
    checked(stream->InitializeFromMemory(reinterpret_cast<BYTE*>(const_cast<char*>(bytes.data())),static_cast<DWORD>(bytes.size())));
    ComPtr<IWICBitmapDecoder> decoder;checked(factory->CreateDecoderFromStream(stream.Get(),nullptr,WICDecodeMetadataCacheOnDemand,&decoder));
    ComPtr<IWICBitmapFrameDecode> frame;checked(decoder->GetFrame(0,&frame));
    UINT w{},h{};checked(frame->GetSize(&w,&h));
    if(!w||!h||static_cast<std::uint64_t>(w)*h>16000000)throw lens::Error("image_dimensions_exceeded");
    ComPtr<IWICFormatConverter> converter;checked(factory->CreateFormatConverter(&converter));
    checked(converter->Initialize(frame.Get(),GUID_WICPixelFormat24bppBGR,WICBitmapDitherTypeNone,nullptr,0,WICBitmapPaletteTypeCustom));
    Image img{static_cast<int>(w),static_cast<int>(h),std::vector<BYTE>(static_cast<size_t>(w)*h*3)};
    checked(converter->CopyPixels(nullptr,w*3,static_cast<UINT>(img.bgr.size()),img.bgr.data()));
    return img;
}

// Bilinear resize with half-pixel centres (OpenCV INTER_LINEAR semantics); rows [r0,r1) of the nw x nh result only,
// so the detector can resize one band at a time instead of holding a second full-screen copy.
Image resize(const Image& s,int nw,int nh,int r0=0,int r1=-1) {
    if(r1<0)r1=nh;
    Image d{nw,r1-r0,std::vector<BYTE>(static_cast<size_t>(nw)*(r1-r0)*3)};
    const double fx=static_cast<double>(s.w)/nw,fy=static_cast<double>(s.h)/nh;
    for(int y=r0;y<r1;++y) {
        double sy=std::clamp((y+0.5)*fy-0.5,0.0,static_cast<double>(s.h-1));int y0=static_cast<int>(sy),y1=std::min(y0+1,s.h-1);double wy=sy-y0;
        for(int x=0;x<nw;++x) {
            double sx=std::clamp((x+0.5)*fx-0.5,0.0,static_cast<double>(s.w-1));int x0=static_cast<int>(sx),x1=std::min(x0+1,s.w-1);double wx=sx-x0;
            for(int c=0;c<3;++c) {
                auto at=[&](int yy,int xx){return static_cast<double>(s.bgr[(static_cast<size_t>(yy)*s.w+xx)*3+c]);};
                const double v=(1-wy)*((1-wx)*at(y0,x0)+wx*at(y0,x1))+wy*((1-wx)*at(y1,x0)+wx*at(y1,x1));
                d.bgr[(static_cast<size_t>(y-r0)*nw+x)*3+c]=static_cast<BYTE>(std::clamp(std::lround(v),0L,255L));
            }
        }
    }
    return d;
}

Image sub(const Image& s,int x0,int y0,int x1,int y1) {
    Image d{x1-x0,y1-y0,std::vector<BYTE>(static_cast<size_t>(x1-x0)*(y1-y0)*3)};
    for(int y=y0;y<y1;++y)std::copy_n(&s.bgr[(static_cast<size_t>(y)*s.w+x0)*3],static_cast<size_t>(x1-x0)*3,&d.bgr[static_cast<size_t>(y-y0)*d.w*3]);
    return d;
}

Image rotate_ccw(const Image& s) {  // numpy rot90: counter-clockwise
    Image d{s.h,s.w,std::vector<BYTE>(s.bgr.size())};
    for(int y=0;y<s.h;++y)for(int x=0;x<s.w;++x)for(int c=0;c<3;++c)
        d.bgr[(static_cast<size_t>(s.w-1-x)*d.w+y)*3+c]=s.bgr[(static_cast<size_t>(y)*s.w+x)*3+c];
    return d;
}

struct Runtime {
    Module module;const OrtApiBase* base=nullptr;std::unique_ptr<Ort::Env> env;
    explicit Runtime(const std::filesystem::path& dll) {
        module.h=LoadLibraryExW(dll.c_str(),nullptr,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
        if(!module.h)throw lens::Error("ocr_runtime_unavailable");
        using GetBase=const OrtApiBase*(ORT_API_CALL*)();
        const auto get_base=reinterpret_cast<GetBase>(GetProcAddress(module.h,"OrtGetApiBase"));
        if(!get_base)throw lens::Error("ocr_runtime_api_unavailable");
        base=get_base();const auto api=base->GetApi(ORT_API_VERSION);if(!api)throw lens::Error("ocr_runtime_version_mismatch");
        Ort::InitApi(api);env=std::make_unique<Ort::Env>(ORT_LOGGING_LEVEL_FATAL,"Lens",quiet_ort,nullptr);env->DisableTelemetryEvents();
    }
    std::unique_ptr<Ort::Session> session(const std::filesystem::path& model,int threads) {
        Ort::SessionOptions options;options.SetIntraOpNumThreads(threads);options.SetInterOpNumThreads(1);
        options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
        // Every screen and line has a new shape: the CPU arena and memory patterns would keep the largest (and each new)
        // shape's buffers for the life of the --serve worker (measured 1.45 GB after two 2560x1600 requests).
        options.DisableCpuMemArena();options.DisableMemPattern();
        return std::make_unique<Ort::Session>(*env,model.c_str(),options);
    }
    // Sessions are cached per (model, threads); screen requests release all but one recogniser after each request.
    std::map<std::pair<std::wstring,int>,std::unique_ptr<Ort::Session>> sessions;std::map<std::string,std::vector<std::string>> dictionaries;
    std::string preferred="general";  // recogniser key that read most of the previous auto screen
    Ort::Session& cached(const std::filesystem::path& model,int threads,double& load_ms) {
        auto& s=sessions[{model.wstring(),threads}];
        if(!s){const auto t=std::chrono::steady_clock::now();s=session(model,threads);load_ms+=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-t).count();}
        return *s;
    }
};

std::vector<Ort::Value> run(Ort::Session& s,std::vector<float>& input,const std::array<std::int64_t,4>& shape) {
    Ort::AllocatorWithDefaultOptions allocator;
    auto in=s.GetInputNameAllocated(0,allocator);auto out=s.GetOutputNameAllocated(0,allocator);
    const char* in_names[]={in.get()};const char* out_names[]={out.get()};
    auto memory=Ort::MemoryInfo::CreateCpu(OrtDeviceAllocator,OrtMemTypeDefault);
    auto tensor=Ort::Value::CreateTensor<float>(memory,input.data(),input.size(),shape.data(),shape.size());
    auto values=s.Run(Ort::RunOptions{nullptr},in_names,&tensor,1,out_names,1);
    if(values[0].GetTensorTypeAndShapeInfo().GetElementType()!=ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT)throw lens::Error("ocr_output_type_mismatch");
    return values;
}

// Right-to-left recognisers (arabic_*) emit the line in visual (left-to-right) order. Logical order: reverse the code
// points, then restore left-to-right runs — ASCII letters/digits, joined by , . : / % + - or a space only when both
// neighbours belong to the run (so "48,250", "4:30", "B12" survive and a sentence-final "." stays outside) — and mirror
// brackets outside those runs. PaddleOCR's pred_reverse splits numbers at "," and ":" ("48,250" -> "250,48").
std::string reverse_rtl(const std::string& text) {
    std::vector<std::string> cps;
    for(size_t i=0;i<text.size();) {
        const auto c=static_cast<unsigned char>(text[i]);const size_t n=c<0x80?1:c<0xE0?2:c<0xF0?3:4;
        cps.push_back(text.substr(i,n));i+=n;
    }
    std::reverse(cps.begin(),cps.end());
    auto strong=[&](size_t i){return i<cps.size()&&cps[i].size()==1&&std::isalnum(static_cast<unsigned char>(cps[i][0]));};
    auto joiner=[&](size_t i){return cps[i].size()==1&&std::string(",.:/%+- ").find(cps[i][0])!=std::string::npos;};
    std::string out;
    for(size_t i=0;i<cps.size();) {
        if(!strong(i)) {
            static const std::map<std::string,std::string> mirror{{"(",")"},{")","("},{"[","]"},{"]","["},{"{","}"},{"}","{"},{"<",">"},{">","<"}};
            const auto m=mirror.find(cps[i]);out+=m==mirror.end()?cps[i]:m->second;++i;continue;
        }
        size_t j=i+1;
        while(j<cps.size()&&(strong(j)||(joiner(j)&&strong(j+1))))j+=strong(j)?1:2;
        for(size_t k=j;k-->i;)out+=cps[k];
        i=j;
    }
    return out;
}

struct Recognizer {
    Ort::Session* session;const std::vector<std::string>* dictionary_ptr;bool rtl=false;
    std::pair<std::string,double> operator()(const Image& crop) {
        constexpr int height=48;
        const int width=std::clamp(static_cast<int>(height*std::max(320.0/height,static_cast<double>(crop.w)/crop.h)),1,3200);
        const int resized_width=std::max(1,std::min(width,static_cast<int>(std::ceil(height*static_cast<double>(crop.w)/crop.h))));
        const auto r=resize(crop,resized_width,height);
        std::vector<float> input(static_cast<size_t>(3)*height*width,0.0f);
        for(int y=0;y<height;++y)for(int x=0;x<resized_width;++x)for(int c=0;c<3;++c)
            input[(static_cast<size_t>(c)*height+y)*width+x]=r.bgr[(static_cast<size_t>(y)*resized_width+x)*3+c]/127.5f-1.0f;
        auto values=run(*session,input,{1,3,height,width});
        auto dims=values[0].GetTensorTypeAndShapeInfo().GetShape();
        const auto& dictionary=*dictionary_ptr;
        if(dims.size()!=3||dims[0]!=1||dims[2]!=static_cast<std::int64_t>(dictionary.size()))throw lens::Error("ocr_output_shape_mismatch");
        const float* prediction=values[0].GetTensorData<float>();
        std::string text;double confidence=0;size_t count=0,previous=0;
        for(std::int64_t t=0;t<dims[1];++t) {
            const auto row=prediction+t*dims[2];
            const auto best=static_cast<size_t>(std::max_element(row,row+dims[2])-row);
            if(best!=0&&best!=previous){text+=dictionary.at(best);confidence+=row[best];++count;}
            previous=best;
        }
        return {rtl?reverse_rtl(text):text,count?confidence/count:0.0};
    }
};

const std::vector<std::string>& load_dictionary(Runtime& rt,const std::string& path) {
    auto& d=rt.dictionaries[path];
    if(d.empty())d=json::parse(lens::read_file(lens::utf8_path(path),2000000)).get<std::vector<std::string>>();
    return d;
}

struct Box {int x0,y0,x1,y1;};

// Tile origins along one axis: tiles of `tile` px overlapping by `overlap`, the last one aligned to the end.
std::vector<int> tile_starts(int size,int tile,int overlap) {
    std::vector<int> s{0};
    while(s.back()+tile<size)s.push_back(std::min(s.back()+tile-overlap,size-tile));
    return s;
}

// DB post-processing on the probability map, axis-aligned: threshold, 8-connected components, mean-probability score,
// unclip by area*ratio/perimeter, rescale to the input image. Inputs above `budget` pixels run at native scale as
// overlapping full-width horizontal bands (tiles only beyond 1600 px width), each keeping its centre minus half the
// overlap, so detector activations stay bounded by the budget instead of growing with the screen. Bands avoid vertical
// seams, which split text lines; the stitched map is close to, not identical with, a whole-screen run (the network
// pools globally).
std::vector<Box> detect(Ort::Session& session,const Image& img,float thresh,float box_thresh,float unclip,int budget) {
    double r=1.0;
    if(std::min(img.w,img.h)<64)r=64.0/std::min(img.w,img.h);
    if(std::max(img.w,img.h)*r>4000)r=4000.0/std::max(img.w,img.h);
    const int nh=std::max(32,static_cast<int>(std::lround(img.h*r/32))*32),nw=std::max(32,static_cast<int>(std::lround(img.w*r/32))*32);
    constexpr int overlap=64;
    int tw=nw,th=nh;
    if(static_cast<std::int64_t>(nw)*nh>budget) {
        tw=std::min(nw,std::max(256,budget/256/32*32));th=std::min(nh,std::max(256,budget/tw/32*32));
    }
    // probability map as 16-bit fixed point (step 1.5e-5) and a 1-byte visited map: 4K screens stay within ~150 MB
    std::vector<std::uint16_t> prob(static_cast<size_t>(nw)*nh);std::vector<float> input(static_cast<size_t>(3)*th*tw);
    const auto q=static_cast<std::uint16_t>(std::clamp(thresh,0.0f,1.0f)*65535.0f);
    const float mean[3]={0.485f,0.456f,0.406f},stdv[3]={0.229f,0.224f,0.225f};
    for(const int oy:tile_starts(nh,th,overlap)) {
        const auto band=resize(img,nw,nh,oy,oy+th);
        for(const int ox:tile_starts(nw,tw,overlap)) {
            for(int y=0;y<th;++y)for(int x=0;x<tw;++x)for(int c=0;c<3;++c)
                input[(static_cast<size_t>(c)*th+y)*tw+x]=(band.bgr[(static_cast<size_t>(y)*nw+ox+x)*3+c]/255.0f-mean[c])/stdv[c];
            auto values=run(session,input,{1,3,th,tw});
            const auto dims=values[0].GetTensorTypeAndShapeInfo().GetShape();
            if(dims.size()!=4||dims[2]!=th||dims[3]!=tw)throw lens::Error("ocr_detector_shape_mismatch");
            const float* p=values[0].GetTensorData<float>();
            const int y0=oy?overlap/2:0,y1=oy+th<nh?th-overlap/2:th,x0=ox?overlap/2:0,x1=ox+tw<nw?tw-overlap/2:tw;
            for(int y=y0;y<y1;++y)for(int x=x0;x<x1;++x)
                prob[static_cast<size_t>(oy+y)*nw+ox+x]=static_cast<std::uint16_t>(std::lround(std::clamp(p[static_cast<size_t>(y)*tw+x],0.0f,1.0f)*65535.0f));
        }
    }
    std::vector<BYTE> seen(static_cast<size_t>(nw)*nh,0);std::vector<Box> boxes;std::vector<std::pair<int,int>> stack;
    const double sx=static_cast<double>(img.w)/nw,sy=static_cast<double>(img.h)/nh;
    for(int y=0;y<nh&&boxes.size()<1000;++y)for(int x=0;x<nw;++x) {
        const size_t i=static_cast<size_t>(y)*nw+x;
        if(seen[i]||prob[i]<=q)continue;
        seen[i]=1;stack.assign(1,{x,y});int x0=x,x1=x,y0=y,y1=y;double sum=0;size_t n=0;
        while(!stack.empty()) {
            auto [cx,cy]=stack.back();stack.pop_back();sum+=prob[static_cast<size_t>(cy)*nw+cx]/65535.0;++n;
            x0=std::min(x0,cx);x1=std::max(x1,cx);y0=std::min(y0,cy);y1=std::max(y1,cy);
            for(int dy=-1;dy<=1;++dy)for(int dx=-1;dx<=1;++dx) {
                const int ax=cx+dx,ay=cy+dy;if(ax<0||ay<0||ax>=nw||ay>=nh)continue;
                const size_t j=static_cast<size_t>(ay)*nw+ax;
                if(!seen[j]&&prob[j]>q){seen[j]=1;stack.push_back({ax,ay});}
            }
        }
        const double w=x1-x0+1,h=y1-y0+1;
        if(std::min(w,h)<3||sum/n<box_thresh)continue;
        const double d=w*h*unclip/(2*(w+h));
        const double bx0=x0-d,by0=y0-d,bx1=x1+1+d,by1=y1+1+d;
        if(std::min(bx1-bx0,by1-by0)<5)continue;
        Box b{static_cast<int>(std::clamp(bx0*sx,0.0,static_cast<double>(img.w))),static_cast<int>(std::clamp(by0*sy,0.0,static_cast<double>(img.h))),
              static_cast<int>(std::clamp(bx1*sx,0.0,static_cast<double>(img.w))),static_cast<int>(std::clamp(by1*sy,0.0,static_cast<double>(img.h)))};
        if(b.x1-b.x0>=2&&b.y1-b.y0>=2)boxes.push_back(b);
    }
    std::sort(boxes.begin(),boxes.end(),[](const Box& a,const Box& b){return a.y0!=b.y0?a.y0<b.y0:a.x0<b.x0;});
    for(size_t i=0;i+1<boxes.size();++i)  // PaddleOCR sorted_boxes: same line (10 px) reads left to right
        for(size_t j=i+1;j-->0;) {
            if(std::abs(boxes[j+1].y0-boxes[j].y0)<10&&boxes[j+1].x0<boxes[j].x0)std::swap(boxes[j],boxes[j+1]);else break;
        }
    return boxes;
}

std::vector<char> base64_decode(const std::string& text) {
    DWORD size=0;
    if(!CryptStringToBinaryA(text.data(),static_cast<DWORD>(text.size()),CRYPT_STRING_BASE64,nullptr,&size,nullptr,nullptr))throw lens::Error("image_decode_failed");
    std::vector<char> out(size);
    if(!CryptStringToBinaryA(text.data(),static_cast<DWORD>(text.size()),CRYPT_STRING_BASE64,reinterpret_cast<BYTE*>(out.data()),&size,nullptr,nullptr))throw lens::Error("image_decode_failed");
    out.resize(size);return out;
}

double ms_since(std::chrono::steady_clock::time_point t){return std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-t).count();}

json screen(const json& req,Runtime& rt,Image img) {
    if(req.contains("region")) {
        const auto r=req.at("region").get<std::vector<int>>();
        if(r.size()!=4||r[0]<0||r[1]<0||r[2]<1||r[3]<1||r[0]+r[2]>img.w||r[1]+r[3]>img.h)throw lens::Error("invalid_region");
        img=sub(img,r[0],r[1],r[0]+r[2],r[1]+r[3]);
    }
    const int threads=std::clamp(req.value("threads",2),1,8);
    double load_ms=0;
    auto& det=rt.cached(lens::utf8_path(req.at("detector").get<std::string>()),threads,load_ms);
    const auto t_det=std::chrono::steady_clock::now();
    const int budget=std::clamp(req.value("det_pixels",409600),65536,16000000);
    auto boxes=detect(det,img,req.value("det_thresh",0.3f),req.value("box_thresh",0.6f),req.value("unclip_ratio",1.5f),budget);
    // drop_edge_boxes: for horizontal band regions, discard lines cut by the band's top or bottom edge (partial text).
    if(req.value("drop_edge_boxes",false))
        boxes.erase(std::remove_if(boxes.begin(),boxes.end(),[&](const Box& b){return b.y0<=1||b.y1>=img.h-1;}),boxes.end());
    const double det_ms=ms_since(t_det);
    const auto& specs=req.at("recognizers");const std::string route=req.value("route",std::string("auto"));
    const double auto_threshold=req.value("auto_threshold",0.9);
    // At most `max_recognizers` recogniser sessions are loaded at once (least recently used is released first).
    const size_t max_loaded=static_cast<size_t>(std::clamp(req.value("max_recognizers",2),1,16));
    std::map<std::string,Recognizer> loaded;std::vector<std::string> lru;double rec_load_ms=0;
    auto model_key=[&](const std::string& key){return std::make_pair(lens::utf8_path(specs.at(key).at("model").get<std::string>()).wstring(),threads);};
    auto get=[&](const std::string& key)->Recognizer& {
        lru.erase(std::remove(lru.begin(),lru.end(),key),lru.end());lru.push_back(key);
        auto it=loaded.find(key);if(it!=loaded.end())return it->second;
        if(!specs.contains(key))throw lens::Error("recognizer_unavailable");
        while(loaded.size()>=max_loaded){const auto old=lru.front();lru.erase(lru.begin());loaded.erase(old);rt.sessions.erase(model_key(old));}
        Recognizer r{&rt.cached(lens::utf8_path(specs.at(key).at("model").get<std::string>()),threads,rec_load_ms),
                     &load_dictionary(rt,specs.at(key).at("dictionary").get<std::string>()),specs.at(key).value("rtl",false)};
        return loaded.emplace(key,r).first->second;
    };
    const auto t_rec=std::chrono::steady_clock::now();json lines=json::array();
    // Auto order: the previous screen's script first (it is still loaded), then the general recogniser, then the rest;
    // within a screen the most recently successful script moves to the front. After `max_probe_misses` lines that no
    // recogniser reads confidently (a script without a recogniser), lines stop probing every model.
    std::vector<std::string> order;
    if(specs.contains(rt.preferred))order.push_back(rt.preferred);
    if(specs.contains("general")&&rt.preferred!="general")order.push_back("general");
    for(const auto& [key,_]:specs.items())if(std::find(order.begin(),order.end(),key)==order.end())order.push_back(key);
    const int max_misses=req.value("max_probe_misses",2);int misses=0;const bool merge_lines=req.value("merge_lines",true);
    for(const auto& b:boxes) {
        auto crop=sub(img,b.x0,b.y0,b.x1,b.y1);
        if(crop.h>=1.5*crop.w)crop=rotate_ccw(crop);
        std::string used=route=="auto"?order.front():route;auto [text,conf]=get(used)(crop);
        if(route=="auto"&&conf<auto_threshold) {
            const size_t limit=misses>=max_misses?std::min<size_t>(2,order.size()):order.size();bool found=false;
            for(size_t k=1;k<limit;++k) {
                auto [t2,c2]=get(order[k])(crop);
                if(c2>conf){text=t2;conf=c2;used=order[k];}
                if(c2>=auto_threshold){std::rotate(order.begin(),order.begin()+k,order.begin()+k+1);found=true;break;}
            }
            if(!found&&limit==order.size())++misses;
        }
        if(text.find_first_not_of(' ')==std::string::npos)continue;
        // The detector can split one line at wide word gaps (Urdu, code). A box that overlaps the previous one
        // vertically by >= 50% and starts within two line heights of it continues that line; right-to-left
        // recognisers' segments are joined right to left. Farther segments join only as a row of a table, form or
        // list (vertical centres within 20% of the text height, heights within 60% — unclip makes short words' boxes
        // taller), never two wide segments (side-by-side text columns).
        if(!lines.empty()&&merge_lines) {
            auto& prev=lines.back();const auto pb=prev.at("box").get<std::vector<int>>();
            const int overlap=std::min(pb[3],b.y1)-std::max(pb[1],b.y0),h=std::min(pb[3]-pb[1],b.y1-b.y0),tall=std::max(pb[3]-pb[1],b.y1-b.y0);
            const bool row=std::abs((pb[1]+pb[3])-(b.y0+b.y1))*10<=4*h&&h*10>=6*tall&&!((pb[2]-pb[0])*100>35*img.w&&(b.x1-b.x0)*100>35*img.w);
            if(overlap*2>=h&&b.x0>=pb[0]&&(b.x0-pb[2]<=2*h||row)) {
                const bool rtl=specs.at(used).value("rtl",false)&&specs.at(prev.at("recognizer").get<std::string>()).value("rtl",false);
                const auto pt=prev.at("text").get<std::string>();
                const double n0=static_cast<double>(pt.size()),n1=static_cast<double>(text.size());
                prev["confidence"]=(prev.at("confidence").get<double>()*n0+conf*n1)/(n0+n1);
                prev["text"]=rtl?text+" "+pt:pt+" "+text;
                prev["box"]={pb[0],std::min(pb[1],b.y0),std::max(pb[2],b.x1),std::max(pb[3],b.y1)};
                continue;
            }
        }
        lines.push_back({{"text",text},{"confidence",conf},{"box",{b.x0,b.y0,b.x1,b.y1}},{"recognizer",used}});
    }
    // Keep one recogniser resident between requests: the one that read the most lines (the screen's script), which the
    // next auto request tries first; the others are released and reload (~0.1-0.6 s) only when a later screen needs them.
    std::map<std::string,int> votes;for(const auto& l:lines)++votes[l.at("recognizer").get<std::string>()];
    std::string keep=route=="auto"?order.front():route;int best=0;
    for(const auto& [key,n]:votes)if(n>best){best=n;keep=key;}
    for(const auto& [key,_]:loaded)if(key!=keep)rt.sessions.erase(model_key(key));
    if(route=="auto")rt.preferred=keep;
    PROCESS_MEMORY_COUNTERS pmc{};GetProcessMemoryInfo(GetCurrentProcess(),&pmc,sizeof pmc);
    return {{"ok",true},{"lines",lines},{"boxes",boxes.size()},{"width",img.w},{"height",img.h},
            {"timing_ms",{{"detector_load",load_ms},{"detect",det_ms},{"recognizer_load",rec_load_ms},{"recognize",ms_since(t_rec)-rec_load_ms}}},
            {"peak_working_set_bytes",pmc.PeakWorkingSetSize},{"runtime_version",rt.base->GetVersionString()},
            {"scope","screen text detection + script-routed recognition"}};
}

json handle(const json& req,Runtime& rt) {
    if(!req.value("consent",false))throw lens::Error("consent_required");
    const auto bytes=req.contains("image_base64")?base64_decode(req.at("image_base64").get<std::string>())
                                                  :lens::read_file(lens::utf8_path(req.at("image").get<std::string>()),64000000);
    auto img=decode(bytes);
    if(req.value("mode",std::string("crop"))=="screen")return screen(req,rt,std::move(img));
    double load_ms=0;
    Recognizer rec{&rt.cached(lens::utf8_path(req.at("model").get<std::string>()),2,load_ms),&load_dictionary(rt,req.at("dictionary").get<std::string>())};
    const auto [text,confidence]=rec(img);
    return {{"ok",true},{"text",text},{"confidence",confidence},{"runtime_version",rt.base->GetVersionString()},
            {"scope","text recognition crop; use mode=screen for detection"}};
}

// --serve: answer one JSON request per line until stdin closes, keeping ONNX Runtime and model sessions loaded.
// Errors come back as {"ok":false,"error":...} lines. The caller closes stdin when idle to release the memory.
int serve() {
    std::unique_ptr<Runtime> rt;std::filesystem::path runtime_path;Com com;
    if(FAILED(com.result)){std::cout<<json{{"ok",false},{"error","image_decoder_unavailable"}}.dump()<<std::endl;return 1;}
    std::string line;
    while(true) {
        const auto status=lens::read_line(std::cin,line,64*1024*1024);
        if(status==lens::Line::end)return 0;
        json response;
        try {
            if(status!=lens::Line::ready)throw lens::Error("request_too_large");
            const auto req=json::parse(line);
            if(!req.value("consent",false))throw lens::Error("consent_required");
            const auto path=lens::utf8_path(req.at("runtime").get<std::string>());
            if(!rt){rt=std::make_unique<Runtime>(path);runtime_path=path;}
            else if(path!=runtime_path)throw lens::Error("runtime_mismatch");
            response=handle(req,*rt);
        } catch(const lens::Error& e){response={{"ok",false},{"error",e.what()}};}
        catch(const Ort::Exception&){response={{"ok",false},{"error","ocr_runtime_failed"}};}
        catch(...){response={{"ok",false},{"error","ocr_request_failed"}};}
        std::cout<<response.dump()<<std::endl;
    }
}
}

int main(int argc,char** argv) {
    if(argc>1&&std::string(argv[1])=="--serve")return serve();
    try {
        std::string line;if(lens::read_line(std::cin,line,64*1024*1024)!=lens::Line::ready)throw lens::Error("invalid_request");
        const auto req=json::parse(line);
        if(!req.value("consent",false))throw lens::Error("consent_required");
        Runtime rt(lens::utf8_path(req.at("runtime").get<std::string>()));
        Com com;if(FAILED(com.result))throw lens::Error("image_decoder_unavailable");
        std::cout<<handle(req,rt).dump()<<'\n';
    } catch(const lens::Error& e){std::cerr<<e.what()<<'\n';return 1;}
    catch(const Ort::Exception&){std::cerr<<"ocr_runtime_failed\n";return 1;}
    catch(...){std::cerr<<"ocr_request_failed\n";return 1;}
}
