# Lens Micro

Read docs/architecture.md and docs/acceptance-gates.md before changing scope.
The authoritative user specification is docs/product-requirements.md (restored 2026-10-26).
The complete deliverable is the distributed Lens system; the earlier engine-only scope is superseded.
Follow its dependency order: models, encrypted memory/context, authorized collectors/importers,
authenticated sync/execution, then Windows/Android/Wear clients and original UI. No fictional capabilities.
Preserve user files. Never push, publish, or change repository visibility without approval.
Use pinned upstream runtimes; Python is development-only. No cloud inference or private-data training.
No microphone, screen, notification, accessibility or other capture without specific consent.
Personal content must never enter Git, model weights, telemetry, logs or plaintext databases.
Keep originals immutable; derived records link to their sources. Retrieval can return not_found.
Models run serially and unload explicitly. RAM (founder, 2026-10-26): absolute 800,000,000-byte ceiling for
the complete always-on background system, idle target 50–100 MB. CPU-only inference is mandatory; never assume
CUDA, AVX2, a modern CPU or a dGPU; ISA extensions only behind runtime dispatch (docs/LENS_V1_SPEC.md §15).
Benchmark low-end tiers on real hardware, never extrapolate from the development laptop. Privacy, consent, provenance and correctness gates remain mandatory.
Record exact commands, hashes, dataset provenance and failed runs. Missing measurements never pass a gate.
Use .agents/skills/lens-benchmark, lens-privacy, lens-wear-validation and lens-release-gates when relevant.
No system-wide installs or privileged configuration changes without approval. Use existing tools and project-local dependencies.
