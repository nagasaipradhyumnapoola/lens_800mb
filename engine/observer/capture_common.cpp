// Portable parts of screen_capture.hpp: changed-region detection and in-memory BMP encoding for the OCR worker.
#include "screen_capture.hpp"
#include "../platform.hpp"
#include <algorithm>
#include <cstdint>
#include <cstring>

namespace lens::observe {
std::optional<Rect> changed_region(const Frame& a,const Frame& b) {
    if(a.w!=b.w||a.h!=b.h||a.bgr.empty())return Rect{0,0,b.w,b.h};
    constexpr int tile=32;int x0=b.w,y0=b.h,x1=-1,y1=-1;
    for(int ty=0;ty<b.h;ty+=tile)for(int tx=0;tx<b.w;tx+=tile) {
        const int tw=std::min(tile,b.w-tx),th=std::min(tile,b.h-ty);bool diff=false;
        for(int y=ty;y<ty+th&&!diff;++y)diff=std::memcmp(&a.bgr[(static_cast<size_t>(y)*a.w+tx)*3],&b.bgr[(static_cast<size_t>(y)*b.w+tx)*3],static_cast<size_t>(tw)*3)!=0;
        if(diff){x0=std::min(x0,tx);y0=std::min(y0,ty);x1=std::max(x1,tx+tw);y1=std::max(y1,ty+th);}
    }
    if(x1<0)return std::nullopt;
    return Rect{x0,y0,x1-x0,y1-y0};
}

// 24-bit top-down BMP (BITMAPFILEHEADER + BITMAPINFOHEADER, little-endian), base64-encoded.
std::string bmp_base64(const Frame& f) {
    const uint32_t stride=(static_cast<uint32_t>(f.w)*3+3)&~3u,image=stride*static_cast<uint32_t>(f.h),offset=14+40;
    std::string file(offset+image,'\0');
    auto put=[&](size_t at,uint32_t v,int bytes){for(int i=0;i<bytes;++i)file[at+i]=static_cast<char>((v>>(8*i))&0xFF);};
    file[0]='B';file[1]='M';put(2,offset+image,4);put(10,offset,4);
    put(14,40,4);put(18,static_cast<uint32_t>(f.w),4);put(22,static_cast<uint32_t>(-f.h),4);put(26,1,2);put(28,24,2);put(34,image,4);
    for(int y=0;y<f.h;++y)std::memcpy(file.data()+offset+static_cast<size_t>(y)*stride,&f.bgr[static_cast<size_t>(y)*f.w*3],static_cast<size_t>(f.w)*3);
    return lens::platform::base64_encode(file);
}
}
