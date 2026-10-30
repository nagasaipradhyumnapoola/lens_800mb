# Lens V1 — release readiness

Production gates from docs/LENS_V1_SPEC.md §18–20. Status is evidence-based (docs/VERIFICATION.md).
V1 is NOT release-ready.

## Gates

| Gate | Status | Evidence / blocker |
|---|---|---|
| Retrieval quality (exact ≥0.99, R@10 ≥0.90, top-1 ≥0.80, abstention ≥0.95) on sealed holdout | FAIL (abstention 0.811 at 10k) | reports/retrieval-nl/m2-holdout/ |
| Complete Lens system ≤ 500 MB peak RAM (founder, 2026-10-29), idle 50–100 MB (whole process tree, every hardware tier) | NOT VERIFIED on H1–H3 (H0: observer 18 MB + idle engine ≈ 30–36 MB idle; serial model workers peak 440 MB private; concurrent 995 MB, now prevented by the agent's resource governor (TTS alone; OCR held while retrieval models are loaded — functional tests only, whole tree not re-measured); 30-minute sustained run on H0: peak 474 MB working set / 425 MB private, flat per phase, idle 53 MB, 0 crashes — reports/perf/) | reports/ram/ |
| CPU-only, low-end hardware compatibility (tiers H0–H3, docs/acceptance-gates.md) | PARTIAL: static audit PASS after ggml runtime dispatch; ASR degrades cleanly; prebuilt runtimes NOT VERIFIED (SDE execution blocked by permission); H1–H3 BLOCKED (no test machines); without AVX whisper is ~10× slower | reports/hardware/compat-audit.json |
| Battery consumption per tier | NOT VERIFIED | — |
| Installed footprint ≤ 1,000,000,000 bytes per device (founder, 2026-10-29; docs/acceptance-gates.md) | PASS on the H0 package (861.7 MB with Canary 207 MB + Kokoro 187 MB) | scripts/package_lens.py manifest; tests/test_installer.py |
| Verified minimum hardware requirements | NOT VERIFIED (proposed floor: x86-64 SSE4.2 + POPCNT) | — |
| OCR: detection + multilingual recognition + screen-to-memory benchmark | PARTIAL: 87-screen dev + 89-screen held-out sets, 17 languages; held-out Telugu 1.65% PASS; Arabic 21% / Urdu 30% FAIL; Bengali and Gujarati FAIL (no recogniser); worker RAM peak ≤141 MB up to 4K PASS on H0; region latency < 150 ms NOT VERIFIED (contended runs); Tesseract/EasyOCR comparison NOT MEASURED (needs owner approval) | reports/ocr-screens/, docs/VERIFICATION.md M4 2026-10-28 |
| Windows observation (UIA, change detection, exclusions, pause) | PARTIAL: UIA observer with OCR fallback, exclusions, pause/resume; the 2026-10-27 real-screen run FAILED (905 MB private, 179% CPU, scroll-back re-stored, no language ID); fixes verified on synthetic windows only (visible text, settle, delta + near-duplicate suppression, language ID with held-out benchmark vs fastText, CPU throttle); second owner-consented real-screen run required to close | docs/VERIFICATION.md "Observer real-screen fixes"; reports/observer/ |
| Voice capture | PARTIAL: file-driven fixes for every live-mic finding measured on held-out FLEURS (17 languages) and LibriSpeech (owner-only gate); 32-min soak PASS; latency p95 7.4 s (routed languages, contended CPU). Blockers: ur/gu automatic LID, babble noise (VAD + speaker FRR 16%), owner enrolment not wired into the app/agent, live-mic re-test needs owner consent | docs/VERIFICATION.md voice 2026-10-28, reports/voice/ |
| Episodic / temporal / semantic memory layers | PARTIAL: L3 episodes (schema v7); L4 entities/facts and L5 projects (schema v8) with provenance, deletion cascade and recall integration, measured on small synthetic labelled sets only (held-out facts P 1.0 R 0.833, entities P 0.889 R 0.889); real-data quality, preferences and L8 summaries NOT VERIFIED / NOT IMPLEMENTED | docs/VERIFICATION.md |
| Compression and storage budget | PARTIAL: per-row zstd (schema v6) −28 to −32% on a synthetic workload; real-workload and 1M-record growth NOT MEASURED | reports/storage/ |
| Windows GUI + installer, clean-machine install | PARTIAL: app UI, first-run onboarding, tray (pause/resume), per-user opt-in autostart and install/uninstall working on H0 in temp/scratch locations (idle background tree 14–24 MB working set); code signing BLOCKED (owner has no certificate); WebView2 bootstrap, clean-machine install on H1–H3 and usability testing NOT DONE | docs/VERIFICATION.md M8/M9, desktop experience 2026-10-27 |
| Android companion, Wear OS companion | PARTIAL: Android app (pairing, ask, notes, share, offline queue) built + 6 unit tests; Wear app built; neither run on an emulator or device yet | Real hardware: Android device not connected; no physical watch (blocker for production claims) |
| Encrypted device pairing/sync, safe actions | PARTIAL: lens-mesh (TLS 1.3 mutual auth, pinned certs, one-time pairing, allow-listed ops) + typed action registry with laptop-side approval; 6 tests + hostile-input tests; phone-side actions NOT IMPLEMENTED | docs/VERIFICATION.md M10–M13 |
| Security review, crash recovery, backup/restore, key rotation | PARTIAL: encrypted backup (DPAPI or passphrase) with integrity-verified, crash-safe restore; crash-safe key rotation; scoped and delete-all deletion proven by sentinel scans of a decrypted copy and raw DB/WAL/SHM; retention, corrections, pins/feedback (schema v9, 12 tests, synthetic). Partial deletion now retires trained compression dictionaries (sentinel-tested, 2026-10-28). Not done: cross-account DPAPI restore, external security review | docs/VERIFICATION.md |
| Trained Lens model: per-capability benchmarks vs upstream baselines, RAM, latency (docs/LENS_MODEL.md §7) | IN PROGRESS: answerability head v0 trained, v1 training; comparison harness vs Qwen3 rerankers/LLM judges, bge, e5, Arctic, Granite built (lens_model/eval/); not adopted | reports/lens-model/ |
| Demonstrations 1–10 | NOT DEMONSTRATED | — |
| Signed release artifacts | BLOCKED | Requires owner signing keys/certificates |

## Known release blockers needing the owner

- Code-signing certificate (Windows) and Android/Wear signing keys.
- Physical Android phone and Wear OS watch for hardware validation.
- Licence for Lens-specific source: owner decided 2026-10-27 to publish with no licence (all rights reserved) for now; third-party components keep their own licences (third_party/licenses/).
- Low-end test hardware: an 8 GB CPU-only laptop (H1), a 4 GB laptop (H2) and a laptop whose CPU lacks AVX2
  (H3), e.g. older HP models. Optionally Intel SDE (Intel licence; download needs approval) to emulate an
  SSE4.2-only CPU as a supplement, never a substitute.
- Battery measurement with SRUM (`powercfg /srumutil`) needs an elevated prompt, run by the owner.
- Model training: the RTX 5060 is not enumerated by Windows (dGPU appears switched off); enabling it and
  approving a project-local PyTorch/CUDA 12.8 environment are required before LM0.
