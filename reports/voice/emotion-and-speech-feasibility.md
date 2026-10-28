# Emotion/expression understanding and spoken replies — feasibility (2026-10-28)

Owner request (voice session): understand the emotional way of talking and expressions, and both listen and talk.
Status: NOT IMPLEMENTED. This note records what fits Lens's rules (CPU-only, 800 MB whole-system ceiling, one
speech model resident at a time, public/licensed data only, never the owner's voice for training).

## Already implemented in this area (measured, reports/voice/)

- Listening: lens-voice → restricted language ID (17 spec languages) → per-language ASR routing → stored memory.
- Who is talking: owner-only capture (`--enroll`, `--speaker-profile`). Held-out LibriSpeech: FAR 1.5%, FRR 5.3%
  at the dev-chosen threshold; other speakers' segments never leave lens-voice. Enrolment is a deliberate step.

## Emotion / expression — options

| Option | What it gives | Cost | Notes |
|---|---|---|---|
| Text emotion from the transcript, zero-shot NLI | joy/sadness/anger/fear/neutral… per memory | 0 new downloads: `models/MoritzLaurer--multilingual-MiniLMv2-L6-mnli-xnli` (MIT, INT8 118 MB) already installed | Text only: misses tone; quality per language unmeasured |
| Prosody features (pitch range, energy, speaking rate, pauses) | arousal / calm–excited, hesitation | DSP in lens-voice, ~0 MB | Language-independent; no categorical emotion |
| Acoustic speech-emotion model (emotion2vec+ base, SenseVoice-small tags) | categorical emotion from the voice | ~230–360 MB model, serial with ASR | Licence review needed first; SenseVoice covers zh/en/ja/ko/yue only |

Evaluation: ESD and RAVDESS are non-commercial → evaluation only (coordinator rule), never training.
Recommended order: (1) prosody + text emotion, stored as derived records with provenance and confidence,
excluded from answers until measured; (2) acoustic model after licence review and RAM measurement.

## Talking (spoken replies) — options

The pinned sherpa-onnx runtime is the `no-tts` build, so speech output needs a TTS-enabled sherpa-onnx release
(new runtime download) plus voices: Piper/VITS voices (~60–100 MB each, per language; Indian coverage limited) or
Kokoro multi-language (~330 MB; en/zh/ja/es/fr/hi/it/pt). It would run on demand, never while ASR runs.
Microphone + speaker together also needs echo handling so Lens never transcribes its own voice
(the owner-only gate already rejects non-owner voices, including a TTS voice, once enrolment is used).

## Not done / needs the owner's decision

- Which emotion option to build first, and downloads/licence review for acoustic SER and TTS.
- Live microphone remains NOT VERIFIED for these features; no capture without specific consent.
