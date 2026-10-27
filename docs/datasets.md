# Dataset and fixture provenance

ASR smoke: Google FLEURS, CC BY 4.0, immutable dataset revision
`70bb2e84b976b7e960aa89f1c648e09c59f894dd`, test split. Data source and attribution:
[Google FLEURS dataset card](https://huggingface.co/datasets/google/fleurs).
Authors: Conneau et al., FLEURS: Few-shot Learning Evaluation of Universal Representations of Speech (2022).
No model tuning or training uses these fixtures. Upstream pretraining contamination is unknown.

Two first matching audio members per language archive, selected before scoring, with no quality
filtering. scripts/fetch_fleurs.py streams enough of each archive to obtain them; individual WAVs
and TSVs are SHA256-pinned, but full multi-hundred-MB archive digests are not verified. This is
explicitly a small convenience smoke set, not representative holdout certification.

Languages: English, Mandarin Chinese, Spanish, Hindi, French, German, Portuguese, Arabic,
Japanese, Korean, Tamil, Telugu, Malayalam, Kannada, Bengali and Marathi. The first four are
the launch priorities. Exact sample IDs, source URLs, native-script references and hashes are in
data/fixtures/fleurs-smoke.json. Audio/TSVs remain ignored under data/external.

Extraction fixtures are Lens-authored synthetic benchmark cases in extraction-smoke.json.
These are not real captured memories, independent translations verified by native speakers,
or sufficient evidence of broad language support. Routing cases include negation, irrelevant
queries and malicious instructions; no function is executed.

OCR smoke uses labeled synthetic rendered text crops, Nirmala/Arial/Microsoft YaHei fonts from
the existing Windows installation. Font files are neither copied nor redistributed. Windows WPF
does Hindi shaping where Pillow's RAQM is unavailable. These fixtures do not certify real UI OCR.

Priority-language holdout: 100 additional clips each for English, Mandarin Chinese, Spanish and
Hindi, skipping the first two smoke clips. IDs, immutable URLs and individual hashes are recorded
in data/fixtures/fleurs-priority-holdout.json. All 400 clips were evaluated without fine-tuning;
English/Spanish used Whisper and Mandarin/Hindi were also compared with Dolphin. Whisper Small
Hindi produced three invalid-UTF-8 CLI JSON exports, retained as failures. Automatic language ID
was not measured in configured-language holdout runs. This corpus does not establish noisy
conversation, domain-specific or code-switch performance.

Next certification sets: >=100 holdout clips for other supported languages, name/number/date-labeled
speech, >=50 licensed/consented code-switch clips per pair, >=100 authorized real UI screenshots
per script and unseen extraction/routing examples. No covert capture is used to obtain them.
Common Voice/other corpora require edition-specific license and access review before downloading;
no account agreement was accepted or gated data scraped in this session.
