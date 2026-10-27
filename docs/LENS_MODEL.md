# Lens model — feasibility assessment and proposed architecture

Status: IN PROGRESS (2026-10-27). First trained Lens weights exist: the answerability head v0 (LM1 stage T2),
trained on CPU from licensed public data; evaluation and the v1 iteration are recorded in docs/VERIFICATION.md.
The rest of this document remains the plan; estimates are marked. Every number marked *estimate* must
be replaced by a measurement before it is relied on. The working app (retrieval engine, OCR, ASR, Needle,
benchmarks) is preserved unchanged; this is a separate workstream (`lens_model/`, planned).

## 1. What the founder asked for, and what is honest

Lens must become a trained model of its own, not a set of upstream models wired together by application code.
The memory system stays separate: the model understands and processes; the encrypted store keeps personal
experiences. Personal memories are never used as training data.

What is feasible on the available hardware is **not** pretraining a multimodal model from scratch. It is:

- a new **architecture** (shared multilingual trunk, modality input adapters, nine task heads, a device family);
- initialised from permissively licensed pretrained weights (as nearly every production small model is);
- **trained** by multi-task fine-tuning and knowledge distillation on licensed public data, permitted teacher
  outputs and programmatically generated synthetic data;
- quantized, benchmarked against the upstream baselines it replaces, and integrated behind a flag.

Where Lens still depends on an upstream model at inference time (PP-OCR detection, the acoustic encoder of an
ASR model in early phases), the documentation says so, per capability. A capability counts as "Lens model"
only when its inference runs through trained Lens weights and passes its benchmark.

## 2. Hardware: training machine vs. the machines Lens must run on

**Deployment (inference) targets — founder requirement, docs/LENS_V1_SPEC.md §15.** Every Lens-Core variant
must run CPU-only on older, low-end Windows laptops with no dedicated GPU, including 8 GB and (where feasible)
4 GB machines and x64 CPUs without AVX2. The complete background system stays under 800 MB at peak; idle
target 50–100 MB. A GPU is used for training and is only an optional accelerator at inference. Hardware tiers
H0–H3 are defined in docs/acceptance-gates.md; each variant is benchmarked on the tiers it targets.

**Training machine facts (measured 2026-10-26; full profile in reports/hardware/h0-g14.json):**

| Item | Measured |
|---|---|
| Machine | ASUS ROG Zephyrus G14 GA403UM |
| CPU | AMD Ryzen 9 270 (8 cores / 16 threads), Radeon 780M iGPU |
| RAM | 15.3 GB usable |
| Discrete GPU | RTX 5060 Laptop 8 GB per founder; **not enumerated by Windows right now** (only the Radeon 780M is listed; NVIDIA audio endpoints show "Unknown"). Most likely the dGPU is switched off (Eco / iGPU-only mode). It must be enabled (Armoury Crate: Standard or Ultimate) before any GPU training. |
| Disk free | D: 227 GB, C: 165 GB |
| System memory load at profile time | 97% (467 MB available) from other applications; benchmark reports must record memory load because it distorts latency and RAM numbers |
| Software | No PyTorch installed. RTX 50xx (Blackwell, sm_120) needs PyTorch ≥ 2.7 built for CUDA 12.8; to be installed in a separate project-local environment (`.venv-train`), not system-wide. |

## 3. Feasibility by capability

| # | Capability | Train on this machine? | What is trained | Upstream role |
|---|---|---|---|---|
| 3 | Language and context understanding | Yes | Shared trunk (multi-task fine-tune + distillation) | e5-small/MiniLM init; bge-m3 teacher |
| 7 | Memory retrieval intent | Yes | Intent + slot head (time, app, person, entity) | Existing rule parser = baseline |
| 8 | Evidence / answerability | Yes — highest priority (current M2 blocker) | Cross-mode head: supports / related-unsupported / irrelevant + rerank score | mMARCO reranker, QA/NLI = baselines; bge-reranker-v2-m3 teacher |
| 9 | Tool and action routing | Yes | Intent, slots, risk class (read-only vs needs confirmation) | Needle3 = baseline |
| 5 | Memory importance | Yes, small head; data is the hard part | Importance class + keep/summarise/drop | none (no public dataset) |
| 4 | Activity / event interpretation | Yes, small head; data is synthetic | Activity class over event windows | none (no public desktop-activity dataset) |
| 6 | Cross-modal context | Yes, at token level | Layout/role embeddings + contrastive alignment of screen, speech-query and text in one space | SigLIP2 teacher for later pixel adapter |
| 1 | Visual understanding / OCR | Partly | Phase A: screen tokens (UIA + OCR lines + bbox) into the trunk. Phase B: Lens text-line recognizer for te/ta/hi (CTC, ≤30M params) on synthetic renders | PP-OCRv5/v6 stays production OCR until beaten on the real-screenshot benchmark; detection stays upstream |
| 2 | Multilingual speech | Connector only | Speech adapter mapping a frozen acoustic encoder into the trunk (spoken-query understanding, contrastive to transcripts) | whisper.cpp / Dolphin / IndicConformer remain ASR; training competitive ASR from scratch is **not feasible** here (needs thousands of hours of audio and far more compute) |

Not feasible and not claimed: multimodal pretraining from scratch; a >1B-parameter VLM; one identical binary
meeting every target on desktop, phone and watch.

## 4. Proposed architecture: Lens-Core

```
 inputs (each becomes a token sequence in the trunk's space)
 ├─ text / transcript ............ XLM-R tokens, vocabulary trimmed to Lens languages
 ├─ screen observation ........... UIA nodes + OCR lines as tokens, plus learned embeddings:
 │                                 role (button, field, title…), 2-D layout (quantized bbox), app class
 ├─ event window ................. typed event tokens (focus, edit, navigate, media…) + time-gap buckets
 └─ speech (phase LM4) ........... frozen acoustic encoder states → trained conv/attention connector
                       │
            ┌──────────▼───────────┐
            │  shared trunk         │  12 layers × 384 hidden (MiniLM geometry), ~21M non-embedding
            │  (one set of weights) │  parameters + trimmed embeddings (~25M at 64k vocab, estimate)
            └──────────┬───────────┘
   bi-encoder mode (one input)          cross mode ([q] [SEP] [evidence])
   ├─ H1 retrieval embedding (384-d)    ├─ H2 answerability: supports / related-unsupported / irrelevant
   ├─ H3 retrieval intent + slots       └─ H2b rerank score
   ├─ H4 action routing + risk class
   ├─ H5 activity class (event/screen inputs)
   └─ H6 importance (observation inputs)
```

- **Shared representation.** All modalities are mapped into the same trunk, so a typed query, a spoken query
  and a screen observation are embedded in one vector space; H1 is trained contrastively across modalities
  (screen ↔ its description, speech-query ↔ transcript, query ↔ memory text).
- **Why this also fixes RAM.** Today retrieval loads two separate 118M-parameter models (e5-small and the
  mMARCO reranker), each carrying a 96M-parameter 250k-token embedding table. One trunk with a trimmed vocabulary
  replaces both: about 46M parameters, ~50–60 MB INT8 (*estimate*), versus 435 MiB peak for retrieval today.
- **Answerability by design.** H2 is trained with hard near-miss negatives (entity, action, attribution and
  temporal substitutions), the exact failure that no off-the-shelf verifier solved (docs/VERIFICATION.md, M2).

### Model family (sizes are estimates until measured)

| Member | Trunk | Heads | INT8 size | Target device / tier |
|---|---|---|---|---|
| Lens-Core-D | 12 × 384, ~64k vocab | all | ~50–60 MB | Windows H0–H1 (8 GB, AVX2), CPU-only; GPU optional |
| Lens-Core-M | 6 × 384, distilled from D | all except speech connector at first | ~30–35 MB | Windows H2–H3 (4 GB, no AVX2) and Android |
| Lens-Core-W | 4 × 256, ~32k vocab | intent, routing, small embedder | ~8–12 MB | Wear OS (retrieval forwarded to phone) |

Each member gets its own benchmark table; none inherits another's results. The engine picks the variant from
the measured hardware profile (RAM, CPU features) and can fall back to a smaller one under memory pressure.

### Low-end deployment rules

- CPU inference through ONNX Runtime's CPU execution provider by default. Whether the pinned ONNX Runtime
  1.24.4 runs on a CPU without AVX2 is NOT VERIFIED (scripts/check_hardware_compat.py lists it); it must pass
  the dynamic H3 test before any low-end claim.
- INT8 models must not depend on VNNI or AVX-512 to be correct; their speed is measured per tier.
- One ONNX session serves all heads, so loading Lens-Core costs one model, not nine. It loads lazily and is
  released when idle; memory-mapped weights (ORT format / external initializers) are evaluated for lower
  private commit and measured, not assumed.
- Long jobs (re-indexing, activity classification over history) run only when idle, on AC power or above a
  battery threshold, and back off under OS memory pressure.

## 5. Training plan

Teachers run offline once; their outputs are cached with hashes. Students never call teachers at inference.

| Stage | Objective | Data (licence as published on the dataset card, checked 2026-10-26) |
|---|---|---|
| T0 vocabulary trim | keep tokens covering Lens languages; measure coverage loss | Wikipedia (CC BY-SA 3.0), MIRACL corpora (Apache-2.0) |
| T1 embedding distillation | match bge-m3 (MIT) and e5 (MIT) teacher vectors + in-batch contrastive | MIRACL (Apache-2.0: en, es, hi, te, zh…), Mr. TyDi (Apache-2.0), MASSIVE paraphrases (CC BY 4.0) |
| T2 answerability + rerank | 3-way classification + margin distillation from bge-reranker-v2-m3 (Apache-2.0) | SQuAD 2.0 (CC BY-SA 4.0, adversarial unanswerables), TyDi QA (Apache-2.0, null answers), IndicQA (CC BY 4.0), XQuAD (CC BY-SA 4.0), MLQA (CC BY-SA 3.0), programmatic near-miss substitutions over that public text |
| T3 intent, slots, routing | token + sequence classification; risk class | MASSIVE (CC BY 4.0; 51 languages incl. hi, ta, te, zh, es), MINDS-14 (CC BY 4.0), xLAM function calling (CC BY 4.0, gated), Lens action schema (synthetic) |
| T4 activity + importance | sequence classification | synthetic event-stream simulator (authored), WebSight (CC BY 4.0) UI semantics; RICO/ScreenQA after licence check |
| T5 speech connector | contrastive speech↔transcript alignment | FLEURS (CC BY 4.0), IndicVoices (CC BY 4.0, gated), LibriSpeech (CC BY 4.0), Common Voice (CC0 per Mozilla; card unverified) |
| T6 Indic line recognizer | CTC | synthetic renders with Noto fonts (OFL) over public text; PP-OCR as teacher where its licence allows (Apache-2.0) |
| T7 family distillation | D → M → W, logit + hidden-state distillation | outputs of the trained D model on the above data |

Excluded from training (licence): mMARCO / MS MARCO (non-commercial terms), XNLI (CC BY-NC), Samanantar
(hub card says CC BY-NC 4.0), MobileCLIP weights (Apple AMLR research licence), SenseVoice (custom licence) —
these may be used only as independent benchmarks where their terms allow. Every dataset is recorded in a
manifest (source, revision, licence, sha256, rows used) before training starts.

Synthetic data rule: generated programmatically or by local open-weight models whose licence permits training
use; no personal data, no hosted-API outputs used as training labels without verified terms.

## 6. Compute requirements (estimates; LM0 measures them)

- Fits in 8 GB VRAM: fine-tuning ≤150M-parameter encoders in bf16 with gradient checkpointing (batch 32–64,
  sequence 128–256); fp16 inference of bge-m3 (568M) and bge-reranker-v2-m3 for teacher caching; ≤30M-parameter
  CTC recognizers.
- T0–T3 (Lens-Core-D text capabilities): teacher caching for 1–3M passages ≈ 2–6 GPU-hours; training ≈ 10–30
  GPU-hours. Feasible on this laptop over several nights.
- T4–T7: ≈ 20–60 GPU-hours more. Feasible, slower. A rented single A100/H100 (~US$2–4/hour) is an optional
  accelerator, never a runtime dependency.
- 16 GB system RAM limits data loading: datasets are streamed from memory-mapped Arrow files on D:.
- Storage: ≈ 60–120 GB for datasets, teacher caches and checkpoints (D: has 227 GB free).

## 7. Benchmark standard: aim for best in class, report honestly

The founder's bar: Lens-Core should be one of the best-benchmarked models of its kind. That means:

- Standard public benchmarks, not only Lens fixtures: MIRACL and Mr. TyDi (multilingual retrieval, nDCG@10 and
  Recall@100, MTEB/MMTEB protocol), SQuAD 2.0 dev and TyDi QA (answerability: false-answer rate and correct-answer
  rate reported separately), MASSIVE test (intent accuracy, slot F1, per language), FLEURS (spoken-query
  retrieval), a real-screenshot OCR set per script (CER), plus the Lens retrieval-nl fixtures and the sealed
  acceptance holdout.
- Comparison against the strongest published models of the same size and RAM class (for example
  multilingual-e5-small, bge-m3 as an upper reference, the current rerankers, PP-OCR, Whisper tiny/base), run
  by us on the same data and hardware, not copied from papers.
- Every result table carries quality, RAM (full process), latency and hardware tier together; a model that wins
  on quality but breaks the 800 MB ceiling or fails on H2/H3 does not count as a win.
- Claims are scoped: "best in its size class" only when measured against that class; never parity with large
  models without measurement. Losses are published alongside wins.
- Submitting results to public leaderboards is publishing and needs the founder's approval first.

## 8. Integration with the memory engine

- Exported as ONNX, loaded through the existing hash-verified `OnnxModel` helper (ONNX Runtime 1.24.4); one
  session, task selected by head. CPU-only by default and always supported; DirectML/CUDA execution providers
  optional and measured.
- New engine ops (behind a flag, e5 + reranker remain the fallback until Lens-Core passes):
  `embed` (index and query), `verify` (question, evidence), `interpret` (query → recall filters),
  `route` (command → proposed action, never executed without confirmation), `classify` (observation →
  activity, importance → `derived` table, which exists and is currently unused).
- Re-indexing: `embedding_chunks.model` already records the model id; switching models re-embeds in place.
- Privacy: inference only on personal data. No on-device training on memories in V1.

## 9. How we prove it is a trained Lens model, not a wrapper

1. Architecture spec, training code, data manifest, seeds and configs in the repository; checkpoints and
   training logs kept as artifacts with sha256.
2. Weight-delta report: per-layer distance between the initial checkpoint and Lens-Core; new heads and
   embeddings (layout, role, event) do not exist in any upstream model.
3. Ablation: the initial checkpoint without Lens training, evaluated through the same heads, must score
   clearly worse on every head's benchmark.
4. Replacement test: with Lens-Core enabled, the capabilities it claims run with e5, the reranker and Needle
   unloaded (process module list recorded).
5. Reproducibility: a second training run from the manifest reaches metrics within a stated tolerance.
6. Per-capability benchmarks against the upstream baselines on public test sets plus Lens fixtures, with the
   sealed acceptance holdout used once, at the end.

A checkpoint is not production-ready because training finished: it must pass quality, latency, RAM, storage and
privacy gates. Failing capabilities stay on their upstream fallback and are reported as failing.

## 10. Workstream milestones

| Milestone | Deliverable | Gate |
|---|---|---|
| LM0 | `lens_model/` scaffold, `.venv-train`, dataset manifest with licences and hashes, GPU enabled, pilot run; baseline runs of the current models on the public benchmarks in §7, CPU-only | measured throughput, VRAM and RAM for T1/T2; baseline table per hardware tier available |
| LM1 | Lens-Core-D v0: vocabulary trim, H1 embedding, H2 answerability | beats e5 + reranker on dev, expansion and near-miss data at lower RAM; public MIRACL / SQuAD 2.0 numbers |
| LM2 | H3 intent/slots, H4 routing | MASSIVE test; Lens query fixtures; Needle comparison |
| LM3 | screen tokens, H5 activity, H6 importance | new labelled evaluation sets (synthetic + founder-authored, no personal data) |
| LM4 | speech connector; Indic line recognizer | FLEURS spoken-query retrieval; real-screenshot OCR benchmark vs PP-OCR |
| LM5 | Lens-Core-M and -W via distillation, INT8 | per-tier RAM, latency, size, accuracy on H2/H3 laptops and devices |
| LM6 | engine integration behind flag; sealed acceptance | release gates in docs/RELEASE_READINESS.md |

The V1 order in docs/LENS_V1_SPEC.md continues in parallel; LM1 is the planned fix for the M2 answerability
failure.
