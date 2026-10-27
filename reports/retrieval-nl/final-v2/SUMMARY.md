# Milestone 1 final retrieval results (final engine)

Engine: literal-match priority + indexed keyword candidates + cached semantic scan + default rerank.
Held-out test split only; thresholds fixed from dev (cosine 0.8309, rerank logit -1.8282); reports re-verified independently (0 mismatches).

| Events | Mode | R@1 | R@10 | MRR@10 | nDCG@10 | Unanswerable rejected | Answerable wrongly rejected | Top-1 correct evidence | p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10,000 | legacy_search | 0.272 | 0.272 | 0.272 | 0.272 | 1.000 | 0.714 | 0.272 | 47 | 53 |
| 10,000 | keyword | 0.449 | 0.469 | 0.457 | 0.460 | 1.000 | 0.721 | 0.269 | 4 | 33 |
| 10,000 | semantic | 0.741 | 0.867 | 0.788 | 0.808 | 0.833 | 0.310 | 0.582 | 41 | 63 |
| 10,000 | hybrid | 0.759 | 0.884 | 0.807 | 0.826 | 0.833 | 0.252 | 0.643 | 40 | 79 |
| 10,000 | hybrid_rerank | 0.823 | 0.878 | 0.843 | 0.851 | 0.881 | 0.139 | 0.762 | 192 | 228 |
| 100,000 | legacy_search | 0.272 | 0.272 | 0.272 | 0.272 | 1.000 | 0.714 | 0.272 | 420 | 896 |
| 100,000 | keyword | 0.449 | 0.476 | 0.459 | 0.463 | 1.000 | 0.721 | 0.269 | 9 | 297 |
| 100,000 | semantic | 0.728 | 0.830 | 0.769 | 0.784 | 0.833 | 0.310 | 0.578 | 329 | 398 |
| 100,000 | hybrid | 0.745 | 0.854 | 0.790 | 0.806 | 0.833 | 0.252 | 0.636 | 359 | 651 |
| 100,000 | hybrid_rerank | 0.803 | 0.854 | 0.823 | 0.831 | 0.857 | 0.150 | 0.748 | 520 | 810 |

## 10,000 events, default mode (hybrid + rerank)

| Language | R@1 | R@10 | MRR@10 | Unanswerable rejected |
|---|---:|---:|---:|---:|
| en | 0.714 | 0.786 | 0.750 | 0.71 |
| zh | 0.810 | 0.833 | 0.815 | 0.86 |
| es | 0.952 | 0.952 | 0.952 | 1.00 |
| hi | 0.821 | 0.875 | 0.844 | 0.86 |
| ta | 0.821 | 0.929 | 0.850 | 1.00 |
| te | 0.821 | 0.875 | 0.842 | 0.86 |

| Query type | n | R@1 | R@10 |
|---|---:|---:|---:|
| exact | 80 | 0.988 | 0.988 |
| exact_ambiguous | 4 | 0.250 | 0.250 |
| paraphrase | 84 | 0.857 | 0.952 |
| cross_language | 84 | 0.726 | 0.810 |
| code_switch | 42 | 0.690 | 0.714 |

Resources: import 6 s; index 65 s (6.5 ms/event); encrypted DB 17.0 MB; peak working set 397 MiB; peak private 398 MiB; engine sha256 12000f34f6753fa8

## 100,000 events, default mode (hybrid + rerank)

| Language | R@1 | R@10 | MRR@10 | Unanswerable rejected |
|---|---:|---:|---:|---:|
| en | 0.690 | 0.738 | 0.714 | 0.57 |
| zh | 0.786 | 0.810 | 0.792 | 0.86 |
| es | 0.952 | 0.952 | 0.952 | 1.00 |
| hi | 0.804 | 0.857 | 0.825 | 0.86 |
| ta | 0.786 | 0.875 | 0.819 | 1.00 |
| te | 0.804 | 0.875 | 0.835 | 0.86 |

| Query type | n | R@1 | R@10 |
|---|---:|---:|---:|
| exact | 80 | 0.988 | 0.988 |
| exact_ambiguous | 4 | 0.250 | 0.250 |
| paraphrase | 84 | 0.833 | 0.929 |
| cross_language | 84 | 0.690 | 0.762 |
| code_switch | 42 | 0.667 | 0.690 |

Resources: import 82 s; index 650 s (6.5 ms/event); encrypted DB 169.3 MB; peak working set 435 MiB; peak private 441 MiB; engine sha256 12000f34f6753fa8
