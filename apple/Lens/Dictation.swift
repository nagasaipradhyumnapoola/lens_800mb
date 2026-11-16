import AVFoundation
import Speech

/// Voice notes and spoken questions, recognised on this iPhone only (requiresOnDeviceRecognition): the audio is never
/// stored and never leaves the device. Where on-device recognition is unavailable Lens says so instead of using a server.
@MainActor
@Observable
final class Dictation {
    private(set) var transcript = ""
    private(set) var running = false
    private(set) var problem: String?
    private let engine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?

    func toggle() async { running ? stop() : await start() }

    func start() async {
        problem = nil
        transcript = ""
        let speech = await withCheckedContinuation { c in SFSpeechRecognizer.requestAuthorization { c.resume(returning: $0 == .authorized) } }
        guard speech, await AVAudioApplication.requestRecordPermission() else {
            problem = "Allow the microphone and speech recognition for Lens in Settings to speak notes."
            return
        }
        guard let recognizer = SFSpeechRecognizer() ?? SFSpeechRecognizer(locale: Locale(identifier: "en-US")), recognizer.isAvailable else {
            problem = "Speech recognition is not available right now."
            return
        }
        guard recognizer.supportsOnDeviceRecognition else {
            problem = "On-device speech recognition is not available for this language. Lens never sends your voice off the iPhone."
            return
        }
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.requiresOnDeviceRecognition = true
        request.shouldReportPartialResults = true
        request.addsPunctuation = true
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.record, mode: .measurement, options: .duckOthers)
            try session.setActive(true, options: .notifyOthersOnDeactivation)
            let input = engine.inputNode
            input.installTap(onBus: 0, bufferSize: 1024, format: input.outputFormat(forBus: 0)) { buffer, _ in request.append(buffer) }
            engine.prepare()
            try engine.start()
        } catch {
            problem = "The microphone could not start."
            return
        }
        self.request = request
        running = true
        task = recognizer.recognitionTask(with: request) { [weak self] result, error in
            let text = result?.bestTranscription.formattedString
            let finished = error != nil || result?.isFinal == true
            Task { @MainActor in
                guard let self else { return }
                if let text { self.transcript = text }
                if finished { self.stop() }
            }
        }
    }

    func stop() {
        guard running else { return }
        running = false
        engine.stop()
        engine.inputNode.removeTap(onBus: 0)
        request?.endAudio()
        task?.finish()
        request = nil
        task = nil
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }
}
