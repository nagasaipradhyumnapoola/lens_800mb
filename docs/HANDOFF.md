# Lens Micro — engineering handoff (current)

Updated 2026-10-27. Only executed, recorded facts appear here; evidence is in docs/VERIFICATION.md, per-capability
status in IMPLEMENTATION_STATUS.md, release gates in docs/RELEASE_READINESS.md.

## What exists (built in build/engine/Release)

| Process | Role |
|---|---|
| lens-agent | Always-on owner: starts the engine (hash-verified models, keyword-only fallback), the consented observer, lens-mesh; user-only named pipe; periodic consolidate + index; action registry with laptop-side approval |
| lens-engine | Encrypted store (SQLCipher, DPAPI key, schema v7: zstd text, FTS, int8 vectors, episodes), import, ASR, recall (keyword/semantic/hybrid + rerank, time windows), idle model unload |
| lens-observer | UIA text first, OCR fallback (PrintWindow + tile diff + band OCR through a persistent lens-ocr worker), privacy exclusions, dedup, adaptive polling; requires `--consent` |
| lens-ocr | PP-OCRv5 detection + script-routed recognition (PP-OCRv6 tiny general, devanagari/ta/te) |
| lens-voice | Consent-gated microphone capture, energy VAD → engine `ingest_audio` |
| lens-app | Win32 + WebView2 UI (Ask, Timeline, Privacy + Requests, Status); strict CSP, textContent rendering |
| lens-mesh | Device link: TLS 1.3 mutual auth, pinned self-signed P-256 certs, one-time pairing token, allow-listed remote ops |
| android/ | :core (pairing, Keystore identity, pinned link, repository), :app (Compose phone), :wear (Wear Compose) |
| lens_model/ | Trained Lens answerability head (v0 trained; v1 training), data builders, export/quantize |

## How to run

```powershell
.venv\Scripts\python.exe scripts/bootstrap_pwsh.py                 # project-local PowerShell 7.6.6
.venv\Scripts\python.exe -B -m unittest discover -s tests -v       # ~176 tests; temp dirs; invisible test windows only
.venv\Scripts\python.exe -B scripts/package_lens.py                # per-user package (unsigned)
.venv\Scripts\python.exe -B scripts/sustained_run.py --minutes 30  # whole-tree RAM/CPU/recall under load
.venv\Scripts\python.exe -B scripts/profile_combined.py            # combined RAM, concurrent vs serial
.venv\Scripts\python.exe -B scripts/check_hardware_compat.py       # static ISA audit (SSE2 baseline)
.venv\Scripts\python.exe -B scripts/benchmark_retrieval_nl.py --split dev ...   # tune on dev only
.venv\Scripts\python.exe -B scripts/experiment_answer_verifier.py --verifier lens --lens-model <int8.onnx>
```
Android: `android\gradlew.bat` with JAVA_HOME = JDK 17 (Android Studio's JBR 25 does not work with Gradle 8.14).

## Rules learned

- Tune only on the dev split; the sealed holdout runs once per candidate, after the decision is frozen.
- Never rebuild an exe a running benchmark holds; never run two heavy benchmarks (or training + benchmark) together.
- INT8 dynamic-quantized models run one sequence per inference (batch padding changes outputs).
- Tests never show windows or read the real screen: `lens-observer-testapp --invisible` (hidden desktops break UIA).
- Bash heredocs collapse backslashes; use the Edit tool for C++/JSON with escapes.
- Migrations must be idempotent; SQL functions used in triggers need `SQLITE_INNOCUOUS`.
- Agent/mesh requests are type-checked and wrapped per request; a bad field must never kill a thread.

## Blockers needing the owner

- Code-signing certificate (installer, app, agent).
- Real low-end hardware (H1–H3) for RAM/latency/battery gates; Intel SDE execution permission for no-AVX checks.
- Physical Android phone and Wear OS watch; battery measurement needs an elevated SRUM read.

## Next steps (ordered)

1. Lens answerability v1: finish training, export INT8, evaluate on the verifier harness; adopt only if it beats
   the QA verifier at 5% false answers on dev, then the sealed holdout once.
2. Android emulator end-to-end (tests/test_android_link.py against a headless `lens-test` AVD), then Wear emulator.
3. Telugu recognition (te page CER 8.7%, ra-vattu glyphs), OCR held-out screen set.
4. Demos 1–10 and the acceptance report; facts/entities (M5), QR pairing, onboarding/tray.
