import Foundation
import PDFKit
import UniformTypeIdentifiers
import Vision

/// Text from what the user hands Lens: photos and screenshots (on-device Vision text recognition) and files (plain text,
/// PDF text). Nothing leaves the iPhone.
enum Extract {
    static let limit = 20000

    static func text(inImage data: Data) async throws -> String {
        try await Task.detached(priority: .userInitiated) {
            let request = VNRecognizeTextRequest()
            request.recognitionLevel = .accurate
            request.usesLanguageCorrection = true
            request.automaticallyDetectsLanguage = true
            try VNImageRequestHandler(data: data, options: [:]).perform([request])  // reads the photo's orientation itself
            let lines = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
            return String(lines.joined(separator: "\n").prefix(limit))
        }.value
    }

    /// Plain text or PDF text of a file the user picked or shared; nil for anything else.
    static func text(inFile url: URL) -> String? {
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        let type = UTType(filenameExtension: url.pathExtension)
        if type?.conforms(to: .pdf) == true {
            return PDFDocument(url: url)?.string.map { String($0.prefix(limit)) }
        }
        if type?.conforms(to: .text) == true || type == nil {
            return (try? String(contentsOf: url, encoding: .utf8)).map { String($0.prefix(limit)) }
        }
        return nil
    }
}
