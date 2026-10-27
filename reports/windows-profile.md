# Windows native engine measurements

Host inventory: environment.json / environment.md. Audited host is Windows 11 x64, Ryzen 9 270,
8 cores/16 threads and about 16 GB installed RAM. WMI exposed Radeon 780M; an NVIDIA GPU was
not verified. These runs used CPU inference. Other applications were active; this is one host/run.

The corrected workload completed 1800.49 seconds, 800
cycles, 0 failures and exit code 0.
Each cycle loaded Whisper Base Q5_1, transcribed the public 11-second JFK fixture, unloaded the
model, persisted/deduplicated the immutable source through SQLCipher and retrieved its text.
This is a repeated recorded-fixture workload, not 30 minutes of distinct live audio.

| Measurement | Actual value |
|---|---:|
| p95 complete cycle | 2325.75 ms |
| Average complete cycle | 2046.60 ms |
| Peak sampled working set | 184766464 bytes |
| Peak sampled private bytes | 693264384 bytes |
| Observed OS high-water commit | 693276672 bytes |
| Sampling interval | 20 ms |
| Samples / maximum observed processes | 49874 / 1 |

Engine SHA256: `6da3b517f184c0d47a1e0d12a82d51227430f408e9ba8dfbdac9cbb4dd239d76`. The isolated copy and current core EXE match.
The first run was interrupted for input-boundary fixes; its progress log is preserved and never
counted as a full-duration pass. Full evidence: windows-endurance.json and its .log.txt files.

This profile is the English Base configuration only. Selected Spanish/Dolphin configurations
have larger measured peaks in model-comparison.md; their own 30-minute cycles remain pending.
Private commitment above 500 MB is reported, not hidden by the smaller working-set figure.
Cold OS caches, suspend/resume and prolonged idle are not fully characterized.

## Actual developer bundle

Staged directory: `D:\Lens\artifacts\lens-micro-0.1.0-dev-20261025T220923Z`.
There are 54 files totaling **596,957,774 bytes**
(596.96 decimal MB), including selected models, both native ONNX
runtimes, SQLCipher/OpenSSL, C++ worker EXEs, client, dictionaries, manifests and notices.
There is no Python environment, model cache, upstream checkout, benchmark dataset or database.
The original 500 MB target is exceeded; the user explicitly requested preservation of features.
The bundle requires installed Windows x64, PowerShell 7 and MSVC runtime prerequisites. This is
an actual staged-file count, not a clean-machine installer or installed Android/Wear footprint.

The staged-folder check passed 18 checks, launching from an unrelated
temporary working directory: native audio for all four priority languages, OCR for each script,
encrypted persistence/reopen, source search, not_found and untrusted extraction proposals.
Fixture input paths refer to public/synthetic test data outside the bundle. Product processes
were staged native EXEs; Python was only the development controller. Network blocking was not
imposed; this does not satisfy the network-restricted offline gate. See staged-bundle-check.json.

Latest source suite: 29 executed, 0 failed,
0 errors, 0 skipped. See test-results.json.
