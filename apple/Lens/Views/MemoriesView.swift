import SwiftUI

/// What this iPhone remembers, newest first, grouped by day. Each item can be opened in full or deleted.
struct MemoriesView: View {
    @Environment(AppModel.self) private var model
    @State private var filter = ""
    @State private var pendingDelete: Evidence?

    private var days: [(day: Date, items: [Evidence])] {
        let shown = filter.isEmpty ? model.memories : model.memories.filter { $0.text.localizedCaseInsensitiveContains(filter) }
        let groups = Dictionary(grouping: shown) { Calendar.current.startOfDay(for: $0.date ?? .distantPast) }
        return groups.keys.sorted(by: >).map { ($0, groups[$0] ?? []) }
    }

    var body: some View {
        NavigationStack {
            Group {
                if model.memories.isEmpty {
                    ContentUnavailableView("Nothing remembered yet", systemImage: "tray",
                                           description: Text("Notes, voice, photos and things you share to Lens appear here."))
                } else {
                    List {
                        ForEach(days, id: \.day) { group in
                            Section(group.day == .distantPast ? "Undated" : group.day.formatted(.dateTime.weekday(.wide).day().month(.wide))) {
                                ForEach(group.items) { item in
                                    NavigationLink(value: item) { MemoryRow(item: item) }
                                        .swipeActions {
                                            Button(role: .destructive) { pendingDelete = item } label: { Label("Delete", systemImage: "trash") }
                                        }
                                }
                            }
                        }
                    }
                    .searchable(text: $filter, prompt: "Filter")
                }
            }
            .navigationTitle("Memories")
            .navigationDestination(for: Evidence.self) { item in MemoryDetail(item: item) { pendingDelete = $0 } }
            .refreshable { await model.refresh() }
            .task { await model.refresh() }
            .confirmationDialog("Delete this memory?", isPresented: Binding(get: { pendingDelete != nil }, set: { if !$0 { pendingDelete = nil } }),
                                titleVisibility: .visible, presenting: pendingDelete) { item in
                Button("Delete", role: .destructive) { Task { await model.delete(item) } }
            } message: { _ in
                Text("It is removed from this iPhone with everything Lens derived from it. A copy already sent to your laptop stays there.")
            }
        }
    }
}

private struct MemoryRow: View {
    let item: Evidence

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: item.symbol)
                .foregroundStyle(.tint)
                .frame(width: 24)
            VStack(alignment: .leading, spacing: 4) {
                Text(item.text).lineLimit(2)
                HStack(spacing: 4) {
                    Text(item.app)
                    if let date = item.date { Text("·"); Text(date, style: .time) }
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 2)
    }
}

private struct MemoryDetail: View {
    let item: Evidence
    let delete: (Evidence) -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text(item.text).textSelection(.enabled)
                Divider()
                VStack(alignment: .leading, spacing: 6) {
                    Label(item.app, systemImage: item.symbol)
                    if let date = item.date { Label(date.formatted(date: .complete, time: .shortened), systemImage: "calendar") }
                    Label("Stored encrypted on this iPhone", systemImage: "lock")
                }
                .font(.footnote)
                .foregroundStyle(.secondary)
            }
            .padding()
        }
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .destructiveAction) {
                Button(role: .destructive) { delete(item); dismiss() } label: { Image(systemName: "trash") }
                    .accessibilityLabel("Delete")
            }
            ToolbarItem(placement: .primaryAction) {
                ShareLink(item: item.text)
            }
        }
    }
}
