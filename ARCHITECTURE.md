# Lens — architecture (as built)

This document describes components that exist in the repository. Planned components are listed separately and
are not implied to work. Verification status: IMPLEMENTATION_STATUS.md and docs/VERIFICATION.md. Retrieval design:
docs/retrieval.md. Original model-proof decision record: docs/architecture.md.

## Process structure

```
lens-app.exe (Win32 + WebView2 UI, bundled engine/app/ui)        android/ :app (phone), :wear (watch)
      │ user-only named pipe                                            │ TLS 1.3, mutual auth, pinned certificates
      ▼                                                                 ▼
lens-agent.exe (engine/agent/) ── lens-mesh.exe (engine/mesh/) ────────┘
  │ op allow-list, consent and exclusions (%LOCALAPPDATA%\Lens\config.json), import jobs, action registry
  │ with in-app approval, periodic consolidation and indexing, diagnostics, tray
  ├─ lens-engine.exe (engine/main.cpp, store.cpp) ── SQLCipher database + DPAPI-wrapped key
  ├─ lens-observer.exe (engine/observer/) ── lens-ocr.exe --serve (persistent OCR worker)
  └─ lens-voice.exe (engine/voice/) ── audio to lens-engine ingest_audio ── lens-sherpa.exe (Dolphin, IndicConformer)
CLI and import: scripts/lens.ps1, scripts/import-history.ps1 (PowerShell 7) over JSON lines on stdin/stdout
```

## Encrypted store (schema v9)

- Immutable observations with optional per-row zstd text (`lens_text()`), source metadata and provenance.
- FTS5 index over the `observation_text` view; int8 passage vectors in `embedding_chunks` inside SQLCipher.
- Derived layers, all source-linked and removed with their sources: episodes and members (v7); entities, aliases,
  mentions, facts and fact sources, projects and their links, extraction state (v8); pins, recall feedback,
  user facts, fact status and retention rules (v9).
- Lifecycle operations: encrypted backup and verified restore, crash-safe key rotation, scoped and complete
  deletion with FTS merge and WAL truncation, retention, export, corrections, latest-versus-superseded facts.

## Retrieval (engine/retrieval.cpp, temporal.cpp, query_understanding.cpp)

Keyword (FTS5 plus unspaced-script bigrams), semantic (multilingual-e5-small INT8 with per-script centering),
coverage-weighted reciprocal-rank fusion, cross-encoder reranking (mMARCO mMiniLMv2 INT8), natural-language time
windows, application and entity signals, user pins and feedback, abstention, and verbatim evidence with byte offsets.

## Perception

- Observation: UI Automation visible text first; OCR fallback on changed bands only; settle and debounce;
  per-window delta storage with near-duplicate suppression; language identification (lens-lid-ngram-v1);
  privacy exclusions (password fields, protected windows, private browsing, excluded applications); CPU throttle.
- OCR: PP-OCRv5 detection; recognition routed by script (PP-OCRv6 tiny general; PP-OCRv5 Japanese, Arabic,
  Cyrillic, Devanagari, Tamil; a Lens fine-tuned Telugu recogniser); bounded worker memory.
- Speech: whisper.cpp (base, q5_1) in-process with runtime CPU dispatch (SSE2 baseline upward); Dolphin for
  Mandarin and IndicConformer for Indian languages through lens-sherpa; language identification restricted to the
  specified languages; hallucination filtering; optional owner-only capture (speaker verification).

## Resource policy

Models load lazily in the process that needs them, run one heavy model at a time, and unload when idle
(`--model-idle-unload-ms`, default 60 s; OCR worker after 30 s). The 800,000,000-byte ceiling applies to the
complete background process tree. Measurements are recorded in docs/VERIFICATION.md.

## Not yet built

Encrypted synchronisation, conflict resolution and deletion propagation between devices; phone-side action
capabilities; operating-system notification and device-event capture; integration of Needle proposals into the
action flow; preference and relationship memory beyond role and affiliation; hierarchical summaries; a documented
integration interface for Recursion.
