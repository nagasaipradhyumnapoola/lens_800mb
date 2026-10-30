# Lens Micro — engineering handoff (current)

Updated 2026-10-28. Only executed, recorded facts appear here; evidence is in docs/VERIFICATION.md, per-capability
status in IMPLEMENTATION_STATUS.md, release gates in docs/RELEASE_READINESS.md.

## What exists (built in build/engine/Release)

| Process | Role |
|---|---|
| lens-agent | Always-on owner: starts the engine (hash-verified models, keyword-only fallback), the consented observer and voice capture, lens-mesh; user-only named pipe with an op allow-list; periodic consolidate + index; action registry with laptop-side approval; import jobs; diagnostics; tray (`--tray`) |
| lens-engine | Encrypted store (SQLCipher, DPAPI key, schema v9: zstd text, FTS, int8 vectors, episodes, entities/facts/projects, pins, feedback, retention, corrections), import, ASR, recall (keyword/semantic/hybrid + rerank, time windows, entity signal), backup/restore, key rotation, scoped deletion, export, idle model unload |
| lens-observer | UIA visible text first, OCR fallback (PrintWindow + tile diff + band OCR through a persistent lens-ocr worker), settle/debounce, per-window delta storage, language ID (lens-lid-ngram-v1), CPU throttle, privacy exclusions; requires `--consent` |
| lens-ocr | PP-OCRv5 detection + script-routed recognition (PP-OCRv6 tiny general; PP-OCRv5 ja, arabic, cyrillic, devanagari, ta; Lens Telugu fine-tune); no Bengali/Gujarati recogniser |
| lens-voice | Consent-gated microphone capture, adaptive VAD, LID restricted to the 17 spec languages, routing (zh → Dolphin, Indic → IndicConformer, others → whisper base), hallucination filter, optional owner-only capture |
| lens-app | Win32 + WebView2 UI (Ask, evidence viewer, Timeline, People, Projects, Devices with QR pairing, Import, Privacy + Requests, Storage, Diagnostics, onboarding); strict CSP, textContent rendering |
| lens-mesh | Device link: TLS 1.3 mutual auth, pinned self-signed P-256 certs, one-time pairing token, allow-listed remote ops |
| lens-needle | Standalone Needle runner; not wired into consolidation or the action flow |
| android/ | :core (own memory via liblens-core.so + Keystore-wrapped key, pairing, Keystore identity, pinned link, repository), :app (Compose phone), :wear (Wear Compose); phone app tested on the emulator, never on a device; watch never run |
| lens_model/ | Trained Lens answerability heads v0/v1 (not adopted), data builders, export/quantize, comparison harness |

## How to run

```powershell
.venv\Scripts\python.exe scripts/bootstrap_pwsh.py                 # project-local PowerShell 7.6.6
.venv\Scripts\python.exe -B -m unittest discover -s tests -v       # 251 tests, ~13 min; temp dirs; invisible test windows only
.venv\Scripts\python.exe -B scripts/package_lens.py                # per-user package (unsigned)
.venv\Scripts\python.exe -B scripts/sustained_run.py --minutes 30 --snapshot  # whole-tree RAM/CPU/recall under load
.venv\Scripts\python.exe -B scripts/profile_combined.py            # combined RAM, concurrent vs serial
.venv\Scripts\python.exe -B scripts/check_hardware_compat.py       # static ISA audit (SSE2 baseline)
.venv\Scripts\python.exe -B scripts/benchmark_retrieval_nl.py --split dev ...   # tune on dev only
.venv\Scripts\python.exe -B scripts/experiment_answer_verifier.py --verifier lens --lens-model <int8.onnx>
```
Baseline 2026-10-28 (HEAD a7533c3 + working tree): 250 of 251 OK, test_android_link skipped (no device).
Android: `android\gradlew.bat` with JAVA_HOME = JDK 17 (Android Studio's JBR 25 does not work with Gradle 8.14).

Other operating systems (engine/portable.cmake; docs/VERIFICATION.md "Portable core"):
```powershell
docker build -t lens-linux ci/linux                                  # Ubuntu 24.04 image (GTK 4, WebKitGTK 6, Xvfb, ORT 1.24.4)
docker run --rm -v "D:\Lens:/src" lens-linux bash ci/linux/build.sh  # build + ci/linux/smoke.py (agent, app self-test, OCR parity)
powershell ci\android\build.ps1                                      # arm64-v8a with NDK r27.1 (needs vcpkg arm64-android deps)
powershell ci\android\build.ps1 -Abi x86_64 -CoreOnly                # emulator library (vcpkg x64-android deps); both stage android/native-libs
# emulator: emulator -avd lens-test -no-window -no-audio; then tests/test_android_link.py (also runs LocalMemoryTest)
.venv\Scripts\python.exe -B ci\ocr_parity.py <lens-ocr> <onnxruntime library>   # English hard-screen dev set, any OS
```
macOS arm64 and the iOS memory core build and run their smoke tests in .github/workflows/portable.yml on every push to
the public repository; compiler errors appear as a job annotation (ci/annotate_log.sh), readable without signing in.

## Rules learned

- Tune only on the dev split; the sealed holdout runs once per candidate, after the decision is frozen.
- Never rebuild an exe a running benchmark holds; never run two heavy benchmarks (or training + benchmark) together.
- INT8 dynamic-quantized models run one sequence per inference (batch padding changes outputs).
- Tests never show windows or read the real screen: `lens-observer-testapp --invisible` (hidden desktops break UIA).
- Run the test suite from PowerShell: headless Edge exits without output inside Claude Code's Bash-tool sandbox, which
  gave 9 false failures (test_app views, Edge-rendered OCR screens) on 2026-10-28; the same tests pass from PowerShell.
- Bash heredocs collapse backslashes; use the Edit tool for C++/JSON with escapes.
- Migrations must be idempotent; SQL functions used in triggers need `SQLITE_INNOCUOUS`.
- Agent/mesh requests are type-checked and wrapped per request; a bad field must never kill a thread.
- A public-benchmark win does not predict Lens false answers: answerability v0 led every public QA set but scored
  AUC 0.578 on the Lens harness; judge candidates on the Lens harness at 5% false answers.

## Blockers needing the owner

- Code-signing certificate (installer, app, agent); Android/Wear signing keys.
- Real low-end hardware (H1–H3) for RAM/latency/battery gates; Intel SDE execution permission for no-AVX checks.
- Physical Android phone and Wear OS watch; battery measurement needs an elevated SRUM read.
- Consent for a second real-screen run and a live-microphone re-test.
- RTX 5060 enablement and approval of a CUDA training environment; approval to run Tesseract/EasyOCR for bn/gu.

## Next steps (ordered; language priority en → hi → zh → es, no major Telugu-specific work)

1. English false answers (sealed holdout 100k: rejection 0.67, worst of all languages): Lens-Core answerability v2
   with English-heavy near-miss negatives, judged on the Lens harness at 5% false answers; sealed acceptance set once.
2–3. (Done 2026-10-28: partial deletion retires trained zstd dictionaries; the 318 MB idle private sample did not
   reproduce. docs/VERIFICATION.md.)
4. Public retrieval baselines (LM0): MIRACL en/hi/zh/es and the MMTEB retrieval subset for e5-small vs
   EmbeddingGemma-300M INT8, CPU-only with RAM; LongMemEval_S retrieval recall.
5. Hindi ASR (FLEURS held-out WER 26.6%), then English/Spanish with whisper small q5 vs base (RAM, latency).
6. Second real-screen run (needs consent); Needle into the pending-action flow; device events/notifications.
7. Android: phone emulator end-to-end done (2026-10-31); next the retrieval models on the phone (keyword-only today),
   a physical phone, then Wear; demos 1–10 and the acceptance report.
