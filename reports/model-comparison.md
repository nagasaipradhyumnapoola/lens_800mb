# Executed model comparison

Priority languages are English, Mandarin Chinese, Spanish and Hindi. The engine reuses upstream
models; no new foundation model was trained and no personal data was used for training.
All numbers below come from actual execution, with original JSON/CSV and failed runs retained.
The 100 clips per language are from the pinned public FLEURS test split, disjoint from the first
two smoke clips per language. Dataset provenance is in ../docs/datasets.md.

| Language | Selected upstream model | Clips | WER | CER | p95 wall ms | Peak resident bytes | Peak private commit bytes | Failures |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| English | Whisper Base Q5_1 | 100 | 10.27% | 4.81% | 3618 | 175230976 | 689942528 | 0 |
| Mandarin Chinese | Dolphin small CTC int8 | 100 | 89.53% | 13.31% | 3980 | 687767552 | 853663744 | 0 |
| Spanish | Whisper Small Q5_1 | 100 | 5.87% | 1.95% | 8282 | 429424640 | 895180800 | 0 |
| Hindi | Dolphin small CTC int8 | 100 | 40.27% | 25.90% | 3839 | 777400320 | 855371776 | 0 |

English and Spanish meet provisional configured-language WER <=20% / CER <=15% thresholds on
this corpus. Mandarin's primary CER is 13.31%, within the provisional 15% limit; whitespace WER
is not a useful primary score for Chinese. Hindi fails both provisional limits and remains
experimental. Language ID, conversational noise, code switching and entity accuracy are pending;
these rows are not full language-release certifications.

The selected defaults retain the larger Spanish and Dolphin models, as authorized by the user.
The original 500 MB limits are visible optimization targets. Resident memory and private committed
memory are different metrics; the table does not report whole-product RAM or a mobile measurement.
Each benchmark starts a fresh inference process; OS disk caches were not controlled. Wall latency
includes process/model startup, depends on clip length and is not streaming partial-result latency.
The controller is excluded. Sampling every 10 ms is supplemented by observed Windows process
high-water counters; short-lived child completeness is not certified.
The initial repository had no commit during the runs. Raw build_commit values such as HEAD
are unresolved labels, not valid source revision pins; source_dirty is true. Runtime and model
hashes are recorded independently. The eventual local source commit must not retroactively
replace those historical labels or be represented as a benchmark rerun.

## Failed comparisons remain visible

Whisper Tiny Q5_1 Mandarin CER was 41.43% over 100 clips; Dolphin reduced it to 13.31%.
Whisper Small Q5_1 Hindi WER was 62.04%, CER 35.43%, with three invalid-UTF-8 JSON export
failures counted over 100 clips. Dolphin Hindi had zero runtime failures, WER 40.27%, CER 25.90%.
The runner's nonzero Hindi exit and raw failed logs remain intact. No lossy decoding repaired scores.
See asr-holdout-hi-results.json, asr-holdout-zh-results.json and sherpa-holdout-results.json.

Tiny Q5_1, Tiny Q8_0, Base Q5_1 and Small Q5_1 initial 16-language smoke/baseline comparisons
remain in asr-by-language.csv, asr-configured-by-language.csv, asr-low-memory-by-language.csv
and asr-small-baseline-by-language.csv. Two clips per language do not establish broad coverage.

## Structured extraction

Canonical extraction.csv uses the native C++ UTF-8 adapter and official Needle3 DLL/weights.
There are only 22 synthetic cases across languages, code-switch text and adversarial/negative
requests. English including negatives has field F1 0.667 and safe-routing precision 0.50.
Spanish's single event has F1 1.0, Hindi's single event 0.5 and Mandarin's single event 0.0.
None meets the required sample count. Needle is experimental and its calls are never executed.
The earlier Windows CLI non-Latin argv runs were corrupted to question marks; the explicitly
invalid ANSI comparison is not evidence about the model's multilingual capability. Needle native
runtime source was not available in its published source repository; its binary was hash-pinned.

## OCR

Native WIC/ONNX Runtime recognition uses official Paddle weights and script-specific dictionaries.
One synthetic crop per priority language gives CER 0% for English, Spanish and Chinese and
12.5% for Hindi. See ocr-by-script.csv and native-ocr-results.json. These are functional smoke
results, not real screenshot accuracy. Text-box detection is pending; unsupported scripts reject
explicitly. No real user screenshots were captured. The suite rejects non-float model outputs
before reading typed output memory.
