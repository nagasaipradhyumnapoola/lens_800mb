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
            await sendWaiting()
        }
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
