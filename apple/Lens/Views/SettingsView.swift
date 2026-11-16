import SwiftUI

struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @State private var pairing = false
    @State private var confirmUnpair = false
    @State private var confirmErase = false
    @State private var erased = false

    var body: some View {
        NavigationStack {
            Form {
                laptopSection
                Section {
                    LabeledContent("Apple Watch", value: model.watchStatus)
                } footer: {
                    Text("Ask and take notes from your wrist. The watch goes through this iPhone and keeps nothing itself.")
                }
                privacySection
                Section("About") {
                    LabeledContent("Version", value: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "1.0")
                    LabeledContent("Memory on this iPhone", value: ByteCountFormatter.string(fromByteCount: model.service.storageBytes(), countStyle: .file))
                    if let problem = model.storeProblem { LabeledContent("Memory", value: "Unavailable (\(problem))") }
                }
            }
            .navigationTitle("Lens")
            .sheet(isPresented: $pairing) { PairView { model.paired() } }
            .confirmationDialog("Unpair your laptop?", isPresented: $confirmUnpair, titleVisibility: .visible) {
                Button("Unpair", role: .destructive) { model.unpair() }
            } message: {
                Text("This iPhone stops asking your laptop. It can pair again only with a laptop of the same Lens account.")
            }
            .alert("Erase this iPhone's memory?", isPresented: $confirmErase) {
                Button("Erase", role: .destructive) { Task { await model.erase(); erased = true } }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("Deletes every note, voice note and saved text Lens stored on this iPhone, and its encryption key. Your laptop's memory is not touched. This cannot be undone.")
            }
        }
    }

    @ViewBuilder private var laptopSection: some View {
        Section {
            if let laptop = model.laptop {
                Label("Paired with your laptop", systemImage: "checkmark.seal.fill")
                    .foregroundStyle(.green)
                LabeledContent("Since", value: laptop.paired.formatted(date: .abbreviated, time: .omitted))
                LabeledContent("Waiting to send", value: "\(model.pending)")
                if model.pending > 0 {
                    Button {
                        Task { await model.sendWaiting() }
                    } label: {
                        HStack { Text("Send now"); if model.sending { Spacer(); ProgressView() } }
                    }
                    .disabled(model.sending)
                }
                Button("Unpair", role: .destructive) { confirmUnpair = true }
            } else {
                Button {
                    pairing = true
                } label: {
                    Label("Pair with your laptop", systemImage: "laptopcomputer.and.iphone")
                }
            }
        } header: {
            Text("Laptop")
        } footer: {
            Text("Questions search your laptop's whole memory over an encrypted link on your Wi-Fi. Your laptop approves this iPhone once; devices of another Lens account can never pair.")
        }
    }

    private var privacySection: some View {
        Section {
            Label("Remembers only what you give it", systemImage: "hand.raised")
            Label("Encrypted on this iPhone, never in iCloud backups", systemImage: "lock")
            Label("Voice recognised on this iPhone, never stored", systemImage: "waveform")
            Label("Never reads other apps or your screen", systemImage: "eye.slash")
            Button("Erase this iPhone's memory", role: .destructive) { confirmErase = true }
            if erased { Text("This iPhone's memory was erased.").font(.footnote).foregroundStyle(.secondary) }
        } header: {
            Text("Privacy")
        }
    }
}
