# Lens — product vision

Lens is the local-first perception and long-term memory engine of Second Brain AI's unified Recursion
application. There is one product, Lens V1, with platform clients (Windows, Android and Wear OS) sharing one
memory architecture, one data format, one retrieval contract and one privacy model.

## What Lens must do

- Observe only what the user authorises (screen text, speech, imported history), with visible controls and pause.
- Keep every captured original immutable and encrypted on the device; derived records link to their sources.
- Answer natural-language questions across languages and code-switched text and speech, returning the original
  evidence with time and source, or an explicit "not found" instead of a guess. English is the primary language,
  followed by Hindi, Mandarin Chinese and Spanish, then the other specified languages (docs/LENS_V1_SPEC.md §1a).
- Understand time ("last week"), people, applications, projects and changed facts (original versus latest).
- Keep the complete Lens system within 500,000,000 bytes of RAM at peak, with an idle target of 50–100 MB, on
  CPU-only and low-end hardware, using at most 1 GB of storage (docs/LENS_V1_SPEC.md §15).
- Run on every major operating system — Windows, macOS, Linux, Android, iOS — from one portable core; Windows first.
- Synchronise and act across the user's paired devices only through authenticated, end-to-end encrypted channels
  and deterministic permission checks; a model may propose an action, never authorise it.

## Principles

- Models process; the encrypted memory remembers. No personal data in model weights, logs or telemetry.
- No cloud inference, no paid model APIs, no covert capture.
- Only measured, independently verified behaviour is reported as working (docs/VERIFICATION.md).
