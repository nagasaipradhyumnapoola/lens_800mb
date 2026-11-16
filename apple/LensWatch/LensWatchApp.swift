import SwiftUI
import WatchConnectivity

/// Lens on Apple Watch: ask your memory and take notes by voice or Scribble. Everything goes through the paired iPhone,
/// which asks the laptop; the watch keeps no memory, keys or history of its own.
@main
struct LensWatchApp: App {
    @State private var model = WatchModel()

    var body: some Scene {
        WindowGroup {
            WatchRoot().environment(model)
        }
    }
}

struct WatchResult: Identifiable, Hashable {
    let id = UUID()
    let quote: String
    let app: String
    let date: Date?
}

@MainActor
@Observable
final class WatchModel {
    private(set) var busy = false
    private(set) var status: String?
    private(set) var asked: String?
    private(set) var results: [WatchResult] = []
    private(set) var origin = ""
    private let link = PhoneLink()

    init() {
        link.activate()
        if UserDefaults.standard.bool(forKey: "LensDemo") {  // screenshot runs only: a synthetic answer, no iPhone involved
            asked = "When is the dentist appointment?"
            origin = "From your iPhone"
            results = [WatchResult(quote: "Dentist appointment moved to Thursday 20 Nov at 8:30 am with Dr. Mehta at the Elm Street clinic.",
                                   app: "Lens", date: Date().addingTimeInterval(-3 * 3600))]
        }
    }

    func ask(_ query: String) {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty else { return }
        busy = true
        status = nil
        asked = q
        results = []
        link.send(["op": "ask", "query": q]) { [weak self] reply in
            guard let self else { return }
            self.busy = false
            guard let reply else { self.status = "Your iPhone is not reachable. Keep it nearby with Lens installed."; return }
            self.results = (reply["results"] as? [[String: Any]] ?? []).map { r in
                let t = r["time"] as? Double ?? 0
                return WatchResult(quote: r["quote"] as? String ?? "", app: r["app"] as? String ?? "Lens",
                                   date: t > 0 ? Date(timeIntervalSince1970: t) : nil)
            }
            self.origin = reply["origin"] as? String == "laptop" ? "From your laptop" : "From your iPhone"
            if self.results.isEmpty { self.status = "No reliable memory. Lens won't guess." }
            else if reply["unreachable"] as? Bool == true { self.status = "Laptop not reachable; searched your iPhone." }
        }
    }

    func remember(_ text: String) {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return }
        let note: [String: Any] = ["op": "note", "text": t, "kind": "voice_note"]
        busy = true
        link.send(note) { [weak self] reply in
            guard let self else { return }
            self.busy = false
            if let reply { self.status = reply["message"] as? String ?? "Saved." }
            else {
                self.link.queue(note)  // delivered once the iPhone is back in reach
                self.status = "Saved for later: it goes to your iPhone when it is nearby."
            }
        }
    }
}

/// WatchConnectivity to the iPhone app. Replies arrive on the main actor.
final class PhoneLink: NSObject, WCSessionDelegate {
    func activate() {
        guard WCSession.isSupported() else { return }
        WCSession.default.delegate = self
        WCSession.default.activate()
    }

    func send(_ message: [String: Any], reply: @escaping @MainActor ([String: Any]?) -> Void) {
        let session = WCSession.default
        guard session.activationState == .activated, session.isReachable else { Task { @MainActor in reply(nil) }; return }
        session.sendMessage(message, replyHandler: { r in Task { @MainActor in reply(r) } },
                            errorHandler: { _ in Task { @MainActor in reply(nil) } })
    }

    func queue(_ message: [String: Any]) { WCSession.default.transferUserInfo(message) }

    func session(_ session: WCSession, activationDidCompleteWith state: WCSessionActivationState, error: Error?) {}
}

struct WatchRoot: View {
    @Environment(WatchModel.self) private var model

    var body: some View {
        NavigationStack {
            List {
                TextFieldLink(prompt: Text("Ask your memory"), label: { Label("Ask", systemImage: "magnifyingglass") },
                              onSubmit: { model.ask($0) })
                    .listItemTint(.indigo)
                TextFieldLink(prompt: Text("What should Lens remember?"), label: { Label("Remember", systemImage: "plus") },
                              onSubmit: { model.remember($0) })
                    .listItemTint(.indigo)
                if model.busy {
                    HStack { ProgressView(); Text("Asking…").foregroundStyle(.secondary) }
                }
                if let status = model.status {
                    Text(status).font(.footnote).foregroundStyle(.secondary)
                }
                if let asked = model.asked, !model.results.isEmpty {
                    Section {
                        ForEach(model.results) { r in
                            VStack(alignment: .leading, spacing: 4) {
                                Text(r.quote).font(.footnote).lineLimit(6)
                                HStack(spacing: 3) {
                                    Text(r.app)
                                    if let date = r.date { Text("·"); Text(date, format: .relative(presentation: .named)) }
                                }
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                            }
                            .padding(.vertical, 2)
                        }
                    } header: {
                        Text(model.origin)
                    } footer: {
                        Text("“\(asked)”")
                    }
                }
            }
            .navigationTitle("Lens")
        }
    }
}
