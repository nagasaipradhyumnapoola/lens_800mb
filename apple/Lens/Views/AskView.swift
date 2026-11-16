import SwiftUI

struct AskView: View {
    @Environment(AppModel.self) private var model
    @State private var query = ""
    @State private var asked = ""
    @State private var answer: Answer?
    @State private var asking = false
    @State private var dictation = Dictation()
    @FocusState private var focused: Bool

    private let examples = ["What did I note about the venue?", "When is the dentist appointment?", "Which flight did I book?"]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    field
                    if let problem = dictation.problem { Notice(text: problem, symbol: "mic.slash") }
                    content
                }
                .padding(.horizontal)
                .padding(.bottom, 24)
            }
            .scrollDismissesKeyboard(.interactively)
            .background(Color(uiColor: .systemGroupedBackground))
            .navigationTitle("Ask")
        }
        .task {  // demo runs: `-LensAsk "question"` asks once the synthetic memory is in place
            guard LensPaths.demo, answer == nil, let q = UserDefaults.standard.string(forKey: "LensAsk") else { return }
            for _ in 0..<40 where model.memories.count < 5 { try? await Task.sleep(for: .milliseconds(250)) }
            query = q
            ask()
        }
        .onChange(of: dictation.transcript) { _, text in if !text.isEmpty { query = text } }
        .onChange(of: dictation.running) { _, running in if !running && !query.isEmpty && !asking { ask() } }
    }

    private var field: some View {
        HStack(alignment: .bottom, spacing: 10) {
            TextField("Ask your memory", text: $query, axis: .vertical)
                .lineLimit(1...4)
                .focused($focused)
                .submitLabel(.search)
                .onSubmit(ask)
                .padding(.vertical, 12)
            Button {
                Task { await dictation.toggle() }
            } label: {
                Image(systemName: dictation.running ? "waveform" : "mic")
                    .symbolEffect(.variableColor.iterative, isActive: dictation.running)
                    .frame(width: 32, height: 32)
            }
            .accessibilityLabel(dictation.running ? "Stop listening" : "Ask by voice")
            .padding(.bottom, 6)
            Button(action: ask) {
                Image(systemName: "arrow.up.circle.fill").font(.title)
            }
            .disabled(query.trimmingCharacters(in: .whitespaces).isEmpty || asking)
            .accessibilityLabel("Ask")
            .padding(.bottom, 4)
        }
        .padding(.horizontal, 14)
        .background(Color(uiColor: .secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }

    @ViewBuilder private var content: some View {
        if asking {
            HStack(spacing: 10) {
                ProgressView()
                Text(model.laptop != nil ? "Searching your laptop…" : "Searching this iPhone…").foregroundStyle(.secondary)
            }
            .padding(.top, 8)
        } else if let answer {
            AnswerView(answer: answer, query: asked, paired: model.laptop != nil)
        } else {
            VStack(alignment: .leading, spacing: 10) {
                Text("Try").font(.footnote.weight(.semibold)).foregroundStyle(.secondary)
                ForEach(examples, id: \.self) { example in
                    Button {
                        query = example
                        ask()
                    } label: {
                        Label(example, systemImage: "text.magnifyingglass").frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .buttonStyle(.bordered)
                }
            }
            .padding(.top, 4)
        }
    }

    private func ask() {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty, !asking else { return }
        dictation.stop()
        focused = false
        asking = true
        asked = q
        Task {
            answer = await model.service.ask(q)
            asking = false
        }
    }
}

private struct AnswerView: View {
    let answer: Answer
    let query: String
    let paired: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if answer.laptopUnreachable {
                Notice(text: "Your laptop is not reachable, so this searched only this iPhone.", symbol: "wifi.exclamationmark")
            }
            if answer.results.isEmpty {
                ContentUnavailableView {
                    Label("No reliable memory", systemImage: "questionmark.circle")
                } description: {
                    Text(answer.error.map { "Lens could not search (\($0))." }
                         ?? "Lens found nothing that answers this\(answer.searchedLaptop ? " on your laptop or this iPhone" : ""). It won't guess.")
                }
                .padding(.top, 12)
            } else {
                Label(answer.origin == .laptop ? "From your laptop's memory" : "From this iPhone",
                      systemImage: answer.origin == .laptop ? "laptopcomputer" : "iphone")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(.secondary)
                EvidenceCard(item: answer.results[0], query: query)
                if answer.results.count > 1 {
                    Text("Other matches")
                        .font(.footnote.weight(.semibold))
                        .foregroundStyle(.secondary)
                        .padding(.top, 6)
                    ForEach(answer.results.dropFirst().prefix(2)) { EvidenceCard(item: $0, query: query).opacity(0.85) }
                }
            }
            if !paired && answer.origin == .iPhone {
                Text("Pair with Lens on your laptop to ask everything it remembers.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
    }
}

struct Notice: View {
    let text: String
    let symbol: String

    var body: some View {
        Label(text, systemImage: symbol)
            .font(.footnote)
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.orange.opacity(0.12), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}
