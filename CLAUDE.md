# Lens — engineering instructions for Claude Code

Read these before changing code, every session:
- AGENTS.md — rules (authoritative).
- docs/LENS_V1_SPEC.md — canonical product specification (what Lens V1 must be; one product, no v2/v3).
- PRODUCT_VISION.md, ARCHITECTURE.md (as built), IMPLEMENTATION_STATUS.md (what exists).
- docs/VERIFICATION.md (test evidence), docs/RELEASE_READINESS.md (gates/blockers), docs/HANDOFF.md (how to continue).
- docs/LENS_MODEL.md (trained Lens model: feasibility, architecture, training plan).
- docs/retrieval.md (retrieval design); docs/REQUIREMENTS.md (detailed requirements register, binding where not
  superseded by the specification; machine-readable copy docs/requirements.json).
Never present a planned feature as implemented. BUILD → TEST → VERIFY → FIX → RETEST → DOCUMENT → CONTINUE.
The sealed retrieval holdout (data/fixtures/retrieval-nl/holdout.json) is never used for tuning.

## Verified facts (update only from executed evidence)

- Native C++20 engine (`engine/`), built with Visual Studio 18 CMake into `build/engine/Release/`.
  Build one target: `"C:/Program Files/Microsoft Visual Studio/18/Community/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe" --build build/engine --config Release --target lens-engine`
  A running `lens-engine.exe` locks the binary; never rebuild while a benchmark uses it.
- Client: `scripts/lens.ps1` on project-local PowerShell 7.6.6 (`.venv\Scripts\python.exe scripts/bootstrap_pwsh.py`).
- Tests: `.venv\Scripts\python.exe -B -m unittest discover -s tests -v` (temp dirs only), run from the PowerShell tool:
  headless Edge fails inside the Bash tool's sandbox. Baseline 2026-10-28: 250/251 OK, android_link skipped (no device).
  Do not run `scripts/test_all.py` casually: it overwrites reports/test-results.json.
- Store: SQLCipher, DPAPI-wrapped key file beside the DB, schema v9 (v7 episodes + episode_members; v8 entities/entity_aliases/entity_mentions, facts/fact_sources, projects/project_sources/
  project_episodes/project_entities, extraction_state — all derived by `consolidate`, deleted with their sources by triggers;
  v9 pins, recall_feedback, user_facts, fact_status, retention_rules; observations with optional zstd text
  `text_codec`/`text_zstd`, read only through `lens_text()`; source_metadata, derived, memory_fts over the
  `observation_text` view, embedding_chunks with int8 vectors, text_dictionaries). Explicit `begin`/`commit` ops
  poison on failure. Migrations must stay idempotent (tests reset user_version on current databases).
- Retrieval: `recall` op (keyword | semantic | hybrid RRF) with multilingual-e5-small INT8, default cross-encoder
  rerank (mmarco-mMiniLMv2 INT8) when configured, and natural-language time windows; pinned ONNX Runtime 1.24.4 DLL.
  Verified at 1k/10k/100k (docs/VERIFICATION.md): functional gates pass, quality targets do not yet.
- RAM ceiling (founder, 2026-10-29): 500 MB peak for the complete Lens system (was 800 MB), storage up to 1 GB, idle target 50–100 MB, CPU-only
  mandatory, low-end laptops supported (spec §15). Measured on the G14 only: serial model workers 440 MB private
  (under 500, after the whisper commit patches), concurrent 995 MB (over); lens-tts alone 394 MB; engine idle 11 MB, 18 MB after
  model unload (automatic after 60 s idle, `--model-idle-unload-ms`); synthetic 30-minute whole-tree run with observer
  401 MB working set / 366 MB private; the 2026-10-27 real-screen run FAILED (905 MB private); low-end tiers NOT VERIFIED.
- CPU compatibility: whisper.cpp is built in build/whisper-dl as shared libs with runtime-selected ggml CPU variants
  (SSE2 baseline … AVX-512); the engine delay-loads it (engine/ggml_cpu_dispatch.hpp). `scripts/check_hardware_compat.py`
  passes statically; prebuilt ONNX Runtime/OpenSSL/Needle stay NOT VERIFIED without AVX (Intel SDE in .tools/sde,
  execution needs owner permission). `scripts/hardware_profile.py` records a tier profile.
- Retrieval benchmark: `scripts/benchmark_retrieval_nl.py` (fixture data/fixtures/retrieval-nl/v1.json; dev split
  01-06 is the only data used for tuning). Verify reports with `scripts/verify_retrieval_report.py`.
- Building upstream source from fresh clones may be blocked by this environment's permission policy; ask first.
