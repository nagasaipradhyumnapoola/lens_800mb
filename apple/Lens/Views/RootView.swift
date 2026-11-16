import SwiftUI

struct RootView: View {
    @Environment(AppModel.self) private var model
    @AppStorage("onboarded") private var onboarded = false

    var body: some View {
        TabView {
            AskView()
                .tabItem { Label("Ask", systemImage: "magnifyingglass") }
            RememberView()
                .tabItem { Label("Remember", systemImage: "plus.circle") }
            MemoriesView()
                .tabItem { Label("Memories", systemImage: "clock") }
            SettingsView()
                .tabItem { Label("Lens", systemImage: "gearshape") }
        }
        .sheet(isPresented: Binding(get: { !onboarded }, set: { if !$0 { onboarded = true } })) {
            OnboardingView { onboarded = true }
                .interactiveDismissDisabled()
        }
    }
}

/// First run: what Lens on iPhone does and does not do, before anything is stored.
struct OnboardingView: View {
    let done: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 28) {
            Spacer(minLength: 12)
            Image(systemName: "circle.circle")
                .font(.system(size: 56, weight: .light))
                .foregroundStyle(.tint)
            Text("Your memory, private to you")
                .font(.largeTitle.bold())
            VStack(alignment: .leading, spacing: 20) {
                Point(symbol: "hand.raised", title: "Only what you give it",
                      detail: "Notes, voice, photos and things you share. Lens never reads other apps on your iPhone.")
                Point(symbol: "lock", title: "Encrypted on this iPhone",
                      detail: "Kept on this device only, never in iCloud backups. Voice is recognised here and never stored.")
                Point(symbol: "laptopcomputer", title: "Your laptop's memory, here",
                      detail: "Pair with Lens on your laptop to ask everything it remembers, over an encrypted link on your Wi-Fi.")
                Point(symbol: "checkmark.shield", title: "Answers with evidence",
                      detail: "Every answer shows where it came from. When nothing supports an answer, Lens says so instead of guessing.")
            }
            Spacer()
            Button(action: done) {
                Text("Continue").frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
        }
        .padding(28)
    }

    private struct Point: View {
        let symbol: String, title: String, detail: String
        var body: some View {
            HStack(alignment: .top, spacing: 16) {
                Image(systemName: symbol)
                    .font(.title2)
                    .foregroundStyle(.tint)
                    .frame(width: 32)
                VStack(alignment: .leading, spacing: 3) {
                    Text(title).font(.headline)
                    Text(detail).font(.subheadline).foregroundStyle(.secondary)
                }
            }
        }
    }
}

/// One piece of evidence: what was remembered, from where and when. The text is selectable; query words are marked.
struct EvidenceCard: View {
    let item: Evidence
    var query: String = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) {
                Image(systemName: item.symbol)
                Text(item.app)
                if !item.window.isEmpty { Text("·"); Text(item.window).lineLimit(1) }
                Spacer(minLength: 8)
                if let date = item.date { Text(date, format: .relative(presentation: .named)) }
            }
            .font(.caption)
            .foregroundStyle(.secondary)
            Text(highlighted)
                .font(.body)
                .textSelection(.enabled)
            if !item.device.isEmpty && item.device != "phone" {
                Label(item.device, systemImage: "laptopcomputer")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(uiColor: .secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .accessibilityElement(children: .combine)
    }

    private static let stopwords: Set<String> = ["the", "and", "for", "with", "what", "when", "where", "which", "who", "how", "did", "does", "was",
        "were", "are", "about", "this", "that", "from", "have", "has", "had", "will", "can", "you", "your", "our", "his", "her", "its", "they", "them"]

    private var highlighted: AttributedString {
        var text = AttributedString(item.quote)
        let plain = item.quote
        for word in query.split(whereSeparator: { !$0.isLetter && !$0.isNumber }) where word.count >= 3 && !Self.stopwords.contains(word.lowercased()) {
            var from = plain.startIndex
            while let found = plain.range(of: word, options: [.caseInsensitive, .diacriticInsensitive], range: from..<plain.endIndex) {
                if let range = Range(found, in: text) {
                    text[range].inlinePresentationIntent = .stronglyEmphasized
                    text[range].backgroundColor = Color.accentColor.opacity(0.18)
                }
                from = found.upperBound
            }
        }
        return text
    }
}
