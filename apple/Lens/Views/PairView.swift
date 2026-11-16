import SwiftUI
import UIKit
import VisionKit

/// Pairing: scan (or paste) the code Lens shows on the laptop, then approve this iPhone on the laptop when both show the
/// same 8-digit code. Nothing is shared until the laptop's user approves.
struct PairView: View {
    let onPaired: () -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var pasted = ""
    @State private var verification: String?
    @State private var busy = false
    @State private var message: String?
    @State private var scanning = DataScannerViewController.isSupported && DataScannerViewController.isAvailable

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    if let verification {
                        approval(verification)
                    } else {
                        Text("On your laptop, open Lens › Devices and choose Pair a device. Then scan the code it shows.")
                            .foregroundStyle(.secondary)
                        if scanning && !busy {
                            QRScanner { use($0) }
                                .frame(height: 300)
                                .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
                                .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).strokeBorder(Color.accentColor.opacity(0.5), lineWidth: 2))
                        }
                        DisclosureGroup("Paste the code instead") {
                            TextField("Pairing code", text: $pasted, axis: .vertical)
                                .lineLimit(3...6)
                                .font(.footnote.monospaced())
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                            Button("Pair") { use(pasted) }
                                .buttonStyle(.borderedProminent)
                                .disabled(pasted.isEmpty || busy)
                        }
                        if busy { ProgressView("Connecting to your laptop…") }
                    }
                    if let message {
                        Label(message, systemImage: "exclamationmark.triangle.fill")
                            .foregroundStyle(.orange)
                    }
                }
                .padding()
            }
            .navigationTitle("Pair laptop")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { LensService.shared.stopPairing(); dismiss() }
                }
            }
        }
        .interactiveDismissDisabled(busy)
    }

    private func approval(_ code: String) -> some View {
        VStack(spacing: 18) {
            Text("Approve this iPhone on your laptop only if it shows the same code")
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
            Text(code)
                .font(.system(size: 44, weight: .semibold, design: .rounded).monospacedDigit())
                .textSelection(.enabled)
                .accessibilityLabel("Verification code \(code.map { String($0) }.joined(separator: " "))")
            ProgressView("Waiting for approval…")
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 24)
    }

    private func use(_ text: String) {
        guard !busy else { return }
        guard let code = PairingCode(text) else { message = "That is not a Lens pairing code."; return }
        busy = true
        message = nil
        Task {
            let error = await LensService.shared.pair(code, deviceName: UIDevice.current.name) { shown in
                Task { @MainActor in verification = shown }
            }
            busy = false
            verification = nil
            if let error { message = error } else { onPaired(); dismiss() }
        }
    }
}

/// The system's live QR scanner (VisionKit); reports the first Lens-shaped payload it sees.
struct QRScanner: UIViewControllerRepresentable {
    let found: (String) -> Void

    func makeUIViewController(context: Context) -> DataScannerViewController {
        let scanner = DataScannerViewController(recognizedDataTypes: [.barcode(symbologies: [.qr])], qualityLevel: .balanced,
                                                isHighlightingEnabled: true)
        scanner.delegate = context.coordinator
        return scanner
    }

    func updateUIViewController(_ scanner: DataScannerViewController, context: Context) {
        if !scanner.isScanning { try? scanner.startScanning() }
    }

    static func dismantleUIViewController(_ scanner: DataScannerViewController, coordinator: Coordinator) { scanner.stopScanning() }

    func makeCoordinator() -> Coordinator { Coordinator(found: found) }

    final class Coordinator: NSObject, DataScannerViewControllerDelegate {
        let found: (String) -> Void
        private var reported = false
        init(found: @escaping (String) -> Void) { self.found = found }

        func dataScanner(_ scanner: DataScannerViewController, didAdd items: [RecognizedItem], allItems: [RecognizedItem]) {
            for case .barcode(let code) in items {
                guard !reported, let payload = code.payloadStringValue, payload.contains("\"token\"") else { continue }
                reported = true
                UINotificationFeedbackGenerator().notificationOccurred(.success)
                found(payload)
            }
        }
    }
}
