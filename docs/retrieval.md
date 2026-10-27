# Multilingual hybrid retrieval (Milestone 1)

Status: implemented in the native engine (schema v5, `index` and `recall` ops); measured by
`scripts/benchmark_retrieval_nl.py`. Results: see "Measured results" below and `reports/retrieval-nl/`.

## Pipeline

```
question ──► recall op (engine/retrieval.cpp)
   ├─ keyword: query units (ASCII words minus en/es stopwords, whole words of spaced scripts,
   │           Han/kana/Hangul/Thai character bigrams) ─► FTS5 OR/bm25 candidates (+ literal scan only for
   │           unspaced-script bigrams) ─► unit hit counts on those candidates
   ├─ semantic: "query: " + text ─► e5 tokenizer ─► ONNX Runtime ─► mean pool ─► L2 ─► scan of
   │           int8 passage vectors in SQLCipher (embedding_chunks) ─► max cosine per source
   ├─ fusion (hybrid): RRF k=60; keyword term weighted by coverage² and only when coverage ≥ 0.5
   ├─ rerank (default when configured): mmarco-mMiniLMv2 cross-encoder scores the top 20 fused
   │           candidates on their evidence passages; order by its logit
   ├─ abstention: not_found unless every query unit matched literally, or the best rerank logit ≥ −1.8282
   │           (without a reranker: best cosine ≥ 0.8309)
   ├─ time: "last week", "昨天", "el mes pasado", "கடந்த வாரம்"… become an event-time window in the
   │           caller's UTC offset; if no evidence is in the window the question is retried without it
   └─ results: original source + exact evidence quote with byte offsets + per-signal scores
```

Indexing is explicit and incremental: `{"op":"index"}` embeds sources lacking vectors for the configured
model id. `lens.ps1` imports then indexes in the same engine process. Deleting a source cascades to its
vectors. Vectors from a different model id are ignored and reported as `unindexed_sources`.

## Decisions

| Decision | Choice | Reason / evidence |
|---|---|---|
| Embedding model | intfloat/multilingual-e5-small @614241f, `onnx/model_qint8_avx512_vnni.onnx` (118 MB, MIT) | Requested model; INT8 vs official fp32 ONNX cosine ≥ 0.993 on 48 FLEURS sentences, identical similarity ordering on probes |
| Runtime | Existing pinned ONNX Runtime 1.24.4 DLL, loaded at runtime | No new runtime; same DLL as OCR, hash-verified by the client |
| Tokenizer | Native C++ reimplementation of the model's tokenizer.json (Precompiled charsmap per grapheme cluster, whitespace collapse, Metaspace, Unigram Viterbi, fused unk) | Building upstream sentencepiece from a fresh clone was blocked by this session's permission policy. Parity gate: 0 token-id mismatches vs Hugging Face `tokenizers` on 500+ texts in 16+ scripts and edge cases (tests/test_embedding.py) |
| Grapheme segmentation | Windows ICU (`icu.dll`, OS component) | Needed to match the reference for combining sequences (e.g. `e` + U+0301) |
| Batching | One text per inference | Dynamic INT8 quantization scales activations per tensor; padding made vectors depend on batch neighbours (measured 0.9975 cosine drift) |
| Vector storage | `embedding_chunks` table inside SQLCipher; per-vector symmetric int8 + float scale (384 B + scale) | Stays inside the encrypted page store, WAL included; no plaintext vector file |
| sqlite-vec | Evaluated, not adopted now | Its `vec0` tables would also live in the encrypted DB, but it must be compiled into/loaded by the SQLCipher build (external source build, blocked this session) and its KNN is a brute-force scan like ours. Revisit when an ANN index is needed (≫100k chunks) |
| Chunking | ≤1500 B single passage; otherwise 1200 B windows, 200 B overlap, cut at whitespace/sentence punctuation | Evidence quotes are exact byte ranges of the original text |
| Fusion | RRF (k=60), coverage-weighted keyword term with 0.5 floor | Plain RRF lost to semantic-only on dev cross-language/paraphrase because one shared word flipped close semantic ranks; tuned on dev split only |
| Abstention | hybrid: full keyword match OR cosine ≥ 0.8309 | Threshold maximizing dev balanced accuracy at 10,000 events; never fitted on test |
| Reranker | cross-encoder/mmarco-mMiniLMv2-L12-H384-v1 @1427fd6, `onnx/model_qint8_avx512_vnni.onnx` (118 MB, Apache-2.0), default on | At 10k (test split): top-1 correct evidence 0.643→0.731, answerable wrongly rejected 0.252→0.139, Chinese unanswerable rejection 0.00→0.86; Recall@10 0.884→0.861; +170 ms p50; peak working set 268→397 MB. Logit threshold −1.8282 fitted on dev |
| Keyword candidates | FTS5 bm25 for tokenizable units; literal scan only for Han/kana/Hangul/Thai bigrams; unit hits counted on candidates | Same quality as the full-scan version at 10k (R@1 0.446→0.449); keyword p50 161→5 ms |
| Semantic scan | In-process cache of decrypted int8 vectors, invalidated by chunk count/max id | p50 93→45 ms at 10k; memory only, nothing written outside SQLCipher |
| Time words | Rule table for en/zh/es/hi/ta/te plus romanized Hinglish/Tanglish/Tenglish; Hindi "कल" (yesterday or tomorrow) deliberately ignored | A phrase can describe content ("the October bill"), hence relax-on-no-evidence; tests/test_temporal_query.py |

## Limits

- Semantic scan is linear in stored chunks; latency at 100k events is reported, not hidden.
- Code-switched romanized Hindi/Tamil/Telugu queries are the weakest category (see results).
- The AVX512-VNNI-tuned INT8 model runs on any x64 CPU, but accuracy on non-VNNI CPUs is unmeasured.
- Fixture memories and distractors are Lens-authored synthetic text, not real user activity; LongMemEval and
  temporal/changed-fact evaluation are Milestone 3/4 work.
