# Acceptance gates and user-approved budget revision

Current revision (founder, 2026-10-26, supersedes the 500 MB and 740 MB figures below for RAM): the complete
always-on background system has an absolute 800 MB (800,000,000 bytes) RAM ceiling, idle target 50–100 MB,
CPU-only operation mandatory, low-end hardware compatibility required (docs/LENS_V1_SPEC.md §15). The hardware
compatibility gates at the end of this file apply to every release claim.

User revision on 2026-10-26: "740 mb is fine, go on, dont skip nay features for 500mb".
The original size/RAM limits below remain visible optimization targets, not feature blockers.
Preserve historical measurements; no new hard ceiling is inferred. Privacy/correctness gates remain.

Budgets use decimal bytes: 500 MB = 500,000,000 bytes, not 500 MiB.
The application process tree includes native workers; a benchmark controller is measured separately.
Windows working-set and private-commit peaks must both be reported. Sampled tree peaks are lower
bounds; per-process OS high-water counters supplement sampling. Missing child accounting fails a release claim.

| Gate | Required evidence | Pass condition |
|---|---|---|
| Native ASR smoke | native build, weight SHA256, real licensed audio, output and reference | actual transcript scored, no crash; this alone is not a language-quality pass |
| Per-language ASR | disjoint, licensed holdout >=100 clips per language; CER/WER and language-ID | provisional WER <=0.20 and CER <=0.15; CJK CER primary; language-ID >=0.90 |
| Code switching | >=50 real clips per language pair with spans | same error limits per span language; pending until consented/licensed data exists |
| Extraction | >=100 unseen examples per tested language, unsupported/negated/adversarial requests | field micro-F1 >=0.90; all language failures visible |
| Routing | explicit actionable/non-actionable labels | safe routing precision >=0.95; zero unapproved action execution |
| Retrieval | >=100 labeled queries with distractors, >=10,000 history records | Recall@5 >=0.90; unanswerable queries return not_found |
| OCR | >=100 real UI screenshots per script; no synthetic-only certification | CER <=0.10, exact match reported separately |
| Installed footprint | staged actual app+runtime+models (including optional installed packs) | <=500,000,000 bytes per device |
| RAM | cold/warm/idle/reload/active and 30-minute workload, full tree, on each hardware tier below | working-set and private-commit peaks <=800,000,000 bytes; idle (no model loaded) target 50–100 MB, reported per tier |
| Privacy | wrong-key, tamper, rotation, WAL/temp/backup/log checks | no personal plaintext leakage; all negative tests pass |
| Offline | cached local models, network-restricted execution | core functions succeed without downloads/HTTP/model API |

These are engineering targets, not measured scores. Small smoke sets establish functionality,
not usable multilingual accuracy. Untested languages are experimental, even if a language token exists.
Do not tune on holdout data or lower a threshold to turn a report green.

No quality claim may use a single aggregate to conceal a failed language. On a hard privacy
failure, stop feature expansion, preserve failed evidence and investigate. Budget overages remain
visible optimization work under the user's revision; they do not silently discard functionality.
Quality, correctness, privacy and target-device measurement requirements still govern release.

## Hardware compatibility gates (founder requirement, 2026-10-26)

Measured on real machines, never extrapolated from the development laptop. Each tier is reported separately;
a tier with no physical test machine is BLOCKED, not passed.

| Tier | Reference machine (to be acquired or borrowed) | Purpose |
|---|---|---|
| H0 development | ASUS G14 GA403UM, Ryzen 9 270, 16 GB, dGPU disabled | development numbers only |
| H1 mainstream low-end | 8 GB RAM, 4-core x64 with AVX2, no dGPU (e.g. HP laptop, Core i3 / Ryzen 3) | default experience |
| H2 constrained | 4 GB RAM, 2–4 core x64, no dGPU | degraded but working core |
| H3 legacy ISA | x64 CPU without AVX2 (and ideally without AVX), e.g. Celeron/Pentium Silver | instruction compatibility |

| Gate | Required evidence | Pass condition |
|---|---|---|
| CPU-only | every capability run with no GPU present or with GPU execution providers disabled | all functions work; results reported per tier |
| Instruction compatibility (static) | `scripts/check_hardware_compat.py` over every shipped native binary and build configuration | no dependency requires AVX/AVX2/AVX-512/VNNI unconditionally; any such use is behind runtime dispatch |
| Instruction compatibility (dynamic) | full workflow on an H3 machine, or under an instruction-set emulator (e.g. Intel SDE) restricted to SSE4.2 as a supplement | no illegal-instruction crash; capabilities that cannot run degrade with a visible explanation |
| Memory per tier | full-tree sampling plus OS high-water counters: idle, cold start, each model active, 30-minute mixed workload | peak <=800,000,000 bytes on every tier; H2 uses its adaptive cap and must not push the system into sustained paging |
| Response time per tier | p50/p95 for recall, OCR of a changed region, ASR real-time factor, observer event-to-store latency | targets reported per tier; H0 numbers never stand in for H1–H3 |
| Accuracy per tier | the same quality benchmarks run on the deployed variant for that tier | any variant swap (smaller model) is benchmarked; failures stay visible |
| Battery | `powercfg /batteryreport` and SRUM per-application energy (`powercfg /srumutil`, elevated prompt) over a 2-hour idle-observer run and a 30-minute active run, on battery | drain attributable to Lens reported per tier; no claim without a measured run |
| Graceful degradation | forced low memory, battery saver, high CPU load, missing CPU features | no crash or data loss; degraded mode visible to the user; core capture, encrypted storage and keyword retrieval keep working |
| Minimum requirements | published CPU instruction floor, Windows versions, RAM, free storage | every published number backed by a passing tier run |
| Hardware profile | `scripts/hardware_profile.py` output stored with every tier report | CPU model and instruction features, cores, RAM, Windows build, GPUs, power source recorded |
