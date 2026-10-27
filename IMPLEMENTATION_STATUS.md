# Lens V1 — implementation status

Status labels: WORKING, PARTIALLY WORKING, FAILED (gate), NOT IMPLEMENTED, NOT VERIFIED.
Evidence for every line is in docs/VERIFICATION.md; update this file only from executed results.

| Milestone / capability | Status |
|---|---|
| M0 foundation (UTF-8, stdin input, chunked atomic import, pinned PowerShell) | WORKING |
| M1 encrypted vectors, semantic/hybrid/rerank retrieval, time windows | WORKING (functional); quality gates FAILED |
| M2 language-identity centering, cross-validated abstention | WORKING on v1 diagnosis data; sealed-holdout gate pending |
| M2 structured query interpretation (applications in 6 languages, action trace, relax-on-no-evidence) | WORKING (7/7 tests); entity filters NOT IMPLEMENTED |
| M2 answerability verifier (feature, extractive-QA, multilingual NLI) | FAILED (best 0.558 correct answered at 5% false answers; QA/NLI exceed RAM) — NOT ADOPTED |
| M2 romanized-Indic transliteration (IndicXlit) | NOT ADOPTED (evaluated; Python-only, 11M params) |
| Background RAM ≤ 800 MB peak, idle 50–100 MB | NOT VERIFIED on target tiers (H0: observer 18 MB + idle engine 11–18 MB ≈ 30–36 MB idle; serial workers 440 MB private; concurrent 995 MB; 30-minute sustained run peak 474 MB working set / 425 MB private, flat, idle 53 MB, 0 crashes) |
| CPU-only / low-end compatibility (no AVX2, 4–8 GB) | PARTIALLY WORKING: whisper ggml runtime dispatch + graceful ASR degradation (4 tests, SSE2 path verified); prebuilt ONNX Runtime/OpenSSL/Needle and low-end tiers NOT VERIFIED |
| Hardware profile + static ISA audit tools | WORKING (9 tests) |
| M3 Windows observation | PARTIALLY WORKING: consent-gated UIA observer with OCR fallback (changed-region) → encrypted engine, privacy exclusions, change dedup, pause/resume (13 tests); supervisor and real-app coverage NOT IMPLEMENTED |
| M4 microphone capture (voice) | PARTIALLY WORKING: consent-gated lens-voice with VAD → engine ingest_audio (3 tests via file input); live microphone NOT VERIFIED |
| Screen OCR (detection + script-routed recognition, native) | PARTIALLY WORKING: dev-set page CER en/zh/es ≤0.07%, ta 0.3%, hi 2.9%, te 8.7% (FAIL); region p50 78 ms; not yet in the observer |
| M5 episodes / facts / entities | PARTIALLY WORKING: L3 episodes (schema v7) plus L4 entities/facts and L5 projects (schema v8, 2026-10-27): rule-based, model-free extraction in en/es/hi/ta/te/zh inside `consolidate` (incremental, user gazetteer, cross-script names); ops `entities`, `entity_context`, `facts`, `projects`, `project_context`; recall entity signal + linked facts; every fact source-backed, deletion cascades. Labelled synthetic sets only (dev P/R 1.0; held-out entities P 0.889 R 0.889, facts P 1.0 R 0.833); not measured on real user data; preferences, relationships beyond affiliation/role, L8 summaries NOT IMPLEMENTED |
| M6 compression | PARTIALLY WORKING: schema v6 per-row zstd (+trained dictionary), −28 to −32% bytes/record on a synthetic observer workload; retrieval-latency impact not yet measured |
| M7 history import | PARTIALLY WORKING (WhatsApp/JSONL/text) |
| Background agent (engine + consented observer + user-only named pipe) | WORKING on H0 (3 tests; idle tree 41 MB working set) |
| M8 Windows GUI | PARTIALLY WORKING: WebView2 app (Ask, Timeline, Privacy, Status) over the agent; first-run onboarding (what is captured, where data lives, separate screen/microphone/phone-link/autostart opt-ins all off, exclusions editor; nothing sent before Finish); tray icon in lens-agent (status, Pause/Resume, Open, Quit; pause stops screen + microphone); 7 tests (6 pass; AppHost expects schema 8 from another session's pending store change); not usability-tested, tray icon itself not exercised by tests (no visible UI in tests) |
| M9 installer | PARTIALLY WORKING: per-user package/install/uninstall; opt-in autostart via HKCU Run → `lens-app --background` (no console, no admin); uninstall stops the agent, removes Run value + shortcut, keeps data; 4 tests incl. install → sign-in launch → onboarding → uninstall in scratch locations; code signing BLOCKED (no certificate); no clean-machine run |
| Encrypted device link (lens-mesh: mTLS 1.3, pinned certs, one-time pairing, allow-listed ops) | PARTIALLY WORKING: laptop side, 3 tests; phone/watch clients NOT IMPLEMENTED |
| Android companion | PARTIALLY WORKING: pairing, pinned mTLS link, ask, notes/share with offline queue; 6 unit tests; emulator end-to-end pending; no real device |
| Safe cross-device actions | PARTIALLY WORKING: typed registry, approval only in the laptop app, audit memories; 3 tests; phone-side capabilities NOT IMPLEMENTED |
| Wear OS | PARTIALLY WORKING: :wear module (ask laptop memory, quick notes over the same pinned link) builds a debug APK; never run on an emulator or watch |
| Trained Lens model (Lens-Core family, docs/LENS_MODEL.md) | IN PROGRESS: answerability head v0 trained (held-out AUC 0.953–0.969, INT8 124 MB) but does not yet help on Lens fixtures; v1 data built; NOT ADOPTED |
