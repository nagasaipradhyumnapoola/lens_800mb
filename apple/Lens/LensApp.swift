import SwiftUI

@main
struct LensApp: App {
    @State private var model = AppModel()
    @Environment(\.scenePhase) private var phase

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .tint(.indigo)
        }
        .onChange(of: phase) { _, now in
            if now == .active { model.becameActive() }
        }
    }
}

/// App state the views share: the paired laptop, items waiting for it, and this iPhone's memories.
@MainActor
@Observable
final class AppModel {
    let service = LensService.shared
    private(set) var laptop: Laptop?
    private(set) var pending = 0
    private(set) var memories: [Evidence] = []
    private(set) var storeProblem: String?
    private(set) var sending = false
    private let relay: WatchRelay

    init() {
        relay = WatchRelay(service: LensService.shared)
        laptop = LensService.shared.laptop
        relay.activate()
    }

    var watchStatus: String { relay.status }

    func becameActive() {
        Task {
            storeProblem = await service.storeProblem()
            await refresh()
            if LensPaths.demo && memories.isEmpty { await seedDemo() }
            await sendWaiting()
        }
    }

    /// Synthetic items for demo and screenshot runs (`-LensDemo YES`), stored in the separate demo memory.
    private func seedDemo() async {
        let items = [("Book recommendation from Ana: The Overstory by Richard Powers.", "note"),
                     ("Call Tomás about the catering quote before Wednesday.", "voice_note"),
                     ("Flight to Lisbon: TP 1351 on 4 December, departs 07:40, seat 14C.", "share"),
                     ("Kestrel Hall is booked for the team dinner on Saturday 14 December from 6 pm. Deposit of $400 paid.", "share"),
                     ("Dentist appointment moved to Thursday 20 Nov at 8:30 am with Dr. Mehta at the Elm Street clinic.", "note")]
        for (text, kind) in items { _ = await service.remember(text, kind: kind) }
        await refresh()
    }

    func refresh() async {
        memories = await service.timeline()
        pending = service.pendingCount()
        laptop = service.laptop
    }

    func sendWaiting() async {
        guard laptop != nil, service.pendingCount() > 0, !sending else { return }
        sending = true
        await service.flush()
        sending = false
        pending = service.pendingCount()
    }

    func remember(_ text: String, kind: String, metadata: JSON? = nil) async -> SaveResult {
        let result = await service.remember(text, kind: kind, metadata: metadata)
        await refresh()
        return result
    }

    func delete(_ item: Evidence) async {
        if await service.delete(item.id) { memories.removeAll { $0.id == item.id } }
    }

    func paired() { laptop = service.laptop }

    func unpair() {
        service.unpair()
        laptop = nil
    }

    func erase() async {
        await service.erase()
        await refresh()
    }
}
