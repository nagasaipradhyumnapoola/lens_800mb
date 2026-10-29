# Lens Micro Engine V1 — implementation decision

Status: the native proof is implemented; full distributed product scope was restored on 2026-10-26.
The authoritative specification is LENS_V1_SPEC.md, detailed in REQUIREMENTS.md. The earlier engine-only limitation is
superseded. Models and memory remain first; collectors/importers, trusted sync/execution and
Windows/Android/Wear clients are mandatory subsequent phases. Future platforms stay future.
Launch language priority (founder, 2026-10-28; supersedes the earlier en, zh, es, hi order):
English first, then Hindi, Mandarin Chinese and Spanish, followed by worldwide language coverage
(docs/LENS_V1_SPEC.md §1a). Lens is a global product; Indian-language testing is part of the
international matrix and does not define the product's geographic focus.
Budget: the 500,000,000-byte absolute ceiling for the complete Lens system (peaks, working set and
private commit) and the 50–100 MB idle target (founder, 2026-10-29; spec §15) supersede the earlier
800 MB ceiling and 740 MB acceptance; installed storage may reach 1 GB. Do not cut
requested functions to reach it.

## Selected approach and alternatives

Use a portable C++20 core with a C ABI at platform boundaries, pinned whisper.cpp for CPU ASR,
script-specific PaddleOCR candidates, SQLite FTS5 inside SQLCipher, and one active model at a time.
Python 3.12 is allowed only in the development/benchmark environment. This follows the supplied
architecture; no frontend framework, cloud service or paid dependency is selected.

Alternatives considered: Python-first packaging makes prototyping easier but imposes a packaged
interpreter and larger dependencies. A general-purpose quantized LLM would make fluent output
easier but has unproven accuracy/RAM within this budget. Neither is selected for V1.

## Boundaries

`audio -> ASR -> immutable observation -> extraction -> derived facts -> encrypted index -> retrieval`

Each adapter must support explicit load/run/unload, structured errors, cancellation, bounded inputs
and measurement. Audio is 16 kHz mono PCM; strings are UTF-8 and preserve native scripts.
The memory core must accept source ID, device ID, UTC capture time, language, source text,
confidence, consent scope and content hash. Derived facts have separate IDs and foreign keys to
originals; no summary can overwrite a source. Schema migrations are transactional/versioned.

Model scheduling is serial until combined-process measurements prove another policy is safe.
No embeddings are bundled initially; use exact phrase and FTS5 retrieval with source citations.
Languages without whitespace need evaluated segmentation/character search, not a claim that
default FTS5 tokenization provides adequate multilingual recall.

## Upstream caveats

The current Needle repository supplies Python reference/training code and prebuilt native engines;
it does not include the native runtime's C++ sources. Evaluate pinned binaries with
NEEDLE_TELEMETRY=0 and DO_NOT_TRACK=1, local paths and no automatic downloads during inference.
This is not a source-build or security-audit pass. Production adoption remains pending the
runtime-license review and resolution of source/audit requirements. Needle cannot execute actions:
its output is untrusted structured data; a separate consent/policy layer must authorize actions.

PP-OCRv6's unified pack is not an all-script recognizer. Tamil, Telugu and Devanagari require
their own available packs; Bengali, Kannada and Malayalam stay unverified until supported models
and real script fixtures pass. Do not silently substitute Latin OCR or translate originals.

SQLCipher is the only planned persistent personal database; plain SQLite is not a fallback.
Use OS keystore-protected random keys, never hardcoded keys. Encrypted backups, rotation,
wrong-key rejection, deletion, WAL/temp-file scans and recovery are separate gates.

## Future platform work (not implemented by model proof)

Windows capture requires explicit user opt-in. Android uses authorized OS mechanisms.
Wear listening is manually started/stopped with a visible recording state; independent local
inference must be measured on-device. No claims of app-history access or physical-watch testing.
Sync needs authenticated encryption, explicit pairing, replay counters, revocation, offline queue
and deletion propagation; same login alone is insufficient. No network sync in this phase.

## Versioning and release decision

This first artifact is `0.1.0-dev`, an experimental engine proof, not a trained foundation model.
Weights retain upstream identities/hashes. No personal inputs are used for fine-tuning.
Only measured functions can be promoted. A production framework, hardware promise or proprietary
runtime commitment requires a concrete decision after reports exist.
