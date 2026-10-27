# Independent native-core review and corrections

An independent read-only reviewer examined the native core and Windows key adapter using the
requesting-code-review skill. No Critical defect was proven. Four Important defects were found:

1. JSON limits were applied after an unbounded read (a rejected 32 MiB request retained ~34 MB extra working set).
2. A ~1 KiB, 1 Hz WAV could expand to ~65 MB PCM before model loading.
3. An FTS token match suppressed other valid Chinese substring matches.
4. Embedded NUL in Needle text/system/path strings silently truncated C API inputs.

The corrected boundary reads lines and files with enforced byte limits, checks resampled audio
frame counts using upstream miniaudio before PCM allocation, merges FTS/literal search results
with stable ordering and deduplication, and rejects embedded NUL before native calls. Oversized
JSON closes the request stream with an explicit error. Audio imports currently accept up to
64 MB encoded / 600 seconds decoded per request; longer recordings require explicit chunked import.

A potential diagnostic-path leak was hardened with a dedicated literal-code exception type.
An actual path leak was not reproduced by the ordinary filesystem probes; it is not presented
as a measured leak. The reviewer found no reproduced original overwrite/loss in canonical-ID tests.

Regression commands and actual red/green evidence: input-safety-red.log.txt,
cjk-retrieval-red.log.txt, tests-hardened-final.log.txt and test-results.json.
No synthetic/private test content was captured from a real user.

The OCR follow-up review found one further Important defect: untyped GetTensorData<float>()
could read an unexpected non-float ONNX output with the wrong element size. The adapter now
requires a FLOAT output before obtaining the pointer. A genuine uint8-output ONNX regression
failed before the fix and passed afterward; see native-ocr-output-type-red.log.txt and
native-ocr-output-type-green.log.txt. The final suite contains 29 passing tests, zero skips.

The first endurance run was intentionally interrupted after at least 350 completed cycles
(802 seconds in its last progress item) to apply these corrections. Its progress log is retained
as windows-endurance-initial-interrupted.log.txt. The corrected run uses an isolated executable
copy and records the measured SHA256; the interrupted run is not a 30-minute pass.
The corrected run completed 1,800.49 seconds and 800 cycles with zero failures; its binary hash
matches the current lens-engine.exe. See windows-endurance.json for exact measurements.

The review does not certify apps, sync, key rotation/backups, forensic erasure, natural-language
QA, all-language quality, physical-watch operation or a production security audit.
