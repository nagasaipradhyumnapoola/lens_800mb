import PhotosUI
import SwiftUI
import UniformTypeIdentifiers

/// Everything Lens on iPhone remembers comes from here (or the Share sheet): typed or spoken notes, text in photos and
/// screenshots, and text files or PDFs. Each is stored only when the user taps to keep it.
struct RememberView: View {
    @Environment(AppModel.self) private var model
    @State private var note = ""
    @State private var noteKind = "note"
    @State private var dictation = Dictation()
    @State private var photo: PhotosPickerItem?
    @State private var importing = false
    @State private var working = false
    @State private var result: SaveResult?
    @State private var draft: Draft?
    @FocusState private var focused: Bool

    /// Text taken from a photo or file, shown for review before it is stored.
    struct Draft: Identifiable {
        let id = UUID()
        var text: String
        let kind: String
        let source: String
        let metadata: JSON
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    ZStack(alignment: .topLeading) {
                        if note.isEmpty && !dictation.running {
                            Text("Type or speak something to remember")
                                .foregroundStyle(.tertiary)
                                .padding(.top, 8)
                                .padding(.leading, 5)
                                .allowsHitTesting(false)
                        }
                        TextEditor(text: $note)
                            .focused($focused)
                            .frame(minHeight: 140)
                    }
                    HStack {
                        Button {
                            Task { await dictation.toggle() }
                        } label: {
                            Label(dictation.running ? "Stop" : "Speak", systemImage: dictation.running ? "stop.circle.fill" : "mic")
                                .symbolEffect(.pulse, isActive: dictation.running)
                        }
                        .buttonStyle(.bordered)
                        Spacer()
                        Button("Remember") { save(note, kind: noteKind) }
                            .buttonStyle(.borderedProminent)
                            .disabled(note.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || working)
                    }
                    if let problem = dictation.problem { Text(problem).font(.footnote).foregroundStyle(.orange) }
                } footer: {
                    Text("Voice is recognised on this iPhone and never stored; only the text is kept.")
                }

                Section("Add from") {
                    PhotosPicker(selection: $photo, matching: .images) {
                        Label("Text in a photo or screenshot", systemImage: "text.viewfinder")
                    }
                    Button { importing = true } label: {
                        Label("Text from a file or PDF", systemImage: "doc.text")
                    }
                }

                if let result {
                    Section {
                        Label(result.message, systemImage: result.stored ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                            .foregroundStyle(result.stored ? Color.green : Color.orange)
                    }
                }
            }
            .navigationTitle("Remember")
            .overlay { if working { ProgressView().controlSize(.large) } }
            .toolbar {
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("Done") { focused = false }
                }
            }
        }
        .onChange(of: dictation.transcript) { old, text in
            guard !text.isEmpty else { return }
            if old.isEmpty && !note.isEmpty && !note.hasSuffix(" ") { note += " " }
            if let spokenStart { note = String(note.prefix(spokenStart)) + text } else { spokenStart = note.count; note += text }
            noteKind = "voice_note"
        }
        .onChange(of: dictation.running) { _, running in if !running { spokenStart = nil } }
        .onChange(of: photo) { _, item in
            guard let item else { return }
            working = true
            Task {
                defer { working = false; photo = nil }
                guard let data = try? await item.loadTransferable(type: Data.self) else { result = .failed("photo_unreadable"); return }
                let text = (try? await Extract.text(inImage: data)) ?? ""
                if text.isEmpty { result = .failed("no text found in the photo") } else {
                    draft = Draft(text: text, kind: "share", source: "Photo", metadata: ["capture": "photo_ocr"])
                }
            }
        }
        .fileImporter(isPresented: $importing, allowedContentTypes: [.plainText, .pdf, .text]) { picked in
            guard case .success(let url) = picked else { return }
            if let text = Extract.text(inFile: url), !text.isEmpty {
                draft = Draft(text: text, kind: "share", source: url.lastPathComponent, metadata: ["capture": "file", "file_name": url.lastPathComponent])
            } else {
                result = .failed("no text in that file")
            }
        }
        .sheet(item: $draft) { d in
            DraftReview(draft: d) { text in save(text, kind: d.kind, metadata: d.metadata) }
        }
    }

    @State private var spokenStart: Int?

    private func save(_ text: String, kind: String, metadata: JSON? = nil) {
        dictation.stop()
        focused = false
        working = true
        Task {
            let r = await model.remember(text, kind: kind, metadata: metadata)
            working = false
            withAnimation { result = r }
            if r.stored && text == note { note = ""; noteKind = "note" }
        }
    }
}

/// Text found in a photo or file, editable before Lens keeps it.
private struct DraftReview: View {
    let draft: RememberView.Draft
    let keep: (String) -> Void
    @State private var text = ""
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            TextEditor(text: $text)
                .padding(.horizontal)
                .navigationTitle(draft.source)
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Remember") { keep(text); dismiss() }
                            .disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                }
                .safeAreaInset(edge: .bottom) {
                    Text("Check the text before keeping it. Lens stores only the text, not the photo or file.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .padding()
                }
        }
        .onAppear { text = draft.text }
    }
}
