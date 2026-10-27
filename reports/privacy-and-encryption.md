# Privacy and encryption evidence

This is a bounded engineering review of the Windows developer engine. A complete privacy gate
is pending; encryption does not itself prove whole-system privacy.

SQLCipher 4.19.0 is linked explicitly. The store checks cipher_version and fails if cipher support
is absent. A random 32-byte key is generated with Windows BCrypt and protected using per-user
DPAPI in a sidecar .key file; key buffers are cleansed. The database uses encrypted WAL, memory
temporary storage, secure_delete, cipher_memory_security and foreign-key enforcement.
No private memory enters model weights. Models are upstream inference artifacts.

Executed negative/regression tests in test-results.json and tests-release-check.log.txt cover:

- Reopening the encrypted store, rejecting a wrong key, absent plaintext SQLite signature and
  absence of synthetic plaintext markers in database/WAL while live and after crash recovery.
- Required import consent; default sensitive field/known-secret-label exclusion; immutable IDs,
  deduplication, source foreign keys, deletion cascading and removal from search.
- Bounded JSON before full allocation, encoded-file/decoded-audio limits, embedded-NUL rejection,
  generic diagnostic codes rather than private paths, and rejecting incorrect ONNX output types.
- Native speech/OCR to encrypted memory and source retrieval, preserving Unicode originals.

The corpus consists of public audio and explicitly synthetic sentinels/crops. No real private
microphone, screen, notification, accessibility or background device capture was enabled.
File imports are manually requested. Their timestamps mean UTC import time, not recording time.
No remote actions execute from extraction results. Needle's output is an untrusted proposal.
The heuristic secret filter is not comprehensive secret detection. Shell history, terminal output,
process memory, paging, crash dumps and filesystem/SSD snapshots need separate controls/auditing.

Needle telemetry opt-outs are set before DLL load; OCR telemetry is disabled through ORT's API
and log callbacks are quiet. No model API or auto-download is called by Lens native/client code.
However, binary dependencies include code not fully source-audited (especially Needle), and a
network-restricted run/packet-level audit was not performed. The offline/egress gate stays pending.
The separately requested billion-context Codex plugin is developer tooling, never a Lens runtime
dependency. It was installed without starting its proxy or rerouting this conversation.

Outstanding checks/features: systematic ciphertext tamper/integrity tests, robust recovery and
portable encrypted backups, key rotation/export/pairing, full log/temp/backup/egress audit, ACL
hardening and migration failure recovery. DPAPI keys are profile-bound; copying a sidecar to
another machine is not a supported backup. Deletion is logical, not certified forensic erasure.
Physical-watch permissions, recording indicator and battery/privacy behavior remain untested.
