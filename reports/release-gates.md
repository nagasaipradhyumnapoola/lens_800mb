# Engine V1 release decision: experimental developer proof only

The complete product is **not release-ready**. Missing measurements stay pending and
failed quality results stay failed. The user waived 500 MB as a feature blocker, accepted
740 MB RAM and asked to retain features; no new hard ceiling is inferred.

| Gate | Status | Evidence / limit |
|---|---|---|
| Native engine / regression suite | PASS_WITHIN_TESTED_SCOPE | 29 tests; zero failures/errors/skips; staged native client exercised |
| English / Spanish configured ASR | PROVISIONAL_MET | 100 clips each; WER/CER met; language ID/domain tests pending |
| Mandarin configured ASR | PROVISIONAL_MET | 100 clips; CER 13.31%; language ID/domain tests pending |
| Hindi configured ASR | FAIL_QUALITY | 100 clips; WER 40.27%, CER 25.90%; no runtime failure |
| Needle extraction / routing | FAIL_QUALITY_AND_INSUFFICIENT_DATA | 22 synthetic cases; English routing precision 0.50; never execute calls |
| Code-switch speech / entity accuracy | PENDING | No adequate real labeled span/name/date/number set |
| OCR / screenshot detection | PARTIAL | Native crop smoke only; Hindi CER 12.5%; no detector or real UI corpus |
| Literal source retrieval | PASS_SYNTHETIC_SCOPE | 10,000 records; 100/100 Recall@5; 20/20 absent queries |
| 30-minute native workload | PASS_BASE_CONFIGURATION | 800 cycles; zero failures; other configurations pending |
| Original 500 MB targets | EXCEEDED_USER_ACCEPTED_OPTIMIZATION | Staged 596957774 bytes; RAM/commit by configuration retained |
| Encryption / consent / provenance | PARTIAL | Wrong key, WAL, crash recovery, immutability, cascade, bounded-input tests passed |
| Tamper / rotation / backup / full leakage audit | PENDING | Not all mandatory negative tests or recovery features implemented |
| Network-restricted offline execution | PENDING | Local models used; network blocking/packet evidence not established |
| Clean-machine Windows installation | PENDING | Existing host/runtime only; no consumer installer |
| Android / Wear emulator / real watch | PENDING | No APK/device workload or physical-watch capture, thermals or battery tests |

Fixed targets are in ../docs/acceptance-gates.md. Scores are corpus-specific; a passing
unit/integration suite is not a full privacy or multilingual certification. No UI, cloud
inference, private-data training or autonomous remote actions were added.

Next engineering priorities: improve Hindi ASR and extraction/routing on unseen data,
implement text-box detection, complete privacy/recovery/offline tests, then profile
target-device native integrations before the later app phase.
