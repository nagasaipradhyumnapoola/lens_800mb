---
name: lens-release-gates
description: Apply fail-closed Lens release decisions using measured evidence.
---
Read docs/acceptance-gates.md. A missing measurement is pending, never passing.
RAM: 800,000,000 bytes is the absolute ceiling for the complete always-on background system (every
process, working set and private commit, peaks included); idle target 50–100 MB; every hardware tier
measured separately (founder 2026-10-26, docs/LENS_V1_SPEC.md §15). The original 500,000,000-byte
size/RAM targets stay visible as optimization goals; never cut requested features to reach them.
Small smoke tests do not satisfy language-quality, retrieval or routing sample-size requirements.
No development models, datasets, Python runtime, secrets or upstream checkouts in a release.
Stop expansion on hard privacy/correctness failures; preserve evidence and explain residual issues.
