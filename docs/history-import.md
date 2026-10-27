# Import selected historical exports

`scripts/import-history.ps1` imports one explicitly selected local export into the native SQLCipher store. Running this import action authorizes reading that file and importing its records; it does not connect to an account, open a browser, bypass encryption, or capture device activity. The production adapter uses PowerShell 7.5 or newer and .NET built-ins, with the existing native engine. The existing project runtime used for verification is PowerShell 7.6.5. JSON timestamps are explicitly parsed as strings to retain their original offset. Python is used only by development tests.

Each invocation validates the complete export in memory and sends one `import_batch` request to `build/engine/Release/lens-engine.exe --db <database>`. No plaintext intermediate file is created. The original selected file is opened read-only and never changed. Its SHA256 is computed from the original bytes, including a UTF-8 BOM if present.

## Supported inputs

| Format | Supported input | Required source-time information |
| --- | --- | --- |
| `WhatsApp` | Android `31/12/2020, 23:58 - Alice: message` and iOS `[12/31/2020, 11:58:59 PM] Alice: message` TXT exports, including multiline Unicode messages and timestamped system notices | Explicit `-DateOrder DMY` or `MDY` and `-SourceTimeZone`; two-digit export years additionally require `-TwoDigitYearCentury` |
| `LensJsonl` | Version-1 `lens-history` header followed by source records, as described below | Explicit RFC3339 timestamps and timezone fields in each source record |
| `Text` | One selected UTF-8 plain-text or Markdown file, imported as one source record | Explicit `-OriginalTimestamp`; optional `-SourceTimeZone` must agree with its offset |

Files must contain valid UTF-8, with an optional BOM. UTF-16, invalid UTF-8 and embedded NUL are rejected. Importing an entire folder, attachments, a WhatsApp backup database, email, a browser history database, or an account connection is not supported by this adapter. Select an exported file instead.

WhatsApp parsing supports slash or period date separators, four-digit years, 24-hour clocks, and English `AM`/`PM` clocks, optionally including seconds. Android uses ` - ` after the timestamp; iOS uses brackets. The adapter accepts left/right direction marks at the beginning of these headers and normal/nonbreaking/narrow-nonbreaking spaces in the timestamp separator. Other localized export layouts require a reviewed parser addition and are rejected when no supported header starts the export. No date order, timezone, century or source application is inferred from the system locale or filename.

Message text retains its internal line endings and Unicode. One line ending separating export records is removed, and the sender prefix is stored as metadata rather than message text. Timestamped system notices without `sender: ` retain their whole body and an empty sender. A continuation that has the exact syntax of another timestamped export header is indistinguishable from a record boundary in this unescaped TXT format; use the explicit JSONL format when that distinction matters. Media-placeholder messages remain text; attachment bytes are not imported.

## Examples

Run from the repository root using the existing project runtime:

```powershell
pwsh -NoProfile -File scripts/import-history.ps1 -Format WhatsApp `
  -SourcePath 'D:\SelectedExports\chat.txt' -DatabasePath 'D:\SelectedMemory\memory.db' `
  -DateOrder DMY -SourceTimeZone 'UTC+05:30'

pwsh -NoProfile -File scripts/import-history.ps1 -Format WhatsApp `
  -SourcePath 'D:\SelectedExports\ios-chat.txt' -DatabasePath 'D:\SelectedMemory\memory.db' `
  -DateOrder MDY -SourceTimeZone 'America/New_York' -TwoDigitYearCentury 2000

pwsh -NoProfile -File scripts/import-history.ps1 -Format Text `
  -SourcePath 'D:\SelectedExports\old-note.md' -DatabasePath 'D:\SelectedMemory\memory.db' `
  -OriginalTimestamp '2018-05-04T11:12:13+05:30' -SourceApplication 'MyNotes' -Language en

pwsh -NoProfile -File scripts/import-history.ps1 -Format LensJsonl `
  -SourcePath 'D:\SelectedExports\history.jsonl' -DatabasePath 'D:\SelectedMemory\memory.db'
```

The database's parent directory must already exist. It is supplied as an individual process argument, never interpolated into a shell command. Engine key protection and SQLCipher encryption follow the native store's existing behavior.

`-SourceTimeZone` accepts `UTC`, a fixed offset written exactly as `UTC+05:30` or `UTC-04:00`, or an installed .NET timezone identifier such as `America/New_York` or its Windows equivalent. Fixed offsets range from `UTC-14:00` to `UTC+14:00`. A fixed offset is an explicit claim about that export's local clock, not a daylight-saving rule. Named-zone times that fall in a daylight-saving gap or repeat are rejected; the adapter does not choose either possible offset. JSONL and Text timestamps must also agree with their named/fixed timezone. RFC3339 input requires `T`, seconds and a `Z` or numeric offset, with at most seven fractional digits; leap seconds are rejected by .NET validation.

`-TwoDigitYearCentury 2000` explicitly maps export years `00`–`99` to `2000`–`2099`; `1900` maps them to `1900`–`1999`. The argument must be a century divisible by 100. It is never selected automatically. For Text, an absent source time is an error: filesystem modification time is not substituted for original creation time. Supply an authorized known time or use a source format with explicit metadata.

`-Language` defaults to `und` for WhatsApp/Text. It is a caller annotation, not language identification. `-SourceApplication` defaults to `SelectedText` for Text; WhatsApp uses `WhatsApp`, and JSONL preserves the record's source application.

## Lens JSONL version 1

The first line is exactly a format/version object:

```json
{"format":"lens-history","version":1}
```

Each following line is one JSON object. This synthetic example is a complete record:

```json
{"id":"synthetic-original-7","text":"Synthetic old note: 北京","language":"en","timestamp":"2018-05-04T11:12:13+05:30","original_timestamp":"2018-05-04T11:12:13+05:30","observed_at":"2020-01-02T03:04:05Z","timezone":"UTC+05:30","device":"synthetic-export-device","kind":"imported_note","source_application":"SyntheticNotes","source_locator":"synthetic:note-7","provenance":"synthetic example only","consent_context":{"mode":"synthetic_prior_authorization"},"metadata":{"sender":"Synthetic Person"}}
```

All example keys are required. `original_timestamp` may instead be explicit JSON `null` when the originating system already records an unknown source time; the adapter does not synthesize an original date. A non-null original timestamp must identify the same instant as `timestamp`. Optional keys are numeric `confidence` in `[0,1]` and nonempty string `model_version`. Unknown top-level keys, unsupported versions, blank records, invalid JSON, duplicate JSON keys, comments, trailing commas, missing required fields, conflicting dates and invalid timezones reject the entire import. One trailing line ending is permitted. Use metadata objects for additional source fields rather than adding unversioned top-level fields.

The imported observation receives a stable ID derived from format, exact export SHA256 and record ordinal. The export's original ID remains in `metadata.source_record_id`; its source observation time remains in `metadata.source_observed_at`, and its source locator remains in `metadata.source_locator`. Existing source metadata remains present, with a complete copy under `metadata.export_metadata` so importer-owned field names cannot erase it. Prior authorization is preserved in `consent_context.source_context`. Prior provenance is included in the new provenance object. New `observed_at` is the current import clock, kept independently from the original source time. `consent_context.mode` is `user_selected_export`, and importer version/export hash are retained.

WhatsApp/Text use `device: "user-selected-export"` to mark that the source device is unknown; the importer does not invent a capture device. JSONL preserves its supplied device. All records use a content-addressed source locator, `sha256:<export hash>#record=<ordinal>`, rather than persisting the selected filesystem path. Retain the original export while you need to resolve that evidence hash.

## Limits and atomic results

The complete import must fit all of these bounds:

- Selected file: at most **16,777,216 bytes**.
- Source text per record: at most **1,048,576 UTF-8 bytes**; required IDs, provenance and metadata also obey the native field bounds.
- Record count: **1–128**. Larger exports are rejected before the database process starts; this adapter does not silently import only the first batch.
- Serialized native request including its newline: at most **2,097,152 UTF-8 bytes**. JSON escaping and metadata count toward this limit, so several individually valid large records can still exceed it.

Validation finishes before the native process starts. The engine's `import_batch` transaction commits every record or rolls back the complete batch, including a later native rejection such as sensitive-content exclusion. Reimporting the same exact export with the same parsing options returns existing canonical IDs and a deduplication count; the new observation/import clock is excluded from the native content hash. Changing the export bytes changes its identity, and changing source-time parsing options for an existing identity yields an immutable-source conflict instead of silently replacing records. This adapter does not claim cross-export semantic message deduplication.

Success exits `0` and emits one JSON object with `ok:true`, `atomic:true`, `partial:false`, `outcome:"committed"`, and record/import/dedup counts plus canonical source IDs. Validation failures and acknowledged native rollbacks exit `1`, report zero imported records, and distinguish `outcome:"not_started"` from `"rolled_back"`. Diagnostics contain fixed error codes and `history_import_failed`, without echoing selected paths, content, keys or raw native exception messages.

If a process failure or timeout prevents acknowledgment, a transaction can have committed before the response was lost. The adapter therefore reports `outcome:"unknown"`, `error:"native_outcome_unknown"` and `imported:null`, rather than claiming zero writes. Retry the identical export/options to resolve through stable IDs. `partial:false` describes the all-or-nothing transaction, not knowledge of its completion.

## Verification

The development-only command is:

```powershell
python -B -m unittest discover -s tests -p test_history_import.py -v
```

The tests generate synthetic exports in temporary directories and run the real PowerShell adapter plus native SQLCipher engine. They cover old and ambiguous dates, both TXT layouts, multiline CRLF/Unicode preservation, explicit centuries, daylight-saving rejection, JSONL validation and source context, whole-batch rollback, exact-export deduplication, notes, size limits and path/content-safe errors. No real conversations or credentials are used. The initial failing run is retained in `reports/verification-2026-10-26/history-import-red.log.txt`.
