# Reused dependencies and provenance

The core is an integration of maintained upstream components with small native adapters.
No foundation model was trained. Exact source/license pins are in third_party/upstream-lock.json;
build/runtime/weight hashes are in build-lock.json, model-lock.json, ocr-runtime-lock.json and
sherpa-reference-lock.json. Full original notices are under third_party/licenses.

| Component | Actual use / pin | License evidence |
|---|---|---|
| whisper.cpp / ggml | Native static inference, source 231638a0717b7822784297e5980965ffcec05810 | MIT; upstream notice retained |
| Whisper Base/Small Q5_1 | Unmodified multilingual HF weights, immutable revision and SHA256 | MIT model card / upstream notice |
| miniaudio | Upstream WAV decoding/resampling, preflight bound before allocation | Full dual-license notice retained |
| Needle3 | Official weights + Windows C API DLL; native implementation source unavailable | Model repository Apache-2.0 notice; no source-audit claim |
| PaddleOCR / PaddleX | Official v6 tiny Latin/Han and v5 Devanagari recognition packs; CTC/preprocessing adapted | Apache-2.0 notices and source attribution |
| ONNX Runtime | Unmodified Windows native DLLs; OCR 1.24.4 and separate sherpa dependency | MIT plus third-party notices retained |
| sherpa-onnx | Official v2.0.0 no-TTS native runtime, archive SHA256 verified | Apache-2.0 notice retained |
| Dolphin small int8 CTC | Published sherpa export; DataoceanAI source/license pinned | Apache-2.0 explicitly covering code and weights |
| SQLCipher | Native 4.19.0 community, FTS5 enabled; fail-closed cipher check | BSD-3-Clause full notice retained |
| OpenSSL | 3.6.5#2 through pinned vcpkg; SQLCipher crypto | Apache-2.0 full transitive copyright file retained |
| nlohmann/json | 3.12.0#2 C++ JSON parsing | MIT notice retained |
| vcpkg | 817892b0ecbc6af994dd6df999c73faf795adbf2 build recipes | MIT full notice retained |

The SQLCipher overlay reuses vcpkg's port with release/digest updates, mandatory SQLCipher 4.19
initialization/thread-safety defines and an added pkg-config template replacing an upstream-removed
template. Source and archive SHA512 are recorded in third_party/overlays/sqlcipher/lens-provenance.json.
Original failed builds remain available. Upstream ML engine implementations were not rewritten.

Paddle2ONNX export requires an isolated Paddle 3.1.1 environment; reference Paddle 3.2.2 failed
to import it and those errors were retained. Python dependencies and public benchmark data are
development-only. The staged bundle excludes Python, training tools, reference repositories,
datasets, source PDB/libs and private databases. Model selection retains current engine features;
Tiny/Q8 and Needle2 remain benchmark/reference artifacts rather than active defaults.

ActivityWatch, Pensieve, sqlite-vec and sqlcipher-android were researched only; their UI/code is
not copied into this engine. SenseVoice was not used because the reviewed licensing path did not
establish the intended use. Google FLEURS is CC BY 4.0, attributed in ../docs/datasets.md, test-only.

The user-requested billion-context Codex plugin and find-skills are development tools, excluded
from Lens runtime. The bundle relies on the existing Windows/MSVC/PowerShell prerequisites;
clean-machine installation and complete redistribution review remain pending. Lens-specific
source has no owner-selected distribution license. Nothing was pushed or published.
