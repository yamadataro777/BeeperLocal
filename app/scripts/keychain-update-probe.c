/* Disposable fixture only. UI is disabled in this process so any required
 * authorization causes failure; this program cannot access production services. */
#include <CoreFoundation/CoreFoundation.h>
#include <Security/Security.h>
#include <stdio.h>
#include <string.h>

#ifndef PROBE_REVISION
#define PROBE_REVISION 1
#endif

int main(int argc, char **argv) {
    const char *prefix = "local.beeperlocal.signed-update-test.";
    if (argc != 3 || strncmp(argv[1], prefix, strlen(prefix)) != 0 ||
        strlen(argv[1]) != strlen(prefix) + 32) return 2;
    for (const char *p = argv[1] + strlen(prefix); *p; p++)
        if (!((*p >= '0' && *p <= '9') || (*p >= 'a' && *p <= 'f'))) return 2;
    OSStatus status = SecKeychainSetUserInteractionAllowed(false);
    if (status) return 3;
    CFStringRef service = CFStringCreateWithCString(NULL, argv[1], kCFStringEncodingUTF8);
    CFMutableDictionaryRef query = CFDictionaryCreateMutable(NULL, 0,
        &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    CFDictionarySetValue(query, kSecClass, kSecClassGenericPassword);
    CFDictionarySetValue(query, kSecAttrService, service);
    CFDictionarySetValue(query, kSecAttrAccount, CFSTR("disposable-fixture"));
    const char *text = "fixture-value";
    CFDataRef value = CFDataCreate(NULL, (const UInt8 *)text, strlen(text));
    if (strcmp(argv[2], "create") == 0) {
        CFDictionarySetValue(query, kSecValueData, value);
        status = SecItemAdd(query, NULL);
    } else if (strcmp(argv[2], "update") == 0) {
        CFMutableDictionaryRef changes = CFDictionaryCreateMutable(NULL, 0,
            &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
        CFDictionarySetValue(changes, kSecValueData, value);
        status = SecItemUpdate(query, changes);
        CFRelease(changes);
    } else if (strcmp(argv[2], "read") == 0) {
        CFDictionarySetValue(query, kSecReturnData, kCFBooleanTrue);
        CFDictionarySetValue(query, kSecMatchLimit, kSecMatchLimitOne);
        CFTypeRef found = NULL;
        status = SecItemCopyMatching(query, &found);
        if (!status && (!found || CFGetTypeID(found) != CFDataGetTypeID() ||
            CFDataGetLength(found) != (CFIndex)strlen(text) ||
            memcmp(CFDataGetBytePtr(found), text, strlen(text)) != 0)) status = errSecDecode;
        if (found) CFRelease(found);
    } else if (strcmp(argv[2], "delete") == 0) {
        status = SecItemDelete(query);
        if (status == errSecItemNotFound) status = errSecSuccess;
    } else status = errSecParam;
    CFRelease(value);
    CFRelease(query);
    CFRelease(service);
    printf("{\"revision\":%d,\"status\":%d,\"interactionAllowed\":false}\n", PROBE_REVISION, (int)status);
    return status ? 1 : 0;
}
