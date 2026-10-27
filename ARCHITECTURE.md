# Lens — architecture (as built)

Only components that exist in the repository are described as present; planned components are marked.
Detailed retrieval design: docs/retrieval.md. Original model-proof decision record: docs/architecture.md.

```
clients ── scripts/lens.ps1 (Windows CLI, PowerShell 7.6.6)      [Windows GUI, Android, Wear OS: planned]
           scripts/import-history.ps1 (WhatsApp/JSONL/text exports)
   │  JSON lines over stdin/stdout (no network listener)
   ▼
lens-engine.exe (engine/main.cpp) ── Store (engine/store.cpp)
   ├─ SQLCipher DB + DPAPI-wrapped random key (adapters/windows/key_store.cpp)
   │    schema v5: observations (immutable L0), source_metadata, derived (unused L2 slot),
   │    memory_fts (FTS5), embedding_chunks (int8 vectors, exact byte ranges)
   ├─ ops: add, import_batch, begin/commit/rollback, delete, stats, search, retrieve_context,
   │       timeline, find_source, index, recall, unload_models, ingest_audio (whisper.cpp in-process)
   └─ retrieval (engine/retrieval.cpp, temporal.cpp)
        keyword: FTS5 + unspaced-script bigram scan → unit coverage
        semantic: e5-small INT8 (embedder.cpp, e5_tokenizer.cpp, onnx_model.cpp) → cached int8 scan
                  with per-script-group centering
        fusion: coverage-weighted RRF; rerank: mMARCO cross-encoder INT8 (reranker.cpp)
        abstention, natural-language time windows, verbatim evidence quotes
agent: lens-agent.exe (engine/agent/) — always-on owner of lens-engine and lens-observer; user-only named pipe for
   the app/CLI; consent in %LOCALAPPDATA%\Lens\config.json; periodic episode consolidation
observer: lens-observer.exe (engine/observer/) — consent-gated UI Automation text capture, privacy exclusions,
   change dedup; emits engine add requests on stdout (pipe into lens-engine)
worker processes (one request each): lens-sherpa.exe (Dolphin zh / IndicConformer hi ASR),
   lens-ocr.exe (PaddleOCR recognition crop), lens-needle.exe (Needle3 proposals, never executed)
```

Models load lazily inside the process that needs them and are released with it (`unload_models` for the
retrieval models). Measured RAM is in docs/VERIFICATION.md; the combined concurrent workload exceeds the 800 MB ceiling (serial
peaks fit on the development laptop). whisper.cpp is linked as delay-loaded DLLs with one ggml CPU
backend per instruction-set level, chosen at first use (SSE2 baseline upward); prebuilt ONNX Runtime and OpenSSL
are not yet verified on CPUs without AVX.

Planned (not built): OCR fallback inside the observer, an observer supervisor/service, microphone capture, episodes/facts/entities (L1/L2), zstd compression, GUI/installer, Android,
Wear OS, device pairing/sync, cross-device actions.
