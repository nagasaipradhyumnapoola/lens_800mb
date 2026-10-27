# Lens Micro Engine 0.1.0-dev

A functional, experimental local memory engine for Windows. Native C++ executables perform
speech recognition, cropped-text OCR, structured extraction and SQLCipher persistence. The
PowerShell client connects them; no Pytton interpreter or cloud model API is required by that
client. Python is used for model export, benchmarks and tests.

**Launch priority: English, Mandarin Chinese, Spanish and Hindi, then worldwide coverage.**
This is an engine proof, not a consumer app release. Hindi speech accuracy and Needle extraction
quality fail the current targets. Full-screen detection, automatic device observation, semantic QA,
backups/key rotation, encrypted sync, Android/Wear clients and real-watch validation remain pending.
No microphone, screen, notification or other private device capture was enabled.

## Run the existing native engine

PowerShell 7 is already installed on the audited machine. Start in `D:\Lens`:

```powershell
pwsh -NoProfile -File scripts/lens.ps1 -Action Stats
pwsh -NoProfile -File scripts/lens.ps1 -Action ImportAudio -Language en -SourcePath 'C:\YourFiles\consented-recording.wav'
pwsh -NoProfile -File scripts/lens.ps1 -Action ImportAudio -Language zh -SourcePath 'C:\YourFiles\consented-mandarin.wav'
pwsh -NoProfile -File scripts/lens.ps1 -Action ImportImage -Language es -SourcePath 'C:\YourFiles\consented-text-crop.png'
pwsh -NoProfile -File scripts/lens.ps1 -Action Search -Query 'Arun'
```

Replace example file paths with actual files you have permission to process. `ImportImage` accepts
a text crop; full screenshot text-box detection is not implemented. `Search` uses exact phrase
and literal substring retrieval, returning original sources; it does not answer arbitrary questions.
An unmatched query returns `not_found`. The client verifies selected weight/runtime digests.

By default, memories and the DPAPI-protected key are created under ignored `data/private/`.
Use `-DatabasePath` for another location. Keep the database and its `.key` together on the same
Windows user profile. The key file contains DPAPI ciphertext, not a plaintext password. Cross-device
key export/pairing is not implemented. Do not treat a copied key file as a portable backup.

Original text is immutable. Identical observations deduplicate; a conflicting existing source ID is
rejected. Source text, language, UTC import timestamp, device, confidence and provenance are stored
separately from derived records. Current file timestamps are **import time**, not proof of when the
speech originally occurred. Dolphin supplies no calibrated confidence: its source record uses a
conservative zero with `model_confidence:null` and an explicit provenance policy; zero is not an
accuracy measurement. Whisper token probability is also not measured accuracy.

Sensitive field types and known password/OTP/financial-secret labels are excluded by default.
This is a bounded heuristic, not proof that every secret is detectable. The CLI is a developer
interface; it does not establish whole-OS plaintext or shell-history privacy.

## Genuine demo and tests

```powershell
.venv\Scripts\python.exe scripts/native-demo.py
.venv\Scripts\python.exe scripts/test_all.py
```

The demo uses the public historical JFK WAV supplied by whisper.cpp, stores its actual transcript,
closes the process, decrypts/retrieves the same source, and checks an absent query. It is explicitly
a recorded-fixture demo, not a microphone or physical-watch test. Additional integration tests
exercise real Mandarin audio and native OCR through the PowerShell client.

Measured evidence: [model comparison](reports/model-comparison.md), [release gates](reports/release-gates.md),
[Windows profile](reports/windows-profile.md), [retrieval](reports/memory-retrieval.md),
[privacy/encryption](reports/privacy-and-encryption.md), [independent review](reports/independent-review.md).
All failed runs are retained. Test success is not a language-quality or production-security certification.

The checked native developer bundle is **596,957,774 bytes (596.96 decimal MB)** with all selected
models. Its path and per-file hashes are in reports/staged-bundle.json. The staged client passed
18 checks from a separate working directory, including audio/OCR imports for all four priority
languages. It uses this host's installed Windows/MSVC/PowerShell prerequisites; a clean-machine
installer is pending. Recreate and validate the explicit bundle with:

```powershell
.venv\Scripts\python.exe scripts/stage-native.py
.venv\Scripts\python.exe scripts/check-staged-bundle.py
.venv\Scripts\python.exe scripts/report-results.py
```

## Reproduce from the pinned source

Existing prerequisites: MSVC C++ tools, Visual Studio CMake, Git, Python 3.12/uv, PowerShell 7.
Do not rerun research_upstreams.py to reproduce a build: that command discovers new candidates.
Use the committed lock files instead:

```powershell
pwsh -NoProfile -File scripts/bootstrap-upstreams.ps1
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements-dev.lock.txt
.venv\Scripts\python.exe scripts/restore-artifacts.py
pwsh -NoProfile -File scripts/build-native.ps1 -Dependencies
```

OCR build/export uses an isolated conversion environment because Paddle2ONNX 2.1.0 does not load
with the reference environment's Paddle 3.2.2:

```powershell
uv venv --python 3.12 .tools/ocr-convert
uv pip install --python .tools/ocr-convert/Scripts/python.exe -r requirements-ocr-export.lock.txt
.venv\Scripts\python.exe scripts/prepare_native_ocr.py
.venv\Scripts\python.exe scripts/prepare_sherpa_reference.py
pwsh -NoProfile -File scripts/build-native.ps1
```

The export environment pins Paddle 3.1.1 and disables optional optimizer auto-installs. Re-exporting
may change serialization hashes: compare output locks intentionally rather than accepting drift.
The native OCR adapter is Windows WIC + unmodified ONNX Runtime + the official PaddleOCR models;
normalization/CTC handling follows PaddleX. Sherpa/Dolphin uses its published native C API.

## Reproduce benchmarks

```powershell
.venv\Scripts\python.exe scripts/fetch_fleurs.py
.venv\Scripts\python.exe scripts/benchmark.py
.venv\Scripts\python.exe scripts/benchmark_priority_holdout.py
.venv\Scripts\python.exe scripts/benchmark_native_needle.py
.venv\Scripts\python.exe scripts/benchmark_ocr.py
.venv\Scripts\python.exe scripts/benchmark_native_ocr.py
.venv\Scripts\python.exe scripts/benchmark_sherpa.py --holdout
.venv\Scripts\python.exe scripts/benchmark_retrieval.py
.venv\Scripts\python.exe scripts/profile_native.py --seconds 1800
```

Google FLEURS audio is CC BY 4.0 and attributed in [dataset provenance](docs/datasets.md). The 100
priority-language holdout clips exclude the first two clips used for the smoke/model comparison.
No fine-tuning or private-data training occurred. Benchmark outputs are generated from executed
inference. Hindi Whisper's three invalid-UTF-8 export failures stay counted; there is no lossy repair.

Budgets: the original 500 MB figures remain visible optimization targets. The user explicitly
accepted 740 MB RAM and instructed not to cut features for 500 MB. Reports retain larger model
configurations and exact working-set/private-commit measurements. These metrics are distinct;
staged-file size is not an installed Android/Wear application measurement.

## Source and scope

See [architecture](docs/architecture.md), [fixed quality gates and revised budgets](docs/acceptance-gates.md),
[dependency licenses](LICENSES.md), [skills](reports/skills.md) and immutable manifests under third_party/.
Upstream source/weights, development environments, public benchmark audio and personal databases
are separate from application source and ignored by Git. No repository was pushed or published.

The owner has not selected a license for Lens-specific source. Upstream licenses remain in force.
