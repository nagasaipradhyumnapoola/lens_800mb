import Foundation
import WatchConnectivity

/// Lens on Apple Watch goes through this iPhone: questions are answered here (the laptop first, then this iPhone) and
/// notes are stored here. The watch never holds memory or keys of its own.
final class WatchRelay: NSObject, WCSessionDelegate {
    private let service: LensService

    init(service: LensService) { self.service = service }

    func activate() {
        guard WCSession.isSupported() else { return }
        WCSession.default.delegate = self
        WCSession.default.activate()
    }

    var status: String {
        guard WCSession.isSupported() else { return "Not available on this iPhone" }
        let s = WCSession.default
        guard s.activationState == .activated, s.isPaired else { return "No Apple Watch paired" }
        return s.isWatchAppInstalled ? "Ready on your Apple Watch" : "Install Lens from the Watch app"
    }

    func session(_ session: WCSession, activationDidCompleteWith state: WCSessionActivationState, error: Error?) {}
    func sessionDidBecomeInactive(_ session: WCSession) {}
    func sessionDidDeactivate(_ session: WCSession) { session.activate() }  // switching to another watch

    func session(_ session: WCSession, didReceiveMessage message: [String: Any], replyHandler: @escaping ([String: Any]) -> Void) {
        Task { replyHandler(await handle(message)) }
    }

    /// Notes queued on the watch while this iPhone was out of reach (delivered once, in order).
    func session(_ session: WCSession, didReceiveUserInfo userInfo: [String: Any] = [:]) {
        Task { _ = await handle(userInfo) }
    }

    private func handle(_ message: [String: Any]) async -> [String: Any] {
        switch message["op"] as? String {
        case "ask":
            guard let query = message["query"] as? String, !query.isEmpty else { return ["ok": false, "error": "empty"] }
            let answer = await service.ask(query)
            return ["ok": answer.error == nil, "origin": answer.origin.rawValue, "unreachable": answer.laptopUnreachable,
                    "results": answer.results.map { e in
                        ["quote": String(e.quote.prefix(600)), "app": e.app, "kind": e.kind, "time": e.date?.timeIntervalSince1970 ?? 0]
                    }]
        case "note":
            guard let text = message["text"] as? String else { return ["ok": false, "error": "empty"] }
            let result = await service.remember(text, kind: message["kind"] as? String == "voice_note" ? "voice_note" : "note",
                                                app: "Apple Watch")
            return ["ok": result.stored, "message": result.message]
        default:
            return ["ok": false, "error": "unsupported_operation"]
        }
    }
}
