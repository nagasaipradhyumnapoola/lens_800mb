import Foundation
import Security
import LensCore

/// Swift side of the Lens C API (adapters/capi/lens.h): this iPhone's encrypted memory, the device identity for the Lens
/// link, and the link to a paired laptop. Requests and responses are the engine's JSON protocol.
typealias JSON = [String: Any]

extension Dictionary where Key == String, Value == Any {
    var ok: Bool { self["ok"] as? Bool ?? false }
    var error: String? { self["error"] as? String }
    func flag(_ key: String) -> Bool { self[key] as? Bool ?? false }
}

struct LensFailure: Error, Sendable { let code: String }

private func encode(_ object: Any) -> String? {
    guard JSONSerialization.isValidJSONObject(object), let data = try? JSONSerialization.data(withJSONObject: object) else { return nil }
    return String(data: data, encoding: .utf8)
}

private func decode(_ text: String?) -> JSON {
    guard let data = text?.data(using: .utf8), let object = (try? JSONSerialization.jsonObject(with: data)) as? JSON else {
        return ["ok": false, "error": "invalid_response"]
    }
    return object
}

/// Takes ownership of a string returned by the C API.
private func take(_ pointer: UnsafeMutablePointer<CChar>?) -> String? {
    guard let pointer else { return nil }
    defer { lens_free(pointer) }
    return String(cString: pointer)
}

/// Where Lens keeps this iPhone's memory: the app group container shared with the Share extension (the app's own
/// Application Support folder when the group is unavailable). Excluded from backups; protected until first unlock.
enum LensPaths {
    static let group = "group.org.secondbrain.lens"
    static var root: URL {
        let base = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: group)
            ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("Lens", isDirectory: true)
    }
    /// Screenshot and demo runs only (launch argument `-LensDemo YES`): a separate memory filled with synthetic items and
    /// no laptop; the user's own memory is never opened.
    static var demo: Bool { UserDefaults.standard.bool(forKey: "LensDemo") }
    static var memory: URL { root.appendingPathComponent(demo ? "Demo" : "Memory", isDirectory: true) }
    static var outbox: URL { root.appendingPathComponent(demo ? "demo-outbox.jsonl" : "outbox.jsonl") }
    static var defaults: UserDefaults { UserDefaults(suiteName: group) ?? .standard }

    static func prepare(_ directory: URL) throws {
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                                                attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication])
        var url = directory
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try? url.setResourceValues(values)
    }
}

/// The memory core in this process (SQLCipher; the database key is wrapped by a Keychain key that never leaves this device).
final class MemoryStore {
    private var handle: OpaquePointer?

    init(directory: URL) throws {
        try LensPaths.prepare(directory)
        var error: UnsafeMutablePointer<CChar>?
        guard let opened = lens_store_open(directory.appendingPathComponent("memory.db").path, "{}", &error) else {
            throw LensFailure(code: take(error) ?? "database_open_failed")
        }
        handle = opened
    }

    func request(_ request: JSON) -> JSON {
        guard let handle else { return ["ok": false, "error": "store_closed"] }
        guard let text = encode(request) else { return ["ok": false, "error": "invalid_request"] }
        return decode(take(lens_store_request(handle, text)))
    }

    func close() {
        if let handle { lens_store_close(handle) }
        handle = nil
    }

    deinit { close() }
}

/// Generic-password Keychain items of this app: this device only, readable after first unlock, never synced or backed up.
enum Keychain {
    private static func query(_ service: String, _ account: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: account]
    }

    static func read(service: String, account: String) -> Data? {
        var q = query(service, account)
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess else { return nil }
        return out as? Data
    }

    @discardableResult
    static func write(_ data: Data, service: String, account: String) -> Bool {
        delete(service: service, account: account)
        var q = query(service, account)
        q[kSecValueData as String] = data
        q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        return SecItemAdd(q as CFDictionary, nil) == errSecSuccess
    }

    static func delete(service: String, account: String) {
        SecItemDelete(query(service, account) as CFDictionary)
    }
}

/// This device's link identity: a P-256 key and self-signed certificate, made once and kept in the Keychain.
enum DeviceIdentity {
    struct Material: Codable { let key: String; let cert: String; let fingerprint: String }
    private static let service = "org.secondbrain.lens.link", account = "device-identity"

    static func current() throws -> Material {
        if let data = Keychain.read(service: service, account: account),
           let material = try? JSONDecoder().decode(Material.self, from: data) { return material }
        var key: UnsafeMutablePointer<CChar>?, cert: UnsafeMutablePointer<CChar>?, fingerprint: UnsafeMutablePointer<CChar>?
        guard lens_link_identity(&key, &cert, &fingerprint) == 0,
              let k = take(key), let c = take(cert), let f = take(fingerprint) else { throw LensFailure(code: "identity_failed") }
        let material = Material(key: k, cert: c, fingerprint: f)
        guard let data = try? JSONEncoder().encode(material), Keychain.write(data, service: service, account: account) else {
            throw LensFailure(code: "identity_failed")
        }
        return material
    }

    static func forget() { Keychain.delete(service: service, account: account) }
}

/// The pairing code the laptop shows (QR or text): where to connect, which certificate to trust, a one-time token.
struct PairingCode: Sendable {
    let hosts: [String]
    let port: Int
    let fingerprint: String
    let token: String

    init?(_ text: String) {
        guard let data = text.trimmingCharacters(in: .whitespacesAndNewlines).data(using: .utf8),
              let o = (try? JSONSerialization.jsonObject(with: data)) as? JSON, o["v"] as? Int == 1,
              let hosts = o["hosts"] as? [String], let port = o["port"] as? Int,
              let fp = (o["fp"] as? String)?.lowercased(), let token = (o["token"] as? String)?.lowercased() else { return nil }
        let usable = hosts.filter { !$0.isEmpty && $0.count <= 253 }
        guard !usable.isEmpty, (1...65535).contains(port), fp.isHex(64), token.isHex(32) else { return nil }
        self.hosts = usable
        self.port = port
        self.fingerprint = fp
        self.token = token
    }
}

extension String {
    /// Lower-case hexadecimal of exactly `length` characters.
    func isHex(_ length: Int) -> Bool { count == length && allSatisfy { $0.isHexDigit && !$0.isUppercase } }
}

/// A paired laptop: its addresses on the local network and the fingerprint its certificate must have.
struct Laptop: Codable, Sendable, Equatable {
    var hosts: [String]
    var port: Int
    var fingerprint: String
    var paired: Date
}

/// TLS 1.3 connection to the paired laptop: this device's certificate, the laptop pinned by fingerprint.
final class LaptopLink {
    private var handle: OpaquePointer?

    private init(handle: OpaquePointer) { self.handle = handle }

    static func connect(hosts: [String], port: Int, fingerprint: String, timeoutMs: Int32 = 8000) throws -> LaptopLink {
        let identity = try DeviceIdentity.current()
        guard let hostList = encode(hosts) else { throw LensFailure(code: "invalid_request") }
        var error: UnsafeMutablePointer<CChar>?
        guard let opened = lens_link_connect(hostList, Int32(port), fingerprint, identity.key, identity.cert, timeoutMs, &error) else {
            throw LensFailure(code: take(error) ?? "laptop_unreachable")
        }
        return LaptopLink(handle: opened)
    }

    func ask(_ request: JSON) -> JSON {
        guard let handle else { return ["ok": false, "error": "link_closed"] }
        guard let text = encode(request) else { return ["ok": false, "error": "invalid_request"] }
        return decode(take(lens_link_ask(handle, text)))
    }

    deinit { if let handle { lens_link_close(handle) } }
}
