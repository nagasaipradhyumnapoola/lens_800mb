# Lens V1 — canonical product specification

Source: founder directives (Second Brain AI; founder Naga Sai Pradhyumna Poola), 2026-10-26, consolidated.
This file is the durable record of WHAT Lens must be. It does not state what exists — see
IMPLEMENTATION_STATUS.md and docs/VERIFICATION.md. Never present a planned item here as implemented.
Older specification: docs/product-requirements.md (still binding where not superseded).

## 1. What Lens is

The perception and memory engine of Second Brain AI, giving the unified Recursion application persistent,
permission-based understanding of the user's digital life: what they do, in which application, with what
information, when, for which project, how events relate, what is worth remembering or ignoring, and what
changed. Lens is NOT a screen recorder, screenshot database, OCR app, chatbot with vector search, voice
transcriber, or large-context LLM. It is one coherent, privacy-preserving personal memory system.
There is one product, Lens V1 (no parallel "v2/v3" products).

## 2. Role inside Recursion

One unified application. Internal capabilities share one memory and context: Personal Twin, Project Twins,
Organization Twin (future), Cognition (agentic execution/verification), Buddy (conversation/voice), PAP
(authorized cross-device communication/sync). Lens exposes stable internal interfaces; no duplicate memory
systems. V1 ships Lens as a deployable subsystem with a usable interface, cleanly integrable later.

## 3. Observation scope (local-first, permission-based, never covert, never bypassing OS boundaries)

- Windows: foreground app changes, authorized windows, accessible UI text, permitted browser content, PDFs and
  documents, IDEs, permitted terminals, reading/research activity, user-selected files/folders, relevant
  notifications, explicitly authorized voice, window/activity transitions.
- Android: authorized app integrations, approved sharing, user-selected files, permitted notifications,
  user-initiated voice, authorized calendar/reminders, cross-device communication.
- Wear OS: explicitly triggered voice, short queries, notifications, approved quick actions, retrieval via a
  paired phone/computer, lightweight local intelligence where practical.

## 4. Event-driven observation pipeline

1 detect app/UI event → 2 inspect accessibility info → 3 decide whether meaningful content changed →
4 capture only authorized regions when needed → 5 OCR as fallback/visual complement → 6 extract text and
context → 7 identify activity → 8 decide whether worth remembering → 9 deduplicate → 10 save compact
encrypted evidence → 11 update the index → 12 continue efficiently.
Required: window-change and content-change detection, region hashing, adaptive sampling, duplicate
suppression, bounded queues, OCR scheduling, resource-aware throttling, sleep/resume, error recovery.
An unchanged screen must never produce repeated identical memories. No continuous full-screen OCR.

## 5. OCR and multilingual screen perception (core capability)

- Windows UI Automation first (visible text, window/app info, document context, selected UI structure,
  timestamps, source identifiers). OCR only when UIA is unavailable, insufficient or misses visual content.
- Authorized capture: multiple monitors, resolutions, DPI scaling, app windows, browser pages, PDFs, dev tools,
  dark/light themes; only permitted apps/regions; no raw screenshot retention by default.
- Detection: evaluate official PP-OCRv5 mobile detector; full detection → crop → orientation → recognition →
  boxes → confidence → reading order. (The current line-only recognizer is insufficient.)
- Recognition: evaluate PP-OCRv6 tiny/small, PP-OCRv5 Devanagari, Tamil, Telugu, and existing recognizers;
  six quality-critical languages (en, zh, es, hi, ta, te); mixed-script screens; script-aware model selection
  and fallback; never all recognizers resident at once; never assume one model covers every language.
- Speed: event-driven, changed-region detection, frame/region hashing, duplicate suppression, adaptive
  intervals, ROI OCR, bounded queues, reusable sessions, lazy load/unload, CPU-aware scheduling; CPU-only operation is
  mandatory and GPU acceleration optional (§15). Targets measured on real hardware: < 150 ms median for small
  changed-region OCR, < 500 ms p95 where feasible; full-screen OCR measured separately.
- Accuracy benchmark on real screenshots: small fonts, blur, dark backgrounds, code editors, terminals,
  browsers, PDFs, chat apps, tables, mixed language, zh/hi/ta/te, multiple fonts. Metrics: detection
  precision/recall, CER, WER, missed regions, false detections, per-language and end-to-end accuracy.
  Compare candidates on the same images and hardware; choose by measured quality, speed and RAM.
- Memory integration: observation → UIA/OCR → text/layout → event extraction → dedup → context enrichment →
  encrypted storage → indexing → retrieval. Record original text, app, window/document identity, timestamp,
  language, confidence, provenance, entity relationships. Example: "What was the paper I was reading in Chrome
  yesterday?" and "Nethu Chrome la paatha research paper enna?" must retrieve correct evidence.
- Privacy: excluded apps never observed; never password fields, protected screens or private browsing against
  preference; permission changes apply immediately; pause/resume, exclusions, visible status, inspection,
  deletion, retention.
- Diagnostics UI: captured window, detected regions, extracted text, confidence, timing, selected model,
  memory use, whether saved — all from real processing.
- OCR is production-ready only when it passes both standalone and screen-to-memory-to-retrieval benchmarks.
  Reuse mature upstream detectors/recognizers/preprocessing/inference; do not rewrite them unnecessarily.

## 6. Voice and audio

Reuse Whisper, Dolphin and Indic ASR. Speech-to-text, language detection, multilingual and code-switched
transcription, timestamped utterances, user-triggered capture, confidence, error recovery, low latency,
resource-aware loading. Never continuous microphone capture without a separately authorized, visibly
indicated mode. Wear OS: explicit start/stop; heavy models may run on a paired phone/desktop, and the user must
know when processing is remote.

## 7. Cactus and small models

Use Cactus only for what its APIs and verified benchmarks support (intent classification, tool routing, simple
event classification, fast local decisions). It provides no networking, device-control authorization or
memory. Choose the smallest model that meets the quality gate; ~20–30 MB watch components where practical,
verified separately for model, runtime and total-device memory.

## 8. Memory architecture (most important)

The model does not remember the user; memory is external, persistent and encrypted.
L1 raw evidence · L2 structured observations (events) · L3 episodic sessions · L4 semantic facts/preferences/
relationships with evidence · L5 project memory · L6 temporal memory (before/after, yesterday, last week,
during a project, latest vs superseded) · L7 retrieval intelligence (hybrid, entities, time, rerank) ·
L8 consolidation (dedup, summaries, compression without destroying evidence) · L9 lifecycle (updates,
corrections, retention, deletion, backup, restore, sync). All derived memory has provenance; observed facts
are distinguished from inferences; unsupported inferences are never presented as certain.

## 9. Storage

SQLCipher, structured events, dedup, content hashing, incremental indexing, compact metadata, selective
lossless compression (benchmark zstd on real workloads first), tiered retention, selective summaries, entity
references, temporal links, configurable budgets, source pointers, original evidence retrievable when policy
allows. Measure bytes/observation, growth/day, 10k/100k/1M storage, index overhead, compression ratio,
retrieval impact, recovery integrity. Goal: useful memory per stored byte.

## 10. Retrieval must feel intelligent

Indirect questions ("that milkshake I ordered last time", "article before my OS assignment", "GitHub repo I saw
yesterday", "what did I change last week", "what did I discuss with my friend about that paper"). Combine exact
text, semantics, app context, time, entities, project and event relationships, preferences and evidence.
Expose uncertainty when several memories are plausible; abstain or ask when evidence is insufficient; never
hallucinate. Correct first evidence, low false-answer rate and user trust matter as much as Recall@10.

## 11. History import

WhatsApp exports, authorized email, calendar, reminders, contacts (permission), documents, PDFs, authorized
browser history, notes, project files, user archives. Preview, source selection, progress, dedup,
cancellation, summaries, error recovery, source-specific deletion. Credentials in platform secure storage;
no secrets or private content in command-line arguments or logs. No scraping or bypassing access controls.

## 12. Continuous learning without training

Improve the external memory, not model weights: verified preference updates, corrections, relevance feedback,
reinforcement, temporal updates, session consolidation, project association, conflict detection,
user-pinned memories, forgetting/retention rules. Optional digests, reminders, progress summaries only via
transparent preferences; nothing intrusive.

## 13. Cross-device PAP mesh

Search permitted laptop memory from the phone and vice versa, resume context, send approved commands, relay
notifications. Cryptographic device identity, explicit pairing, E2E encryption, key management, device
authorization, offline queues, conflict resolution, incremental sync, retry, revocation, capabilities, audit
logs. Cactus may route; a separate authenticated layer authorizes. Never execute privileged commands from
model output alone.

## 14. Safe cross-device actions

Typed capability registry: device, permissions, parameters, side effects, confirmation, status, verification.
Confirmation for sensitive operations; no unauthorized messaging, payments, deletion, credential access or
remote execution. Personal data (addresses, phone numbers) in protected storage; no raw card storage.

## 15. Resource efficiency and hardware compatibility (founder requirement, 2026-10-26)

Lens must work on older, low-end Windows laptops, including machines with no dedicated GPU, for ordinary users
worldwide. Never assume CUDA, AVX2, a modern processor or a discrete GPU.

- CPU-only inference is mandatory and complete. A GPU (CUDA, DirectML) is an optional accelerator; every
  capability must work, and be benchmarked, with no GPU.
- RAM: absolute ceiling 800 MB (800,000,000 bytes) for the complete always-on background system — every Lens
  process (observer, engine, model workers), working set and private commit, peaks included. Idle target
  50–100 MB. Heavy models (OCR, ASR, retrieval, verifier, Lens-Core heads) are loaded lazily, never resident
  together unless the measured combined peak stays inside the budget, and unloaded when idle.
- Low-memory machines: support 8 GB systems; support 4 GB systems wherever technically feasible. The background
  budget adapts to the machine (smaller peak cap and deferred heavy work under OS memory pressure on 4 GB).
- CPU instruction sets: the baseline is x86-64 with SSE4.2 and POPCNT (the Windows 11 24H2 floor). AVX, AVX2,
  AVX-512 and VNNI may only be used through runtime CPU dispatch; no shipped binary may require them
  unconditionally. Every native dependency's instruction requirements are audited and recorded.
- Techniques: compact INT8 (or smaller) models, lazy loading, memory-mapped weights, caching, bounded queues,
  one heavy model at a time by default, scheduling by idle state, power source and memory pressure.
- Graceful degradation, never a crash: on old CPUs, low RAM, battery saver or thermal limits Lens lowers OCR
  frequency, defers indexing, selects smaller model variants, or disables an optional capability with a visible
  explanation. Core capture, encrypted storage and keyword retrieval must always work.
- Measurement: complete-process-tree memory (idle, peak, working set, private commit), response time, accuracy,
  CPU use and battery consumption, on actual low-end hardware (CPU-only, no dGPU, 4 GB and 8 GB, a CPU without
  AVX2). Results from the development laptop (G14) are never extrapolated to low-end machines.
- Minimum hardware requirements (CPU instruction set, Windows versions, RAM, storage) are published only after
  they are verified on real hardware; until then they are proposals and are labelled as such.
- Optimize RAM, CPU, battery, storage, model loading, OCR frequency, scheduling and startup/shutdown. Report
  unmet hardware constraints with evidence; never trade privacy, integrity or correctness for attractive metrics.
- The trained Lens-Core model (docs/LENS_MODEL.md) remains the goal; optimized deployment variants per hardware
  tier are expected and are benchmarked separately.

## 16. User experience

Polished Windows app, not a CLI: onboarding, clear permissions, observation controls, timeline, natural-language
search, evidence viewer, source links, projects, device pairing, integrations, import management, storage,
privacy/deletion, model/device status, diagnostics. Minimal, premium, dark graphite with restrained gray
gradients, readable typography, smooth interactions, good loading/empty states, established component system.
Every control works; no fake dashboards.

## 17. Privacy and trust

Explicit consent, exclusions, pause/resume, visible status, local encryption, secure keys, revocation,
retention, export, deletion, unlinking, backup protection, source auditing, sensitive-operation access logs,
safe diagnostics. Local-first; optional cloud sync is encrypted and separate. No third-party inference
uploads without explicit authorization; never circumvent OS protections.

## 18. Production release

Installable Windows app + installer, Android companion, Wear OS companion; macOS/iOS later via portable core.
Real hardware testing, including low-end CPU-only laptops (4 GB and 8 GB, no AVX2, no dGPU; §15);
emulator/build success is not production readiness. Validate workflows, permissions,
crash recovery, offline, migration, backup/restore, updates, uninstall, secure sync, sensitive data, model
performance, CPU/RAM, battery, UI quality, accessibility, signed artifacts, clean-device install.
Missing hardware, signing keys or permissions are release blockers to report.

## 19. Benchmarks

Reproducible and honest: OCR (CER, missed text, latency, RAM), ASR (WER/CER, latency, memory), retrieval
(R@1, R@10, top-1 evidence, false answers, false rejections, temporal accuracy), memory (compression,
efficiency, retention, integrity), observation (CPU, RAM, latency, missed events), devices (pairing,
encryption, sync, battery), application (task completion, usability, recovery). Per language
en/zh/es/hi/ta/te, code-switching and romanized Indic. Separate dev and immutable holdout; never tune on the
holdout or alter benchmarks retroactively. Report PASS/FAIL/BLOCKED.

## 20. Required end-to-end demonstrations (real components only)

1 screen memory (Chrome → close → later question → evidence) · 2 cross-application memory (PDF + discussion +
project) · 3 multilingual recall (mixed Tamil/Hindi-English) · 4 temporal (what changed last week; current vs
superseded) · 5 voice (capture → transcript → retrieval with evidence) · 6 cross-device (phone retrieves laptop
memory over encrypted link) · 7 safe action (permission → confirmation → execution → verification) ·
8 privacy (pause stops recording; deletion follows policy) · 9 recovery (crash without corruption) ·
10 performance (full observer within budget over a sustained period, on the development laptop AND on a
low-end CPU-only laptop).

## 21–23. Process and order

Every change: understand → smallest change → reuse upstream → implement → compile → unit/integration/edge tests
→ benchmark → fix → regressions → document → checkpoint → continue. Never mark code complete because it exists;
bounded monitors; preserve user data; no unnecessary installs.
Order: (1) M2 retrieval quality and multilingual understanding → (2) memory/model scheduling → (3) Windows
observation → (4) high-speed multilingual OCR → (5) observations to encrypted memory → (6) episodic memory,
dedup, compression → (7) voice → (8) Windows UI → (9) installer → (10) Android → (11) Wear OS →
(12) encrypted sync → (13) cross-device actions → (14) security/reliability testing → (15) sustained
real-device performance → (16) fix release blockers → (17) signed reproducible artifacts → (18) acceptance report.

V1 is complete only when an ordinary user can install it, grant permissions, use their devices normally,
build useful memories, retrieve information accurately, control their data and rely on it without technical
knowledge.
