## HIST-META-01 — Preserve historical source metadata independently of import time

> "Lens should identify supported export/import methods,
> obtain authorization, process the imported records,
> and preserve their source and timestamps."
> — User's attached brief, Part 9, `Pasted text.txt:L806-L808`
>
> "Every record should preserve appropriate fields:"
>
> "Source application"
>
> "Original timestamp"
>
> "Observation timestamp"
>
> "Time zone"
>
> "Consent context"
> — Same brief, Part 11, `L941`, `L949-L952`, `L958`

**Verdict:** partial · confidence: high

**Audit baseline:** `ff5e3dfa11594f62218ecfe81e7ef69cd2500104`. All code line citations below refer to that commit, before the orchestrator's subsequent implementation. A comparison against this commit returned no changes in the audited code and tests when read. This is a source audit, not a measurement or a claim about the provenance of an existing executable. No runtime tests were executed and no personal records, external services, or network resources were accessed. The only file written by this audit is this report.

**Specification identity:** `C:\Users\poola\.codex\attachments\8392976f-799c-40ac-80a5-b43fcdf5a248\Pasted text.txt`, SHA256 `5205865eb845f942a0e8cffc0c614d5461f06dcc2ba9e805d083bf3a453679d6`. This is the supplied specification, not an imported personal-content fixture.

---

**What this demands of an implementation:** A historical record's source time must survive import without becoming the time Lens observed/imported it. The record must preserve the applicable timezone, source application and consent context alongside those distinct times, and return that information with retained source evidence. These are data semantics, not a requirement to create one table per logical entity: the brief explicitly says "Do not blindly create separate tables when a simpler normalized design is better" (`Part 11:L938-L939`). A caller-supplied string can preserve a timestamp or timezone, but an implementation must actually carry the appropriate metadata through its supported import, persistence, deduplication and retrieval paths.

---

**Where enforcement lives:**

```cpp
// engine/store.cpp:L63-L64
CREATE TABLE observations(id TEXT PRIMARY KEY,text TEXT NOT NULL,language TEXT NOT NULL,captured_at TEXT NOT NULL,
device TEXT NOT NULL,kind TEXT NOT NULL,provenance TEXT NOT NULL,sha256 TEXT NOT NULL UNIQUE,confidence REAL NOT NULL CHECK(confidence>=0 AND confidence<=1));

// engine/store.cpp:L81-L83
if(!j.value("consent",false))throw Error("consent_required");
const auto id=required(j,"id"),text=required(j,"text",1024*1024),lang=required(j,"language",32),
    timestamp=required(j,"timestamp",64),device=required(j,"device"),kind=required(j,"kind",64),prov=required(j,"provenance",8192);

// engine/store.cpp:L96-L98
Statement s(db_,"INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?);");
int n=1;for(const auto& value:{id,text,lang,timestamp,device,kind,prov,content_hash})s.text(n++,value);
check(sqlite3_bind_double(s.p,9,confidence));s.step();
```

- The core preserves exactly one timestamp in `captured_at`, together with language, device, kind and opaque provenance. The insertion binds the supplied timestamp directly; the source serializer returns it as `timestamp` (`engine/store.cpp:L38-L40`, `L96-L98`, `L105-L108`). This is real partial support: a direct caller can provide a historical timestamp and get that same string back.
- `required` checks string presence/type, nonemptiness, size and embedded NUL only; it does not validate a timestamp, derive a second clock, parse a timezone, or parse provenance (`engine/store.cpp:L33-L37`, `L82-L83`). An offset embedded in the one timestamp string can survive, but no independent timezone field or interpretation is enforced.
- The consent Boolean gates insertion, but neither consent nor a consent context appears in the stored column set or returned source object (`engine/store.cpp:L63-L64`, `L81-L83`, `L96-L98`, `L38-L40`). This finding concerns retained consent context; it does not imply that the existing Boolean rejection is missing.
- Unrecognized JSON fields are not persisted: insertion and hashing construct explicit subsets and there is no generic request/metadata serialization on the add path (`engine/store.cpp:L82-L98`). Thus supplying `original_timestamp`, `observation_timestamp`, `time_zone`, `source_application` or `consent_context` at the top level does not preserve them.
- Deduplication hashes text/language/the single timestamp/device/kind/provenance/confidence and can return before insertion. Extra metadata changes are outside this hash and outside the conflict check (`engine/store.cpp:L89-L98`). They therefore cannot distinguish a new import context or create a retained metadata record.
- Original observations reject SQL updates, which preserves what was actually stored, including an incorrect import-time substitution. Derived records use a source foreign key, but the explicit `derive` operation is separate from add and search returns observations only (`engine/store.cpp:L65-L70`, `L105-L119`, `L121-L128`). The presence of arbitrary derived JSON is not an automatic historical-metadata path.

```powershell
# scripts/lens.ps1:L52-L54
$record=@{op='add';consent=$true;id=$Id;text=$Text;language=$(if($Language -eq 'auto'){'und'}else{$Language});
  timestamp=[DateTime]::UtcNow.ToString('o');device=[Environment]::MachineName;kind='manual_import';
  provenance='explicit local text import';confidence=1.0}
```

- The CLI has no original/observation time, timezone, application or consent-context parameters (`scripts/lens.ps1:L1-L5`). It initializes the one timestamp to the UTC import clock for all three import actions (`L50-L55`). Audio and image branches change recognition-related fields and provenance, but retain this import timestamp (`L69-L80`, `L97-L100`).
- Audio provenance records a recognizer provider and hashes, and image provenance records hashes and a text-crop scope. These identify processing artifacts/scope, not the historical source application and authorization context demanded by the audited requirement (`scripts/lens.ps1:L70-L71`, `L79`, `L98`). A manual direct caller could encode extra information inside the opaque provenance string, but no CLI parameter, enforced schema or metadata serializer establishes that contract (`L1-L5`, `L52-L54`; `engine/store.cpp:L33-L40`, `L82-L98`).
- The report generator explicitly describes the limitation: "All original timestamps in these file imports represent import time; no claim is made about recording creation time" (`scripts/report-results.py:L170-L171`). This corroborates the code; it is not used as a substitute for reading enforcement.

---

**Paths walked:**

| Entry path | Call chain and verified result |
| --- | --- |
| Direct JSON `add` | `engine/main.cpp:L17-L25` → `Store::request` → string/consent checks → explicit hash/dedup → nine-column insertion. One supplied time and provenance survive; independent metadata fields are dropped (`engine/store.cpp:L33-L40`, `L80-L99`). |
| Direct JSON `ingest_audio` | `engine/main.cpp:L18-L24` → `transcribe` → mutate only op/text/language/confidence → same add path. No-speech and transcription errors reject rather than insert. Consent is checked before audio read; returned `start_ms`/`end_ms` are relative segment offsets, not historical/observation wall-clock metadata (`engine/asr.cpp:L32-L69`; `engine/main.cpp:L19-L23`). |
| CLI `ImportText` | Parameter binding → shared record → `Memory` → native engine. Historical source time cannot be supplied through this interface; `UtcNow` becomes its sole stored timestamp (`scripts/lens.ps1:L1-L5`, `L31`, `L50-L54`, `L100`). |
| CLI `ImportAudio`, Mandarin/Hindi | Shared record → consented sherpa worker → copy recognized text/confidence/kind/provenance → `Memory` → add. The worker reads audio after consent and returns recognition/language data; its caller keeps the shared import clock (`scripts/lens.ps1:L52-L73`; `engine/sherpa_main.cpp:L21-L23`, `L54-L58`). |
| CLI `ImportAudio`, other branch | Shared record → set `ingest_audio`, paths, language/kind/provenance → `Memory` → engine audio path → add. No historical metadata enrichment occurs (`scripts/lens.ps1:L74-L80`; `engine/main.cpp:L18-L24`). |
| CLI `ImportImage` | Shared record → consented OCR worker → copy text/confidence/kind/provenance → `Memory` → add. Image bytes are decoded for recognition; the worker returns text/confidence/runtime/scope, and neither it nor its caller extracts a source date or application (`scripts/lens.ps1:L82-L99`; `engine/ocr_main.cpp:L26-L40`, `L79-L88`). |
| Search, FTS and literal fallback | Both queries select the same nine observation fields and use the same serializer. Neither can recover metadata never stored. Both order on the single `captured_at` field (`engine/store.cpp:L38-L40`, `L105-L119`). |
| Database reopen/versioning | Constructor reads `user_version`, rejects versions above 1, and creates only the version-1 observation/derived/FTS schema for a new database. No metadata side table or later migration exists (`engine/store.cpp:L43-L74`). |
| Key adapter | Store calls `load_or_create_key`; it decrypts a per-user DPAPI key or creates/protects a random key. No observation/request metadata passes into this function, so key storage does not supply missing source metadata (`engine/store.cpp:L43-L50`; `adapters/windows/key_store.cpp:L13-L41`; `engine/store.hpp:L6-L15`). |
| Other operations | `derive` writes separate linked JSON; `delete` removes an observation; `stats` returns counts/schema/cipher versions; unsupported operations throw. None enriches the imported source metadata (`engine/store.cpp:L121-L141`). CLI `Extract` invokes the standalone proposal worker and does not insert into memory (`scripts/lens.ps1:L39-L49`). |
| Build configuration | `lens-store` is built from `store.cpp` and the Windows key adapter, and `lens-engine` from `main.cpp`/`asr.cpp`. Its compile definitions are `SQLITE_HAS_CODEC`/`NOMINMAX`; the inspected schema/metadata logic has no alternate debug/release branch (`engine/CMakeLists.txt:L42-L56`; `engine/store.cpp:L43-L143`). |

---

**Tests inspected:**

- The common integration fixture provides one timestamp and a provenance string (`tests/test_engine_integration.py:L22-L25`). Its source-search assertions check content/ID and reopening (`L27-L44`); the audio test explicitly checks that one supplied timestamp survives (`L103-L113`). These establish the partial single-time behavior.
- Consent rejection checks a false Boolean and zero source count, without asserting any retained authorization context (`tests/test_engine_integration.py:L57-L67`). Dedup/immutability tests do not vary independent source time, timezone, application or consent context (`L27-L44`).
- CLI tests import text, an image and Mandarin audio, then assert source content/ID and confidence. They do not supply or assert historical time or other independent metadata (`tests/test_cli.py:L16-L36`). No existing test found by the baseline metadata vocabulary searches below covers those fields. This is test coverage inspection, not a test run.

---

**Searched:**

The following commands were run locally from `D:\Lens`. `ff5e3df` resolves to the full audit baseline above. Successful broad matches were followed into the cited code, rather than treated as enforcement.

```powershell
git rev-parse ff5e3df
git diff ff5e3df -- engine/main.cpp engine/store.cpp engine/store.hpp scripts/lens.ps1 adapters/windows/key_store.cpp engine/asr.cpp engine/sherpa_main.cpp engine/ocr_main.cpp engine/CMakeLists.txt tests/test_engine_integration.py tests/test_cli.py
git grep -n -E 'original_timestamp|observed_at|observation_timestamp|imported_at|time_zone|timezone|source_application|source_app|consent_context' ff5e3df -- engine adapters scripts/lens.ps1 tests/test_engine_integration.py tests/test_cli.py
git grep -n -i -E 'original[_ -]?(timestamp|time)|observ(ed|ation)?[_ -]?(at|timestamp|time)|import(ed)?[_ -]?(at|timestamp|time)|time[_ -]?zone|(^|[^a-z])tz([^a-z]|$)|source[_ -]?(app|application)|consent[_ -]?(context|scope|record|evidence)' ff5e3df -- engine adapters scripts tests docs
git grep -n -E 'Store|INSERT INTO observations|CREATE TABLE|ALTER TABLE|user_version|captured_at|timestamp' ff5e3df -- engine adapters scripts tests
git grep -n -i -E 'created[_ -]?(at|time)|creation[_ -]?(date|time)|event[_ -]?(at|time)|source[_ -]?time|offset|iso.?8601|rfc.?3339|gmt|utc|authorization|authorisation|permission|consent' ff5e3df -- engine adapters scripts/lens.ps1 tests/test_cli.py tests/test_engine_integration.py
git grep -n -E 'store\.request|Store::request|load_or_create_key' ff5e3df -- engine adapters scripts tests
git ls-tree ff5e3df -- engine/store.cpp engine/store.hpp engine/main.cpp engine/asr.cpp engine/sherpa_main.cpp engine/ocr_main.cpp engine/input.hpp engine/CMakeLists.txt adapters/windows/key_store.cpp scripts/lens.ps1 tests/test_engine_integration.py tests/test_cli.py
Get-FileHash -LiteralPath 'C:\Users\poola\.codex\attachments\8392976f-799c-40ac-80a5-b43fcdf5a248\Pasted text.txt' -Algorithm SHA256
```

- Baseline diff: 0 output, exit 0 at audit time.
- Exact metadata-field sweep: 0 hits, exit 1. This does not alone establish the finding; the explicit schema, read/write bindings and wrapper paths above do.
- Broad metadata vocabulary sweep: finds the observation schema and its existing operations, benchmark/environment clocks, import-time documentation and the architecture's stated consent scope. It finds no independent original/observation timestamp, timezone, source-app or consent-context enforcement in the source paths. The loose observation pattern also matches ordinary `observations` names; those false-positive matches were read.
- Schema/timestamp sweep: 32 matching lines (verified with `@(git grep ...).Count`). There is one observation timestamp column, one observation insertion, version-1 creation, and no `ALTER TABLE` migration. Other time hits are benchmark/demo/controller timestamps or ASR print options.
- Alternate vocabulary/consent sweep: 15 matching lines (verified with `@(git grep ...).Count`), all Boolean consent checks/fixtures and the shared UTC import clock. No hidden creation-date/offset/application/consent-context extractor appears.
- Callsite/key sweep: 6 matching lines: two `store.request` callers, the `Store::request` definition, the key call and its definition/declaration. Both store callers were walked.
- Initial discovery used `rg --files` over engine/adapters/tests/scripts/docs and `rg -n` metadata vocabulary over docs/engine/scripts/tests/reports. Two scope-expansion searches returned exit 1 because `.planning` and `reports/compliance` did not exist at that time; those missing directories are not treated as evidence of absent implementation. The subsequent baseline Git searches above completed over all tracked enforcing paths.
- Full numbered file reads used `$n=0; Get-Content -LiteralPath '<path>' | ForEach-Object { $n++; '{0,4}: {1}' -f $n,$_ }` for the code paths and tests cited above. The supplied brief was read with the same counter, restricted to lines 780–1050. `docs/architecture.md` and `docs/acceptance-gates.md`, plus the assigned checker and `ANALYSIS_FORMAT.md`/`DOMAIN_NOTES.md`, were read before analysis.

Key baseline Git blob identities: `engine/store.cpp` = `455a729fa53ab3f4d7094bfb8e443369b2a90120`; `engine/main.cpp` = `96555a2402371f9b6fc59708565bcecb2bdd5d9a`; `scripts/lens.ps1` = `fc1c0a1263ca269586f2f21c0790ddf124bc4f96`; `tests/test_engine_integration.py` = `fa53028c1d806c1938c67884bf692723ca473bc0`; `tests/test_cli.py` = `8996bfad4dd46fb5d5ecf97c646ab9b4b829a29e`. These are Git blob object IDs, not SHA256 digests of model weights.

---

**Concrete failure paths:**

1. An old transcript or image imported through the CLI receives today's UTC time even when its historical source date is known. The interface cannot carry that source date or source application; every import branch inherits the initializer (`scripts/lens.ps1:L1-L5`, `L52-L54`, `L69-L80`, `L97-L100`). Search consequently returns import time under the sole `timestamp` property (`engine/store.cpp:L38-L40`, `L105-L119`).
2. A direct `add` request containing distinct `timestamp`, `original_timestamp`, `observation_timestamp`, `time_zone`, `source_application` and `consent_context` can report success, but only `timestamp` from that group is inserted and returned. The other fields are outside the explicit storage subset (`engine/store.cpp:L82-L99`, `L38-L40`).
3. Repeating the same stored fields with a changed source application or consent context is considered the same hashed record, because those independent fields are excluded. The duplicate return has no write that could retain the second context (`engine/store.cpp:L89-L98`).
4. Supplying a historical value in the one `timestamp` slot preserves that historical string but leaves no independent observation/import clock. Supplying import time instead loses a separately queryable historical time. The schema/serializer have only that one slot (`engine/store.cpp:L38-L40`, `L63-L64`, `L96-L98`).

These are source-derived counterexamples, not executed reproductions. They use only hypothetical/synthetic metadata.

---

**How the verdict was reached:** `partial` fits because the native add and audio paths really preserve a supplied timestamp and provenance, consent can reject ingestion, and stored originals are immutable. `implemented` fails because the existing supported CLI paths substitute import time and the native contract does not independently retain the requested metadata. `absent` would erase the working single-time/provenance behavior. The entire requirement is not categorized `contradicted` because direct callers can preserve a historical timestamp or embed metadata in provenance; the CLI's specific substitution is the incompatible path within a partially implemented requirement (`engine/store.cpp:L38-L40`, `L63-L70`, `L80-L99`; `scripts/lens.ps1:L52-L54`).

---

**Safest schema-compatible implementation recommendations (not changes made by this audit):**

1. Introduce an explicit version-2 migration inside a transaction. An additive, foreign-key-linked metadata table avoids rewriting existing immutable observations, their content hashes and FTS rowids. If adding columns instead, first replace the positional `INSERT INTO observations VALUES(...)` with an explicit column list; the baseline insertion assumes exactly nine columns (`engine/store.cpp:L96-L98`). Update the constructor's `v>1` rejection and reported schema version together (`L54-L72`, `L138-L139`).
2. Preserve a raw original timestamp plus an independently supplied/recorded observation timestamp, timezone, source application and structured consent context. Keep any normalized UTC representation additional to the raw source value. Represent unavailable source time/zone/application/context explicitly as unknown; never backfill a fabricated historical creation time from the old ambiguous `captured_at` or filesystem modification time. Existing version-1 rows need an explicit legacy/unknown interpretation, since both historical caller timestamps and wrapper import timestamps use the same slot (`engine/store.cpp:L83`, `L97`; `scripts/lens.ps1:L53`).
3. Validate the metadata before committing any source record and write source plus metadata atomically. Preserve the existing consent rejection and source-conflict rule; keep metadata immutable while retained and linked with deletion cascading. Do not hide recognized metadata in an unvalidated string or silently ignore it (`engine/store.cpp:L65-L70`, `L81-L98`, `L130-L133`).
4. Decide whether import events are one-to-one source metadata or a separate one-to-many record. If repeated imports may have distinct observation/consent contexts, retain those events against the canonical source ID even when source-content deduplication succeeds. Otherwise use a versioned metadata-aware identity/conflict check. Do not rewrite version-1 hashes or silently deduplicate differing independent metadata under the old subset (`engine/store.cpp:L89-L98`).
5. Extend the shared CLI record builder and parameters, then propagate the same metadata through text, both audio branches and image imports. Take original metadata from an authorized export/parser or explicit caller input; the UTC clock can populate observation/import time only. Return all retained fields from both source-search branches (`scripts/lens.ps1:L1-L5`, `L50-L100`; `engine/main.cpp:L18-L25`; `engine/store.cpp:L105-L119`).
6. Verify with synthetic historical metadata: distinct old original time/new observation time, offset/zone preservation, source application and consent-context round-trip after close/reopen; direct add/audio and each CLI branch; invalid/missing metadata behavior; changed-metadata dedup/conflict semantics; migration of a real version-1 fixture without changing its source bytes/hash; atomic rollback and cascade deletion. These tests close gaps in the baseline's single-timestamp and Boolean-only assertions (`tests/test_engine_integration.py:L22-L44`, `L57-L67`, `L103-L113`; `tests/test_cli.py:L16-L36`).

---

**Open questions / limits:**

- The brief does not prescribe a timestamp serialization, timezone identifier format, consent-context object schema, or repeated-import event policy. Those representation choices remain implementation decisions; their absence from the brief does not make the independent metadata requirement undecidable.
- No executable was run, no database was created/decrypted, and no existing private import was inspected. Runtime reproduction and the orchestrator's subsequent fixes must be assessed separately from this pinned baseline report.
