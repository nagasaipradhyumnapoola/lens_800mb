// Linux capture for screen_capture.hpp: the frame's on-screen area read from the X server (X11 or Xwayland; a native
// Wayland session gives no screen access without the desktop portal, so capture returns an empty frame there).
#include "screen_capture.hpp"
#include "atspi_registry.hpp"
#include "../platform.hpp"
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <algorithm>
#include <mutex>

namespace lens::observe {
Frame capture_window(Window id) {
    AtspiAccessible* frame=atspi_frame(id);if(!frame)return {};
    AtspiComponent* c=atspi_accessible_get_component_iface(frame);if(!c)return {};
    GError* e=nullptr;AtspiRect* r=atspi_component_get_extents(c,ATSPI_COORD_TYPE_SCREEN,&e);if(e)g_clear_error(&e);g_object_unref(c);
    if(!r)return {};
    int x=r->x,y=r->y,w=r->width,h=r->height;g_free(r);
    static std::mutex lock;static Display* display=nullptr;std::lock_guard g(lock);
    if(!display)display=XOpenDisplay(nullptr);
    if(!display)return {};
    const int sw=DisplayWidth(display,DefaultScreen(display)),sh=DisplayHeight(display,DefaultScreen(display));
    if(x<0){w+=x;x=0;}if(y<0){h+=y;y=0;}w=std::min(w,sw-x);h=std::min(h,sh-y);  // the visible part of the frame
    if(w<8||h<8||static_cast<long long>(w)*h>16000000)return {};
    XImage* img=XGetImage(display,DefaultRootWindow(display),x,y,static_cast<unsigned>(w),static_cast<unsigned>(h),AllPlanes,ZPixmap);
    if(!img)return {};
    Frame f;f.w=w;f.h=h;f.bgr.resize(static_cast<size_t>(w)*h*3);
    const bool direct=img->bits_per_pixel==32&&img->red_mask==0xFF0000&&img->green_mask==0xFF00&&img->blue_mask==0xFF&&img->byte_order==LSBFirst;
    for(int yy=0;yy<h;++yy)for(int xx=0;xx<w;++xx) {
        unsigned char* out=&f.bgr[(static_cast<size_t>(yy)*w+xx)*3];
        if(direct){const auto* p=reinterpret_cast<const unsigned char*>(img->data)+static_cast<size_t>(yy)*img->bytes_per_line+static_cast<size_t>(xx)*4;out[0]=p[0];out[1]=p[1];out[2]=p[2];}
        else {
            const unsigned long px=XGetPixel(img,xx,yy);
            auto chan=[&](unsigned long mask){if(!mask)return static_cast<unsigned char>(0);int s=0;while(!((mask>>s)&1))++s;const unsigned long m=mask>>s;return static_cast<unsigned char>(((px&mask)>>s)*255/m);};
            out[0]=chan(img->blue_mask);out[1]=chan(img->green_mask);out[2]=chan(img->red_mask);
        }
    }
    XDestroyImage(img);
    bool blank=true;for(size_t i=3;i<f.bgr.size()&&blank;i+=3)blank=f.bgr[i]==f.bgr[0]&&f.bgr[i+1]==f.bgr[1]&&f.bgr[i+2]==f.bgr[2];
    return blank?Frame{}:f;
}
}
