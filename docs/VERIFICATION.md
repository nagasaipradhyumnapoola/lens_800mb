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

## Voice capture quality under noise — file-driven (2026-10-27) — PARTIAL (VAD fixed and measured; zh/hi superseded 2026-10-28)

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
- Superseded for zh/hi and segment lengths by the 2026-10-28 section below (routing, 12/20 s segments).

## Voice: 17-language routing, hallucination filter, owner-only capture (2026-10-28) — PARTIAL (file-driven; ur/gu fail; live mic NOT VERIFIED)

Fixes for the owner-consented live-mic findings, all measured file-driven on public data (no microphone opened).
- Language ID restricted to the user's languages (default: the 17 spec §1a languages, `lens-voice --languages`):
  whisper's language probabilities, best among the allowed set (engine/asr.cpp). Held-out FLEURS: LID accuracy
  0.94-1.00 for 13 languages; mr 0.68 (some → bn), **ur 0.33 (→ hi) and gu 0.32 (→ mr)**.
- Routing (lens-voice discovers installed models; lens-engine frees whisper, then runs lens-sherpa as a child with
  the audio over a pipe): zh → Dolphin small CTC; hi/bn/te/mr/ta/ur/gu → IndicConformer 120M int8 (pinned revision
  9721eb71, hashes in reports/voice/model-downloads-lock.json); every other language → whisper base q5_1.
  Bug found and fixed: a forward-slash DLL path made Windows load System32's onnxruntime 1.17 ("API version 28 not
  available"); lens-sherpa now loads its library by fully qualified path.
- Held-out FLEURS, clean, 40 clips/language, ~21-32 utterances each through lens-voice → engine
  (asr-heldout-adaptive-product-global17{,-final}.json). WER (CER) before routing → after; Whisper paper Table 13
  FLEURS WER for base / small in brackets (their normaliser, not comparable digit-for-digit):
  en 9.5% → 9.5% [8.9/6.1]; es 11.7 → 11.9 [9.9/5.6]; ar 53.2 [48.8/30.6]; fr 26.3 [28.5/15.0]; pt 15.8 [13.0/7.3];
  ru 22.3 [20.5/11.4]; id 37.1 [33.1/16.3]; de 21.0 [17.9/10.2]; ja CER 25.3% [WER 22.8/12.0]; zh CER 11.4%
  (Dolphin) [WER-as-printed 34.1/20.8]; hi 29.3 → 26.6 (CER 17.7) [101.1/38.4]; **bn 100.4 → 14.8** [100.6/104.4];
  **te 110.8 → 34.4** [105.2/98.2]; **mr 106.2 → 44.3** [100.3/60.2]; **ta 94.1 → 29.7** [58.7/35.2];
  ur 82.8 → 68.1 [52.0/37.3]; gu 100.5 → 73.4 [101.4/106.4]. ur/gu FAIL with automatic LID because it sends them
  to the hi/mr model; with the language configured (`--language ur|gu`, same held-out clips) ur WER 18.1% (CER 7.0%)
  and gu WER 24.5% (CER 9.4%) (asr-heldout-adaptive-configured-configured-urgu.json) — the models work, LID is the gap.
- Hallucination filter (engine/asr.cpp): whisper annotations ([BLANK_AUDIO], (music), ♪…) stripped, punctuation-only
  text → no_speech_found, repetition loops (3× covering 80%, 4× covering half, or 8×) → repetition_rejected, invalid
  UTF-8 from split tokens dropped (it had produced an `invalid_request`). Token probability turned out to be a weak
  signal on dev (0.52 drops 1.2% of good segments but only 15% of garbage: garbage is short and confident), so the
  default rule is instead: segment < 2.5 s and restricted-LID probability < 0.7 → uncertain_short_segment
  (dev: 70% of garbage rejected, 1.2% of good segments; only 20 garbage examples — reports/voice/confidence-dev.json).
  `--min-confidence` stays available (default 0).
- Shorter segments: soft split at the first pause after 12 s, hard cap 20 s (dev: 8/15 s cost +2.2 WER points;
  20/30 s allowed 18.7 s segments). Fixed a 10 ms overshoot at the cap (test_segments_never_exceed_twenty_seconds).
- Latency, paced 1.0x, final build, 80 held-out utterances (en/es/zh/hi/ta × clean/babble10, CPU shared with other
  sessions): speech end → stored p50 4.6 s, p95 7.4 s, max 10.8 s (latency-heldout-adaptive-product-final.json);
  before: p50 4.2, p95 7.5, max 13.2 s; live test: p90 19.6 s.
- RAM (lens-voice + lens-engine + lens-sherpa child, sampled 200 ms): whisper path ~175 MB; IndicConformer 375-415 MB;
  Dolphin 483-532 MB peak. Whole-system total with agent/observer/app not measured in this run.
- Owner-only capture (lens-voice `--enroll <profile>`, `--speaker-profile <profile>`, `--require-owner`): NeMo
  TitaNet-small speaker embeddings (4 s windows, mean), profile DPAPI-encrypted; segments below the threshold are
  dropped inside lens-voice (never emitted). LibriSpeech test-clean (CC BY 4.0) speakers split by hash: dev 14 owners
  chose 0.46 (FAR 0.4%, FRR 4.8%); held-out 26 owners at 0.46: FAR 1.5%, FRR 5.3% (clean 0.6%/0%, pink 10 dB
  0.6%/0%, babble 10 dB 3.2%/16.0%); FLEURS other-language impostors accepted: 0. Two CAM++ exports separated
  speakers poorly in this runtime and were rejected (speaker-dev-campplus-failed.json). lens-voice peaks ~185-190 MB
  with the speaker model. Not verified: the owner's own voice, cross-language enrolment (enrol in English, speak
  Telugu), children/elderly voices, overlapping speakers within one segment (decision is per segment).
- Tests: tests/test_voice.py 16/16 (adds routing hi/zh, allowed-set LID regression on FLEURS ta/te/hi, noise never
  stored, owner-only emission with an encrypted profile, refusal without a profile, 20 s cap).
- Emotion/expression and spoken replies: NOT IMPLEMENTED; options and costs in reports/voice/emotion-and-speech-feasibility.md.
- 30-minute soak, final build (reports/voice/soak.json): 1945.9 s of English FLEURS sessions streamed at 1.0x with
  the noise changing every block (clean, pink 20/5, fan 20/10, babble 10, white 10) plus 2-minute noise-only
  stretches: exit 0, no overrun, 143 segments, 138 stored / 5 rejected (no_speech_found, repetition_rejected,
  uncertain_short_segment), WER 19.3% (dev and held-out clips mixed — not a tuning set), latency p50 3.4 s,
  p95 4.9 s, max 7.6 s; lens-voice working set ≤ 7 MB with a second-half slope of 14 KB/min (no leak); pair peak
  174 MB; engine idle 8 → 21 MB after 138 stored memories.

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
  - Measured on H0: lens-app time to interactive 2.72–2.78 s from process start (UI ready at 2.1 s). A rerun on
    2026-10-28 (HEAD 2fcc6f0, other sessions' jobs running) took 3.05–4.19 s (UI ready at 2.2 s); app idle 338 MB working set. lens-app idle
    with the hidden window, 7 processes including WebView2: 339 MB working set, 131 MB private. Background agent tree
    23 MB, so app plus agent is about 362 MB, under 800 MB.
  - The app runs only while its window is open. The visible window's RAM, low-end tiers and usability with people are
    not measured.

## Milestone 4 — screen OCR: Telugu, bounded worker RAM, 10 scripts, held-out set (2026-10-27/28) — PARTIAL (Telugu PASS; Arabic/Urdu weak; Bengali/Gujarati have no recogniser)

- Metric (scripts/benchmark_ocr_native.py): page CER on NFC text with ZWNJ/ZWJ removed (invisible, so no recogniser
  can emit them); the unnormalised figure is kept as `page_cer_raw`. Process per request, CPU only, 2 threads, H0 with
  other sessions' CPU jobs running (CPU load 90–100% during most runs, so latencies are upper bounds).
- Sets. Dev (artifacts/ocr-screens/v1, scripts/make_ocr_screens.py): 87 screens = the original 32 (unchanged, sha256
  checked) + fr, pt, de, id, ru, ja, ar, ur, bn, mr, gu × 5 styles; fonts Segoe UI / Yu Gothic UI / Nirmala UI.
  HELD-OUT (artifacts/ocr-screens/heldout-v1, scripts/make_ocr_screens_heldout.py): 89 screens, all 17 languages,
  newly authored text, other fonts (Georgia, Verdana, Calibri, Tahoma, Trebuchet MS, SimSun, Microsoft YaHei Light,
  MS (P)Gothic, Yu Gothic, Times New Roman, Arial, Nirmala Text — none used in dev or training), other layouts (mail
  list, dark notes, cards, heading + body, compact 13 px), new seeds. Never used for tuning, training or rule design;
  its images were only checked for correct rendering before the first evaluation.
- Telugu diagnosis (dev): Nirmala UI draws the ra-vattu (్ర) as a hook left of the consonant; te_PP-OCRv5_mobile_rec
  reads it as "[", "(" or a separate ర, or drops it. Crop padding (+10/20%, −5%) and 2× upscaling do not help
  (8.7% → 8.7–10.9%); te_PP-OCRv3_mobile_rec: 39.8%; the PP-OCRv6 recognisers have no Indic characters.
- Telugu fix: scripts/make_ocr_te_train.py renders 20,495 synthetic lines (programmatic Telugu orthography with
  ra-vattu weighted up, digits, Latin tokens, genuine brackets; 400 pages; Nirmala UI Regular/Semilight/Bold and Noto
  Sans Telugu (OFL, training only); headless Edge over DevTools; crops from the shipped detector's boxes) and
  scripts/train_ocr_te_screen.py fine-tunes only the EncoderWithSVTR neck and CTC head (632k parameters; backbone and
  BatchNorm statistics frozen; ONNX Runtime backbone + Paddle dygraph neck, parity with the export 3.4e-6 before and
  3.6e-6 after) for 1,200 steps (batch 32, AdamW 4e-4 cosine, 9,228 s CPU). Synthetic validation CER 22.8% → 5.1%.
  Output models/Lens--te_PP-OCRv5_mobile_rec_screen (Apache-2.0 derivative: same graph, new constants), pinned under
  `derived` in third_party/ocr-runtime-lock.json (inference.onnx sha256 6d74dea8…). Training text is synthetic
  syllables, not real vocabulary.
  Telugu page CER: dev 8.37% → 1.37% (line accuracy 0.27 → 0.93); **held-out 1.65% — gate ≤ 3% PASS**
  (PaddleOCR-as-published on the same held-out screens: 5.18%).
- Worker memory (scripts/benchmark_ocr_memory.py; `lens-ocr --serve`; Edge-rendered synthetic page at device scale 1.5).
  Before: 2560×1600 held 808 MB after one request and 1,446 MB working set / 2,315 MB private after two (ONNX Runtime
  CPU arena and memory patterns keep every new shape; whole-screen detection). After: arena and memory patterns off;
  detector runs in full-width bands of ≤ 409,600 px (`det_pixels`), each resized on the fly; 16-bit probability map and
  1-byte visited map; at most 2 recognisers loaded per request (LRU) and 1 kept between requests.
  **2560×1600 peak 119 MB, 3840×2160 peak 141 MB, idle 18–36 MB** (target ≤ ~150 MB: PASS on H0); dev/held-out
  per-request peak 111/115 MB. Cost: banded detection is close to, not bit-identical with, a whole-screen run (the
  detector pools globally); on the original dev screens en 0.07 → 0.33% before line merging (one code line split).
- Recognition changes: routing tries the previous screen's recogniser first, then general, then the rest (most recent
  success first; full probing stops after 2 lines no recogniser reads confidently); Arabic-script output is converted
  from visual to logical order keeping left-to-right runs ("48,250", "4:30", "B12") and mirroring brackets
  (PaddleOCR's pred_reverse splits numbers at "," and ":"; Arabic dev 6.7% → 3.7%); same-row segments the detector
  split at wide gaps are merged (gap ≤ 2 line heights; right-to-left order for Arabic script; Urdu dev 14.2% → 10.6%).
- Recognisers (Apache-2.0, fetched at pinned revisions with LFS sha256 checks by scripts/fetch_ocr_models.py, exported
  with the pinned paddle2onnx 2.1.0): general PP-OCRv6_tiny_rec (en, es, fr, pt, de, id, zh), PP-OCRv5_mobile_rec (ja),
  arabic_PP-OCRv5_mobile_rec (ar, ur), cyrillic_PP-OCRv5_mobile_rec (ru), devanagari_PP-OCRv5_mobile_rec (hi, mr),
  ta_PP-OCRv5_mobile_rec, the Lens Telugu fine-tune. **No PaddleOCR recogniser exists for Bengali or Gujarati script**
  (Hugging Face PaddlePaddle catalogue, 2026-10-27). Urdu renders in Naskh: no Nastaliq font is installed.
- Page CER, auto routing (dev: reports/ocr-screens/ocr-native-dev-v5-auto-20261027T160513Z.json; held-out:
  ocr-native-heldout-v5-auto-20261027T205613Z.json). PaddleOCR-as-published = scripts/ocr_reference.py (official DB
  post-processing with quad crops, upstream models, oracle routing, pred_reverse; ocr-reference-heldout-v5-oracle-*):

  | Script / language | Lens dev | Lens held-out | PaddleOCR-as-published held-out |
  |---|---:|---:|---:|
  | Latin en / es / fr / pt / de / id | 0.13 / 0.07 / 0.63 / 0.12 / 0.26 / 0.06% | 0.00 / 0.11 / 0.29 / 0.20 / 0.16 / 0.11% | 0.18 / 0.57 / 0.44 / 0.30 / 0.37 / 0.49% |
  | Han zh | 0.21% | 0.00% | 0.34% |
  | Japanese ja | 0.75% | 0.76% | 1.08% |
  | Cyrillic ru | 0.34% | 3.05% (oracle routing 0.00%) | 0.00% |
  | Devanagari hi / mr | 2.65 / 4.20% | 2.35 / 5.37% (mr oracle 3.69%) | 2.35 / 2.98% |
  | Tamil ta | 0.21% | 0.71% | 0.91% |
  | Telugu te | 1.37% | **1.65%** | 5.18% |
  | Arabic ar / Urdu ur | 3.67 / 10.6% | **21.2 / 30.1%** (oracle 19.9 / 28.5%) | 15.9 / 30.5% |
  | Bengali bn / Gujarati gu (no recogniser) | 84.7 / 80.1% | 88.1 / 77.9% | 83.6 / 79.2% |

  Losses: Arabic and Urdu do not generalise to the held-out fonts (Tahoma, Times New Roman, Arial), and Lens is worse
  than PaddleOCR-as-published on held-out Arabic (21.2 vs 15.9%). Under held-out fonts the correct recogniser's
  confidence can fall below 0.9 and routing picks a wrong script (ru 3.05% vs 0.00% with oracle routing; mr 5.4 vs
  3.7%). Dev routing equals oracle on every screen, so these were found only on held-out and are NOT fixed here (no
  tuning on held-out). Bengali and Gujarati fail for want of any recogniser.
- Strongest openly licensed CPU recognisers on the same held-out images (oracle routing, Lens worker; dev in the
  reports ocr-native-*-oracle-PP-OCRv*): PP-OCRv6_small_rec en/zh/es/fr/pt/de/id 0.00/0.17/0.00/0.05/0.10/0.00/0.05% —
  slightly better than the shipped tiny model at the same 102 MB peak, but region compute p50 326 ms vs 86 ms (dev),
  over the 150 ms target, so tiny stays; PP-OCRv6_medium_rec similar CER at 201 MB peak; PP-OCRv5_server_rec 13–19% on
  Latin (garbles screen crops in this pipeline) at 250 MB peak. The PaddleOCR-as-published Python pipeline peaks at
  472–519 MB vs the Lens worker's 115 MB. Tesseract 5.4 (Apache-2.0; tessdata_best covers Bengali and Gujarati) was
  downloaded, but running the downloaded binary was refused by this environment's permission policy, and EasyOCR was
  not attempted for the same reason: both NOT MEASURED, owner approval needed.
- Latency (dev, process per request, compute inside the worker, contended CPU): Lens region p50 86 ms / p95 275 ms on
  the Latin/Han/Japanese subset; full 87-screen auto run region p50 392 ms at 100% CPU load. Serve-mode warm band
  requests (scripts/benchmark_ocr_latency.py, original 6 languages, CPU 96%): p50 260 ms, p95 900 ms. A quiet
  re-measurement is needed before the < 150 ms median gate can be called.
- Tests: tests/test_native_ocr.py 14/14 OK (new: a 2560×1600 screen keeps the serve worker < 200 MB peak and < 100 MB
  after requests with all 24 rows read; Arabic numbers keep left-to-right order; split segments merge; the Telugu
  fine-tune is pinned; the Nirmala ra-vattu is read as a conjunct; metric normalisation).
- Not yet: Bengali and Gujarati recognisers (no PaddleOCR model — fine-tune a new CTC head on Dakshina-vocabulary
  renders, or Tesseract with owner approval); Arabic-script robustness to unseen fonts; script-consistency routing
  validated on a fresh font set; real-vocabulary (Dakshina) training text; the agent's default OCR config and
  packaging of the new recognisers (engine/agent, scripts/package_lens.py); a quiet latency re-measurement.

## Observer real-screen fixes (2026-10-28) — PARTIAL (synthetic verification; second real-screen run pending owner consent)

Fixes for the failures of the owner-consented real-screen run (reports/perf/real-screen-20261027T041404Z.json, aggregate
numbers only): whole scroll-back captured (median 15,528 chars), the same transcript re-stored every ~4 s, 179% CPU,
every observation `und-Latn`. All changes are in engine/observer/; the engine `add` contract is unchanged (new fields
travel in `metadata`).
- Visible text only (uia_text.cpp): an element is read only if its UIA bounding rectangle intersects the visible area
  (window ∩ virtual screen, narrowed by every native child window and scroll container); subtrees fully outside are
  not walked. Edit/document TextPattern contributes `GetVisibleRanges` only (never `DocumentRange`) and its subtree is not
  walked again. Native multi-line Edit controls without visible ranges are read line by line from the first visible line
  to the client bottom (EM_GETFIRSTVISIBLELINE / EM_POSFROMCHAR / EM_GETLINE, 200 ms timeouts) — found because the Win32
  proxy truncates Value at 4,096 characters and exposes no visible ranges. Stored text capped at 4,000 bytes per
  observation (`metadata.truncated` records a cut). A walk stopped by the time budget is retried with a doubled budget
  (300 ms → 2 s); after three in a row the partial text is used and marked truncated.
- Settle/debounce: changed content is stored once it has been unchanged for `settle_ms` (2 s), or after `max_settle_ms`
  (12 s) at the latest; each consecutive forced capture of the same window doubles that bound (up to 8×) and slows the
  settle polling.
- Delta storage (capture_delta.hpp): per window a bounded fingerprint of 64-bit line hashes (no text). The first capture,
  a document (title) change and every 10 minutes give a full `snapshot`; otherwise only lines not yet stored are
  emitted as a `delta` with `window_key`, `previous_capture` and `base_snapshot` links. Not stored: deltas under 4
  characters, and re-renders with ≥ 90% line overlap and < 24 new characters (clock ticks, counters).
- Language identification (language_id.hpp, lens-lid-ngram-v1): script detection for every §1a language (kana share
  ja/zh, Urdu letters ur/ar, Ukrainian letters uk/ru; danda and native digits are not letters), plus a character
  1–4-gram + word Naive Bayes for Latin script (en, es, fr, pt, de, id, hi-Latn, ta-Latn, te-Latn) and Devanagari
  (hi, mr). The tables (lid_model_data.hpp, 288 KB, generated by scripts/train_observer_lid.py, report
  reports/observer/lid-train-20261027T205602Z.json, sha256 7f68cb8f…20be) are trained on balanced text (54k
  characters per Latin class, 62k per Devanagari class): Belebele authored questions/answers (CC BY-SA 4.0; FLORES
  passages never read) and Belebele native questions transliterated with Aksharantar pairs (CC-BY 4.0 / CC0; pairs
  sourced from Dakshina excluded). The table is a CC BY-SA 4.0 derivative (stated in the header). Code-switching:
  a second script with ≥ 20% of the words, or English plus another Latin-script language each winning ≥ 25% of
  three-word windows → `mixed` with both components. `language_detail` carries script, confidence and method.
- CPU: below-normal priority (the OCR worker inherits it); polling stretched so the observer's own CPU per check stays
  under ~5% duty (thread CPU time, not UIA wall time, which is mostly waiting on the target app); a throttle doubles
  every interval (up to 16×) while the observer's CPU over 5 s exceeds `cpu_budget_percent` (5% of one core).
- Tests (tests/test_observer.py, 27 tests, invisible synthetic window only; test app extended with `fill`/`append`/
  `offscreen`/`panel` commands for scroll-back, streaming, off-screen and clipped elements): 26/26 OK in one full run
  plus the new throttle test OK on its own — of 400 lines in a scrolled edit box only the ~10 visible ones are
  captured; off-screen and panel-clipped labels not captured; cap + truncation flag; streaming text stored once after
  it settles; never-settling text captured within the bound with back-off (forced_captures ≥ 1, ≤ 4 records in 12 s);
  delta holds only the new line and links to the snapshot; near-duplicate re-render not stored; title change →
  snapshot; language labels es/en and `--identify-language` over 20 languages, mixed text and und; throttle engages
  under a tiny budget; observer CPU on a streaming window 0.9–1.5% of one core (budget < 10%). Earlier runs were flaky
  on this machine (CPU 100%, RAM 96% from other jobs: observer start up to 7 s, single UIA calls up to 3.7 s); positive
  waits were made condition-based (up to 25–40 s) and three test expectations were corrected where the observer was
  right (lines scrolled out of view are no longer captured).
- Language-identification benchmark (scripts/benchmark_observer_lid.py; held-out test split, never used for tuning;
  reports/observer/lid-benchmark-test-20261027T211026Z.json): 7,536 strings, balanced per language and bucket —
  FLEURS test transcriptions (CC-BY-4.0) for the 17 §1a languages, Dakshina romanized test sentences (CC BY-SA 4.0)
  for hi/ta/te, synthetic English + Indic code-switched concatenations; buckets short (5–40 characters, screen-like),
  sentence, paragraph. Reference: fastText lid.176.ftz (938 KB, CC BY-SA 3.0, evaluation only, isolated venv
  .tools/lid-eval), same strings.

  | Set (accuracy) | Lens lens-lid-ngram-v1 | fastText lid.176 |
  |---|---|---|
  | 17 languages, all buckets | 99.1% | 98.4% |
  | 17 languages, short 5–40 chars | 98.0% | 95.6% |
  | 17 languages, sentence / paragraph | 99.5% / 99.9% | 99.5% / 100% |
  | romanized hi/ta/te (exact tag) | 92.6% (short 87.3%) | 0% (no such labels) |
  | code-switched, both components named | 62.7% | 0% (single label) |
  | code-switched, either component | 97.0% | 93.0% |

  Weakest: short es (93.3%, confused with pt), en short (94.7%), te-Latn (short 84.7%; confused with hi-Latn/id),
  en+ta-Latn / en+te-Latn mixing (48–51%). Throughput 0.09 ms per string including process start and JSON I/O
  (fastText 0.12 ms, Python binding). Development history (dev split only): hand-written lexicons lens-lid-rules-v1
  reached 95.5% (17 languages), 33.8% (romanized) and 22.5% (code-switch) on dev
  (lid-benchmark-dev-20261027T204823Z.json), so they were replaced by the n-gram tables; the code-switch thresholds
  were then chosen on dev (lid-benchmark-dev-20261027T210936Z.json). Caveats: FLEURS sentences are read-speech
  transcripts of formal text, not UI chrome; romanized ta/te training text is machine-transliterated; the code-switch
  set is synthetic; stronger open identifiers (GlotLID, OpenLID) were not compared.
- Synthetic sustained run, 30 minutes, after the fixes (scripts/sustained_run.py --snapshot: binaries copied to a temp
  folder so other work's builds are not blocked; invisible windows changing every 3–8 s, alternating 5-minute UIA and
  OCR phases, recall every 30 s; other sessions' jobs loading the laptop):
  - reports/perf/sustained-20261027T215134Z.json (final build): 0 crashes, 346 samples; whole-tree peak 401 MB working
    set / 366 MB private (≤ 800 MB: PASS; per process peak engine 323, OCR worker 49, observer 23.5, agent 11 MB);
    mean CPU 8.6% of one core (observer 0.97%, OCR worker 2.47%, engine 4.94%, agent 0.26%; UIA phases 6.3%, OCR phases
    10.8%); 57/57 recalls OK, p50 294 ms, p95 3.5 s; 233 memories stored, 127 embedded at the end.
  - reports/perf/sustained-20261027T211445Z.json (before the OCR worker's CPU counted towards the observer's budget):
    peak 401 / 364 MB, mean CPU 12.0% of one core (OCR worker 4.75%).
  - Measurement fix: sustained_run.py previously read the tree's cumulative CPU, which resets whenever the agent
    restarts at a phase switch, so the 1.7% reported for reports/perf/sustained-20261027T000528Z.json (Milestone 15)
    covers only the last phase and is an undercount. CPU is now accumulated per process across restarts
    (real_screen_run.py likewise, so exiting OCR workers keep their CPU).
  - Open: idle after load shows 23 MB working set but 318 MB private (the 2026-10-27 run: 21 MB private). The idle
    sample had no per-process private bytes, so the owner of the commit is not identified; both scripts now record
    private bytes per process. Engine-side work (embedding, consolidation) is the largest CPU share and is outside the
    observer.
- Not yet: a second owner-consented real-screen run (the decisive test of these fixes on real applications, incl. the
  Electron chat app); real-application UIA coverage beyond the synthetic window; low-end hardware tiers.

## Memory lifecycle L9, user memory §12 and history import §11 — schema v9 (2026-10-28) — PARTIAL (synthetic data; 100k import measured under contention)

- Built: engine/lifecycle.{hpp,cpp}, engine/user_memory.{hpp,cpp}, recovery in engine/store.cpp, DPAPI helpers in
  adapters/windows/key_store.*. Schema v9 adds `pins`, `recall_feedback` (keyed by a SHA-256 of the normalised question;
  question text is never stored), `user_facts`, `fact_status`, `retention_rules`; migration is CREATE IF NOT EXISTS only.
- Backup / restore (`backup`, `restore`): a SQLCipher export written page-encrypted (no plaintext copy on disk) with a
  random key DPAPI-wrapped beside it, or the user's passphrase (≥ 12 characters, SQLCipher's KDF; passphrases only in JSON
  on stdin). A manifest records format, schema, key mode, source count, size and SHA-256 (no content). Before anything is
  written, restore checks the manifest hash, SQLCipher's per-page HMAC (`cipher_integrity_check`), SQLite's
  `integrity_check` and the source count. It then builds the copy as `<target>.restoring`, verifies it the same way, and
  moves the database into place, then its key. An engine start completes a key move that a crash interrupted. Refused:
  tampered file (`backup_integrity_failed`), wrong passphrase (`backup_key_invalid`), existing or relative target; no
  files are left behind. DPAPI-mode backups restore only for the same Windows user; use passphrase mode to move machines.
- Key rotation (`rotate_key`): export under a new key to `<db>.next` + `<db>.key.next`, verify, then atomic
  write-through swaps (database, then key). At start, the engine resolves an interrupted rotation: exactly one key opens
  the file, and leftovers are removed.
- Deletion (`delete` and `delete_sources` with scope all | source_ids | application | kind | start/end | import):
  everything derived from the deleted sources goes too: vectors, FTS terms, mentions, facts, projects, episode bounds,
  pins and feedback. Derived names and keys are refreshed, the FTS index is merged so no deleted term survives in old
  segments, and the WAL is truncated (`secure_delete` zeroes freed pages). Delete-all also removes user corrections and
  the trained zstd dictionaries and compacts (VACUUM).
  NOT covered: a partial delete leaves trained dictionaries, which may contain fragments of the deleted text, in place.
- Export (`export`, consent required): JSONL `lens-history/1` with full provenance; it re-imports through the LensJsonl
  importer, and the round trip is tested. The file is plaintext by the user's choice and the response says so.
- Retention (`retention_set/list/remove`): rules by kind and/or application with a maximum age (1–36,500 days), applied
  at the start of `consolidate` by the same purge; pinned sources never expire.
- Corrections (`correct_fact`: correct | reject | confirm): the original derived fact stays with its sources, marked
  `superseded` or `rejected`. The correction is a user fact (`status: user_stated`) with provenance
  `{kind: user_correction, supersedes, supersedes_sources}`. A corrected date must be a date.
  L6 latest vs superseded: among deadline/meeting/amount facts about one subject, the most recently evidenced is
  `current` and the others carry `superseded_by_later`; `facts` takes `current_only`. Evaluated within the returned set.
- Pins (`pin/unpin/pins`) and relevance feedback (`feedback`): recall orders positive feedback for the same
  question first, then pinned sources, then the rest, then negative feedback (`user_signals`, default on; results carry
  `pinned` and `feedback`).
- History import (scripts/import-history.ps1, PowerShell 7):
  - New formats: Mbox (streamed, mboxo/mboxrd), Eml, Ics (TZID/UTC/all-day; floating times need -SourceTimeZone;
    RRULE recorded, not expanded), Vcf (2.1 QP, 3.0; REV or import time), BrowserHistory (Google Takeout JSON or CSV;
    query strings, fragments and user-info are removed from URLs) and Pdf (literal-string text operators,
    FlateDecode; scanned or CID/hex-font PDFs are refused as `pdf_text_unavailable`, not OCR'd).
  - Options: `-Preview` (counts, skips by reason, in-file duplicates, time range, 3-item sample; writes nothing),
    `-Progress` (progress lines before the result), `-CancelPath` (checked at every chunk; rolls back), `-EnginePath`
    (installed builds).
  - One engine transaction per import. Parse errors, cancellation or a rejected record roll everything back; the
    result's `export_sha256` drives `imports` / `delete_sources {scope:{import}}`.
  - Diagnostics carry error codes only: no paths, no content.
  - MIME/mbox parsing is compiled in memory with Add-Type; no file is written.
- Tests (synthetic, temp dirs):
  - tests/test_lifecycle.py, 12 tests: DPAPI and passphrase backup/restore, tamper and wrong key, crash at both restore
    steps followed by integrity-checked reopen, export round trip, scoped and delete-all deletion with sentinel scans,
    retention with pin exemption, rotation and a crash at both rotation steps, corrections, latest-vs-superseded,
    pins/feedback, and 300 hostile requests with no stray files.
  - Sentinel scans: before deletion, a decrypted logical copy of every table (FTS shadow tables included) contains the
    sentinel (positive control). After deletion, neither that copy nor the raw DB, WAL and SHM bytes (UTF-8 and
    UTF-16) contain it, and the WAL is empty.
  - tests/test_history_import.py, 19 tests: 12 existing plus 7 new ones covering MIME (QP, base64, encoded words,
    ISO-8859-1 HTML), dedup and skips, preview, ICS zones, vCard, browser-history token removal, PDF text and refusal,
    and a mid-stream cancel after a chunk was already written inside the open transaction (nothing is kept),
    followed by delete-by-import.
  - Also passing: test_unicode_privacy 6, test_memory_layers, test_memory_v2, test_episodes, test_text_compression,
    test_security.
- Import throughput and RAM (H0, other sessions' model evaluation, OCR benchmark and tests running throughout;
  scripts/benchmark_history_import.py, synthetic mailbox with plain/QP/base64/HTML parts in six languages):
  - 10,000 e-mails with the first PowerShell parser: 37.5 then 29.3 e-mails/s; peak tree 172–179 MB working set /
    86–91 MB private (pwsh ~155 MB, engine ~16 MB); 2.9 KB per e-mail in the database; delete-by-import of 10,000 in
    5.3–8.0 s.
  - Profiling showed parsing at ~25 ms per message, so MIME/mbox parsing moved to the in-memory C# helper: 2,000
    e-mails preview in 12 s (6 ms/message) and import in 23 s (≈ 88 e-mails/s).
  - 100,000 e-mails: 1,301.6 s (21.7 min, 76.8 e-mails/s); all 100,000 imported in one transaction across 782 chunks with 782
    progress lines; peak tree 240.3 MB working set / 153.1 MB private (pwsh 218.5 MB, engine 16.6 MB, under the 800 MB
    ceiling); 236.5 MB mailbox became a 287.3 MB database (2.87 KB per e-mail); delete-by-import of all 100,000 in
    130.3 s. Report: reports/history-import/ (mbox-100000-*.json). Measured under contention, so idle-machine and
    low-end-tier throughput is NOT VERIFIED. E-mail dates, headers and MIME follow the English RFC 5322 formats
    first (spec §1a); other date layouts are skipped and counted, never guessed.
- Read-only ops for the mesh: `imports`, `pins`, `retention_list`.
- Not done: restoring DPAPI backups on another account, real mail archives (only synthetic), attachment text, ICS
  recurrence expansion, cross-file e-mail dedup (same file re-import is deduplicated), dictionary re-training after
  partial deletes, and an agent-side import lock. The desktop app keeps its own C++ parser until it can run this script
  (needs PowerShell 7 in the package).

## Correction and fix: compression dictionaries after partial deletion (2026-10-28) — PASS (synthetic)

- Defect confirmed before the fix (tests/test_lifecycle.py `test_partial_delete_retires_trained_dictionaries`, run
  against the previous engine): a dictionary trained after 130 synthetic sources contained the sentinel text
  (positive control read from a decrypted logical copy), and after deleting only the sentinel sources the dictionary
  survived (`text_dictionaries` 1, expected 0). The "NOT covered" item in the schema v9 entry above was a real leak path.
  Exposure was limited to direct engine use: lens-agent refuses `train_text_dictionary` (tests/test_agent.py).
- Fix (engine/text_codec.cpp `retire_dictionaries`, called by `purge_sources` for every delete that removed rows,
  including retention): inside the deleting transaction, every dictionary-coded row is re-encoded as a plain zstd frame
  (or plain text when that no longer saves 15%) in batches of 256, each new encoding checked to decode to the identical
  text, then all dictionaries are deleted. The immutability trigger is dropped and recreated within that transaction
  for this storage-only rewrite. New rows stop using dictionaries at once; decoders stay loaded so a rollback leaves
  every row readable.
- After the fix: no dictionary remains, the sentinel is absent from the decrypted copy and from the raw DB/WAL/SHM
  bytes, all 100 surviving sources export byte-exact, and a source written after the delete decodes in a new process.
- Regression: full suite 252 tests OK, 1 skipped (test_android_link: no device), 2026-10-28, run from PowerShell.

## Idle private commit re-measured (2026-10-28) — the 318 MB idle sample does not reproduce

- scripts/sustained_run.py now records private bytes per process. 30-minute synthetic run
  (reports/perf/sustained-20261028T061621Z.json, --snapshot, invisible windows, UIA/OCR phases, recall every 30 s):
  0 crashes; peak 431 MB working set / 380 MB private (under the 500 MB working target and the 800 MB ceiling);
  mean CPU 6.8% of one core; recall p50 219 ms, p95 2.52 s. Idle after load: 53.9 MB working set / 20.2 MB private
  (agent 2.3, engine 12.3, observer 5.6 MB private). A 6-minute run gave 51.2 / 16.8 MB
  (reports/perf/sustained-20261028T060450Z.json). The earlier 318–333 MB idle private readings came from runs without
  per-process private accounting and are superseded; no idle commit owner exists to fix.

## English speech input and spoken replies (2026-10-29) — PARTIAL (functional on H0; installed-footprint gate FAIL)

- Input: NVIDIA Canary-180M-flash (CC-BY-4.0; sherpa-onnx INT8 export, encoder 132.7 MB + decoder 74.4 MB) routed for
  en/es/de/fr through lens-sherpa (`model_type` canary, punctuation and capitalisation on); whisper base still identifies
  the language first. Published Open ASR leaderboard WER (model card, not measured here): LibriSpeech clean/other
  1.87/3.83%, AMI 14.86%, Earnings-22 13.33%. Fetched at pinned revisions with LFS sha256 checks
  (scripts/fetch_speech_models.py, third_party/model-lock.json). Tests: tests/test_voice.py 18/18 OK (new: English routes
  to Canary and the JFK clip comes back capitalised and punctuated; Canary refuses languages it cannot transcribe).
  Not yet measured: WER on LibriSpeech/FLEURS held-out audio, latency and RAM of the routed worker, live microphone.
- Output: lens-tts (engine/tts_main.cpp, engine/g2p_en.cpp) = misaki US lexicons (Apache-2.0, 90,201 gold + 93,361
  silver entries; replaces espeak-ng, GPL-3.0) with numbers, ordinals, years, times, money, percentages, "dot" in
  domains, CamelCase/suffix/compound decomposition, then Kokoro-82M v1.0 (Apache-2.0) through the pinned ONNX Runtime
  1.24.4, 24 kHz WAV. One worker serves many requests (model loaded once); lens-agent `speak` starts it on first use,
  verifies every file's sha256 first and stops it after 60 s idle. App: "Listen" on English evidence cards reads
  "<app>, <when>. <quote>" (no generated text); CSP allows `media-src blob:` only.
- Model choice (G2P from this pipeline, 4 threads, CPU 26% busy from other apps; intelligibility = Canary transcription
  of the synthetic speech): upstream dynamic INT8 export 88 MB, real-time factor 1.52 (ConvInteger kernels), correct;
  FP32 310 MB, RTF 0.53, correct, lens-tts peak 620 MB (554 MB with sentence packing, 521 MB without the CPU arena);
  static QDQ INT8 of everything 129 MB, RTF 0.32, garbled ("in Chrome" -> "and pronounced"); **Lens mixed export
  (scripts/export_kokoro.py: static QDQ INT8 except the iSTFTNet generator, FP32) 178 MB, RTF 0.51, 0/25 word errors on
  2 sentences; lens-tts peak 394 MB working set** (under the 500 MB working target). Chunks pack sentences up to 200
  phonemes (hard cap 500 of Kokoro's 512).
- Tests: tests/test_tts.py 4/4 OK (number/symbol reading, worker reuse with model_load < 5 ms on the second request and
  recovery after bad requests, long reply chunked with peak < 500 MB, Canary hears "document … research paper … chrome …
  yesterday afternoon"); tests/test_agent.py AgentSpeech OK (audio over the pipe, unknown voice refused, worker exits
  when idle); tests/test_app.py `test_listen_speaks_the_evidence_locally` OK (headless Edge, autoplay allowed by flag
  because a scripted click is not a user gesture).
- Package: scripts/package_lens.py now ships lens-sherpa.exe, lens-tts.exe, the sherpa-onnx runtime DLLs, Canary,
  Kokoro (mixed) and misaki. **Installed footprint 861,742,126 bytes: FAIL against the 500,000,000-byte gate**
  (docs/acceptance-gates.md); tests/test_installer.py footprint test fails accordingly, the other 3 installer tests pass.
- Not done: G2P has no part-of-speech tagging (heteronyms use DEFAULT), unknown words fall back to spelling, English only;
  real-time factor on low-end CPUs, first-audio latency and listening (MOS) tests not measured.

## Lens-Core answerability head v2 — teacher distillation sweep (2026-10-28/29) — v2c selected, NOT ADOPTED (gate not run)

- Data (lens_model/data/build_distill.py): 26,645-pair language-balanced pool (en 27%), bge-reranker-v2-m3 teacher
  scores on the RTX 5060 (bf16 off: FP32 inference; content-keyed cache). Defect found and fixed before training: the
  undamped Platt fit diverged (a = 8.1e7), so every p_teacher was exactly 0 or 1; the fit now uses Platt's smoothed
  targets, standardized scores and backtracking Newton steps (a = 0.307, b = −0.099, log-loss 0.434; pairs with
  |gold − teacher| > 0.9: 5,554 → 380), and the build refuses a degenerate calibration.
- The teacher measures topical relevance, not answer presence: wrong side of 0.5 on 33% of supported windows, 31% of
  substitution near-misses and 41% of unanswerable near-misses, but ≤ 3% on other-article and long negatives.
- Training (GPU, bf16 autocast, FP32 master weights; ~2.5 min per run), deployment form = INT8 ONNX on the CPU
  execution provider only. CPU INT8 results on the comparison sets (reports/lens-model/benchmark/lens-v2*-int8.json):

  | run | init | targets | Lens harness AUC | 17-language macro AUC | Belebele global | SQuAD 2.0 dev |
  |---|---|---|---:|---:|---:|---:|
  | v1 (previous) | — | — | 0.825 | 0.783 | 0.665 | 0.931 |
  | v2a | mmarco | soft, MarginMSE 0.1 | 0.854 | 0.923 | 0.960 | 0.807 |
  | v2b | mmarco | soft | 0.849 | 0.927 | 0.931 | 0.862 |
  | **v2c** | v1 | soft, MarginMSE 0.1 | **0.871** | **0.932** | **0.966** | 0.858 |
  | bge-reranker-v2-m3 (teacher, 1.79 GB) | — | — | 0.923 | 0.924 | 0.986 | 0.788 |

  v2c: 13 ms p50 per pair, benchmark process peak 490 MB working set. Ablations v2d (gold labels on answer-containment
  kinds) and v2e (gold labels only) trained and scored only on the training-time held-out sets (dev 0.898/0.907 vs v2b
  0.873); their CPU INT8 runs were not made. Latency numbers of v2a–v2c were taken while GPU training ran (upper bounds).
- Not done: the M2 answerability gate (correct answered at 5% false answers, 614 questions), engine integration.

## Budget revision (founder, 2026-10-29): 500 MB RAM ceiling, 1 GB storage, every OS, wearables later

- RAM ceiling for the complete Lens system is now 500,000,000 bytes (was 800,000,000), working set and private
  commit; installed storage may reach 1,000,000,000 bytes; Lens aims at every major OS; wearables are deferred.
- Existing H0 evidence against the new ceiling (no new measurement): 30-minute synthetic run peak 431 MB working set /
  380 MB private — within; serial model workers 440 MB private — within; concurrent workers 879 MB / 995 MB — over;
  2026-10-27 real-screen run 905 MB private — over; lens-tts alone 394 MB (plus the 54 MB idle tree ≈ 448 MB) —
  within only while no other heavy model is loaded. The installed package (861.7 MB) is within the storage budget.
- Consequence: heavy models (OCR, ASR, TTS, retrieval, verifier) must never be resident together; a whole-tree
  resource governor is required before any 500 MB claim. Code, gates and tests now use 500 MB (agent diagnostics
  ceiling, app meter, scripts/profile_combined.py, sustained/real-screen runs, tests/test_app.py) and 1 GB for the
  package (tests/test_installer.py).

## Resource governor v1: spoken replies run alone (2026-10-29) — PASS (functional, H0)

- lens-agent keeps the Kokoro worker (lens-tts, ~394 MB) apart from every other heavy model: before it starts, the
  engine unloads its retrieval models (`unload_models`) and the observer receives `hold_ocr` (its OCR worker exits,
  OCR-only windows are deferred and counted as `ocr_deferred`, UI Automation capture continues); any engine request
  that loads a model (recall, search, retrieve_context, index, ingest_audio) stops the TTS worker first, which sends
  `release_ocr`. An observer started while a reply is loaded starts held.
- Tests: tests/test_agent.py `test_governor_keeps_speech_and_retrieval_models_apart` (engine `models_loaded` false after
  `speak`, lens-tts gone after the next recall), tests/test_observer.py `test_ocr_hold_frees_the_worker_and_defers_ocr_until_release`
  (no OCR worker and no OCR record while held, the deferred change is captured after release); test_agent 5/5,
  test_observer 28/28 OK.
- Not covered: the engine's retrieval models (peak 323 MB on H0) and the OCR worker (≤ 141 MB at 4K) may still be
  resident together (≈ 518 MB with the idle tree in the worst case) — to be removed by the shared Lens-Core trunk or a
  second governor rule; whole-tree 500 MB not yet re-measured with the governor.

## English hard-screen OCR: dev split and row assembly (2026-10-29) — dev only (held-out not yet run)

- Set: scripts/make_ocr_screens_en_hard.py rendered for the first time (dev 25 screens / 411 lines; held-out 25 screens,
  untouched): 9–11 px settings panes, code editors (gutter, syntax colours, dark/light), shell and PowerShell terminals,
  browser pages, PDF-like pages with 9 px footnotes, tables, chat, mail lists; device scales 1–2. Two ground-truth
  defects fixed before any evaluation: rows with nested coloured spans were rejected as wrapped (client rects counted
  instead of line tops), and the tab bar drew "module.pyx" while the truth said "module.py x" (no gap).
- Dev, oracle route, CPU (page CER on NFC text, whitespace collapsed; reports/ocr-screens/ocr-native-en-hard-dev-*):

  | configuration | page CER | line accuracy | full-screen compute p50 | worker peak |
  |---|---:|---:|---:|---:|
  | shipped: PP-OCRv5 mobile det + PP-OCRv6 tiny rec | 4.35% | 0.54 | 1.6 s | 118 MB |
  | + PP-OCRv6 small rec | 3.93% | 0.55 | 3.3 s | 118 MB |
  | + PP-OCRv6 medium rec | 4.22% | 0.55 | 9.8 s | 210 MB |
  | PP-OCRv5 server det (PaddleOCR's default) + tiny rec | 3.81% | 0.57 | 7.5 s | 374 MB |
  | PP-OCRv5 server det + medium rec | 3.53% | 0.58 | 17.0 s | 373 MB |
  | **shipped models + Lens row assembly** | **2.17%** | **0.89** | 1.6 s | 118 MB |

- Row assembly (engine/ocr_main.cpp): segments farther apart than two line heights now join when they form a row of a
  table, form or list (vertical centres within 20% of the text height, heights within 60% — unclip makes short words'
  boxes taller), but never two segments each wider than 35% of the image (side-by-side text columns). The first
  version (equal heights, ≥ 80% overlap) gave 2.47% / 0.84; settings values like "On" stayed separate.
- Not helpful on dev: detector thresholds (0.2/0.4–0.6: 2.47–2.49%), unclip 2.0 (3.23%), whole-image upscaling before
  detection (×1.5 3.01%, ×2 3.98% vs 3.16% on the small-text/code/terminal/table/mail subset).
- 17-language dev set (auto route): identical page CER and line accuracy for every language before and after the
  change; tests/test_native_ocr.py 14/14 OK.
- Remaining dev errors are recognition: monospace `l`/`1`, dash runs (`-rw-r--r--` -> `-rw-r- -r-`), `PS` -> `P5`, case
  (`csv` -> `CSV`), `%` -> `%6`, spaces inside code (`row[ "amount"]`), terminal progress-dot rows not detected.

## Resource governor v2: retrieval models and the OCR worker never overlap (2026-10-30) — PASS (functional, H0)

- Closes the gap left by v1 (retrieval models up to 323 MB and the OCR worker up to 141 MB resident together, ≈ 518 MB
  with the idle tree). lens-agent now keeps one OCR hold with reasons: "speech" while lens-tts runs, "retrieval" from
  the first model-loading engine request (recall, search, retrieve_context, index, ingest_audio, transcribe) until the
  agent itself unloads the models after `retrieval_idle_seconds` (config, default 30) without such a request. The
  observer gets `hold_ocr` on the first reason and `release_ocr` when none is left (OCR-only windows are deferred
  meanwhile, UI Automation capture continues). One lock orders an unload against a new request, so OCR is never
  released while a request is loading models. `diagnostics` reports `ocr_hold`.
- Tests: tests/test_agent.py — the governor test now also checks `ocr_hold` (["retrieval"] after indexing, ["speech"]
  while speaking, ["retrieval"] after the next recall); new `test_governor_releases_ocr_after_retrieval_idle` (with a
  2 s timer: hold released, and only after the models were unloaded). test_agent 7/7, test_observer 28/28,
  test_native_ocr 14/14 OK.
- Speech models too: the Canary worker (lens-sherpa) peaks at ~404 MB working set on H0 (scripts/benchmark_asr_english.py
  trial) and whisper base at ~175 MB, so lens-engine now releases its retrieval models before every `transcribe` and
  `ingest_audio` request (engine/main.cpp; whisper was already freed before a routed model loads). tests/test_agent.py
  `test_spoken_question_is_transcribed_and_not_stored` checks `models_loaded` false after a spoken question
  (test_agent 7/7, test_voice 19/19 OK).
- Cost: an OCR-only window changed within 30 s of a question is read up to 30 s later; a question more than 30 s after
  the previous one reloads the retrieval models.
- Whole tree re-measured with v2 (scripts/sustained_run.py --minutes 30 --snapshot, H0, synthetic invisible windows,
  UIA + OCR paths, a recall every 30 s): **peak 375 MB working set / 337 MB private** (previous 30-minute runs 431/380
  and 474/425 MB), 0 crashes, 58/58 recalls ok (p50 211 ms, p95 2.5 s), idle after load: agent 11, engine 25,
  observer 22 MB working set (reports/perf/sustained-20261030T043959Z.json). Within 500 MB on H0; low-end tiers still
  NOT VERIFIED.

## Voice questions: speech in -> recall -> speech out (2026-10-29) — PASS (functional, H0; no live microphone)

- App: a Speak button beside Ask records from the default microphone (getUserMedia; WebView2's own permission prompt),
  stops on a second click or after 15 s, resamples to 16 kHz 16-bit WAV in the page and sends it to the agent's new
  `transcribe` op (≤ 1.4 MB base64 ≈ 30 s). The transcript fills the question box and is asked like typed text; when
  the question came by voice, the first English evidence card is read aloud (`speak`).
- Agent `transcribe` -> engine `transcribe` (new op): the same whisper language identification and routes as voice
  capture (engine/asr_routes.hpp, now shared by lens-voice and lens-agent; English -> Canary-180M-flash), consent
  required, and nothing stored. The governor treats it as model-loading (stops the TTS worker first).
- Tests: tests/test_voice.py `test_transcribe_returns_text_and_stores_nothing` (JFK clip, source_count stays 0, no
  consent refused); tests/test_agent.py `test_spoken_question_is_transcribed_and_not_stored` (over the pipe, oversize
  audio refused); tests/test_app.py `test_voice_question_is_transcribed_asked_and_answered_aloud` (1 s at 48 kHz ->
  16 kHz RIFF, call order transcribe -> recall -> speak). test_app + test_voice 36/36 OK.
- Not verified: a real microphone in the desktop app (needs the owner), end-to-end latency, noisy rooms.

## Lens answerability head v2c in recall: reranker + verifier + answer gate (2026-10-30) — integrated; gate below target

- Retrieval with v2c replacing the mMARCO reranker (same 614 v1 dev/test + expansion + near-miss questions, 10k
  synthetic corpora, scripts/experiment_answer_verifier.py --reranker; never the sealed holdout): top-1 correct for
  answerable questions 0.827 -> 0.836, recall@3 0.900 -> 0.927, paraphrase top-1 0.69 -> 0.72; other types equal.
- Gate (correct top-1 answered with ≤ 5% of unanswerable questions answered; 5-fold grouped CV over all 614):
  mMARCO rerank + cosine + literal 0.420; v2c as verifier on mMARCO retrieval 0.509; **v2c reranking + cosine + literal
  0.493 (+ a separate v2c verifier pass 0.496: the same model adds no new signal)**; target 0.80, ceiling = top-1 0.836.
- Shipped gate (lens_model/eval/fit_gate.py, models/Lens--answerability-v2c/gate.json, pinned): logistic over
  (v2c support of the top evidence, best rerank, best cosine, full literal match), fitted on the v1 dev split and the
  near-miss set only; threshold 0.715 for 5% false answers there. Validation: v1 test 0.456 correct answered,
  unanswerable rejected 1.0; expansion 0.233 (unanswerable and near-miss rejected 1.0).
- Engine: the verifier reuses the reranker instance when both point at the same model (one model resident); with
  gate.json beside the model, recall abstains when the gate probability is below its threshold (a full literal match is a
  feature, not an override). Agent: v2c is used as reranker and verifier when its model, tokenizer and gate all match
  third_party/model-lock.json, otherwise the pinned mMARCO reranker. Package: v2c replaces mMARCO.
- Tests: tests/test_answer_gate.py (supported question answered with answer_probability; unrelated question abstains);
  test_agent 6/6, test_installer 4/4 (an uninstall race fixed: PowerShell's Process.Path is re-read per access and
  can turn null between two reads; lens-tts and lens-sherpa are now stopped on uninstall).
- Not met: the 0.80 gate. Verifier quality on Lens-style memories is the limit (harness AUC 0.871 vs the 1.79 GB
  teacher's 0.923); next: training data from Lens-style (memory, question) pairs with near-misses.

## Answerability head v3: stronger answer-presence teacher (2026-10-30) — NOT ADOPTED (no gain on Lens-style data)

- Teacher choice on the tuning data only (Lens harness v1 dev split + the near-miss set, 258 pairs, 96 supported;
  never test, expansion or the sealed holdout): AUC bge-reranker-v2-m3 0.917 (the v2 teacher), Qwen3-Reranker-0.6B
  0.832, **Qwen3-1.7B zero-shot judge 0.974**, shipped v2c INT8 0.892. On the v1 dev split alone every judge is near the
  top (bge 0.995, Qwen3-1.7B 0.988, v2c 0.948): the near-miss questions are what separates them.
- v3 data: the same 53,265-pair public pool as v2, relabelled by the Qwen3-1.7B judge on the RTX 5060
  (compare_answerability.py: LENS_JUDGE_DEVICE=cuda, bf16, last-position logits only and no KV cache after two
  out-of-memory stops; build_distill.py --out); Platt a 0.098, b 0.058; 673 pairs where teacher and gold disagree by
  > 0.9. Students (MarginMSE 0.1): v3a from v1, 2 epochs; v3b from v2c, 1 epoch at 2e-5. INT8 sign agreement 0.995.
- Result on the same 258 tuning pairs: **v3a 0.885, v3b 0.875 vs v2c 0.892** — a better teacher on public QA text does
  not move Lens-style near-misses; v2c stays shipped. A first try at Lens-style training memories generated by
  Qwen3-1.7B (lens_model/data/build_lens_style.py, 48 items, fixture-leak guard dropping ~40%) gave malformed
  near-miss and answerable questions on inspection, so no model was trained on it.
- Next: Lens-style pairs with programmatic near-misses (entity, day, number substitution in generated memories),
  labelled by the Qwen3-1.7B judge, or a larger generator; the 0.80 gate stays unmet.

## Answerability head v3c: programmatic Lens-style near-misses (2026-10-31) — ADOPTED; gate improved, still below target

- Data (lens_model/data/build_lens_style.py, no LLM writing): 4,000 generated memories from nine event schemas
  (meeting, order, doctor, flight, recommendation, bill, tech decision, child's event, deadline), en 2,254 / hi 616 /
  zh 556 / es 574 plus cross-lingual questions; per memory answerable questions, near-misses that change one detail
  (entity 3,383, specific 2,961, attribution 2,128, action 2,027) and one unrelated question: 22,197 pairs. Leak guard
  against every data/fixtures/retrieval-nl/*.json (5-word sequences, in-sentence names): 22 dropped, 1,175 duplicates.
- Labels: y = 0.5·gold + 0.5·Platt(Qwen3-1.7B judge) (a 0.181, b 0.311); judge AUC against gold 0.990, 1,012 pairs
  disagree by > 0.5 (mostly answerable questions the judge doubts). Training set: these pairs + an equal random sample of
  the v3 public pool (44,394 rows). Student v3c from v2c, 1 epoch, batch 32, lr 2e-5, max length 384, MarginMSE 0.1
  (1,387 steps, 139 s on the RTX 5060). INT8: sign agreement 0.988, Pearson 0.9985 on 600 pairs.
- Tuning pairs (v1 dev + near-miss set, 258): **AUC v3c 0.920 vs v2c 0.892**.
- Recall with v3c as reranker and verifier (scripts/experiment_answer_verifier.py, same 614 questions, 10k synthetic
  corpora; never the sealed holdout): 5-fold grouped CV gate **0.598 vs 0.493** (unanswerable rejected 0.951, expansion
  near-misses rejected 1.0). Retrieval cost: top-1 correct for answerable questions **0.836 -> 0.798** (recall@3
  0.927 -> 0.911); paraphrase 0.72 -> 0.62, code-switch 0.77 -> 0.73, cross-language 0.82 -> 0.80, exact/cross-app/
  timeline equal. Verifier latency p50 8.1 ms, p95 12.2 ms.
- Shipped gate refit (fit_gate.py on dev + near-miss only, threshold 0.592; models/Lens--answerability-v3c/gate.json):
  validation **v1 test 0.544 correct answered (v2c 0.456)**, unanswerable rejected 1.0, wrong evidence answered 0.041
  (v2c 0.017); **expansion 0.533 (v2c 0.233)**, unanswerable and near-miss rejected 1.0; dev 0.556 (v2c 0.421);
  near-miss set rejected 0.944 (unchanged).
- Adopted: pinned with lens_model/export/pin_model.py (model_int8.onnx sha256 be6e3e5f…, tokenizer, gate,
  quantization and training reports in third_party/model-lock.json); lens-agent, scripts/package_lens.py,
  ci/linux/smoke.py and tests/test_answer_gate.py use models/Lens--answerability-v3c. Same size as v2c (118 MB INT8),
  one model resident. Tests from PowerShell: test_answer_gate 1/1, test_agent 7/7, test_installer 4/4.
- Not met: the 0.80 gate. Next: ranking-preserving paraphrase pairs in the Lens-style data (the paraphrase top-1 loss
  caps answered-correct), and more near-miss variety for the 0.944 near-miss rejection.

## English speech input: accuracy, memory bound, fallback (2026-10-30) — PASS (H0, CPU, public audio)

- scripts/benchmark_asr_english.py, no tuning: FLEURS en_us priority hold-out (100 clips, the set whisper base was
  measured on) and LibriSpeech test-clean (273 utterances, sha256(id) % 10 == 0); WER with benchmarks/metrics.py
  (case-folded, punctuation removed, no number normalisation: "10,000" vs "ten thousand" counts as errors).
- Canary-180M-flash direct, whole clip at once: FLEURS 20.6% (one clip looped, "T H I N T H I N …", 19× WER on its own),
  LibriSpeech 2.84%; lens-sherpa peak working set grew with length: 341 MB ≤ 6 s, 428 MB at 18 s, **577 MB at 34 s**.
- Fixes: lens-sherpa decodes in pieces of at most 8 s, cut at the quietest 100 ms between 5 and 8 s (34 s clip: 390 MB,
  10 s instead of 19 s); lens-engine retries a routed segment that loops or returns nothing with whisper base
  (`routed_fallback` in the transcript) instead of storing it.
- Product path (lens-engine `transcribe`, English route + fallback): **FLEURS 8.69%** (whisper base on the same clips
  10.27%), **LibriSpeech 3.03%**, 0 failures, 0 fallbacks needed, real-time factor 0.40–0.49 including model load,
  peak 444 MB for engine + worker (reports/voice/asr-english-engine-20261030T040028Z.json; direct run
  asr-english-canary-20261030T033031Z.json). Tests: test_voice 19, test_tts 5 OK.

## Guardrails: one account per device link, no involuntary actions (2026-10-30) — PASS (functional, H0)

- Founder rule (docs/LENS_V1_SPEC.md §13–14, AGENTS.md): devices of different Lens accounts never share data; Lens
  never acts, changes settings or starts a conversation on its own.
- lens-mesh: one account id per laptop (mesh/account.json); a pairing device that presents another account is refused
  (`account_mismatch`) before approval is offered. A valid one-time token no longer pairs by itself: the device waits
  (`pair_status`) until the user approves it in the app, which shows the same 8-digit code as the device
  (SHA-256 of both certificate fingerprints); denied or expired requests cannot be approved later. Paired status is
  checked on every request, so revoking cuts open connections. Approve/deny exist only on the agent's local endpoint.
- Actions: undecided requests expire (default 600 s, `action_expiry_seconds`) and cannot be approved afterwards.
- App: Devices shows waiting devices with their code, Approve and Deny. Android companion: sends and keeps its account
  id, shows the code while waiting, refuses a laptop of another account (compiles; core unit tests pass; not run on a
  device).
- Tests (Windows): test_mesh 4 (new: other account refused and never listed, denial holds, no late approval, a device
  cannot approve itself, revocation cuts an open link), test_actions 4 (new: expiry), test_agent 7, test_security 5,
  test_app 17 OK.

## Linux app; English hard-screen OCR held-out (2026-10-30)

- lens-app for Linux (engine/app/linux/app_gtk.cpp: GTK 4 + WebKitGTK 6, the same UI through a WebView2-compatible
  shim, lens:// bundle only, microphone the only grantable permission, agent started detached when absent):
  `--self-test` against the running agent on Xvfb: 9 views, no errors, UI ready 971 ms. Linux smoke 20/20 PASS.
  macOS host (engine/app/macos/app_mac.mm, WKWebView) is built and self-tested only in CI.
- OCR held-out, 25 screens, run once per configuration (no tuning): Lens shipped (PP-OCRv5 mobile det + v6 tiny rec +
  Lens row assembly) page CER **1.59%**, line accuracy 0.85, 1.4 s, 119 MB; PaddleOCR server det + v6 medium rec as
  PaddleOCR outputs lines 4.85% / 0.33 / 18.2 s / 373 MB; the same Baidu models with Lens row assembly 0.76% / 0.92 /
  17.8 s / 374 MB (reports/ocr-screens/ocr-native-en-hard-heldout-*). Any change to close the gap is chosen on dev.
- Decision on dev only (25 screens, Lens row assembly): mobile det + tiny rec 2.17%; mobile det + v6 small rec
  **1.75%** (2.9 s, 119 MB — same RAM); mobile det + v6 medium rec 2.04% (8.7 s, 209 MB); server det + tiny rec 1.46%
  (6.8 s, 374 MB: too heavy for low-end laptops beside the rest of Lens). Shipped English/Latin recogniser is now
  PP-OCRv6 small (agent default, package, CLI, ci/ocr_parity.py). Held-out once after the decision: **0.85% page CER,
  line accuracy 0.91, 2.9 s full screen, 173 ms changed region, 119 MB** — within 0.1 point of Baidu's largest models
  with Lens row assembly (0.76%, 374 MB) and 5.7× better than their raw output (4.85%).

## Lens English G2P for unknown words; English screen-recogniser fine-tune (2026-10-30)

- G2P (lens_model/train/train_g2p.py; models/Lens--g2p-en, pinned): a 4.8M-parameter character-to-phoneme Transformer
  trained on the misaki US lexicons (Apache-2.0) on the RTX 5060, 30 epochs. Held-out words (sha256(word) % 50 == 0,
  3,422 words never seen in training): **word accuracy 75.7%, phoneme error 4.97%**. ONNX export with fixed padded
  shapes (the TorchScript exporter baked attention's sequence length into Reshape constants; export wrappers are put in
  eval mode because the exporter restores their training flag afterwards); parity: 200 held-out words decode
  identically in ONNX and PyTorch. lens-tts uses it (greedy decoding, engine/g2p_en.cpp) for words the lexicon and the
  decomposition rules cannot read, instead of spelling them; the agent passes it when its files match the lock.
  Example: Kubernetes -> kjˌubəɹnˈiɾiz, Zephyrus -> zˈɛfəɹəs (were spelled letter by letter). tests/test_tts.py 5/5.
- Screen recogniser (scripts/make_ocr_en_train.py 59,126 synthetic lines; scripts/train_ocr_screen_rec.py head-only
  fine-tune of PP-OCRv6 tiny, 8,000 steps, CTC + KL to the original): synthetic validation CER 3.28% -> 2.47%, but on the
  English hard-screen dev set page CER **2.17% -> 2.39% (worse)**: code improved (JavaScript light 2.2 -> 0.9%, SQL
  light 2.0 -> 1.0%) while tables (1.2 -> 3.3%), 9 px settings text (1.9 -> 4.6%) and terminals regressed. NOT
  ADOPTED; the shipped PP-OCRv6 tiny recogniser stays. Likely cause: training crops are whole rendered rows, while table
  and settings cells reach the recogniser as separate detector segments.

## Portable core: Linux build and smoke test; Android build; macOS/iOS CI (2026-10-30)

- Founder directive 2026-10-30: build for iPhone, Android, Windows, Linux and macOS. The core's OS-specific calls moved
  behind engine/platform.{hpp,cpp} (shared libraries, durable new files, atomic replace, environment, executable folder,
  child processes with pipes, base64) and engine/ggml_cpu_dispatch.hpp (ggml CPU-variant selection on every OS); the
  engine entry point accepts UTF-8 arguments on POSIX. Windows behaviour is unchanged (full rebuild + test suite).
- Keys off Windows (adapters/posix/key_store.cpp): the database key is AES-256-GCM-wrapped (OpenSSL) with a per-user
  master key held only by the OS secret store — Secret Service via libsecret (adapters/linux), the Keychain with
  kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly (adapters/apple), the Android Keystore through the app over JNI
  (adapters/android). A locked or missing store fails closed (key_unavailable); there is no plaintext fallback.
- SQLCipher 4.19.0 (the version the Windows overlay pins), built from its SHA-512-checked source tarball as an
  amalgamation (ci/sqlcipher/amalgamation.sh) with the Windows build's definitions (FTS5, temp store in memory, thread
  safety, the 4.19 init/shutdown hooks) on every non-Windows platform. Ubuntu's own libsqlcipher package failed the
  engine's schema migration (database_operation_failed) and is not used.
- whisper.cpp at the pinned commit with both Lens RAM patches (ci/fetch_whisper.sh, sha256-checked), GGML_OPENMP=OFF,
  shared libraries with all 15 x86-64 ggml CPU variants selected at run time, as on Windows.
- Linux (ci/linux: Ubuntu 24.04 container, GCC 13.3, ONNX Runtime 1.24.4 checked against GitHub's published sha256):
  lens-engine, lens-tts, lens-embed, lens-sherpa and lens-ocr build; ci/linux/smoke.py on synthetic data, with the
  pinned models mounted: **11/11 PASS** — add/stats/keyword search, wrapped key file in the Secret Service keyring, no
  plaintext in the database file, semantic recall with e5 + the Lens v2c reranker, plaintext export, encrypted backup,
  restore into a new database that opens and searches, spoken reply with Kokoro + misaki (2.9 s of audio, real-time
  factor 0.52), and screen OCR on the 25-screen English hard-screen dev set: **page CER 2.17%, the same as the Windows
  build** (ci/ocr_parity.py on Windows: 2.174%, peak working set 124 MB; Linux peak RSS 141 MB).
- .github/workflows/portable.yml: Linux (the same container), macOS 14 arm64 (Homebrew deps, ONNX Runtime osx-arm64
  1.24.4 sha256-pinned, smoke test with a temporary keychain) and iOS arm64 (vcpkg deps at the overlay's vcpkg commit;
  links the memory core, lens-store). Results only once pushed and run on GitHub's hosted runners.
- Android arm64-v8a (ci/android/build.ps1 on the Windows host: NDK r27.1, API 29, vcpkg OpenSSL/zstd/utf8proc/nlohmann-json
  for arm64-android; vcpkg's SQLCipher port is Windows-only, so the amalgamation; vcpkg's ICU does not build for
  Android, so grapheme clusters come from utf8proc on every non-Windows platform): lens-engine, lens-tts, lens-embed,
  lens-sherpa, lens-ocr and the seven Android ggml CPU variants (armv8.0 … armv9.2 with SME) **build and link**, no
  warnings. SQLCipher's logcat hook needs liblog. **Not executed**: no Android device or emulator here.
- Speech input off Windows: lens-sherpa now uses the platform layer (library loading, base64) and builds from the
  sherpa-onnx C API header at the pinned commit (ci/fetch_sherpa_header.sh; sha256 equal to the v2.0.0 SDK header the
  Windows build uses). Windows: rebuilt, tests/test_voice.py 19, test_cli_extended 2, test_tts 5 OK.
- Screen OCR off Windows: lens-ocr decodes PNG/JPEG/BMP with stb_image (pinned in third_party/upstream-lock.json,
  MIT or Unlicense) instead of WIC, loads ONNX Runtime and reports peak memory through the platform layer
  (`peak_memory_bytes`: peak working set on Windows, ru_maxrss elsewhere). ci/ocr_parity.py (standard library only)
  runs one lens-ocr build on the English hard-screen dev set with the shipped configuration.
- macOS CI, first runs: Linux and iOS jobs PASS on GitHub's runners; macOS failed in ggml's apple_m4 CPU variant (SME
  intrinsics need a newer clang than Xcode 15 on macos-14: `'svmmla_s32' needs target feature sve,i8mm`), found
  through ci/annotate_log.sh, which turns compiler errors into a job annotation readable without the job log. The Apple
  jobs moved to macos-15 (Xcode 16); ggml modules load as .so on macOS; Metal and Accelerate BLAS are off (CPU-only).
  Run 40977462445 (commit 37c7fc0 on the public repository): **macOS arm64 build + smoke test PASS** (engine, TTS,
  speech input, OCR and embedding workers built; storage, the database key wrapped by a temporary login keychain,
  encryption at rest, keyword search, export, backup and restore on synthetic data — models are not in Git, so no
  semantic recall, speech or OCR there), **Linux PASS**, **iOS arm64 memory core PASS**.
- lens-agent off Windows (engine/agent/os.{hpp,cpp}): the client endpoint is a Unix domain socket in a folder only the
  user can enter ($LENS_RUNTIME_DIR, else $XDG_RUNTIME_DIR/lens, else /tmp/lens-<uid>; created 0700 and refused unless
  owned by the user with no group/other access), socket file 0600, every peer's user id checked (SO_PEERCRED,
  getpeereid) before a request is read; one agent per user by flock; the process tree's memory from /proc (VmRSS,
  Private_Clean + Private_Dirty) or libproc on macOS; child workers via posix_spawn. ONNX Runtime off Windows is the
  official release library beside the executables, hash-pinned in third_party/ocr-runtime-lock.json
  (`portable_runtimes`, linux-x64 1.24.4). Windows keeps the user-only named pipe, tray and Run-key autostart;
  rebuilt and re-tested: test_agent 7, test_actions 3, test_app 17, test_installer 4, test_mesh 3, test_security 5 OK.
- Linux smoke test with the agent: **19/19 PASS** — besides the 11 engine/worker checks: agent status over the socket
  (semantic recall verified), socket mode 0600, add and search passed through to the engine, observation consent
  accepted with no observer on this OS (reported, not crashed), diagnostics process tree (lens-agent, lens-engine;
  28 MB working set idle), a spoken reply through the agent with the governor holding OCR, clean shutdown.
  Android arm64 also builds lens-agent. GitHub run 40979831791 (commit 31e3e8e): the same agent checks **PASS on the
  macOS arm64 runner** (peer check by getpeereid, process tree by libproc; keyword-only there, no models), Linux and
  iOS PASS.
- lens-voice off Windows: miniaudio capture (ALSA/PulseAudio, Core Audio, AAudio), native-string arguments, speaker
  profiles sealed with AES-256-GCM under the OS-held master key (DPAPI stays on Windows). Linux smoke: a file-input
  session segments speech and the engine transcribes and stores it (now 22 checks PASS); Windows test_voice 19 OK.
  No live microphone tested on any OS here.
- lens-observer on Linux: the capture loop (settle, delta, exclusions, language labels, OCR fallback, CPU budget, OCR
  hold) is now shared; the OS side is engine/observer/os_window.hpp — Windows: Win32/DWM + UI Automation + PrintWindow
  (unchanged behaviour, test_observer 28/28 OK after the refactor); Linux: AT-SPI frames on the accessibility bus
  (SHOWING-only walk, password-text role never read, visible text ranges where the toolkit reports them), /proc process
  names, X server capture of the frame's area for the OCR fallback (native Wayland gives no capture without the portal:
  OCR is skipped there), Linux exclusions (password managers, gcr-prompter, pinentry, polkit agents, screen lockers).
  Linux smoke on Xvfb with a synthetic GTK 4 window (lens-observer-testapp): the window's note is stored as a
  screen_observation, the password field is never read, an edit is captured, the observer stops cleanly, and the agent
  starts/stops it with consent. Smoke now 29/29 PASS (OCR parity with the small recogniser: 1.75%, as on Windows).
- macOS observer (engine/observer/os_window_mac.mm, uia_text_ax.mm, capture_mac.mm): the frontmost/followed
  application's focused window through the Accessibility API (visible character range of text areas, secure text fields
  never read, elements outside the window skipped), ScreenCaptureKit for the OCR fallback; refuses to start without the
  user's Accessibility permission. GitHub's macOS runner (which grants that permission) builds it and the smoke test
  passes there (language labeller, refusal without consent, clean start and stop); no capture of a real macOS window
  has been verified.
- Android phone observer (android/app ScreenObserverService, android/core ScreenText.kt): Android's accessibility tree
  of the app in front, only while the user has both enabled "Lens screen memory" in Android accessibility settings
  and switched "Observe phone screen" on in Lens (off by default); never password fields, Lens itself, password
  managers, the lock screen, system settings/permission prompts or private-browsing tabs; content must settle for 2 s;
  only lines new to that app window are queued and sent to the paired laptop of the same account, where lens-mesh
  stores them as `screen_observation` with consent mode `paired_device_screen` and source `android:<package>` (only a
  plausible package name; anything else stays "lens-companion"). JVM unit tests 11/11 (ScreenTextTest 5 new), debug APK
  builds; tests/test_mesh.py covers the laptop side. Not run on a phone or emulator.
- Not ported yet: the Android app's use of the native core (memory stays on the laptop), sign-in autostart off Windows.
  No real Linux desktop session tested. No run on macOS, iOS or Android hardware beyond GitHub's macOS runner.

## Android: the phone's own memory through the native core; emulator end-to-end (2026-10-31) — PASS (emulator only)

- liblens-core.so (adapters/android/lens_jni.cpp, engine/portable.cmake `lens-core`): the memory core (lens-store:
  SQLCipher, zstd text codec, keyword recall, deletion, provenance) inside the app's process through JNI; JSON requests
  as UTF-8 byte arrays (JNI's modified UTF-8 would break characters outside the BMP); one request at a time; open
  failures surface as reason codes, never content. Only the five JNI entry points are exported (static OpenSSL/SQLCipher
  hidden), 16 KB page alignment for Android 15+. Stripped size 8.6 MB (arm64-v8a), 9.4 MB (x86_64); needs only libc,
  libm, libdl, liblog. Built by `ci/android/build.ps1 [-Abi arm64-v8a|x86_64] [-CoreOnly]`, staged in
  android/native-libs/ for Gradle (git-ignored).
- Key chain (android/core LocalMemory.kt): random 32-byte master key, stored as "LENSMK01" | IV | AES-256-GCM
  ciphertext under a non-exportable Android Keystore key; unwrapped once per process and handed to the native side
  (adapters/android/master_key.cpp), which wraps the database key file as on Linux/macOS. A missing Keystore key or
  master-key file next to an existing database fails with `key_unavailable` and never creates a new key. Erase deletes
  the Keystore key (crypto-erase), then the files. Storage: noBackupFilesDir (excluded from backups).
- App: notes, shares and phone screen observations are stored on the phone first; with a paired laptop they are also
  queued and delivered as before (only while paired: pairing later never uploads earlier phone-only items). Ask uses
  the laptop when reachable, else this phone's memory, and says so. Pairing is optional (the app opens on Ask, with
  "Pair laptop"); "Erase this phone's memory" with confirmation. Fixed: on Android 15 (edge to edge) the keyboard
  covered the note field and the title sat under the status bar (safe-drawing insets now); evidence times are shown in
  the phone's time zone instead of UTC.
- Recall on the phone is keyword-only (exact and spaced-script words; English stopwords dropped): the embedding and
  reranker models do not ship on Android yet, so paraphrased questions find nothing on the phone alone.
- Tests, emulator `lens-test` (Android 15, x86_64 image, WHPX, headless `-no-window`), synthetic data only:
  - LocalMemoryTest 7/7 (store and recall incl. Hindi, dedup, unrelated question finds nothing; emoji and U+20000
    round trip; sensitive content refused; no plaintext sentinel in any file incl. WAL, reopen after release; lost
    Keystore key or key file never opens or starts over; erase removes files and Keystore key; malformed requests come
    back as errors and the store keeps answering). x86_64 native: 6.3 s; the arm64-v8a library itself (the phone
    binary) also passes 7/7 under the emulator's ARM translation (libndk_translation, 77 s).
  - tests/test_android_link.py now runs (first time; it approves the pending phone as the laptop's user would, since
    pairing needs laptop approval): the phone pairs with a real lens-agent/lens-mesh on the host over pinned TLS 1.3,
    recalls laptop memory, an unrelated question finds nothing, its note reaches the laptop with device and provenance
    set by the laptop, a wrong pin never connects; the same run executes LocalMemoryTest: 8/8 on the device, Python
    test OK (94 s).
  - UI smoke (adb input, uiautomator): app opens without pairing; a typed note is "Saved on this phone." and Ask finds
    it; with the store open the debug app uses 88.8 MB PSS (12.5 MB native heap).
  - JVM unit tests 11/11; debug APK and test APK build.
- Not verified: any physical phone; release (minified) build; the accessibility observer storing locally on a device
  (code path shared with notes, not exercised on the emulator); Wear OS; the Windows suite was not re-run (no Windows
  code changed).

## Android: the laptop's retrieval models on the phone (2026-10-31) — PASS functional (emulator); RAM near the ceiling

- What ships: multilingual-e5-small INT8 (embeddings) and the Lens answerability head v3c (reranker, verifier and
  answer gate with gate.json), the same files and lock-file hashes as the laptop. android/app `stageLensModels`
  copies them from models/ into the APK assets after checking every SHA-256 against third_party/embedding-lock.json
  and model-lock.json (build fails otherwise; `-PlensModels=false` builds a keyword-only app). ONNX Runtime: the
  official onnxruntime-android 1.24.3 AAR (Maven Central, sha256 67397e4a…cbce; the newest 1.24 Android release,
  desktop pins 1.24.4, same C API 24), native library only; the app is restricted to arm64-v8a and x86_64.
- On the phone (android/core LensModels.kt): models are copied once to app-private storage and each copy re-hashed
  against the APK manifest (17 s on the emulator, started in the background at app launch); the engine is opened
  with them over JNI. New items are embedded in the background; models are released after 30 s idle (as
  lens-agent) and on low memory (onTrimMemory). Phone sessions use no ONNX Runtime arena, no memory patterns and no
  pre-packed weight copy (new `low_memory` flag; desktop unchanged), and freed memory is purged after release.
- Parity: the phone (x86_64 emulator) and lens-engine on Windows over the same 103 synthetic notes give identical
  scores to every printed digit (best rerank -1.3448833227157593 and -0.384787380695343, best cosine
  0.6027097920828265 and 0.5751416995628419). Both decline to answer those two paraphrased questions: the answer
  gate's conservatism is the known gap (target 0.80 not met), not a phone effect.
- Emulator tests (synthetic data): SemanticMemoryTest 3/3 (paraphrase ranked first without the gate; a question
  nothing answers abstains; models reload after release; background embedding of a new note; a stale or damaged
  model install is replaced and re-verified), with LocalMemoryTest 7/7 and LaptopLinkTest: 11/11 on the device,
  tests/test_android_link.py OK. Desktop retrieval tests after the shared-code change: answer gate 1, hybrid
  retrieval 10, idle unload 3, query interpretation 7, temporal query 6 — all OK; JVM unit tests 11/11.
- Measured on the emulator (Android 15 x86_64, debug build, indicative only): embedding 100 notes 0.6–1.4 s; warm
  recall 0.25–0.6 s; recall after release (models reload) 2.4–5.4 s. Process RSS: 148 MB before models, 323 MB with
  the embedder, 460–498 MB with both models (PSS 370–409 MB; the spread is between runs of the same build), ~195 MB
  after release. Without the low-memory options the peak was 494–499 MB.
- Open: the phone peak with both models is at the 500 MB ceiling on its own; weights mapped from file (ONNX external
  data) would make them reclaimable. APK size: 346 MB debug with two ABIs (about 290 MB for one ABI), above Google
  Play's 200 MB base limit (asset packs needed for a store release). No physical phone; release build not run.
