# Lens Micro verification report

Persistent record of milestone verification. Every entry lists what was executed, where the raw
evidence is, and what remains unverified. Historical entries are never rewritten; corrections are
appended. Status values: PASS, FAIL, BLOCKED, PARTIAL, NOT VERIFIED.

Host for all measurements unless stated: Windows 11 x64, AMD Ryzen 9 270 (8C/16T), ~16 GB RAM, CPU inference.

## Milestone 0 — foundation repair (2026-10-26) — PASS

Commit `9e19434` (checkpoint of prior agent's work: `a0ae604`).

| Check | Result | Evidence |
|---|---|---|
| Full regression suite | 80/80 pass (74 pre-existing + 6 new) | reports/verification-2026-10-26/m0-full-suite.log.txt |
| UTF-8 CLI output on code page 1252 host | zh/hi/ta/te/es text round-trips exactly through ImportText → encrypted DB → Source/Search | tests/test_unicode_privacy.py |
| Weak output-to-output Hindi test | Now asserts Devanagari, no `?`/U+FFFD, CER ≤ 0.25 vs FLEURS reference | tests/test_cli_extended.py |
| Private text off the command line | ImportText/Search/Context read stdin when -Text/-Query absent; empty stdin rejected | tests/test_unicode_privacy.py |
| Plaintext at rest | Sentinel absent from DB, WAL and key files | tests/test_unicode_privacy.py |
| 128-record import cap | Removed: chunked import in one explicit transaction; 300-message export imports; rejected record 281 rolls back all chunks | tests/test_unicode_privacy.py |
| Transaction poisoning | Failed request inside begin/commit forces rollback; exit without commit rolls back | tests/test_unicode_privacy.py |
| Reproducible PowerShell | 7.6.6 zip pinned by SHA-512/SHA-256 (third_party/pwsh-lock.json), placed under .tools | scripts/bootstrap_pwsh.py |

Changed test expectation (documented, not weakened): `test_file_record_and_native_wire_limits_reject_before_any_write`
no longer expects a 129-record export to fail, because removing that cap was a milestone requirement.

## Milestone 1 — multilingual semantic + hybrid retrieval (2026-10-26) — FUNCTIONAL PASS, QUALITY TARGETS FAIL

Final engine sha256 `12000f34f6753fa8b29695844d96419830935f37237999802fc28ba8f1d01c88`; design in docs/retrieval.md.

### Functional gates

| Gate | Result | Evidence |
|---|---|---|
| Regression suite | PASS — 101/101 | reports/verification-2026-10-26/m1-full-suite.log.txt |
| Native tokenizer parity (e5 + reranker pairs) | PASS — 0 token mismatches vs HF tokenizers on 500+ texts, 5 query families | tests/test_embedding.py |
| Native embedding / rerank parity | PASS — cosine > 0.9999; logits within 1e-3 of Python ORT | tests/test_embedding.py |
| Vectors encrypted at rest | PASS — no table names, plaintext or SQLite header in DB/WAL/key | tests/test_hybrid_retrieval.py |
| Cross-language evidence with exact byte-offset quotes | PASS | tests/test_hybrid_retrieval.py |
| Incremental index, delete cascade, filters, model-id isolation | PASS | tests/test_hybrid_retrieval.py |
| Natural-language time windows (6 languages, offsets, relax) | PASS | tests/test_temporal_query.py |
| Schema v5 migration from v1/v2 | PASS (made idempotent after a failure on synthetic downgraded DBs) | tests/test_memory_v2.py |
| Benchmark reproducibility | PASS — every report re-derived from raw rows, 0 mismatches; engine default abstention equals simulation | scripts/verify_retrieval_report.py |

### Quality targets (held-out test split, default mode = hybrid + rerank)

| Target | 10k events | 100k events | Status |
|---|---:|---:|---|
| Exact recall@10 ≥ 0.99 (strings unique in corpus) | 0.988 | 0.988 | FAIL (1 of 80 missed) |
| Semantic recall@10 ≥ 0.90 (all answerable) | 0.878 | 0.854 | FAIL |
| Top-1 correct evidence ≥ 0.80 | 0.762 | 0.748 | FAIL |
| Correct abstention ≥ 0.95 | 0.881 | 0.857 | FAIL |

Per language at 100k (R@1 / R@10 / unanswerable rejected): en 0.690/0.738/0.57, zh 0.786/0.810/0.86,
es 0.952/0.952/1.00, hi 0.804/0.857/0.86, ta 0.786/0.875/1.00, te 0.804/0.875/0.86.
Weakest query types at 100k: code_switch (romanized Hindi/Tamil/Telugu) R@10 0.690; cross_language 0.762.
Dev error analysis: false abstentions are mostly retrieval misses (romanized code-switch, some cross-language),
not threshold placement; thresholds were therefore not moved. Planned fix: native-script transliteration of
romanized Indic queries (candidate: AI4Bharat IndicXlit) evaluated on dev before any test run.

Baseline vs final at 100k: hybrid p50 2,438 ms → 359 ms; default (with rerank) p50 520 ms, p95 810 ms.
Legacy keyword search (pre-existing) R@10 0.272 at every scale.
Reports: reports/retrieval-nl/final-v2/SUMMARY.md (final engine), reports/retrieval-nl/20261026T092324Z-* (baseline engine).

### Model decisions

| Comparison (10k, test) | Result | Decision |
|---|---|---|
| e5 FP32 vs INT8, with rerank | top-1 evidence 0.731 both; FP32 private peak 1,038 MB vs 398 MB | INT8 |
| Rerank vs hybrid alone (INT8) | top-1 evidence 0.643→0.762 (final engine); wrongly rejected 0.252→0.139; zh unanswerable rejection 0.00→0.86 | rerank on by default |

### RAM (500 MB hard ceiling for the complete always-on observer)

| Measurement | Working set | Private | Status |
|---|---:|---:|---|
| Retrieval engine, e5 + reranker loaded, 100k events | 435 MiB | 441 MiB | PASS alone |
| Retrieval + whisper + Dolphin + OCR concurrently | 980 MB | 1,539 MB | FAIL |
| Same workers strictly serial | 448 MB | 691 MB | WS PASS / private FAIL (whisper.cpp commit) |
| Observation (Milestone 3) | — | — | NOT VERIFIED (not built) |

Evidence: reports/ram/combined-20261026T134032Z.json (scripts/profile_combined.py).
Required design: one model process at a time, idle model unload, and whisper commit reduction (verified against WER).

### Disk (encrypted, synthetic benchmark corpus)

1k events 1.8 MB, 10k 17.0 MB, 100k 169.3 MB (~1.7 KB/event incl. text, FTS5, metadata and one 384-byte int8 vector).
Models added: e5 INT8 118 MB, reranker INT8 119 MB, tokenizers 17 MB each (+ e5 FP32 470 MB reference, not used at runtime).

## Milestone 2 — retrieval quality (in progress, 2026-10-26)

### Benchmark validity

- Sealed holdout created and committed BEFORE diagnosis (`466d83d`): data/fixtures/retrieval-nl/holdout.json,
  72 memories (12 per en/zh/es/hi/ta/te), 252 answerable + 90 unanswerable questions, near-duplicate names.
  Runs only with `--fixture holdout --final` and fixed thresholds; every run logged in
  reports/retrieval-nl/holdout-runs.log.txt. Run 1: 2026-10-26T15:37Z, engine 7b6b109f.
- v1 test split was inspected during M1/M2 diagnosis and is now "diagnosis" data, not a final test.
- Exact queries whose string is non-unique in the corpus are scored separately (`exact_ambiguous`).
- Expansion set (data/fixtures/retrieval-nl/expansion.json, calibration/diagnosis only): 28 cross-app and
  timeline memories, 30 answerable, 25 near-miss + 7 other unanswerable questions.

### Diagnosis

English failures were caused by e5's language-identity component: unrelated Telugu/Tamil/Chinese passages
outranked the right English memory. The official FP32 model shows the same order (0.790 vs 0.781), so it is a
model property, not the native pipeline. Fix: per-script-group mean centering on stored vectors (engine,
`center`, default on). Evaluated IndicLID (≥357 MB romanized model, Python-only) — rejected for the 500 MB
budget; IndicXlit (MIT, 11M params, fairseq/Python-only) — deferred.

### Sealed holdout run 1 (default mode = centered hybrid + rerank; Wilson 95% CI)

| Gate | 10k events | 100k events | Status |
|---|---:|---:|---|
| Exact recall@10 ≥ 0.99 (n=71) | 1.000 | 1.000 | PASS |
| Semantic recall@10 ≥ 0.90 (n=252) | 0.944 [0.91,0.97] | 0.921 [0.88,0.95] | PASS |
| Top-1 correct evidence ≥ 0.80 | 0.813 [0.76,0.86] | 0.806 [0.75,0.85] | PASS (point), CI spans target |
| Unanswerable rejection ≥ 0.95 (n=90) | 0.811 [0.72,0.88] | 0.811 [0.72,0.88] | FAIL |

Uncentered baseline on the same holdout (100k): R@10 0.829, top-1 0.718, rejection 0.878.
Per language at 100k (R@10 / rejection): en 0.97/0.67, zh 0.92/0.73, es 1.00/0.93, hi 0.92/0.80,
ta 0.88/0.93, te 0.88/0.80. Latency p50/p95: 538/818 ms; peak working set 435 MiB.
Error taxonomy at 100k (scripts/error_taxonomy.py): correct 203, reranking errors 24, retrieval misses 15,
false abstentions 10; unanswerable: wrong answers 17, correct rejections 73.
Query interpretation (applications in 6 languages, action trace, relax-on-no-evidence): 7/7 tests pass.

### M2 — false answers: verifier investigation (2026-10-26)

- Acceptance holdout sealed BEFORE verifier work (`da3bad4`, data/fixtures/retrieval-nl/acceptance.json:
  66 answerable, 66 unanswerable of which 58 near-miss). The first holdout is now diagnostic.
- Near-miss training set (data/fixtures/retrieval-nl/nearmiss-v1.json): 72 questions, 12 per language,
  grouped by the v1 memory they target; 8 initially mislabeled items (answerable cross-lingually or ambiguous)
  were found by self-audit and replaced before any run.
- Fusion: `rrf` improved v1 ranking (diagnosis R@1 0.840→0.878, MRR 0.885→0.914) but NOT adopted as default
  pending a fresh holdout (owner instruction); expansion: equal R@10 1.0, top-1 0.967 vs 0.933 (1 question).
- Current fixed abstention rule rejects only 0.111 of the 72 near-miss questions and 0.320 of expansion
  near-misses (all at 10k events).
- Lightweight feature verifier (logistic on rerank, margins, cosine, keyword coverage, language, literal match;
  grouped 5-fold CV over 233 memory groups, 614 questions; reports/retrieval-nl/dev-experiments/answerability-features.json):
  at a 5% false-answer target it rejects 0.951 of unanswerable questions but wrongly rejects 0.408 of correct
  evidence (top-1 answered 0.507 vs 0.813 for the fixed rule). FAILED as a solution: relevance features cannot
  separate supported from unsupported evidence. Next: dedicated extractive-QA verifier (no-answer head).
- Extractive-QA verifier (deepset/xlm-roberta-base-squad2-distilled, onnx-community INT8 export, rev 484112f;
  evaluation only, not locked or shipped; scripts/experiment_answer_verifier.py; report
  reports/retrieval-nl/dev-experiments/answer-verifier-20261026T165918Z.json). Same 614 questions, same grouped
  5-fold CV, 5% false-answer target, top-1 evidence only:

  | Variant | Correct top-1 answered | False rejection of correct evidence | Unanswerable rejected | Expansion near-miss rejected |
  |---|---:|---:|---:|---:|
  | QA score only | 0.211 | 0.745 | 0.957 | 0.92 |
  | QA + rerank + cosine + literal | 0.558 | 0.325 | 0.951 | 0.96 |
  | rerank + cosine + literal (no QA) | 0.420 | 0.492 | 0.945 | 1.00 |

  Trade-off curve (out-of-fold, all sets): at 3.0% false answers QA+features answers 0.513 of answerable
  questions correctly (features alone 0.458 at 6.7%); at 7.9% false answers 0.602 vs 0.540 at 12.2%.
  Cost: model load RSS 555 MB, process peak 625 MB, load 1.6 s, per-pair p50/p95/p99 15.6/19.7/21.6 ms (4 threads).
  Verdict: QA adds real evidence-support signal, but quality is far from the target (≥0.80 correct top-1 at
  ≤5% false answers) and its RAM alone breaks the 500 MB ceiling. NOT ADOPTED.
- Multilingual NLI verifier (MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli, MIT, rev 0a71e92; evaluation only).
  Naive dynamic INT8 destroyed the model (argmax agreement with FP32 0/6 on probe pairs); a per-node sweep showed
  the FFN output MatMuls carry activation outliers (layer 2 logit error 3.7, layer 0 2.1). Export used: per-channel
  INT8, embeddings INT8, the 6 FFN output MatMuls kept FP32 (112 MB, sha256 64dbd73a…; probe agreement 8/8).
  Premise = top-1 evidence, hypothesis = question (report answer-verifier-nli-20261026T171926Z.json):
  NLI only 0.389 correct top-1 answered / 0.530 false rejection; NLI + rerank + cosine + literal 0.469 / 0.433
  (no verifier 0.420 / 0.492); adding NLI to QA does not help (0.540 vs 0.558). All at ~5% false answers.
  Cost: load RSS 388 MB, process peak 470 MB, load 1.4 s, per-pair p50/p95 5.2/7.3 ms.
  Verdict: NOT ADOPTED — questions are not NLI hypotheses; signal is weak and RAM still too high.
- Regression suite after query interpretation and the `rrf` fusion option: 109 tests, OK (2026-10-26).
- Conclusion of the comparison (feature verifier vs QA vs NLI): no off-the-shelf model separates supported from
  near-miss evidence well enough (best: 0.558 correct answered at 5% false answers vs target ≥0.80), and none fits
  the 500 MB ceiling beside the retrieval models. Remaining candidate: a task-specific answerability head trained on
  public multilingual data with unanswerable questions (SQuAD 2.0, IndicQA, translated sets), sharing the already
  loaded reranker so it adds no model RAM. Final adoption only after the sealed acceptance holdout.

## Hardware compatibility (founder requirement 2026-10-26: CPU-only, low-end laptops, 800 MB ceiling)

- Hardware profile tool (scripts/hardware_profile.py; no host or user identity recorded). H0 development laptop
  (reports/hardware/h0-g14.json): Ryzen 9 270, 16 logical processors, 15.3 GB, Windows 11 build 26300, only the
  Radeon 780M enumerated, CPU features up to AVX-512 + VNNI, Windows and CPUID sources agree. System memory
  load was 97% at profile time because of other applications — recorded so latency/RAM runs are interpreted
  correctly.
- Static instruction audit (scripts/check_hardware_compat.py → reports/hardware/compat-audit.json): FAIL.
  whisper.cpp ggml is configured GGML_AVX=ON, GGML_AVX2=ON, GGML_BMI2=ON with GGML_BACKEND_DL=OFF (no runtime
  dispatch) and is linked into lens-engine.exe, lens-sherpa.exe and lens-asr-probe.exe; with MSVC /arch:AVX2 the
  compiler may emit VEX code anywhere in those translation units, so a CPU without AVX2 can fault even outside
  ASR — to be confirmed by a dynamic test, not assumed. Lens's own compile flags: PASS (MSVC x64 default SSE2).
  Prebuilt runtimes (ONNX Runtime 1.24.4, sherpa-onnx's ONNX Runtime, OpenSSL/SQLCipher, Needle3): NOT VERIFIED
  on CPUs without AVX/AVX2.
- Low-end tiers H1–H3 (docs/acceptance-gates.md): BLOCKED — no test machines yet. No low-end number exists.
- Tests: tests/test_hardware_compat.py, 8/8 OK; full suite 117 tests OK (2026-10-26).
- CPU dispatch fix (2026-10-26): whisper.cpp (commit 231638a, ggml 0.27.0) rebuilt in build/whisper-dl as shared
  libraries with GGML_BACKEND_DL=ON, GGML_CPU_ALL_VARIANTS=ON, GGML_NATIVE=OFF, GGML_OPENMP=OFF: nine CPU variants
  (x64 = SSE2 baseline, sse42, sandybridge = AVX, haswell = AVX2, skylakex, cannonlake, cascadelake, icelake,
  alderlake). lens-engine.exe and lens-asr-probe.exe delay-load whisper.dll/ggml.dll (dumpbin: delay-load
  dependencies only), and engine/ggml_cpu_dispatch.hpp selects the highest-scoring variant from the executable's
  own directory only (no current-directory search, no GGML_BACKEND_PATH). lens-sherpa.exe no longer links ggml.
  Static audit now PASS_STATIC (reports/hardware/compat-audit.json); prebuilt runtimes remain NOT VERIFIED.
  Tests: tests/test_cpu_dispatch.py 4/4 OK (variant chosen on this CPU; forced SSE2-only variant transcribes
  jfk.wav correctly; missing whisper runtime and missing CPU variants return `asr_runtime_unavailable` while
  storage and search keep working); tests/test_hardware_compat.py 9/9 OK; engine ASR integration tests OK.
- ASR speed per forced CPU variant on H0 (FLEURS en_us clip 10.56 s, 4 threads, whisper total time, 2 runs,
  quiet machine but only ~460 MB free system RAM):

  | Variant | tiny-q5_1 | base-q5_1 |
  |---|---:|---:|
  | x64 (SSE2) | 9.9–10.1 s | 17.5–21.9 s |
  | sse42 | 9.9–10.0 s | 22.3–23.3 s |
  | sandybridge (AVX) | 3.2 s | 6.2–6.3 s |
  | haswell (AVX2) | 1.06–1.11 s | 2.1 s |
  | cascadelake (AVX-512 VNNI, auto-selected here) | 1.03–1.07 s | 2.0 s |

  Same transcript from every variant. Without AVX, whisper is about 10× slower even on a fast core: on real
  H3 CPUs (e.g. Celeron/Pentium Silver) in-process whisper ASR is not viable for interactive use and must
  degrade to deferred background transcription or a cheaper ASR path — to be measured on an H3 machine.
- Dynamic emulation: Intel SDE 10.13.1 downloaded from Intel's official mirror into .tools/sde (sha256
  74e626ed…, PKCS#7 signature verified, signer Intel Corporation via Sectigo). Running it was BLOCKED by this
  session's permission policy (external code); the H3 dynamic check of ONNX Runtime, OpenSSL/SQLCipher and
  Needle therefore remains NOT VERIFIED until the owner allows it or an H3 machine is available.
- whisper commit reduction (2026-10-26). Cause found by measurement: whisper_init_state added ~590 MB private commit
  regardless of model size (tiny 42→631 MB, base 70→682 MB) while its logged buffers total ~170 MB. Each of the four
  ggml schedulers reserved worst-case multi-backend split storage (4096 nodes × 30 inputs × 2 tensor structs
  ≈ 82 MB), and state->logits reserved n_vocab × n_text_ctx floats (≈ 93 MB) — committed, never touched.
  Two overlay patches (third_party/overlays/whisper.cpp/, recorded with sha256 in third_party/upstream-lock.json):
  single-backend non-parallel schedulers reserve 64 splits; logits grow on demand.
  lens-asr-probe peak private commit: tiny 637 → 204 MB, base 689 → 255 MB; working set unchanged.
  Output check: 24/24 FLEURS clips (en, hi, ta, te, zh, es; auto language) give byte-identical transcripts from
  patched and unpatched builds; ASR tests OK.
- Combined RAM on H0 (scripts/profile_combined.py, limit now 800,000,000 bytes; reports/ram/combined-20261026T182510Z.json):
  serial (retrieval → whisper-base → Dolphin zh → PP-OCRv6) peak working set 448 MB, private 440 MB (was 691) —
  PASS against 800 MB; concurrent 879 MB working set / 995 MB private — FAIL, so heavy models must stay serial.
  Largest single workers: Dolphin zh 449 MB and retrieval 408 MB working set.
- Engine idle footprint on H0: 11 MB working set / 2 MB private after open; 337 / 324 MB with e5 + reranker
  loaded; 18 / 7 MB after unload_models; keyword search keeps working with models unloaded.
- Idle model unload: lens-engine `--model-idle-unload-ms` (default 60000, 0 disables) releases the retrieval models
  after a quiet period; tests/test_idle_unload.py 3/3 OK (unload below 40 MB private, identical recall after
  reload, 0 keeps models, invalid values rejected).

## Milestone 3 — Windows observation, UI Automation first (2026-10-27) — PARTIAL (UIA capture working; OCR fallback not yet)

- lens-observer.exe (engine/observer/): starts only with `--consent`; follows the foreground window (or `--follow pid:<n>`
  for diagnostics/tests); 250 ms foreground/title polling with InternalGetWindowText (no messages sent), adaptive content
  checks 1 s → 30 s while unchanged; UI Automation control-view walk with cached properties under node/depth/character/time
  budgets (4000 / 48 / 32,000 / 400 ms); TextPattern for documents and edits.
- Privacy: password elements (UIA IsPassword) and their subtrees are never read; default-excluded processes (password
  managers, credential/consent/lock UIs, Lens itself) plus configurable exclusions and allow-lists; private-browsing
  titles (InPrivate, Incognito, …); capture-protected windows (display affinity) and invisible/cloaked/minimised windows
  are skipped. stderr diagnostics carry counts and reasons only, never text or titles. pause/resume/status/stop on stdin.
- Output: one engine `add` request per new content (id = SHA-256 of process, title and text, so an unchanged window is
  never stored twice; recent-hash set suppresses A→B→A repeats); kind screen_observation, provenance and consent context,
  window title and capture metadata; dominant-script language label (hi/ta/te/zh/und-Latn/und).
  `lens-observer --consent | lens-engine --db …` stores observations encrypted.
- Tests (tests/test_observer.py, 10/10 OK) run only against lens-observer-testapp in `--invisible` mode (alpha 0,
  click-through, never activated, no taskbar button): capture of label and edit text, password never captured (records
  and stderr), one record while unchanged and a new one after a change, Hindi script label, excluded process, private
  browsing title, capture-protected window, consent required, pause/resume, stored and found through the encrypted engine
  (plaintext absent from the DB file). An earlier visible-window test run disturbed the owner's screen; tests were
  switched to invisible windows. A hidden-desktop approach was tried and rejected: Win32 UIA proxies expose no child
  elements on a never-displayed desktop (root only).
- Resources on H0 over 30 s following a synthetic window: working set 17.7 MB, private 3.1 MB, CPU 0.2 s (0.68% of one
  core); first extraction 152 ms. Observer + idle engine ≈ 30–36 MB, inside the 50–100 MB idle target on H0 only.
- Not yet: OCR fallback for windows without usable UIA text (M4), browser URL/document identity, multi-monitor region
  hashing, a supervisor/service that runs the observer→engine pipeline, real-application UIA coverage benchmarks.

## Milestone 4 — screen OCR with detection (2026-10-27) — PARTIAL (dev benchmark only; Telugu fails)

- Models (Apache-2.0, pinned in models/manifest.lock.json, ONNX exports in third_party/ocr-runtime-lock.json via the
  pinned paddle2onnx 2.1.0 tool): PP-OCRv5_mobile_det (4.8 MB), PP-OCRv6_tiny_det (1.8 MB), PP-OCRv6_tiny_rec
  (general: Latin incl. accents, Chinese), devanagari/ta/te PP-OCRv5_mobile_rec.
- Benchmark screens (scripts/make_ocr_screens.py): 32 screens rendered by headless Microsoft Edge 156.0.4314.42
  (no window shown) at 1280×800 — en/zh/es/hi/ta/te × light, dark, small (12 px), chat, table, plus mixed-script and
  code editor; Windows fonts (Segoe UI, Microsoft YaHei, Nirmala UI, Consolas). Authored synthetic content. These
  screens were inspected while developing and are the OCR DEV set; a separate held-out screen set is still needed.
- Python reference (scripts/ocr_reference.py: official DBPostProcess with OpenCV/pyclipper, oracle routing):
  page CER en 0.4%, zh 0.4%, es 0.1%, hi 2.1%, ta 0.7%, te 9.8%.
- Native worker (lens-ocr.exe mode=screen: axis-aligned DB post-processing, reading order, script routing, optional
  changed region, in-memory base64 images; scripts/benchmark_ocr_native.py, CPU-only, 2 threads, H0 with training
  running in parallel). Auto routing (multilingual recogniser first, Indic recognisers when confidence < 0.9, most
  recently successful script first):

  | Language | Page CER | Line accuracy (CER ≤ 0.05) |
  |---|---:|---:|
  | en | 0.07% | 1.00 |
  | zh | 0.00% | 1.00 |
  | es | 0.07% | 1.00 |
  | hi | 2.9% | 0.77 |
  | ta | 0.3% | 0.97 |
  | te | 8.7% | 0.27 — FAIL |
  | mixed scripts | 3.0% | 0.83 |

  Latency (compute inside the worker): changed region p50 78 ms / p95 426 ms (targets < 150 ms median, < 500 ms p95:
  PASS on H0); full 1280×800 screen p50 612 ms / p95 1065 ms. Per-request wall time p50 842 ms (region) because each
  request starts a process and loads ONNX Runtime and models — a persistent OCR worker is needed. Peak working set
  231 MB per OCR request.
- Telugu failure analysis: the recogniser misreads the ra-vattu conjunct (్ర) as rendered by Nirmala UI and emits
  "[", "(" or "|" before the consonant (e.g. "ప్రణాళిక" → "[పరణాళిక"). This is a font/training-data mismatch; the fix is the
  planned Lens Indic line recogniser trained on Windows-font renders (docs/LENS_MODEL.md, stage T6). No rules were tuned
  on this dev set.
- Tests: tests/test_native_ocr.py 7/7 OK (crop mode unchanged; screen mode reads three lines in order, region mode,
  invalid region rejected, consent required).
- Not yet: OCR fallback wired into lens-observer, persistent worker, held-out real-application screenshot set,
  orientation model, H1–H3 latency.
- OCR fallback in lens-observer (2026-10-27): when UI Automation yields fewer than `min_uia_chars` (default 20) characters
  beyond the window title and the config carries an `ocr` request template, the observer captures the window in memory
  (PrintWindow, full content first), compares 32×32 tiles with the previous frame of that window, skips OCR when nothing
  changed, sends only the changed region (+8 px) when it covers < 60% of the window, and calls lens-ocr.exe with a
  base64 BMP on stdin. Records carry capture "ocr", region, line count, mean confidence, recognisers, OCR time and the
  worker's peak working set. Privacy checks run before any capture; frames are never written to disk.
  Tests: 3 new observer tests (GDI-painted text invisible to UIA is read by OCR; a change produces one new record from
  a changed region; without an OCR config nothing is captured) — tests/test_observer.py 13/13 OK, native OCR 7/7 OK,
  all on invisible windows.
- Persistent OCR worker (2026-10-27): `lens-ocr --serve` answers one request per line with ONNX Runtime, sessions and
  dictionaries kept loaded; errors come back in-line; stdin EOF exits. The observer starts it on first OCR need, kills it
  if a request exceeds 30 s, and closes it after `ocr_idle_ms` (default 30 s) without OCR so idle RAM returns to the
  observer's own footprint. Changed content is OCR'd as a full-width band (change ± 32 px) with lines cut by the band
  edges dropped (`drop_edge_boxes`); the observer keeps the window's OCR lines and replaces only those inside the band,
  so every record holds the whole window text in reading order. Measured on an invisible painted window (H0, training
  running): first OCR 1.04 s (worker start + model load, peak 95 MB), each later change 221–263 ms with correct full
  text. Tests: native OCR 8/8 (serve mode reuses sessions, survives bad requests), observer 14/14 (worker reused, then
  released after idle).

## Storage and compression — schema v6 (2026-10-27) — PARTIAL (synthetic workload only)

- Workload (scripts/benchmark_storage.py): 4,000 observer-shaped records built from public SQuAD 2.0 / TyDi text
  (documents scrolled and edited, chats growing; consecutive records of one window are near-duplicates). Synthetic —
  no real desktop data has been measured.
- Before compression (schema v5): 3,200 database bytes per record for 1,301 bytes of raw text. Breakdown of an
  identical plaintext schema (dbstat): observations 61%, FTS index 16.5%, source_metadata 12.8%, indexes ~9%.
- zstd 1.5.7 level 3 on the same texts: per record 1.84×, with a trained dictionary 2.25×, as a delta against the
  previous version of the same window 11.3×. Deltas were not adopted: they make rows depend on each other (deleting a
  base breaks later versions, and sync must ship chains); per-row frames keep every memory independently decodable.
- Schema v6: texts ≥ 256 bytes are stored as an independent zstd frame (optionally with a trained dictionary from
  `train_text_dictionary`) when that saves ≥ 15%; hashes are computed on the original text; all reads go through the
  registered SQL function lens_text(); FTS5 indexes the `observation_text` view, so search, highlight and deletes see
  original text. Migration is idempotent and re-indexes once.
  Result on the same workload: 2,293 bytes/record without a dictionary (−28%), 2,188 with a dictionary trained after
  1,000 records (−32%); ingest time unchanged (25.5 s → 26.7–27.3 s for 4,000 records).
- Tests: tests/test_text_compression.py 4/4 (exact read-back via find_source and search, compressed plaintext absent
  from the file, delete removes from FTS, dictionary training and decoding, Chinese literal scan over compressed text);
  migration tests updated to schema 6; affected suites OK.
- Not yet measured: retrieval latency impact of decoding on 100k compressed records, 1M-record growth, real workloads.

## Episodic memory L3 — schema v7 (2026-10-27) — PARTIAL

- `consolidate` rebuilds episodes from immutable observations: same device, application and window/document locator,
  gaps ≤ `gap_seconds` (default 600). Episodes are derived (fully rebuildable, deterministic ids from the first
  member), list every member (episode_members, cascades on delete) and contain no inferred content.
  `episodes` lists by time window / application; `episode_context` returns a source's episode plus the previous and
  next episode on the same device ("what was I doing before X"); `recall` results now carry their episode.
- Tests: tests/test_episodes.py 5/5 (grouping and gap split, device separation, filters, neighbours, recall context,
  deterministic rebuild, re-consolidation after a delete).
- Scale: 20,000 synthetic observer records → 2,103 episodes in 4.1 s (full rebuild incl. process start, H0, other
  work running). Full rebuild is O(N); incremental consolidation is needed before 1M-record use.
- Not yet: incremental/automatic consolidation, cross-application work sessions, episode summaries (L8), semantic
  facts (L4), project memory (L5).

## Milestone 7 — voice capture (2026-10-27) — PARTIAL (microphone path not exercised)

- lens-voice.exe: starts only with `--consent`; captures the default microphone at 16 kHz mono (miniaudio), segments
  speech with an energy voice-activity detector (threshold −45 dBFS, 200 ms pre-roll, utterance ends after 800 ms of
  silence, 300 ms minimum speech, 30 s cap) and emits one engine `ingest_audio` request per utterance with the audio as
  base64 WAV — never written to disk. The engine now accepts `audio_base64` as well as a file path. Ids cover the audio
  and its start time, so repeating the same words later is a new memory. stderr reports a "recording" event (the
  signal a supervisor/UI must show), levels and counts only.
- Tests (tests/test_voice.py 3/3, `--input-wav` replaces the microphone): consent required (no output); two
  utterances separated by 1.5 s of silence give two requests that the engine transcribes ("country") and stores as
  voice_note memories; pure silence gives no requests.
- Not verified: live microphone capture (no capture is performed without the owner's specific consent), VAD quality in
  noise, wake/push-to-talk UI, battery impact.

## Background agent (2026-10-27) — WORKING on H0 (no installer/service registration yet)

- lens-agent.exe owns the encrypted engine (model artifacts hash-verified against the lock files before use; on any
  mismatch it runs keyword-only and says why), runs lens-observer only while `observe_screen` consent is recorded in
  %LOCALAPPDATA%\Lens\config.json (set_consent), relays every observation into memory, consolidates episodes every
  10 minutes, supports pause/resume, and is single-instance. Clients use a named pipe whose DACL grants access only to
  the current user (and SYSTEM) and that rejects remote clients; only an allow-list of engine ops passes through.
  Children run detached (no console hosts).
- Tests: tests/test_agent.py 3/3 (status and model verification, passthrough and rejection, observation only after
  consent → stored and searchable → pause → consent withdrawn stops the observer and persists, no plaintext in the DB
  file, single instance). Observer pointed at an invisible synthetic window.
- Whole background system on H0, observing a synthetic window: idle 40.8 MB working set / 7.5 MB private
  (agent 10.6, engine 11.8, observer 18.4 MB) — inside the 50–100 MB idle target; with retrieval models loaded after a
  hybrid recall 381 MB working set (auto-unloaded after 60 s). Low-end tiers H1–H3 still unmeasured.

## Milestone 8 — Windows app (2026-10-27) — PARTIAL (no installer yet; not usability-tested with people)

- lens-app.exe: native window (dark title bar) hosting the bundled UI (engine/app/ui) in WebView2 (SDK 1.0.4258.31,
  BSD-3, static loader; Evergreen runtime 155 present on H0). The page can only load https://lens.local/ (virtual host
  mapped to the bundled folder; other navigations and new windows are cancelled; dev tools, context menus and zoom off;
  strict CSP). The UI reaches memory only through the host → lens-agent named pipe; the host starts the agent if needed.
- UI: Ask (evidence cards with app, window, time, episode, full source, delete with confirmation; explicit "No reliable
  evidence found" abstention), Timeline (episodes by day), Privacy (screen-observation consent switch, pause/resume,
  never-captured list), Status (counts, model verification, storage format); persistent capture status pill.
  Memory text is untrusted and only ever inserted as text.
- Tests (tests/test_app.py 2/2, nothing shown on screen): the host's --self-test runs the real UI against a real agent
  in a never-shown window (status + stats through the bridge, schema 7, 3.3 s); headless Edge with a mock bridge checks
  that injected <script>/<img onerror>/<b> in memory text and titles render literally with zero injected elements and
  no execution, abstention, consent toggle → set_consent → "Observing", timeline day grouping, status values.
- Not yet: installer and autostart, tray icon, onboarding, settings for exclusions, accessibility audit, usability
  testing, low-end performance of the WebView2 process (it runs only while the window is open).

## Milestone 9 — packaging and per-user installer (2026-10-27) — PARTIAL (unsigned; not yet run on a clean machine)

- scripts/package_lens.py stages a self-contained package: binaries, runtime DLLs (SQLCipher, OpenSSL, zstd, whisper +
  all ggml CPU variants), app-local Visual C++ runtime (VC145 redistributable), UI, only the models the product loads
  (each verified against its lock-file sha256) and the pinned ONNX Runtime, plus lock files, licences and a manifest
  with every file's size and sha256. Installed footprint: 436,189,756 bytes (≤ 500,000,000 gate on H0's package);
  largest parts: mMARCO reranker 136 MB, e5-small 135 MB, whisper base+tiny 92 MB, binaries 24 MB.
- scripts/install_lens.ps1 (Windows PowerShell 5.1+): per-user, no administrator rights; refuses 32-bit or pre-Windows-10
  systems; verifies every file against the manifest before copying; Start-menu shortcut; autostart only with
  -Autostart; screen observation stays off until enabled in the app. scripts/uninstall_lens.ps1 stops only this
  installation's processes, removes autostart/shortcut/files, keeps the encrypted memories unless -RemoveData (typed
  confirmation unless -Force). lens-agent finds its install root by locating the lock files above its executable.
- Tests (tests/test_installer.py 3/3, temp folders only): footprint and manifest contents; install → installed agent
  verifies its models → installed app self-test → uninstall removes the program and keeps data; a modified file makes
  the installer refuse before copying anything.
- BLOCKED / not yet: code signing (owner certificate), WebView2 runtime bootstrap for machines without it, clean-machine
  install on H1–H3 hardware, upgrade path, MSIX/winget packaging.

## Milestone 12 — paired-device link (2026-10-27) — PARTIAL (laptop side; phone app not built yet)

- lens-mesh.exe (separate network-facing process, started by lens-agent only while `phone_link` consent is on):
  TLS 1.3 only (OpenSSL 3.6), mutual authentication with self-signed P-256 certificates pinned by SHA-256
  fingerprint; the laptop identity key is DPAPI-protected on disk. Pairing: `mesh_pair_begin` returns a QR payload
  {hosts, port, laptop fingerprint, one-time token}; the token is 128-bit random, single use, valid 5 minutes and
  compared in constant time; the phone's certificate fingerprint is then authorised. Paired devices may only ping,
  recall, search, list episodes/episode context, find a source, read the timeline, and add notes/voice
  notes/shares/reminders — device name, provenance, source application and consent context of contributions are set by
  the laptop, never by the phone. `mesh_unpair` revokes immediately. No memory content is logged.
- Tests (tests/test_mesh.py 3/3, loopback only): link off without consent; unpaired certificate refused; wrong and
  reused tokens refused; search over mutual TLS; delete and consent changes refused remotely; forged provenance
  overwritten; non-allowed kind refused; pairing persists across connections; stranger certificate refused; revocation;
  client without certificate refused; wrong pin detected by the client; identity file contains no plaintext key.
  An agent shutdown hang (the mesh's own pipe connection blocked the client join) was found by these tests and fixed.
- Not yet: phone and watch clients, LAN discovery, firewall rule for private networks (binding all interfaces raises
  the Windows firewall prompt on first use), rate limiting beyond the 1 MB line cap, offline queue/sync of phone notes.

## Milestone 10 — Android companion (2026-10-27) — PARTIAL (built and unit-tested; emulator end-to-end pending)

- android/ (Kotlin 2.1.20, Jetpack Compose, AGP 8.12, minSdk 29, targetSdk 36): pairs with the laptop by pairing code
  (QR scanning to follow), keeps its link identity as a non-exportable P-256 key in Android Keystore, connects with
  TLS 1.3 presenting that key and trusting only the laptop certificate whose SHA-256 is in the pairing code. Features:
  ask laptop memory (evidence cards in plain text; explicit "No reliable evidence found"), quick notes and
  "Share to Lens" from any app, offline queue in app-private no-backup storage delivered when the laptop is reachable;
  cleartext traffic disabled; Lens data excluded from cloud backup and device transfer.
- Built with Gradle 8.14.3 on JDK 17 (debug APK 25 MB). JVM unit tests 6/6 (pairing-code validation, SHA-256 pin,
  pinned trust manager rejections, line framing, evidence/abstention parsing).
- Pending: instrumented end-to-end test against a real lens-agent/lens-mesh (tests/test_android_link.py +
  LaptopLinkTest, emulator image downloading), QR scanning, voice notes, real-phone validation (no device connected —
  release blocker for production claims).
- Wear OS (:wear, Wear Compose): pair, ask laptop memory, quick notes, reusing :core (same Keystore identity and pinned
  link). Builds a debug APK; not yet run on a Wear emulator or a watch (no wear system image installed, no watch).

## Milestone 13 — safe cross-device actions (2026-10-27) — PARTIAL (laptop-side registry; phone-side actions not yet)

- lens-agent action registry (engine/agent/actions.*): fixed typed capabilities with target device, side effects,
  validated parameters and mandatory confirmation — laptop.open_url (absolute https only, no credentials, no
  whitespace/control characters, ≤ 2048 chars) and laptop.remember (1–20,000 characters); a test-only test.echo exists
  only with --test-capabilities. Requests (local or from a paired device via lens-mesh, which forces requested_by to the
  device name) only create pending actions (max 20 open); execution happens only after the user approves in the Lens
  app — lens-mesh never forwards approval. Every transition is stored as an encrypted `action_audit` memory; approved
  laptop.remember stores the note with provenance "lens action <id>". No capability runs arbitrary commands.
- App: "Requests from your devices" on the Privacy page with Approve/Deny and a count on the navigation; request
  details render as text only.
- Tests: tests/test_actions.py 3/3 (registry and 7 validation rejections incl. http/file URLs, credentials and unknown
  capabilities; pending → approve → executed and verified; already-decided; deny never executes; remember stores with
  provenance; audit searchable; paired phone can request with forced requester but cannot approve); UI test extended
  (injected markup in a request renders as text, Approve sends action_decide). laptop.open_url is never approved in
  tests because it would open a browser on screen.
- Not yet: phone-side capabilities (reminders/calendar with on-phone confirmation), action expiry, Needle-proposed
  actions wired into the same pending flow.

## Milestone 14 — security testing, first pass (2026-10-27)

- tests/test_security.py 5/5: the engine answers each of 600 generated hostile lines (random code points, 500-deep
  nesting, wrong types, NUL, SQL/FTS injection strings, path traversal, malformed timestamps, every op) with exactly
  one JSON response, keeps running and keeps its data; a 3 MB request is refused; the agent pipe answers 150 hostile
  lines; the device link survives plaintext HTTP, invalid TLS records and random bytes, answers 120 hostile lines from an
  unpaired peer, refuses a 2 MB line and keeps serving; git tracks no databases, key files or private keys.
- Defect found and fixed: a request whose "op" was not a string made nlohmann::json::value() throw inside a connection
  thread, terminating lens-agent — and lens-mesh, where an UNPAIRED network peer could trigger it (remote denial of
  service). Both now type-check fields and catch per request; regression covered by the fuzz tests above.
- Not yet: authenticated fuzzing of every engine op with valid-but-extreme values at scale, code-signing and DLL
  search-order review of the installed layout, threat model document, third-party review.

## Lens-Core answerability head v0 — first trained Lens weights (2026-10-27) — TRAINED; deployment evaluation in progress

- What was trained (lens_model/): a cross-mode answerability head, label = "this evidence window supports an answer to
  this question", initialised from the shipped mMARCO cross-encoder (Apache-2.0 weights), 12 transformer layers + head
  fine-tuned, 250k-token embedding table frozen. One epoch, 108,352 pairs (SQuAD 2.0 incl. adversarial unanswerables,
  TyDi GoldP 9 languages, IndicQA hi/ta/te 70% of articles, XQuAD es/zh/hi 70% of paragraphs + cross-paragraph
  near-misses; licences and sha256 in lens_model/manifest/datasets.json), batch 32, lr 3e-5, CPU only (16-thread
  Ryzen 9 270, RTX 5060 not enumerated): 4.87 h, peak RSS 4.85 GB. Checkpoint: artifacts/lens-model/checkpoints/
  answerability-v0 (not committed); report: reports/lens-model/answerability-v0-training.json.
- Results (AUC; "kept" = share of supported pairs accepted when 5% of unsupported pairs pass):

  | Set (never trained on: held-out rows) | n | AUC | kept @ 5% false support |
  |---|---:|---:|---:|
  | Starting point (shipped reranker), dev sample | 2,000 | 0.709 | 0.208 |
  | Dev (SQuAD 2.0 + TyDi validation) | 9,071 | 0.959 | 0.769 |
  | IndicQA held-out (hi 0.963, ta 0.938, te 0.958) | 2,584 | 0.953 | 0.774 |
  | XQuAD held-out (es 0.969, hi 0.973, zh 0.964) | 3,353 | 0.969 | 0.817 |

  Mean logit: supported +2.4 to +3.2; related-but-unsupported −4.2 to −5.6; unanswerable near-miss −4.7 to −5.9 —
  the head separates "relevant" from "supported", which every off-the-shelf verifier failed to do.
- Pending: INT8 export parity, evaluation on the Lens retrieval fixtures (the 614-question harness where QA/NLI failed),
  CPU latency and RAM, then the sealed acceptance holdout once, before any adoption.
- v0 INT8 export (lens_model/export/export_onnx.py): 123.7 MB (FP32 470.8 MB); per-node sensitivity kept 3 MatMuls FP32
  (layer 5 FFN output, layers 6 and 8 FFN intermediate); on 600 held-out pairs Pearson 0.9994 with FP32, sign agreement
  0.992, mean |logit error| 0.13. Load RSS 398 MB in the Python harness, per-pair p50/p95 7.9/10.2 ms (4 threads).
- v0 on the Lens retrieval fixtures (same 614 questions and grouped CV as the QA/NLI verifiers; 5% false-answer target):
  head alone 0.202 correct answered; head + rerank + cosine + literal 0.440 (vs 0.420 without; QA 0.558). The public
  benchmark gain did NOT transfer. Diagnosis: (1) Lens near-misses swap the entity/attribute while topic and wording
  match — v0's negatives were mostly wrong windows/paragraphs; unanswerable Lens questions still scored median +1.6/+2.0;
  (2) keyword lookups ("ग्लूटेन", "endodoncia", "memory leak") are not questions and were scored as unsupported;
  (3) cross-lingual pairs, absent from training, inflate every score (unanswerable cross-lingual median +2.0).
  v1 data (lens_model/data/build_answerability_v1.py, public sources only, v0 held-out splits preserved): 23,164
  token-substitution near-misses, 23,984 keyword lookups (present/absent), 6,428 XQuAD cross-lingual pairs, 24,000 v0
  replay. Engine support for a verifier is built (`--verifier-model/--verifier-tokenizer`, `min_support`, abstention
  with `abstained_by: verifier`) but NOT enabled by default.

## Milestone 15 — sustained performance, H0 (2026-10-27) — PASS on H0 (low-end tiers not measured)

- scripts/sustained_run.py, 30 minutes, real components (agent with consent → observer → engine; OCR fallback through the
  persistent worker), invisible synthetic windows changing every 3–8 s, alternating 5-minute UIA and OCR phases, a
  recall every 30 s (reports/perf/sustained-20261027T000528Z.json):
  0 crashes; 352 samples; whole-tree peak 474 MB working set / 425 MB private (≤ 800 MB: PASS); CPU 1.7% of one core on
  average; 58/58 recalls OK, p50 200 ms, p95 2.37 s (cold reloads after idle unload); 327 memories stored, 273 embedded.
  Per phase the tree is flat — UIA 367–369 MB, OCR 465–467 MB (the OCR worker is 96 MB), engine 338 → 340 MB over 30
  minutes — no leak signal. Idle after load stops: 53 MB working set / 21 MB private (agent 11, engine 22, observer 20 MB).
- Not yet: the same run on H1–H3 machines, battery measurement (SRUM needs an elevated prompt), multi-hour runs.

## Real-screen run, H0 (2026-10-27) — FAIL (800 MB ceiling, CPU) — owner-consented, aggregate numbers only

- scripts/real_screen_run.py: the real lens-agent with screen consent on the owner's own desktop for 30 minutes while
  they worked normally (mostly one Electron chat app streaming text); temporary database deleted afterwards
  (reports/perf/real-screen-20261027T041404Z.json). A CPU training job and other work ran concurrently.
- 462 screen observations stored (457 UIA, 5 OCR), 1 failed, 0 exact duplicates, 4 applications; recall answered 3/5
  generic questions, p50 2.0 s; idle after consent off 16 MB.
- FAIL: whole-tree peak 637 MB working set / 905 MB private (> 800 MB); lens-ocr worker peak 507 MB (96 MB on the
  synthetic run); mean CPU 179% of one core (synthetic: 1.7%).
- Causes: the chat app exposes its whole scroll-back through UI Automation, so each capture held ~15.5k characters
  (median) and was re-stored as it grew (near-duplicates every ~4 s), each re-embedded; the OCR worker's memory grows
  with real (large, high-DPI) inputs; every observation was tagged `und-Latn` (no language identification).
- Fixes in progress: visible-text-only capture, settle/debounce, delta storage with near-duplicate suppression,
  per-observation language identification, CPU throttling (observer); bounded OCR worker memory (OCR).
  A second real-screen run needs the owner's consent again.

## Live microphone test, H0 (2026-10-27) — PARTIAL — owner-consented, aggregate numbers only

- lens-voice (`--consent`, whisper base q5_1, auto language) → engine on a temporary encrypted database (deleted):
  265.7 s of speech processed, 38 segments, 36 stored, 2 rejected as no speech; RAM voice 22 MB + engine 160 MB peak.
  Speech end → stored: p50 5.0 s, p90 19.6 s (long segments, CPU contended).
- FAIL on quality: automatic language ID returned languages the owner did not speak (ko/ml/ca/no/pt/fr/de) for Indic
  and English speech; Telugu segments became mixed-script text; 9 of 36 stored items were blank-audio markers,
  repetition loops or low-confidence text. Fixes (allowed-language LID, routing hi→IndicConformer and zh→Dolphin,
  hallucination filtering, shorter segments) are with the voice workstream.

## Memory layers L4/L5 — entities, facts, projects, schema v8 (2026-10-27) — PARTIAL (synthetic labelled sets only)

- Built: engine/semantic_extract.{hpp,cpp} (model-free rules, no new model, no std::regex: a tokenizer over Latin,
  Devanagari, Tamil, Telugu and Han; seed list of ~50 public place names with native spellings) and
  engine/memory_layers.{hpp,cpp} (schema v8: entities, entity_aliases, entity_mentions, facts, fact_sources, projects,
  project_sources, project_episodes, project_entities, extraction_state; migration is CREATE IF NOT EXISTS only).
  `consolidate` now runs episodes, then incremental extraction (`extract_limit`, default 2,000 sources per run; the rest
  is reported as `memory.pending_sources`): rule mentions → the user's own gazetteer (names a rule confirmed anywhere,
  applied to the batch, then FTS/Han-substring backfill of older sources) → facts → entity refresh → project rebuild.
  Names join across scripts by romanised keys (Arun / अरुण / அருண் is one entity; "Chennai" finds சென்னை).
- Facts: deadline (due), meeting (scheduled), amount (budget/salary/rent/refund/invoice/paid/cost, cue required),
  decision (affirmative, non-question), role, affiliation. Each fact has ≥1 `fact_sources` row (source id + byte range of
  the sentence); `status: observed`; a subject taken from elsewhere in the same source is `subject_basis: inferred`,
  `certain: false`. Relative dates resolve against the source's own time; ambiguous d/m dates are left unparsed.
- Privacy: triggers delete a fact when its last source goes and an entity when its last mention goes; the `delete` op
  then refreshes names, aliases and identity keys of touched entities and rebuilds project links in the same
  transaction (test: deleting the only English "Arun" source leaves the entity named from Hindi/Tamil only, no "Arun"
  alias; Globex disappears; re-consolidation never re-derives deleted evidence).
- Ops: `entities` (type/query/time), `entity_context` (aliases, mentions with verbatim excerpts, facts, co-mentioned
  entities, projects, episodes), `facts` (entity/entity_id/type/project_id/source_id/start/end), `projects`,
  `project_context` (entities, episodes by member or window title, facts with `project_link` subject/same_source/
  same_episode, sources). `recall` adds `entities` named in the question, per-result `entities` and `facts`,
  `entity_facts` with sources, and a stable promotion of entity-linked evidence (`entity_boost`, default true;
  `entity_boosted` reports a reorder). No effect on databases that were never consolidated (retrieval benchmarks).
  `stats` adds entity/fact/project counts. lens-agent allow-list gained the five read ops; checked through the agent pipe
  (lens-agent built 10:16): add → consolidate → entities/facts/projects/entity_context/project_context all ok.
- tests/test_memory_layers.py (10 tests, synthetic en/es/hi/ta/te/zh, temp dirs): extraction quality, incremental
  consolidation, provenance (every quote equals the source bytes), cross-script names, ops, projects, recall, deletion
  cascade, genuine v7→v8 migration and re-run idempotence, 400 hostile lines on the new ops (one answer each, no crash).
  Extraction quality (mention = source+type+surface, fact = source+type+value):
  | Set | Mentions P / R | Facts P / R |
  |---|---|---|
  | Development, 28 sources (written alongside the rules) | 1.000 / 1.000 (34) | 1.000 / 1.000 (25) |
  | Held-out, 18 sources (written before the first run, never used to change rules) | 0.889 / 0.889 (18) | 1.000 / 0.833 (18) |
  Held-out errors: "Agreed:" read as a chat speaker; "Helix 2" typed product (labelled project Helix); 华为公司 missed
  (为 is in the Han stop list); missed facts "kickoff" (no meeting cue), "pagamos 200 dólares" (cue/currency word
  missing), "报价" (no cost cue). These sets are tiny and synthetic: real-data quality is NOT VERIFIED.
- Cost (G14, H0; 5,000 synthetic multilingual sources, one engine process, psutil): first consolidate 2,000 sources in
  4.4 s (0.88 ms/source incl. gazetteer backfill), peak working set 16 MB / private 7 MB, no model loaded; keyword recall
  with entity annotation 145–194 ms vs 56 ms for a question naming no entity; project_context 259 ms; entities 6 ms.
  (First measurement 660–985 ms recall exposed fact rendering that decompressed every supporting source; fixed to
  aggregate without text and decompress only returned quotes.)
- Commands: `.venv\Scripts\python.exe -B -m unittest discover -s tests -p "test_memory*" -v` → 21 tests OK;
  `-p test_episodes.py` 5 OK, `-p test_text_compression.py` 4 OK, `-p test_hybrid_retrieval.py` 10 OK,
  `-p test_security.py` 5 OK (2026-10-27, after relinking lens-engine). Schema assertions updated to 8 in
  test_memory_v2, test_hybrid_retrieval, test_text_compression and test_app (`-p test_app.py` 7 OK, run 18:48 against
  the 10:18 lens-engine and 10:16 lens-agent).
- Not done: preferences, routines, commitments/tasks, relationship types beyond role/affiliation, conflict/supersession
  of facts (L6 "latest vs superseded"), L8 summaries, user correction ops for derived records, real-data evaluation.

## Desktop experience: onboarding, tray, autostart, install flow (2026-10-27) — PARTIAL (H0 only; unsigned; tray icon not exercised by tests)

- First-run onboarding (engine/app/ui): shown while the agent reports `onboarded:false`. Plain-language explanation of
  screen / microphone / phone-link capture and of where data lives (the agent's data folder, encrypted, user-only);
  separate opt-ins for screen, microphone, phone link and "Start with Windows", all OFF by default; an exclusions editor
  (app file names, window-title words) on top of the observer's built-in list. Nothing reaches the agent until Finish
  (or "Keep everything off"); Finish sends set_exclusions before set_consent so the first capture already honours them.
  The Privacy page gained the same toggles, Pause covering all capture, and the exclusions editor.
- lens-agent: set_consent accepts microphone/onboarded; set_exclusions (validated: arrays ≤ 200 strings, 1–260 chars, no
  newlines; a running observer restarts to apply them); set_autostart (HKCU Run value `LensAgent` →
  `"<bin>\lens-app.exe" --background`, key overridable for tests). Microphone consent supervises lens-voice. Pause
  stops screen and microphone at once and holds until Resume, including across observer restarts.
- Tray: lowest-RAM design = a thread + never-shown window inside lens-agent (no extra resident process); `--tray` adds
  the notification icon (status Observing/Paused/Off, Pause/Resume, Open Lens, Quit Lens); `--tray-hidden` keeps the
  same command window without the icon (tests). lens-app `--background` is the windowless launcher autostart uses
  (agent is a console-subsystem exe; launching it from Run directly would open a console window).
- Bug found and fixed: a capture child that ended on its own (lens-voice at end of input) was restarted on the same
  Child object while its reader thread was still joinable → std::terminate (agent died on Resume). start_* now reap the
  previous run first.
- Installer: `-Autostart` only on opt-in; `-ProgramsDir` and `-RunKey` (must be HKCU:) recorded in install.json;
  uninstall asks the agent to shut down over its pipe, stops remaining processes from the install folder, removes the
  recorded Run value (only if it points into the install) and shortcut, deletes the program, keeps memories unless
  `-RemoveData`. Code signing: BLOCKED (owner has no certificate); install.json records `code_signed:false`.
- Tests (`.venv\Scripts\python.exe -B -m unittest tests.test_app tests.test_installer -v`, nothing shown on screen,
  observer on the invisible test app, microphone replaced by a silent WAV, autostart in a scratch HKCU key deleted after
  each test, real HKCU Run value checked unchanged): test_installer 4/4 OK (38 s) including install with -Autostart →
  `lens-app --background --tray-hidden` → onboarding visible in --self-test → consent → uninstall with the agent running
  leaves no process, Run value or shortcut and keeps memory.db/config.json; test_app 6/7 — all new tests pass (onboarding
  in headless Edge, consents default off and persist, exclusions validation + a title exclusion keeps the window out of
  memory, autostart Run value, tray Pause stops capture / survives observer restart / Resume captures again / Quit exits
  0); the failing one is AppHost's `schema_version == 8` assertion added by the memory-layers session, pending a rebuilt
  engine (the binary still reports 7).
- Idle RAM, H0, background system as sign-in starts it (lens-app --background, tray command window, every capture off,
  onboarding done), 18 samples over 90 s after a 70 s settle: tree 14.3–23.6 MB working set, 4.6–4.7 MB private
  (agent 7.3 / 1.9 MB, engine 7.5 / 2.7 MB). Well under the 800 MB ceiling and below the 50–100 MB idle target band. The
  notification icon's own cost (shell side) and capture-on idle with the icon were not measured (no visible UI in tests).
- Not yet: running the real tray icon by hand, accessibility audit of onboarding, WebView2 runtime bootstrap, clean-machine
  install on H1–H3, upgrade path, usability testing with people.

## Voice capture quality under noise — file-driven (2026-10-27) — PARTIAL (VAD fixed and measured; zh/hi ASR fails; latency/soak pending)

No microphone was opened. scripts/benchmark_voice.py builds sessions from public FLEURS test clips (CC BY 4.0,
revision 70bb2e84) with 1.2-4 s gaps, mixes white/pink/babble (FLEURS clips of non-evaluated languages)/fan+mains hum
at SNR 20/10/5 dB plus clean, raw FLEURS levels, quiet (-46 dBFS), hot (clipping) and 48 kHz stereo input, and relays
lens-voice requests to lens-engine on a temporary encrypted DB. Clips are split by sentence id (sha256 bucket <3/10 =
dev); VAD parameters were chosen on dev only (reports/voice/vad-tuning-dev*.json, tune-dev-round*.log.txt).
- lens-voice fixes: adaptive VAD (default; `--vad legacy` keeps the old -45 dBFS detector): 80 Hz-3 kHz analysis
  band-pass, noise floor = 20th percentile of last 5 s, start/continue 8/4 dB above floor (>= -65 dBFS), 60 ms onset,
  600 ms hangover (500 ms kept), 150 ms min speech, soft split after 20 s, 30 s cap; resampler LPF order 8; clipping
  counted and reported; file input decoded incrementally (old code held the whole file in RAM) with `--pace`; a
  stalled consumer drops audio past 60 s (counted as overrun). Requests carry stream offsets for evaluation.
- Held-out VAD, all 561 sessions / 4386 utterances (vad-heldout-*-all.json), adaptive vs legacy: non-speech captured
  7.2% vs 66.7%; 30-s capped segments 0 vs 1087; missed speech 4.7% vs 3.3%; utterance recall 0.83 vs 0.94 (legacy
  "recall" comes from capturing everything). Quiet input missed speech 4.9% vs 29.2%; raw FLEURS levels 3.1% vs 22.7%.
  Babble still captures 11-31% of non-speech (energy VAD cannot reject speech-like noise).
- Held-out end-to-end WER (product path: whisper base-q5_1, language auto, 1 session x 8 utterances per cell;
  asr-heldout-*-product.json), adaptive (legacy): en clean 6.3% (5.7%), raw level 13.7% (71.4%), quiet 8.6% (14.9%),
  pink10 13.7% (12.6%), white10 22.3% (24.0%), fan10 6.3% (8.6%), babble10 31.4% (26.9%), white5 42.3%, babble5 54.9%;
  es clean 8.2% (9.3%), quiet 10.9% (36.1%), babble10 18.6% (21.3%). Mandarin CER clean 30% (33.6%), up to 78% at
  babble5; Hindi CER ~100% in every condition: whisper base emits Urdu script/romanised text. The voice path never
  routes zh/hi to Dolphin/IndicConformer (only scripts/lens.ps1 does, from a file) — FAIL for zh/hi voice.
- RAM (sampled, lens-voice + lens-engine, no embeddings): peak sum working set ~180-220 MB; lens-voice ~12 MB.
  Engine reloads whisper per request. Unit tests: tests/test_voice.py 10/10 (noise, hum/clicks, 48 kHz stereo,
  clipping, pacing, 12-min file under 40 MB, legacy comparison).
- Pending at time of writing (running): configured-language zh/hi/es, paced (1.0x) latency speech-end to stored,
  32-minute paced soak with RSS sampling (reports/voice/latency-*.json, soak.json). Live microphone NOT VERIFIED.

## Windows app: remaining views, accessibility, languages (2026-10-27) — PARTIAL (H0; hidden-window measurements; not usability-tested)

- New views (engine/app/ui; same strict CSP, untrusted text only through textContent / SVG geometry):
  - Evidence viewer (drawer dialog): the full source from find_source, with the recall/mention span highlighted from the
    engine's UTF-8 byte offsets (correct after CJK/Telugu text). It shows provenance (time, app, window or file, device,
    kind, language, capture path, consent mode), facts from `facts {source_id}` with an "inferred" marker, the
    people/things named in the passage (`entities {query}`) and "Delete this memory". Esc closes it, focus is trapped
    inside and returns to the opener.
  - Timeline filters (app contains, kind, from/to date) through `timeline {filters}`; with no filter it shows sessions
    (episodes).
  - People and things (`entities`, with type filter and search; `entity_context`: aliases, facts, projects, related,
    mentions that open the evidence at the mention).
  - Projects (`projects`, `project_context`: people, facts, sessions, memories).
  - Devices: phone-link switch, in-app QR pairing from mesh_pair_begin with a 5-minute countdown and the text code,
    paired-device list, revoke (mesh_unpair), and this PC's certificate fingerprint and port.
  - Import: native file picker in the host, preview, import with live progress, cancel, history, and delete-by-import.
  - Storage (engine stats plus the files in the data folder).
  - Diagnostics (agent `diagnostics`: process-tree memory from GetProcessMemoryInfo, uptime, capture state, the last
    screen/voice capture's path and timings, models).
- QR encoder: our own (engine/app/ui/qr.js, ISO 18004 byte mode, level M, versions 1–40, penalty-scored masks), so no
  third-party code. Verified by OpenCV 4.10's independent decoder for 1–400-byte payloads (the pairing code is about
  180 bytes, version 10). A 1200-byte / version-29 payload did not decode in an ad-hoc check, so codes that large are
  NOT VERIFIED.
- lens-agent: `diagnostics` op (real measurements, never captured text); import jobs (engine/agent/imports.hpp) with
  `import_preview|start|status|cancel|delete`. They parse WhatsApp (day/month order chosen by the user, multi-line
  messages, media lines and impossible dates skipped), JSON Lines and plain text, and add records one at a time, so
  the engine's sensitive-content filter rejects single records (counted by code). Records are tagged exactly like
  scripts/import-history.ps1: source_locator `sha256:<file sha256>#record=<n>` (no file name) and provenance JSON
  {export_sha256, format WhatsApp/LensJsonl/Text, importer_version}. Ids derive from that locator, so re-importing the
  same file is deduplicated. Checked: the engine's `imports` op lists an app import (format Text, 2 sources) and
  `delete_sources {scope:{import}}` deletes it. imports.json also lists which ids each import created.
  Only one import runs at a time. The memory-lifecycle session wants parsing to live in scripts/import-history.ps1. That
  needs PowerShell 7, starts its own engine from the repository build path, and would open memory.db a second time, so
  the app keeps the C++ parser until the script can run in the installed layout (to be decided by the coordinator).
- Accessibility (WCAG 2.2 AA, automated in tests/test_app.py AppViews.test_wcag_aa_checks_on_every_view, every view
  with data plus the evidence drawer and all three onboarding steps):
  - Checked: text contrast 1.4.3 (computed colours composited over the real backgrounds; 4.5:1, or 3:1 for large text),
    accessible names 4.1.2, target size 2.5.8 (≥ 24×24 CSS px), no positive tabindex 2.4.3, a :focus-visible outline
    2.4.7, all navigation focusable 2.1.1, page language 3.1.1, dialog role/aria-modal/label, a skip link, forced-colors
    and reduced-motion support.
  - Result: 0 failures across more than 150 text nodes and more than 60 controls. Negative control: lowering --muted
    to #55565c produced 126 contrast failures, and removing the 24 px minimum produced 7 target-size failures.
  - Real keyboard navigation and screen-reader output were not tested (headless).
- Languages (spec §1a, AppLanguages test): text in each of the 17 languages renders through the result cards with lang=
  and dir=auto. Arabic and Urdu come out right-to-left, the others left-to-right. Each resolves to a Windows font whose
  cmap (read by a small reader in the test) covers every character of the sample: Segoe UI, Microsoft YaHei UI, Yu
  Gothic UI or Nirmala UI. Urdu Typesetting is not installed on H0, so Urdu uses Segoe UI's Arabic glyphs (Naskh, not
  Nastaliq).
- Tests (`.venv\Scripts\python.exe -B -m unittest tests.test_app tests.test_installer -v`, no visible window):
  - test_app 15/15 OK, including XSS payloads in every view (0 injected elements, no script execution), the agent
    import/diagnostics tests, and AppHost's self-test loading all 9 views against a real agent with 0 errors.
  - test_installer 4/4 OK.
  - Measured on H0: lens-app time to interactive 2.72–2.78 s from process start (UI ready at 2.1 s). lens-app idle
    with the hidden window, 7 processes including WebView2: 339 MB working set, 131 MB private. Background agent tree
    23 MB, so app plus agent is about 362 MB, under 800 MB.
  - The app runs only while its window is open. The visible window's RAM, low-end tiers and usability with people are
    not measured.
