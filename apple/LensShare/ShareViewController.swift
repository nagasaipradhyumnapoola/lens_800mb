import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// The Share sheet entry: text, a web page, a photo (its text, recognised on the iPhone) or a file shared to Lens is
/// shown for review and stored only when the user taps Remember. It goes to the laptop the next time Lens runs.
final class ShareViewController: UIViewController {
    override func viewDidLoad() {
        super.viewDidLoad()
        let items = (extensionContext?.inputItems as? [NSExtensionItem]) ?? []
        let host = UIHostingController(rootView: ShareView(providers: items.flatMap { $0.attachments ?? [] }) { [weak self] in
            self?.extensionContext?.completeRequest(returningItems: nil)
        })
        addChild(host)
        host.view.frame = view.bounds
        host.view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        view.addSubview(host.view)
        host.didMove(toParent: self)
    }
}

private struct ShareView: View {
    let providers: [NSItemProvider]
    let done: () -> Void
    @State private var text = ""
    @State private var metadata: JSON = ["capture": "share_sheet"]
    @State private var loading = true
    @State private var result: SaveResult?

    var body: some View {
        NavigationStack {
            Group {
                if loading {
                    ProgressView("Reading…")
                } else if text.isEmpty {
                    ContentUnavailableView("Nothing to remember", systemImage: "doc.questionmark",
                                           description: Text("Lens keeps text, web links, text in photos and text files."))
                } else {
                    VStack(alignment: .leading, spacing: 12) {
                        TextEditor(text: $text)
                        if let result {
                            Label(result.message, systemImage: result.stored ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                                .font(.footnote)
                                .foregroundStyle(result.stored ? Color.green : Color.orange)
                        } else {
                            Text("Stored encrypted on this iPhone; only the text is kept.")
                                .font(.footnote)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .padding()
                }
            }
            .navigationTitle("Remember in Lens")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel", action: done) }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Remember") {
                        Task {
                            let r = await LensService.shared.remember(text, kind: "share", metadata: metadata, deliver: false)
                            result = r
                            if r.stored { try? await Task.sleep(for: .milliseconds(700)); done() }
                        }
                    }
                    .disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || result?.stored == true)
                }
            }
        }
        .task { await load() }
    }

    private func load() async {
        defer { loading = false }
        for provider in providers {
            if provider.hasItemConformingToTypeIdentifier(UTType.url.identifier),
               let url = try? await provider.loadItem(forTypeIdentifier: UTType.url.identifier) as? URL {
                if url.isFileURL, let found = Extract.text(inFile: url) {
                    text = found
                    metadata = ["capture": "share_sheet", "file_name": url.lastPathComponent]
                } else if !url.isFileURL {
                    text = url.absoluteString
                    metadata = ["capture": "share_sheet", "url_host": url.host ?? ""]
                }
            } else if provider.hasItemConformingToTypeIdentifier(UTType.image.identifier),
                      let item = try? await provider.loadItem(forTypeIdentifier: UTType.image.identifier) {
                let data: Data? = switch item {  // Photos hands a file URL, screenshots an image, some apps raw data
                case let url as URL: try? Data(contentsOf: url)
                case let image as UIImage: image.pngData()
                case let raw as Data: raw
                default: nil
                }
                if let data { text = (try? await Extract.text(inImage: data)) ?? "" }
                metadata = ["capture": "photo_ocr"]
            } else if provider.hasItemConformingToTypeIdentifier(UTType.plainText.identifier),
                      let shared = try? await provider.loadItem(forTypeIdentifier: UTType.plainText.identifier) as? String {
                text = String(shared.prefix(Extract.limit))
            }
            if !text.isEmpty { return }
        }
    }
}
