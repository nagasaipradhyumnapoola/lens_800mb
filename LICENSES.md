# Lens Micro dependency and attribution policy

Lens-specific source licensing has not been selected by the owner; it is not implicitly relicensed
by the licenses of its dependencies. This repository has not been published.

Full original notices for researched projects are in third_party/licenses. Immutable source pins
and notice SHA256 values are in third_party/upstream-lock.json. Downloaded models and native
Needle binaries have separate artifact SHA256s in third_party/model-lock.json.

| Component | License / use |
|---|---|
| whisper.cpp and bundled ggml/common utilities | MIT; compiled and linked unmodified |
| Whisper weights | MIT model card; immutable ggerganov/whisper.cpp revision |
| Cactus Needle Python tooling | Apache-2.0; copied checkout used for development binding comparison |
| Needle3 weights and published native engine | Published model repository LICENSE is Apache-2.0; included license copied with runtime; native runtime source unavailable for auditing |
| PaddleOCR / PP-OCR packs | Apache-2.0 project/model cards; official weights converted to ONNX for native recognition |
| PaddleX preprocessing/CTC conventions | Apache-2.0; adapted in native OCR with source attribution |
| ONNX Runtime | MIT plus bundled third-party notices; unmodified native DLLs; exact pins in ocr-runtime-lock.json |
| miniaudio | Dual public-domain / MIT No Attribution; bundled upstream decoder, full notice retained |
| SQLCipher | BSD-3-Clause (reviewed actual notice; GitHub API returned NOASSERTION) |
| sqlcipher-android | BSD-3-Clause; researched, not packaged |
| Microsoft vcpkg and reused SQLCipher build recipe | MIT; overlay version/digest changes documented in lens-provenance.json |
| OpenSSL | Apache-2.0; vcpkg copyright notice must accompany redistributed DLL |
| nlohmann/json | MIT; vcpkg copyright notice must accompany redistribution |
| sherpa-onnx | Apache-2.0; official v2.0.0 native runtime, pinned separately from research HEAD |
| Dolphin code and weights | Apache-2.0; official int8 sherpa model export, upstream license retained |
| ActivityWatch | MPL-2.0; reference only, no code copied |
| Pensieve | Apache-2.0; reference only, no UI or code copied |
| sqlite-vec | Actual notice Apache-2.0 (API NOASSERTION); not bundled |
| Vercel find-skills | MIT source in vercel-labs/skills; development instructions only |
| Google FLEURS | CC BY 4.0, attributed in docs/datasets.md; test-only, not shipped |
| intfloat/multilingual-e5-small | MIT (model card); unmodified ONNX INT8 export, pinned in third_party/embedding-lock.json |
| PowerShell 7.6.6 | MIT; official release zip placed under .tools by scripts/bootstrap_pwsh.py (third_party/pwsh-lock.json) |
| Windows ICU (icu.dll) | Operating-system component used for UAX #29 grapheme boundaries; not redistributed |
| Hugging Face tokenizers 0.22.1 | Apache-2.0; development-only parity reference, not shipped |

Other vcpkg dependencies (Tcl, libtommath, SQLite, zlib, minizip and build utilities) are build-time
dependencies; their port metadata/notices remain in the pinned vcpkg checkout. Plain SQLite is a
Tcl build dependency only; Lens persistence links SQLCipher explicitly and checks cipher support.
Development Python dependencies are pinned in requirements-dev.lock.txt and are not release files.
The user-installed billion-context Codex plugin is development tooling, not a Lens runtime dependency.
The local developer bundle relies on the Windows/MSVC runtime already installed on this host;
clean-machine redistribution and Microsoft runtime prerequisites remain a release check.

Before redistribution, generate an actual artifact bill of materials, include all transitive notices,
review runtime redistribution terms, and inspect the exact staged files. Researching a compatible
license does not establish that a complete release is licensed, secure or measured.
