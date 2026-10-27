---
name: lens-benchmark
description: Reproduce Lens native model benchmarks and interpret per-language evidence.
---
Read docs/acceptance-gates.md. Verify upstream and artifact locks before inference.
Use scripts/benchmark.py; Python is development-only. Preserve every failed run.
Record source/build commit, model SHA256, dataset revision/license/split/sample hash,
sample count, cold/warm timing, p95, audio duration/RTF and full-process memory accounting.
Do not infer quality from tokens, model loading or synthetic text. Do not tune on holdout fixtures.
Small smoke samples never certify multilingual support. Keep private transcripts out of reports/Git.
