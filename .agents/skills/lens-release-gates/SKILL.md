---
name: lens-release-gates
description: Apply fail-closed Lens release decisions using measured evidence.
---
Read docs/acceptance-gates.md. A missing measurement is pending, never passing.
The original 500,000,000-byte size/RAM targets remain visible in measurements. The user accepted
740 MB RAM and instructed not to omit features for 500 MB. Overages are optimization work,
not an automatic feature blocker; do not invent another hard ceiling.
Small smoke tests do not satisfy language-quality, retrieval or routing sample-size requirements.
No development models, datasets, Python runtime, secrets or upstream checkouts in a release.
Stop expansion on hard privacy/correctness failures; preserve evidence and explain residual issues.
