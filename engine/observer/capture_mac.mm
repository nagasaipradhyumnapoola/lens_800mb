// macOS capture for screen_capture.hpp: the window's on-screen area through ScreenCaptureKit (macOS 14+), which needs
// the user's Screen Recording permission; without it the frame is empty and the OCR fallback is skipped.
#import <Foundation/Foundation.h>
#import <ScreenCaptureKit/ScreenCaptureKit.h>
#import <CoreGraphics/CoreGraphics.h>
#include "screen_capture.hpp"
#include "ax_registry.hpp"

namespace lens::observe {
Frame capture_window(Window id) {
    AXUIElementRef w=ax_window(id);if(!w)return {};
    CFTypeRef p=nullptr,s=nullptr;CGPoint pt{};CGSize sz{};
    AXUIElementCopyAttributeValue(w,kAXPositionAttribute,&p);AXUIElementCopyAttributeValue(w,kAXSizeAttribute,&s);
    const bool ok=p&&s&&AXValueGetValue(static_cast<AXValueRef>(p),static_cast<AXValueType>(kAXValueCGPointType),&pt)&&
                  AXValueGetValue(static_cast<AXValueRef>(s),static_cast<AXValueType>(kAXValueCGSizeType),&sz);
    if(p)CFRelease(p);if(s)CFRelease(s);
    if(!ok||sz.width<8||sz.height<8||sz.width*sz.height>16000000)return {};
    if(@available(macOS 14.0,*)) {
        __block CGImageRef image=nullptr;dispatch_semaphore_t done=dispatch_semaphore_create(0);
        [SCShareableContent getShareableContentWithCompletionHandler:^(SCShareableContent* content,NSError* error){
            if(error||content.displays.count==0){dispatch_semaphore_signal(done);return;}
            SCContentFilter* filter=[[SCContentFilter alloc] initWithDisplay:content.displays.firstObject excludingWindows:@[]];
            SCStreamConfiguration* cfg=[SCStreamConfiguration new];cfg.sourceRect=CGRectMake(pt.x,pt.y,sz.width,sz.height);
            cfg.width=static_cast<size_t>(sz.width);cfg.height=static_cast<size_t>(sz.height);cfg.showsCursor=NO;
            [SCScreenshotManager captureImageWithFilter:filter configuration:cfg completionHandler:^(CGImageRef img,NSError* err){
                if(!err&&img)image=CGImageRetain(img);dispatch_semaphore_signal(done);}];
        }];
        if(dispatch_semaphore_wait(done,dispatch_time(DISPATCH_TIME_NOW,5*NSEC_PER_SEC))!=0||!image)return {};
        const size_t iw=CGImageGetWidth(image),ih=CGImageGetHeight(image);
        std::vector<unsigned char> rgba(iw*ih*4);
        CGColorSpaceRef cs=CGColorSpaceCreateDeviceRGB();
        CGContextRef ctx=CGBitmapContextCreate(rgba.data(),iw,ih,8,iw*4,cs,kCGImageAlphaNoneSkipLast|kCGBitmapByteOrder32Big);
        CGColorSpaceRelease(cs);if(!ctx){CGImageRelease(image);return {};}
        CGContextDrawImage(ctx,CGRectMake(0,0,iw,ih),image);CGContextRelease(ctx);CGImageRelease(image);
        Frame f;f.w=static_cast<int>(iw);f.h=static_cast<int>(ih);f.bgr.resize(iw*ih*3);
        for(size_t i=0;i<iw*ih;++i){f.bgr[i*3]=rgba[i*4+2];f.bgr[i*3+1]=rgba[i*4+1];f.bgr[i*3+2]=rgba[i*4];}
        return f;
    }
    return {};
}
}
