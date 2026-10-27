# Milestone 1 final retrieval results (engine with optimized candidates + default rerank)

Held-out test split only (memories 07-20 per language, unanswerable 04-10). Thresholds fixed from dev: cosine 0.8309, rerank logit -1.8282.
Each report independently re-verified by scripts/verify_retrieval_report.py (0 mismatches).

| Events | Mode | R@1 | R@10 | MRR@10 | nDCG@10 | Unanswerable rejected | Answerable wrongly rejected | Top-1 correct evidence | p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1,000 | legacy_search | 0.272 | 0.272 | 0.272 | 0.272 | 1.000 | 0.714 | 0.272 | 10 | 15 |
| 1,000 | keyword | 0.456 | 0.520 | 0.475 | 0.486 | 1.000 | 0.721 | 0.269 | 4 | 16 |
| 1,000 | semantic | 0.755 | 0.922 | 0.811 | 0.838 | 0.833 | 0.316 | 0.592 | 11 | 19 |
| 1,000 | hybrid | 0.776 | 0.922 | 0.826 | 0.849 | 0.833 | 0.255 | 0.660 | 14 | 24 |
| 1,000 | hybrid_rerank | 0.782 | 0.905 | 0.830 | 0.849 | 0.762 | 0.116 | 0.731 | 168 | 213 |
| 10,000 | legacy_search | 0.272 | 0.272 | 0.272 | 0.272 | 1.000 | 0.714 | 0.272 | 47 | 87 |
| 10,000 | keyword | 0.449 | 0.469 | 0.457 | 0.460 | 1.000 | 0.721 | 0.269 | 5 | 35 |
| 10,000 | semantic | 0.741 | 0.867 | 0.788 | 0.808 | 0.833 | 0.310 | 0.582 | 41 | 62 |
| 10,000 | hybrid | 0.759 | 0.884 | 0.807 | 0.826 | 0.833 | 0.252 | 0.643 | 43 | 78 |
| 10,000 | hybrid_rerank | 0.793 | 0.861 | 0.818 | 0.829 | 0.881 | 0.139 | 0.731 | 188 | 258 |
| 100,000 | legacy_search | 0.272 | 0.272 | 0.272 | 0.272 | 1.000 | 0.714 | 0.272 | 728 | 850 |
| 100,000 | keyword | 0.449 | 0.476 | 0.459 | 0.463 | 1.000 | 0.721 | 0.269 | 9 | 308 |
| 100,000 | semantic | 0.728 | 0.830 | 0.769 | 0.784 | 0.833 | 0.310 | 0.578 | 322 | 381 |
| 100,000 | hybrid | 0.745 | 0.854 | 0.790 | 0.806 | 0.833 | 0.252 | 0.636 | 348 | 610 |
| 100,000 | hybrid_rerank | 0.772 | 0.837 | 0.799 | 0.809 | 0.857 | 0.150 | 0.718 | 515 | 787 |

## 1,000 events, default mode (hybrid + rerank)

| Language | R@1 | R@10 | MRR@10 | Unanswerable rejected |
|---|---:|---:|---:|---:|
| en | 0.714 | 0.810 | 0.756 | 0.57 |
| zh | 0.857 | 0.881 | 0.863 | 0.86 |
| es | 0.952 | 0.976 | 0.964 | 1.00 |
| hi | 0.732 | 0.911 | 0.805 | 0.57 |
| ta | 0.750 | 0.964 | 0.822 | 0.86 |
| te | 0.732 | 0.875 | 0.793 | 0.71 |

| Query type | R@1 | R@10 |
|---|---:|---:|
| exact | 0.833 | 0.917 |
| paraphrase | 0.774 | 0.952 |
| cross_language | 0.774 | 0.881 |
| code_switch | 0.714 | 0.833 |

Resources: import 1 s, index 8 s (8.3 ms/event), encrypted DB 1.8 MB, peak working set 393 MB, peak private 392 MB

## 10,000 events, default mode (hybrid + rerank)

| Language | R@1 | R@10 | MRR@10 | Unanswerable rejected |
|---|---:|---:|---:|---:|
| en | 0.714 | 0.786 | 0.750 | 0.71 |
| zh | 0.810 | 0.833 | 0.815 | 0.86 |
| es | 0.952 | 0.952 | 0.952 | 1.00 |
| hi | 0.768 | 0.839 | 0.796 | 0.86 |
| ta | 0.768 | 0.911 | 0.814 | 1.00 |
| te | 0.768 | 0.839 | 0.798 | 0.86 |

| Query type | R@1 | R@10 |
|---|---:|---:|
| exact | 0.845 | 0.893 |
| paraphrase | 0.857 | 0.952 |
| cross_language | 0.726 | 0.810 |
| code_switch | 0.690 | 0.714 |

Resources: import 7 s, index 64 s (6.4 ms/event), encrypted DB 17.0 MB, peak working set 397 MB, peak private 399 MB

## 100,000 events, default mode (hybrid + rerank)

| Language | R@1 | R@10 | MRR@10 | Unanswerable rejected |
|---|---:|---:|---:|---:|
| en | 0.690 | 0.738 | 0.714 | 0.57 |
| zh | 0.786 | 0.810 | 0.792 | 0.86 |
| es | 0.952 | 0.952 | 0.952 | 1.00 |
| hi | 0.750 | 0.821 | 0.777 | 0.86 |
| ta | 0.732 | 0.857 | 0.783 | 1.00 |
| te | 0.750 | 0.839 | 0.790 | 0.86 |

| Query type | R@1 | R@10 |
|---|---:|---:|
| exact | 0.845 | 0.893 |
| paraphrase | 0.833 | 0.929 |
| cross_language | 0.690 | 0.762 |
| code_switch | 0.667 | 0.690 |

Resources: import 83 s, index 650 s (6.5 ms/event), encrypted DB 169.3 MB, peak working set 435 MB, peak private 441 MB
