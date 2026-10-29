// macOS and iOS: the master key is a generic-password Keychain item, readable only by this user on this device after the
// first unlock (kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly: never synced to iCloud, never in device backups).
#include "../posix/master_key.hpp"
#include "../../engine/input.hpp"
#include <CoreFoundation/CoreFoundation.h>
#include <Security/Security.h>
#include <cstring>
namespace lens {
namespace {
struct Ref{CFTypeRef p=nullptr;~Ref(){if(p)CFRelease(p);}};
CFMutableDictionaryRef query() {
    auto* q=CFDictionaryCreateMutable(nullptr,0,&kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks);
    CFDictionarySetValue(q,kSecClass,kSecClassGenericPassword);
    CFDictionarySetValue(q,kSecAttrService,CFSTR("org.secondbrain.lens"));
    CFDictionarySetValue(q,kSecAttrAccount,CFSTR("database-key-wrapping"));
    return q;
}
}
Key master_key(bool create) {
    Key key{};Ref q{query()},found;
    CFDictionarySetValue((CFMutableDictionaryRef)q.p,kSecReturnData,kCFBooleanTrue);
    const OSStatus st=SecItemCopyMatching((CFDictionaryRef)q.p,&found.p);
    if(st==errSecSuccess) {
        auto data=(CFDataRef)found.p;if(CFDataGetLength(data)!=static_cast<CFIndex>(key.size()))throw Error("key_unavailable");
        std::memcpy(key.data(),CFDataGetBytePtr(data),key.size());return key;
    }
    if(st!=errSecItemNotFound||!create)throw Error("key_unavailable");
    key=random_key();Ref add{query()},data{CFDataCreate(nullptr,key.data(),static_cast<CFIndex>(key.size()))};
    CFDictionarySetValue((CFMutableDictionaryRef)add.p,kSecValueData,data.p);
    CFDictionarySetValue((CFMutableDictionaryRef)add.p,kSecAttrAccessible,kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly);
    if(SecItemAdd((CFDictionaryRef)add.p,nullptr)!=errSecSuccess){std::memset(key.data(),0,key.size());throw Error("key_unavailable");}
    return key;
}
}
