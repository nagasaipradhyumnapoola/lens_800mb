import Foundation

/// One remembered item as Lens shows it: the evidence text and where and when it came from.
struct Evidence: Identifiable, Hashable, Sendable {
    let id: String
    let quote: String
    let text: String
    let app: String
    let window: String
    let date: Date?
    let device: String
    let kind: String

    /// A source row (timeline, find_source) or, with `quote`, a recall result.
    init?(source: JSON, quote: String? = nil) {
        guard let id = source["id"] as? String else { return nil }
        let text = source["text"] as? String ?? ""
        self.id = id
        self.text = text
        self.quote = (quote?.isEmpty == false ? quote : nil) ?? text
        self.app = Evidence.appName(source["source_application"] as? String ?? "")
        let locator = source["source_locator"] as? String ?? ""
        self.window = locator.hasPrefix("window:") ? String(locator.dropFirst(7)) : ""
        self.date = Evidence.parse(source["timestamp"] as? String)
        self.device = source["device"] as? String ?? ""
        self.kind = source["kind"] as? String ?? "note"
    }

    init?(result: JSON) {
        guard let source = result["source"] as? JSON else { return nil }
        self.init(source: source, quote: (result["evidence"] as? JSON)?["quote"] as? String)
    }

    var symbol: String {
        switch kind {
        case "voice_note": return "waveform"
        case "screen_observation": return "macwindow"
        case "share": return "square.and.arrow.down"
        case "photo": return "text.viewfinder"
        case "reminder": return "bell"
        default: return "note.text"
        }
    }

    static func appName(_ raw: String) -> String {
        var name = raw
        if name.hasPrefix("android:") { name = String(name.dropFirst(8)) }
        if name.lowercased().hasSuffix(".exe") { name = String(name.dropLast(4)) }
        if name.isEmpty || name == "lens-companion" { return "Lens" }
        return name.prefix(1).uppercased() + name.dropFirst()
    }

    private static func parse(_ text: String?) -> Date? {
        guard let text else { return nil }
        let precise = ISO8601DateFormatter()
        precise.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return precise.date(from: text) ?? ISO8601DateFormatter().date(from: text)
    }
}

/// The answer to a question: evidence from the laptop's whole memory or from this iPhone, or nothing (Lens abstains).
struct Answer: Sendable {
    enum Origin: String, Sendable { case laptop, iPhone }
    let results: [Evidence]
    let origin: Origin
    let laptopUnreachable: Bool
    let error: String?
    var searchedLaptop = false  // the laptop answered and had nothing; the iPhone was searched as well
}

/// What happened to an item the user asked Lens to remember.
enum SaveResult: Sendable, Equatable {
    case saved, sent, queued(Int), sensitive, failed(String)

    var message: String {
        switch self {
        case .saved: return "Saved on this iPhone."
        case .sent: return "Saved on this iPhone and your laptop."
        case .queued(let n): return "Saved on this iPhone. It goes to your laptop when it is reachable (\(n) waiting)."
        case .sensitive: return "Not saved: Lens never stores passwords, codes or card details."
        case .failed(let code): return "Could not save (\(code))."
        }
    }
    var stored: Bool { if case .saved = self { return true }; if case .sent = self { return true }; if case .queued = self { return true }; return false }
}

/// Everything Lens does on this iPhone, shared by the app, its Share extension and the Apple Watch relay. The memory and
/// the outbox are used on one serial queue; the laptop link on another, so a slow network never blocks local memory.
/// Items go to the laptop only while one is paired; pairing later never uploads earlier iPhone-only items.
final class LensService: @unchecked Sendable {
    static let shared = LensService()

    private let memoryQueue = DispatchQueue(label: "org.secondbrain.lens.memory", qos: .userInitiated)
    private let linkQueue = DispatchQueue(label: "org.secondbrain.lens.link", qos: .userInitiated)
    private var store: MemoryStore?
    private let lock = NSLock()
    private var cancelPairing = false

    // MARK: Paired laptop

    var laptop: Laptop? {
        get {
            guard !LensPaths.demo else { return nil }
            return LensPaths.defaults.data(forKey: "laptop").flatMap { try? JSONDecoder().decode(Laptop.self, from: $0) }
        }
        set { LensPaths.defaults.set(newValue.flatMap { try? JSONEncoder().encode($0) }, forKey: "laptop") }
    }

    /// The Lens account this iPhone joined with its first pairing; a laptop of another account is refused for good.
    var account: String? { LensPaths.defaults.string(forKey: "account") }

    // MARK: Memory

    private func onMemory<T>(_ work: @escaping (MemoryStore?) -> T) async -> T {
        await withCheckedContinuation { continuation in
            memoryQueue.async {
                if self.store == nil { self.store = try? MemoryStore(directory: LensPaths.memory) }
                continuation.resume(returning: work(self.store))
            }
        }
    }

    private func onLink<T>(_ work: @escaping () -> T) async -> T {
        await withCheckedContinuation { continuation in linkQueue.async { continuation.resume(returning: work()) } }
    }

    /// Whether this iPhone's memory opens; a reason code when it does not.
    func storeProblem() async -> String? {
        await onMemory { store in
            if store != nil { return nil }
            do { _ = try MemoryStore(directory: LensPaths.memory); return nil } catch let e as LensFailure { return e.code } catch { return "store_unavailable" }
        }
    }

    /// Stores one item the user gave Lens (consent is the user's action) and, when paired, sends it to the laptop.
    func remember(_ text: String, kind: String, app: String = "Lens", metadata: JSON? = nil, deliver: Bool = true) async -> SaveResult {
        let text = String(text.trimmingCharacters(in: .whitespacesAndNewlines).prefix(20000))
        guard !text.isEmpty else { return .failed("empty") }
        let id = "iphone-" + UUID().uuidString.lowercased()
        let now = ISO8601DateFormatter().string(from: Date())
        var item: JSON = ["op": "add", "consent": true, "id": id, "text": text, "language": "und", "timestamp": now, "kind": kind,
                          "device": "phone", "provenance": "lens-companion"]
        if let metadata { item["metadata"] = metadata }
        let paired = laptop != nil
        let local: SaveResult = await onMemory { store in
            guard let store else { return .failed("store_unavailable") }
            var add = item
            add["source_application"] = app
            add["consent_context"] = ["mode": kind == "voice_note" ? "explicit_user_voice_note" : "explicit_user_note"]
            let r = store.request(add)
            if r.error == "sensitive_content_excluded" { return .sensitive }
            guard r.ok else { return .failed(r.error ?? "store_unavailable") }
            if paired { self.appendOutbox(item) }
            return .saved
        }
        guard local == .saved, paired else { return local }
        guard deliver else { return .queued(pendingCount()) }
        let delivered = await flush()
        return delivered > 0 && pendingCount() == 0 ? .sent : .queued(pendingCount())
    }

    /// Recent items on this iPhone, newest first.
    func timeline(limit: Int = 100) async -> [Evidence] {
        await onMemory { store in
            guard let r = store?.request(["op": "timeline", "limit": limit]), r.ok else { return [] }
            return (r["sources"] as? [JSON] ?? []).compactMap { Evidence(source: $0) }
        }
    }

    func delete(_ id: String) async -> Bool {
        await onMemory { store in store?.request(["op": "delete", "consent": true, "id": id]).ok ?? false }
    }

    /// Asks the paired laptop (its whole memory) first; this iPhone's memory when there is no laptop, it cannot be
    /// reached, or it has nothing. Lens abstains rather than guessing: no results means no reliable evidence.
    func ask(_ query: String) async -> Answer {
        let query = String(query.trimmingCharacters(in: .whitespacesAndNewlines).prefix(1000))
        var unreachable = false, searched = false
        if let laptop {
            let remote: JSON? = await onLink {
                guard let link = try? LaptopLink.connect(hosts: laptop.hosts, port: laptop.port, fingerprint: laptop.fingerprint) else { return nil }
                return link.ask(["op": "recall", "query": query, "limit": 5])
            }
            if let remote, remote.ok {
                let results = (remote["results"] as? [JSON] ?? []).compactMap { Evidence(result: $0) }
                if !results.isEmpty || remote.flag("not_found") == false { return Answer(results: results, origin: .laptop, laptopUnreachable: false, error: nil) }
                searched = true
            } else {
                unreachable = true
            }
        }
        let searchedLaptop = searched
        let laptopUnreachable = unreachable
        return await onMemory { store in
            guard let store else { return Answer(results: [], origin: .iPhone, laptopUnreachable: laptopUnreachable, error: "store_unavailable") }
            let r = store.request(["op": "recall", "query": query, "limit": 5, "mode": "keyword"])
            let results = r.ok && !r.flag("not_found") ? (r["results"] as? [JSON] ?? []).compactMap { Evidence(result: $0) } : []
            return Answer(results: results, origin: .iPhone, laptopUnreachable: laptopUnreachable, error: r.ok ? nil : r.error,
                          searchedLaptop: searchedLaptop)
        }
    }

    /// Deletes everything Lens stored on this iPhone: the memory, its Keychain key (copies of the files become
    /// unreadable) and items waiting for the laptop. The pairing and the laptop's memory are not touched.
    func erase() async {
        await onMemory { store in
            store?.close()
            self.store = nil
            try? FileManager.default.removeItem(at: LensPaths.memory)
            try? FileManager.default.removeItem(at: LensPaths.outbox)
            Keychain.delete(service: "org.secondbrain.lens", account: "database-key-wrapping")  // adapters/apple/master_key.cpp
        }
    }

    func storageBytes() -> Int64 {
        let files = FileManager.default.enumerator(at: LensPaths.memory, includingPropertiesForKeys: [.fileSizeKey])
        var total: Int64 = 0
        while let url = files?.nextObject() as? URL { total += Int64((try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0) }
        return total
    }

    // MARK: Outbox (items waiting for the laptop)

    private func appendOutbox(_ item: JSON) {  // on memoryQueue
        guard let data = try? JSONSerialization.data(withJSONObject: item) else { return }
        try? LensPaths.prepare(LensPaths.root)
        if !FileManager.default.fileExists(atPath: LensPaths.outbox.path) {
            FileManager.default.createFile(atPath: LensPaths.outbox.path, contents: nil, attributes: [.protectionKey: FileProtectionType.complete])
        }
        guard let handle = try? FileHandle(forWritingTo: LensPaths.outbox) else { return }
        defer { try? handle.close() }
        _ = try? handle.seekToEnd()
        try? handle.write(contentsOf: data + Data("\n".utf8))
    }

    private func outboxItems() -> [JSON] {  // on memoryQueue
        guard let text = try? String(contentsOf: LensPaths.outbox, encoding: .utf8) else { return [] }
        return text.split(separator: "\n").compactMap { (try? JSONSerialization.jsonObject(with: Data($0.utf8))) as? JSON }
    }

    private func dropOutbox(_ ids: Set<String>) {  // on memoryQueue
        let keep = outboxItems().filter { !ids.contains($0["id"] as? String ?? "") }
        let lines = keep.compactMap { try? JSONSerialization.data(withJSONObject: $0) }.map { String(decoding: $0, as: UTF8.self) }
        try? (lines.isEmpty ? "" : lines.joined(separator: "\n") + "\n").write(to: LensPaths.outbox, atomically: true, encoding: .utf8)
    }

    func pendingCount() -> Int { memoryQueue.sync { outboxItems().count } }

    /// Sends waiting items to the laptop, in order; stops at the first refusal. Returns how many were delivered.
    @discardableResult
    func flush() async -> Int {
        guard let laptop else { return 0 }
        let items = await onMemory { _ in self.outboxItems() }
        guard !items.isEmpty else { return 0 }
        let delivered: Set<String> = await onLink {
            guard let link = try? LaptopLink.connect(hosts: laptop.hosts, port: laptop.port, fingerprint: laptop.fingerprint) else { return [] }
            var done = Set<String>()
            for item in items {
                let r = link.ask(item)
                guard r.ok || r.error == "immutable_source_conflict", let id = item["id"] as? String else { break }
                done.insert(id)
            }
            return done
        }
        if !delivered.isEmpty { await onMemory { _ in self.dropOutbox(delivered) } }
        return delivered.count
    }

    // MARK: Pairing

    /// Pairs with the laptop in the code. The laptop's user must approve this iPhone there: `onVerification` receives the
    /// 8-digit code to show, which must match the laptop's. Returns nil once approved, or a message for the user.
    func pair(_ code: PairingCode, deviceName: String, onVerification: @escaping @Sendable (String) -> Void) async -> String? {
        lock.withLock { cancelPairing = false }
        let account = self.account
        return await onLink {
            let link: LaptopLink
            do { link = try LaptopLink.connect(hosts: code.hosts, port: code.port, fingerprint: code.fingerprint) } catch {
                return (error as? LensFailure)?.code == "laptop_mismatch"
                    ? "This is not the laptop in the code. Show a new pairing code on the laptop."
                    : "Could not reach the laptop. Both devices must be on the same Wi-Fi network."
            }
            var request: JSON = ["op": "pair", "token": code.token, "name": String(deviceName.prefix(64))]
            if let account { request["account_id"] = account }
            var r = link.ask(request)
            if r.error == "account_mismatch" { return "This laptop belongs to a different Lens account. Lens never links devices of different accounts." }
            guard r.ok else { return "The laptop refused this code. Show a new pairing code on the laptop and try again." }
            if r.flag("awaiting_approval"), let shown = r["verification_code"] as? String { onVerification(shown) }
            let deadline = Date().addingTimeInterval(300)
            while !r.flag("paired") {
                if r.error == "pairing_denied" { return "Pairing was declined on the laptop." }
                if self.lock.withLock({ self.cancelPairing }) { return "Pairing cancelled." }
                guard r.ok, Date() < deadline else { return "The laptop did not approve this iPhone. Start pairing again." }
                Thread.sleep(forTimeInterval: 2)
                r = link.ask(["op": "pair_status"])
            }
            let joined = r["account_id"] as? String ?? ""
            guard joined.isHex(32), account == nil || account == joined else { return "This laptop belongs to a different Lens account." }
            LensPaths.defaults.set(joined, forKey: "account")
            self.laptop = Laptop(hosts: code.hosts, port: code.port, fingerprint: code.fingerprint, paired: Date())
            return nil
        }
    }

    func stopPairing() { lock.withLock { cancelPairing = true } }

    /// Forgets the laptop and this device's link identity; the iPhone keeps its Lens account, so it can only ever re-pair
    /// within that account.
    func unpair() {
        laptop = nil
        DeviceIdentity.forget()
    }
}
