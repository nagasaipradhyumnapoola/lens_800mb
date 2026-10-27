# Hindi native ASR candidate research — 2026-10-26

Engine V1 proof scope. English, Mandarin, Spanish and Hindi remain the global launch priorities. No UI, APK, installed application, cloud inference, training, microphone or personal-data access is part of this work. The original 500,000,000-byte target remains visible; the accepted 740 MB is not treated as a new hard ceiling.

## Recommendation

Select the **120M Hindi IndicConformer CTC MatMul-int8 export for the next native integration**. It reuses the pinned sherpa-onnx 2.0.0 native CPU runtime, preserves Devanagari, and its required download is 197,663,198 bytes including tokens. The completed disjoint 100-clip native comparison measured **WER 11.19%, CER 4.86%, zero failures**. This improves substantially on the recorded Dolphin result while leaving the other priority-language models in place.

Keep **Qwen3-ASR-0.6B** as the next multilingual quality comparison if further improvement is needed. It covers all four priority languages, has explicit Apache-2.0 model licensing, and has a native llama.cpp path. Its published Q8 model plus projector already total 1,019,141,728 bytes; runtime RAM must be measured and cannot be inferred from that number. Do not assume CUDA hardware or quote GPU throughput as CPU latency.

Use **Dolphin Small FP32 CTC** only as a diagnostic control for quantization loss. It cannot restore the attention decoder removed by the CTC export.

## Candidates and immutable artifact identities

File sizes and SHA256 below come from public Hugging Face `?blobs=true` metadata, not rounded names or parameter-count estimates. Only the selected Hindi IndicConformer export was downloaded and its bytes independently verified in this session.

| Priority | Candidate / repository revision | Required native artifacts | License and native execution | Quality evidence and limits |
|---|---|---|---|---|
| 1 | [Hindi IndicConformer export](https://huggingface.co/parismitaglobalsolutions/indicconformer-sherpa-onnx/tree/9721eb71eea141fae0982cfcdb9dd2e3d4953c4a), `9721eb71eea141fae0982cfcdb9dd2e3d4953c4a` | `hi/model.int8.onnx` **197,595,593 bytes**; shared `tokens.txt` **67,605 bytes** | Source weights **MIT**; export repo tagged Apache-2.0 and explicitly retains source model licenses. Existing `sherpa-onnx-offline.exe --nemo-ctc-model=... --tokens=... --provider=cpu --num-threads=2 --decoding-method=greedy_search`. | Exporter describes masked Hindi vocabulary and MatMul-only int8 validation. No adequately specified Hindi WER/CER benchmark for these exact export bytes was found before local execution. Do not borrow scores from the different 600M multilingual model. |
| 2 | [Qwen3-ASR-0.6B GGUF](https://huggingface.co/ggml-org/Qwen3-ASR-0.6B-GGUF/tree/928ab958557df9aa2ef1c93e0e83c7ad0933fae2), `928ab958557df9aa2ef1c93e0e83c7ad0933fae2` | `Qwen3-ASR-0.6B-Q8_0.gguf` **804,749,248 bytes** plus `mmproj-Qwen3-ASR-0.6B-Q8_0.gguf` **214,392,480 bytes** | Original model **Apache-2.0**. Native llama.cpp/libmtmd supports this model. Inspected runtime source revision `d854d98bae598388ecea1ed84396587e5edc326d`; candidate build not installed or executed. Use explicit local `-m` / `--mmproj`, CPU `-ngl 0 --no-mmproj-offload`; avoid `-hf` automatic runtime downloads. | Publisher's BF16/vLLM greedy evaluation reports **FLEURS Hindi WER 19.12%**, English 4.39%, Spanish 4.94%, Mandarin 2.88%. These are upstream scores with their own normalization/full test protocol, not Lens scores or GGUF Q8 measurements. [Technical report, Appendix A.2](https://arxiv.org/html/2601.21337v2#Sx1). |
| 3, diagnostic | [Dolphin Small CTC FP32](https://huggingface.co/csukuangfj/sherpa-onnx-dolphin-small-ctc-multi-lang-2025-04-02/tree/84644f57ef947bca81c90db97d193c7060ae32c6), `84644f57ef947bca81c90db97d193c7060ae32c6` | `model.onnx` **820,945,619 bytes**, `tokens.txt` **504,662 bytes** | **Apache-2.0** explicitly covers Dolphin code and model weights. Existing sherpa CPU `--dolphin-model=...` path. | No trustworthy Hindi score for these exact native FP32 bytes was found. Pairing this control with existing int8 distinguishes quantization effects; both omit attention decoding. Not downloaded or evaluated here. |

Artifact SHA256:

| Artifact | SHA256 |
|---|---|
| Hindi `hi/model.int8.onnx` | `915c71e04dd7e5378a4057fdebb252b3a587188e4e99db6d7ce0909ad5ad05fa` |
| Hindi `tokens.txt` | `ee60967630213f31951817ac8b402b92ec18cce80718a24a49b388e56672dfb2` |
| Qwen Q8 model | `bca259818b50ca7c4c05e9bdb35a5dc04fa039653a6d6f3f0f331f96f6aa1971` |
| Qwen Q8 projector | `41a342b5e4c514e968cb756de6cd1b7be39eff43c44c57a2ef5fc6522e36603d` |
| Dolphin FP32 model | `72eedbd3a2199c1d92011a8c21328e54646e7323e0cf282220283b9cd9b2c7fa` |

## Weight licensing, provenance and native decoding

The [official Hindi weight repository](https://huggingface.co/ai4bharat/indicconformer_stt_hi_hybrid_ctc_rnnt_large/tree/deada84ce880997c56ee933aa21571d768264700) declares **MIT**, identifies the 120M hybrid CTC/RNNT architecture and the Hindi weight file. Its current immutable source revision is `deada84ce880997c56ee933aa21571d768264700`; `indicconformer_stt_hi_hybrid_rnnt_large.nemo` is 523,192,320 bytes, upstream SHA256 `7cad1308751a56aed1fda1f30c9078077b1906a2e04454f92128d327561d9008`. This is direct licensing on a model/weight repository, not an inference from a runtime's license. The [official model-suite README](https://github.com/AI4Bharat/IndicConformerASR/tree/3a4c52d0e9168746a2df0da841c6ca5fbb6f18d9) and [MIT license](https://github.com/AI4Bharat/IndicConformerASR/blob/3a4c52d0e9168746a2df0da841c6ca5fbb6f18d9/LICENSE) corroborate it. MIT permits commercial use and sale subject to retaining its notice; retain export attribution as well.

The public export's notebook embeds the Hindi vocabulary mask and exposes NeMo CTC metadata. Its source load uses an unpinned NeMo alias, so the precise source checkpoint revision used by that exporter is **not established**. Pinning the export hash makes execution reproducible; it does not prove that missing source chain. Rebuilding an independently verified export from the pinned official source is future provenance work. The official source requires account information sharing/terms acceptance for download; no such agreement was accepted here.

The [Qwen publisher's technical report](https://arxiv.org/html/2601.21337v2) explicitly releases the models under Apache-2.0; the [official weight card](https://huggingface.co/Qwen/Qwen3-ASR-0.6B/tree/5eb144179a02acc5e5ba31e748d22b0cf3e303b0) carries the same license. The official GGUF converter repository names this base model but lacks its own license tag; retain the base model Apache license/attribution when packaging derivatives. The report's evaluations use greedy decoding with no supplied language parameter, BF16 and `max_new_tokens=1024`. Test a pinned native configuration independently, retaining the `language ... <asr_text>` prefix parsing. Language forcing and native greedy equivalence remain to be checked. [llama.cpp native support documentation](https://github.com/ggml-org/llama.cpp/blob/d854d98bae598388ecea1ed84396587e5edc326d/docs/multimodal.md) documents local model/projector and CPU projector flags.

The [Dolphin source README at the Lens pin](https://github.com/DataoceanAI/Dolphin/blob/78ea615194777f91a3970ff010b5d678d0bbf5f0/README.md) expressly licenses code and model weights under Apache-2.0. Its full architecture is CTC plus attention; an upstream attention-model score is not a score for the native CTC export.

## Current Dolphin invocation review

Lens `scripts/benchmark_sherpa.py` uses the correct pinned small int8 model/tokens with `--dolphin-model`, two threads and CPU. There is no evidence it accidentally selects English or a Chinese-only model. It does not set a language flag because [the pinned native Dolphin config](https://github.com/k2-fsa/sherpa-onnx/blob/v2.0.0/sherpa-onnx/csrc/offline-dolphin-model-config.h) contains only the model path. Language/region prompts in Dolphin's Python attention path do not transfer to this CTC interface.

[The pinned native CTC implementation](https://github.com/k2-fsa/sherpa-onnx/blob/v2.0.0/sherpa-onnx/csrc/offline-recognizer-ctc-impl.h) configures Dolphin preprocessing and supports greedy CTC by default. Its other explicit path is a separately supplied CTC FST graph. `modified_beam_search` is for transducers and the CTC implementation rejects it; simply increasing `max_active_paths` or passing a generic beam option is not a fix. A future external LM/FST has its own size, license, provenance and accuracy costs and was not selected here.

Potential quality loss remains attributable to **CTC-only decoding, quantization and model/domain limits**, with the relative contributions unmeasured. FP32 is a diagnostic control rather than a promised fix. The native branch configuration review does not erase the observed Dolphin Hindi WER 40.27% / CER 25.90% failure or Whisper Small Q5 WER 62.04% / CER 35.43% with three invalid-UTF-8 export failures.

The historical `benchmarks.process.measure` uses `errors='replace'` for stdout/stderr. That weakens claims about exact native byte validity; this session leaves it and the historical reports intact. The separate Hindi runner preserves raw bytes and strictly decodes UTF-8, also rejecting escaped lone surrogates and ambiguous multiple transcript objects. Seven parser tests were observed failing before implementation and passing afterward.

## Reproduction and retained runs

Read-only metadata/research included these exact public queries (no token was read):

```powershell
Invoke-RestMethod -Uri 'https://huggingface.co/api/datasets?filter=benchmark:official&limit=500'
Invoke-RestMethod -Uri 'https://huggingface.co/api/models/parismitaglobalsolutions/indicconformer-sherpa-onnx?blobs=true'
Invoke-RestMethod -Uri 'https://huggingface.co/api/models/ai4bharat/indicconformer_stt_hi_hybrid_ctc_rnnt_large?blobs=true'
Invoke-RestMethod -Uri 'https://huggingface.co/api/models/ggml-org/Qwen3-ASR-0.6B-GGUF?blobs=true'
Invoke-RestMethod -Uri 'https://huggingface.co/api/models/csukuangfj/sherpa-onnx-dolphin-small-ctc-multi-lang-2025-04-02?blobs=true'
```

The official benchmark-tag query did not identify an applicable ASR leaderboard, so ranking uses first-party model evidence and local execution rather than an unrelated leaderboard/popularity score. A connected Hugging Face MCP server was unavailable. An attempted NVIDIA `stt_hi_fastconformer_hybrid_large_pc` page did not resolve; no such model is asserted to exist. Initial guesses for Dolphin documentation/implementation URLs failed or timed out and were replaced with the pinned CTC source links above. An upstream binary download link opened through the web reader returned unsupported content type; that did not download or execute weights locally. A dependency probe using system Python 3.14 failed because `soundfile` was unavailable; execution used the existing project Python 3.12.13 environment without installation.

Executed development commands from `D:\Lens`:

```powershell
& '.venv/Scripts/python.exe' 'reports/indic-hindi-parser-tests.py'
& '.venv/Scripts/python.exe' 'scripts/benchmark_indic_hindi.py' --prepare
& '.venv/Scripts/python.exe' 'scripts/benchmark_indic_hindi.py' --mode smoke
& '.venv/Scripts/python.exe' 'scripts/benchmark_indic_hindi.py' --mode holdout
& '.venv/Scripts/python.exe' -m unittest discover -s tests -v
```

`--prepare` downloads only immutable public export paths, verifies LFS SHA256 or Git blob identity plus byte length and saves `third_party/indic-hindi-lock.json`; an existing lock is preserved. Every inference verifies all pinned native runtime artifacts, models/tokens and each fixture digest first. Each inference run uses a unique timestamp report/artifact directory. It cannot overwrite a prior run. The public report contains metrics, hashes and commands; hypotheses, references, raw stdout/stderr and PCM derivatives remain under ignored `artifacts/indic-hindi-*`.

Smoke uses the first two Hindi FLEURS clips; holdout uses the existing 100 Hindi clips, with ID and content-hash disjointness checked before inference. Dataset `google/fleurs`, CC-BY-4.0, test revision `70bb2e84b976b7e960aa89f1c648e09c59f894dd`; individual files are hash checked. The original source archives were not fully hashed, as recorded in existing dataset provenance. No holdout tuning or new dataset download occurred.

The broad suite was run during concurrent memory-core work: **35 tests, six failures**, all in `test_memory_v2`: batch atomicity/timestamps, exact context/abstention, concurrent writes, metadata/dedup, filters, and v1 migration. Those failures are preserved in `reports/indic-hindi-existing-suite-20261026.log.txt`; they are not attributed to the isolated Hindi runner. The seven new parser tests passed separately. No other agent's files were edited to address this snapshot.

## Completed separate native comparison

| Evidence | Clips | WER | CER | Failures | p95 wall ms | Observed peak working-set bytes | Observed peak private-commit bytes |
|---|---:|---:|---:|---:|---:|---:|---:|
| IndicConformer Hindi smoke | 2 | 1.5625% | 0.7937% | 0 | 2,071.623 | 359,923,712 | 385,306,624 |
| IndicConformer Hindi disjoint holdout | 100 | **11.1923%** | **4.8643%** | **0** | **2,751.154** | **520,568,832** | **525,426,688** |
| Historical Dolphin Hindi, same holdout | 100 | 40.27% | 25.90% | 0 | 3,839 | 777,400,320 | 855,371,776 |

The IndicConformer holdout satisfies the provisional WER <=20% and CER <=15% components on this corpus; it does not satisfy the unmeasured language-ID or broader release gates. Total holdout audio was 1,218.96 seconds, aggregate wall-time/audio RTF **0.152317**, p95 per-clip RTF **0.225200**. Wall time includes fresh process/model loading for every clip and has uncontrolled OS disk-cache state. Loaded warm/idle/reload and 30-minute memory were not measured. The Python development controller is excluded from native memory totals. Every clip had one observed native process; 10ms tree sampling is supplemented by per-process OS high-water counters and cannot prove completeness for hypothetical short-lived descendants.

Peak working set exceeds the original 500 MB target by **20,568,832 bytes**, and private commit by **25,426,688 bytes**. These are optimization work under the accepted budget revision, not a reason to remove features or invent a new ceiling. File size is not process RAM, and these measurements are not the whole product or a Wear/Android result.

Retained new files:

- `reports/indic-hindi-smoke-20261026T042607176697Z-results.json` and matching summary CSV.
- `reports/indic-hindi-holdout-20261026T042620961617Z-results.json` and matching summary CSV.
- `reports/indic-hindi-prepare-20261026.log.txt`, smoke/holdout controller logs, parser red/green logs, and the broad-suite snapshot log.
- Strict byte/digest/re-scoring audit under `reports/indic-hindi-audit-*.json`; raw output and scored text stay in ignored artifacts.

Historical source commit for these new measurements is **`ff5e3dfa11594f62218ecfe81e7ef69cd2500104`**, `source_dirty=true`; exact runner/model/runtime-lock/fixture-manifest digests are in result metadata. A later source commit must not be substituted for this recorded measurement context. The native CLI executable SHA256 verified before both runs is `70e083ee9bd572a807437a4ed32d94c56da73d3186388cb9e2f5dd7b85089463`.

No human decision blocks this native engine comparison or the already-authorized adapter integration. A clean source-to-export rebuild would require the user to accept the official weight repository's information-sharing gate if access has not already been granted. That is separate future provenance work, not an agreement silently accepted here.

## Remaining release limits

Native CPU success and a public clean-speech holdout do not establish language-ID, noisy/conversational audio, code switching, entity/date correctness, 30-minute/reload memory behavior or Wear/Android performance. Missing measurements stay pending. An external quality comparison must not be substituted for Lens measurements. No final product-quality, privacy or target-device gate is passed by this research alone.
