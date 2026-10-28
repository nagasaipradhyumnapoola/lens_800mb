# Lens

Lens is the local-first perception and long-term memory subsystem of Second Brain AI's Recursion application.
It observes only what the user authorises (screen text, speech, imported history), stores every original
record encrypted on the device, organises it into episodes, entities, facts and projects, and answers
natural-language questions with the original evidence, or with an explicit "not found".

## Status

Lens V1 is under development and is not release-ready. Current capability status is maintained in
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md), release gates in
[docs/RELEASE_READINESS.md](docs/RELEASE_READINESS.md), and all measurements with their evidence in
[docs/VERIFICATION.md](docs/VERIFICATION.md). Only executed, recorded results are reported as working.

## Documentation

| Document | Content |
|---|---|
| [docs/LENS_V1_SPEC.md](docs/LENS_V1_SPEC.md) | Canonical product specification |
| [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) | Detailed requirements register (machine-readable: [docs/requirements.json](docs/requirements.json)) |
| [docs/acceptance-gates.md](docs/acceptance-gates.md) | Acceptance gates and hardware tiers |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Architecture as built |
| [docs/retrieval.md](docs/retrieval.md) | Retrieval design and decisions |
| [docs/history-import.md](docs/history-import.md) | Historical data import |
| [docs/LENS_MODEL.md](docs/LENS_MODEL.md) | Trained Lens model: architecture and training plan |
| [docs/datasets.md](docs/datasets.md) | Dataset provenance and licences |
| [docs/HANDOFF.md](docs/HANDOFF.md) | Engineering handoff: how to build, test and continue |
| [AGENTS.md](AGENTS.md) | Mandatory engineering rules |
| [LICENSES.md](LICENSES.md) | Third-party licences |

## Components

| Component | Role |
|---|---|
| `lens-agent` | Always-on owner process: engine, consented capture, device link, consolidation, approvals |
| `lens-engine` | Encrypted store (SQLCipher), indexing, retrieval, speech recognition, lifecycle operations |
| `lens-observer` | Consent-gated Windows observation: UI Automation text first, OCR fallback |
| `lens-ocr` | Screen text detection and script-routed recognition (PaddleOCR models, ONNX Runtime) |
| `lens-voice` | Consent-gated microphone capture with voice-activity detection and language routing |
| `lens-app` | Windows application (Win32 + WebView2) |
| `lens-mesh` | Authenticated, encrypted link to paired devices |
| `android/` | Android and Wear OS companions (Kotlin, Jetpack Compose) |
| `lens_model/` | Training, export and evaluation of the Lens model (development only) |

The core is C++20. Python is used only for development, benchmarks, training and tests; it is never a
runtime dependency of the product.

## Building

Prerequisites: Windows 11 x64, Visual Studio with MSVC C++ tools and CMake, Git, Python 3.12 with uv,
and the project-local PowerShell 7.6.6. Dependencies are restored from the committed lock files:

```powershell
.venv\Scripts\python.exe scripts/bootstrap_pwsh.py
pwsh -NoProfile -File scripts/bootstrap-upstreams.ps1
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements-dev.lock.txt
.venv\Scripts\python.exe scripts/restore-artifacts.py
pwsh -NoProfile -File scripts/build-native.ps1 -Dependencies
uv venv --python 3.12 .tools/ocr-convert
uv pip install --python .tools/ocr-convert/Scripts/python.exe -r requirements-ocr-export.lock.txt
.venv\Scripts\python.exe scripts/prepare_native_ocr.py
.venv\Scripts\python.exe scripts/prepare_sherpa_reference.py
pwsh -NoProfile -File scripts/build-native.ps1
```

OCR model export runs in the isolated `.tools/ocr-convert` environment because Paddle2ONNX 2.1.0 does not load
with the development environment's Paddle. Re-exports are compared against the lock files; drift is never
accepted silently.

## Testing

```powershell
.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

Tests use temporary directories and invisible test windows only; they never read the real screen or open the
microphone. The Android companion builds with `android\gradlew.bat` (JDK 17).

## Packaging

```powershell
.venv\Scripts\python.exe -B scripts/package_lens.py
powershell -NoProfile -File scripts/install_lens.ps1
powershell -NoProfile -File scripts/uninstall_lens.ps1
```

The installer is per-user and requires no administrator rights. Screen and microphone capture remain off until
the user enables them in the application. Uninstalling keeps the encrypted memories unless removal is requested.
Release artifacts are not yet code-signed.

## Benchmarks

| Area | Script |
|---|---|
| Retrieval | `scripts/benchmark_retrieval_nl.py` (tuning on the dev split only), `scripts/verify_retrieval_report.py` |
| Screen OCR | `scripts/benchmark_ocr_native.py`, `scripts/benchmark_ocr_memory.py`, `scripts/benchmark_ocr_latency.py` |
| Voice | `scripts/benchmark_voice.py` |
| Observation language ID | `scripts/benchmark_observer_lid.py` |
| Storage and import | `scripts/benchmark_storage.py`, `scripts/benchmark_history_import.py` |
| Resources | `scripts/sustained_run.py`, `scripts/profile_combined.py` |
| Hardware compatibility | `scripts/hardware_profile.py`, `scripts/check_hardware_compat.py` |

Sealed holdout sets are never used for tuning. Every run, including failed runs, is retained under `reports/`.

## Privacy

Capture requires explicit, source-specific consent and can be paused at any time. Personal content never enters
version control, model weights, telemetry or logs. There is no cloud inference. Deletion removes derived records
together with their sources.

## Licence

No licence has been granted for the Lens-specific source code; all rights are reserved by Second Brain AI.
Third-party components remain under their own licences ([LICENSES.md](LICENSES.md), `third_party/licenses/`).
