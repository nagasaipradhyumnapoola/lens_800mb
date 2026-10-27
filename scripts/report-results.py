"""Summarize executed evidence without converting pending release gates into passes."""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'reports'


def read(name):
    return json.loads((REPORTS / name).read_text(encoding='utf-8'))


def rows(name):
    with (REPORTS / name).open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))


def write(name, text):
    (REPORTS / name).write_text(text.strip() + '\n', encoding='utf-8')


def main():
    chosen = [(rows('asr-holdout-en-by-language.csv')[0], 'English', 'Whisper Base Q5_1', 'WER'),
              (next(r for r in rows('sherpa-holdout-by-language.csv') if r['language'] == 'zh'), 'Mandarin Chinese', 'Dolphin small CTC int8', 'CER'),
              (rows('asr-holdout-es-by-language.csv')[0], 'Spanish', 'Whisper Small Q5_1', 'WER'),
              (next(r for r in rows('sherpa-holdout-by-language.csv') if r['language'] == 'hi'), 'Hindi', 'Dolphin small CTC int8', 'WER')]
    table = '| Language | Selected upstream model | Clips | WER | CER | p95 wall ms | Peak resident bytes | Peak private commit bytes | Failures |\n|---|---|---:|---:|---:|---:|---:|---:|---:|\n'
    for row, name, model, metric in chosen:
        table += f"| {name} | {model} | {row['sample_count']} | {float(row['wer']):.2%} | {float(row['cer']):.2%} | {float(row['p95_latency_ms']):.0f} | {row['max_observed_wset_bytes']} | {row['max_observed_commit_bytes']} | {row['failure_count']} |\n"
    write('model-comparison.md', '''# Executed model comparison

Priority languages are English, Mandarin Chinese, Spanish and Hindi. The engine reuses upstream
models; no new foundation model was trained and no personal data was used for training.
All numbers below come from actual execution, with original JSON/CSV and failed runs retained.
The 100 clips per language are from the pinned public FLEURS test split, disjoint from the first
two smoke clips per language. Dataset provenance is in ../docs/datasets.md.

''' + table + '''
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
''')
    endurance = read('windows-endurance.json')
    bundle = read('staged-bundle.json')
    bundle_check = read('staged-bundle-check.json')
    tests = read('test-results.json')
    write('windows-profile.md', f'''# Windows native engine measurements

Host inventory: environment.json / environment.md. Audited host is Windows 11 x64, Ryzen 9 270,
8 cores/16 threads and about 16 GB installed RAM. WMI exposed Radeon 780M; an NVIDIA GPU was
not verified. These runs used CPU inference. Other applications were active; this is one host/run.

The corrected workload completed {endurance['duration_measured_s']:.2f} seconds, {endurance['completed_cycles']}
cycles, {endurance['failure_count']} failures and exit code {endurance['exit_code']}.
Each cycle loaded Whisper Base Q5_1, transcribed the public 11-second JFK fixture, unloaded the
model, persisted/deduplicated the immutable source through SQLCipher and retrieved its text.
This is a repeated recorded-fixture workload, not 30 minutes of distinct live audio.

| Measurement | Actual value |
|---|---:|
| p95 complete cycle | {endurance['p95_cycle_ms']:.2f} ms |
| Average complete cycle | {endurance['average_cycle_ms']:.2f} ms |
| Peak sampled working set | {endurance['peak_sampled_tree_wset_bytes']} bytes |
| Peak sampled private bytes | {endurance['peak_sampled_tree_private_bytes']} bytes |
| Observed OS high-water commit | {endurance['peak_observed_os_commit_bytes']} bytes |
| Sampling interval | {endurance['sampling_interval_ms']} ms |
| Samples / maximum observed processes | {endurance['sample_count']} / {endurance['maximum_observed_process_count']} |

Engine SHA256: `{endurance['engine_sha256']}`. The isolated copy and current core EXE match.
The first run was interrupted for input-boundary fixes; its progress log is preserved and never
counted as a full-duration pass. Full evidence: windows-endurance.json and its .log.txt files.

This profile is the English Base configuration only. Selected Spanish/Dolphin configurations
have larger measured peaks in model-comparison.md; their own 30-minute cycles remain pending.
Private commitment above 500 MB is reported, not hidden by the smaller working-set figure.
Cold OS caches, suspend/resume and prolonged idle are not fully characterized.

## Actual developer bundle

Staged directory: `{bundle['directory']}`.
There are {bundle['file_count']} files totaling **{bundle['total_bytes']:,} bytes**
({bundle['total_bytes']/1_000_000:.2f} decimal MB), including selected models, both native ONNX
runtimes, SQLCipher/OpenSSL, C++ worker EXEs, client, dictionaries, manifests and notices.
There is no Python environment, model cache, upstream checkout, benchmark dataset or database.
The original 500 MB target is exceeded; the user explicitly requested preservation of features.
The bundle requires installed Windows x64, PowerShell 7 and MSVC runtime prerequisites. This is
an actual staged-file count, not a clean-machine installer or installed Android/Wear footprint.

The staged-folder check passed {len(bundle_check['checks'])} checks, launching from an unrelated
temporary working directory: native audio for all four priority languages, OCR for each script,
encrypted persistence/reopen, source search, not_found and untrusted extraction proposals.
Fixture input paths refer to public/synthetic test data outside the bundle. Product processes
were staged native EXEs; Python was only the development controller. Network blocking was not
imposed; this does not satisfy the network-restricted offline gate. See staged-bundle-check.json.

Latest source suite: {tests['tests_run']} executed, {tests['failure_count']} failed,
{tests['error_count']} errors, {tests['skipped']} skipped. See test-results.json.
''')
    memory = read('memory-retrieval-results.json')
    write('memory-retrieval.md', f'''# Source-backed encrypted memory

The native SQLCipher store keeps immutable originals, language, UTC import timestamp, device,
source kind, provenance, SHA256 and confidence. Derived rows require a source foreign key and
store their own model/confidence metadata. Conflicting source IDs reject; identical observations
return their canonical stored ID. Original transcripts are not replaced with model summaries.

FTS5 phrase candidates and literal substring candidates merge with stable ordering and ID dedup.
This preserves Chinese substrings even when a separate FTS token match exists. Parameterized
queries retain Unicode and treat SQL punctuation literally. Up to five original sources return;
absent queries return not_found. This is source search, not semantic QA or inferred event answers.

Executed workload: {memory['history_records']:,} Lens-authored synthetic history records,
{memory['query_count']} labeled anchor queries and {memory['unanswerable_queries']} absent queries.
Recall@5 = {memory['recall_at_5']:.2f}; {memory['correct_not_found']}/{memory['unanswerable_queries']}
correct not_found; insertion failures {memory['insert_failure_count']}.
Each of English, Mandarin, Spanish and Hindi has 25 labeled queries and Recall@5 = 1.0.
Runtime was {memory['elapsed_s']:.2f} seconds on this host. Full query evidence is in
memory-retrieval-results.json. Distinct synthetic anchors make this a bounded retrieval test;
it does not establish human conversational recall, entity resolution or natural-language answering.

The public JFK demo performs actual speech inference, closes/reopens encrypted storage and
retrieves the exact original text. Mandarin audio and Spanish OCR also reach encrypted memory
through the real PowerShell client in integration tests. All original timestamps in these file
imports represent import time; no claim is made about recording creation time.

Deletion cascades to derived rows and search indexes. Encryption and logical deletion do not
prove forensic erasure of filesystem snapshots or SSD media. Backup, key rotation, migrations
beyond schema v1, multi-device conflict resolution and encrypted synchronization remain pending.
''')
    gates = [
        ('Native engine / regression suite', 'PASS_WITHIN_TESTED_SCOPE', f"{tests['tests_run']} tests; zero failures/errors/skips; staged native client exercised"),
        ('English / Spanish configured ASR', 'PROVISIONAL_MET', '100 clips each; WER/CER met; language ID/domain tests pending'),
        ('Mandarin configured ASR', 'PROVISIONAL_MET', '100 clips; CER 13.31%; language ID/domain tests pending'),
        ('Hindi configured ASR', 'FAIL_QUALITY', '100 clips; WER 40.27%, CER 25.90%; no runtime failure'),
        ('Needle extraction / routing', 'FAIL_QUALITY_AND_INSUFFICIENT_DATA', '22 synthetic cases; English routing precision 0.50; never execute calls'),
        ('Code-switch speech / entity accuracy', 'PENDING', 'No adequate real labeled span/name/date/number set'),
        ('OCR / screenshot detection', 'PARTIAL', 'Native crop smoke only; Hindi CER 12.5%; no detector or real UI corpus'),
        ('Literal source retrieval', 'PASS_SYNTHETIC_SCOPE', '10,000 records; 100/100 Recall@5; 20/20 absent queries'),
        ('30-minute native workload', 'PASS_BASE_CONFIGURATION', '800 cycles; zero failures; other configurations pending'),
        ('Original 500 MB targets', 'EXCEEDED_USER_ACCEPTED_OPTIMIZATION', f"Staged {bundle['total_bytes']} bytes; RAM/commit by configuration retained"),
        ('Encryption / consent / provenance', 'PARTIAL', 'Wrong key, WAL, crash recovery, immutability, cascade, bounded-input tests passed'),
        ('Tamper / rotation / backup / full leakage audit', 'PENDING', 'Not all mandatory negative tests or recovery features implemented'),
        ('Network-restricted offline execution', 'PENDING', 'Local models used; network blocking/packet evidence not established'),
        ('Clean-machine Windows installation', 'PENDING', 'Existing host/runtime only; no consumer installer'),
        ('Android / Wear emulator / real watch', 'PENDING', 'No APK/device workload or physical-watch capture, thermals or battery tests'),
    ]
    write('release-gates.md', '# Engine V1 release decision: experimental developer proof only\n\n'
          'The complete product is **not release-ready**. Missing measurements stay pending and\n'
          'failed quality results stay failed. The user waived 500 MB as a feature blocker, accepted\n'
          '740 MB RAM and asked to retain features; no new hard ceiling is inferred.\n\n'
          '| Gate | Status | Evidence / limit |\n|---|---|---|\n' +
          ''.join(f'| {gate} | {status} | {evidence} |\n' for gate, status, evidence in gates) +
          '\nFixed targets are in ../docs/acceptance-gates.md. Scores are corpus-specific; a passing\n'
          'unit/integration suite is not a full privacy or multilingual certification. No UI, cloud\n'
          'inference, private-data training or autonomous remote actions were added.\n\n'
          'Next engineering priorities: improve Hindi ASR and extraction/routing on unseen data,\n'
          'implement text-box detection, complete privacy/recovery/offline tests, then profile\n'
          'target-device native integrations before the later app phase.\n')
    write('release-gates.json', json.dumps({'overall': 'EXPERIMENTAL_DEVELOPER_PROOF_ONLY',
          'production_release_ready': False,
          'budget_revision': '500 MB is an optimization target; user accepted 740 MB and retained features',
          'gates': [{'gate': g, 'status': s, 'evidence': e} for g, s, e in gates]}, indent=2))
    print('Generated comparison, Windows, retrieval and release-gate reports from executed evidence.')


if __name__ == '__main__':
    main()
