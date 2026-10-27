# Independent memory V2 contract review — 2026-10-26

Verdict: **partial compliance for this memory V2 increment**, with three confirmed P2 correctness findings below. The six authored V2 tests pass, and focused migration/rollback/recovery checks preserve synthetic sources. This review does not certify the complete product, retrieval quality, privacy gates, or all Part 14 capabilities.

Read-only review; implementation and tests were not edited. All dynamic inputs were synthetic and used temporary encrypted databases; no model inference, private data, downloads, installations or old-report changes occurred. This is the scoped independent reviewer for the parent spec-to-code compliance work, not a claim that the skill's full per-requirement/refutation workflow ran inside this subtask.

## Snapshot and coverage

Reviewed uncommitted `engine/store.cpp`, `engine/sql.hpp`, `engine/memory_query.cpp` and their headers, `engine/main.cpp` caller/error behavior, `engine/input.hpp`, Windows key storage, CMake linkage, `tests/test_memory_v2.py` and `tests/test_engine_integration.py`. Compared with the HEAD v1 store and `docs/product-requirements.md`, particularly lines 943–982 (metadata, recoverability, migrations, transactions, deduplication, concurrency, WAL/reopening), 1084–1129 (filtered/multilingual retrieval, relevant excerpts, evidence and abstention), and context assembly at 897–902. The parent reports the old 29-test baseline passed before changes; that entire baseline was not rerun here because it includes model inference excluded by this review's scope.

Reviewed artifact identities:

| File | SHA256 |
|---|---|
| `engine/store.cpp` | `524f7bec9a986c762c0399881a61e84be7903b6528a218c844846fc7f9ba704c` |
| `engine/sql.hpp` | `5cfc53a2b804e3fe95b5c2e39d16404a2d737afd96e11468450fcf579d05d7f7` |
| `engine/memory_query.cpp` | `39694088aa5bccbc8f1415253fc4d6882b77dfd841eaf64cbc84362ea7cd31ba` |
| Native `build/engine/Release/lens-engine.exe` tested | `574b66c080661925af3c730c192f480a04d23b0bbddf027b99ceb78876026e8b` |

Line evidence below refers to this snapshot. Later working-tree changes need fresh verification.

## Confirmed actionable findings

### P2 — Preserve fractional instants in filters and timestamp consistency checks

**Specification:** original timestamp/time zone preservation (950–952), time-filtered retrieval (1086), and actual historical evidence (1114–1122).

**Code:** `engine/sql.hpp:35` accepts one through nine fractional digits, but `epoch()` at line 47 constructs whole seconds and discards the fraction. `engine/store.cpp:95` stores that value as `event_seconds`; line 98 uses it to compare original/source timestamps. `engine/memory_query.cpp:20`–21 binds whole-second bounds and line 32 rejects ranges after the same truncation.

**Confirmed native behavior:** add an observation at `2020-06-01T00:00:00.100Z`. A valid `[00:00:00.200Z,00:00:00.800Z)` range returns `invalid_time_range`; `from=00:00:00.500Z` incorrectly includes that earlier observation; `to=00:00:00.500Z` incorrectly excludes it. An add with `timestamp=...00.100Z` and `original_timestamp=...00.900Z` is accepted despite the different instants.

**Consequence:** legitimate imported records fall on the wrong side of supported filters, valid intervals are rejected, and contradictory timestamp evidence is accepted. Time-zone offsets at whole-second boundaries passed the existing V2 test; the defect is precision loss, not an observed offset-sign error.

**Fix direction:** preserve full accepted precision in an orderable normalized representation and use it consistently for storage, comparison, ordering and bound validation; handle legacy records without inventing unknown fractions. If only second precision is intentionally supported, reject fractional input explicitly and document that narrower contract rather than silently accepting and changing it. Add boundary tests with fractions and equivalent offset forms.

### P2 — Choose matching evidence before applying the context byte budget

**Specification:** relevant answer/excerpt (1099), project-related segments (1118), evidence-grounded response (1120), and preparing only needed context (897–902).

**Code:** retrieval correctly finds a matching source, but `engine/memory_query.cpp:82`–88 always copies the first `n` bytes of its text. It does not find a segment containing the matched term before truncation.

**Confirmed native behavior:** store `('irrelevant preface ' * 60) + ' Orion meeting at 09:00.'`, then call `retrieve_context` with `query='Orion'` and `max_context_bytes=256`. It returns `not_found=false`, a truncated 256-byte quote, and a match explanation, but the quote contains no `Orion` or meeting evidence.

**Consequence:** the bounded context supplied to a later model/agent can omit all supporting answer detail even though the full source has it. The source identifier remains recoverable, so this is a context relevance/evidence defect, not permanent source loss or a claim that the quote text was fabricated.

**Fix direction:** assemble a UTF-8-safe relevant excerpt around matching evidence (and expose byte/character offsets if excerpts start mid-source), then apply the budget. If no useful evidence fits, explicitly signal that detail recovery is required instead of returning unrelated prefix text as the contextual evidence. Preserve an exact `find_source` recovery path.

### P2 — Hash canonical stored metadata rather than optional-field presence

**Specification:** content hash (954), stable provenance fields (949–958), deduplication (976), and transactional import (972).

**Code:** `engine/store.cpp:100`–103 applies defaults for omitted metadata, but line 105–106 only places optional fields into the hash when they existed in the incoming JSON. The stored default value and an identical explicitly supplied value therefore produce different hashes. The same-ID check at line 110 reports `immutable_source_conflict`.

**Confirmed native behavior:** add a record with all optional V2 fields omitted. Re-add the same source ID and same original fields, explicitly supplying the values the store actually retained: `original_timestamp=null`, empty timezone/application/locator/model version, `consent_context={'mode':'explicit_api_import'}`, and `metadata={}`. The second call returns `immutable_source_conflict`, although all stored immutable values are unchanged.

**Consequence:** a retry/importer that materializes default fields falsely conflicts; inside an import batch it can roll back otherwise valid records. Real changes to source locator/metadata must continue to conflict; canonicalization should not weaken immutable evidence.

**Fix direction:** construct one validated canonical metadata representation and use it for both persistence and hashing, with a deliberate legacy-hash migration/compatibility policy. Preserve the existing intended behavior that a later ingestion observation time alone does not replace the retained source or cause a duplicate.

## Behavior verified without a finding

| Contract portion | Evidence / result | Limits |
|---|---|---|
| Source and metadata immutability | Update-blocking triggers; metadata included in new hashes; changed locator conflict covered by V2 test. | Canonical-default hashing issue above remains. |
| Unknown original time | Omitted original timestamp stays JSON null; migrated source gets null plus `legacy_unrecorded` consent marker. | `observed_at` defaults to supplied `timestamp` for new legacy-shaped API input; importer documentation should state that caller responsibility. |
| V1 migration preserves source/evidence | Dynamic synthetic migration preserved source text, exact SHA256, source count 1 and derived count 1; schema became 2. | No corrupt-file salvage or interrupted-migration fault injection was attempted. |
| Batch atomicity | Dynamic batch inserted one candidate then hit an existing-ID content conflict; response failed, candidate was absent, original count remained 1. | Existing test also covers invalid timestamp rollback. |
| Statement/transaction lifetimes | Migration PRAGMA statements are scoped before commit; dedup SELECT advances to DONE; writes finish before transaction commit; outer batch owns rollback while inner transaction wrappers do not commit it. | Static path review plus exercised paths, not exhaustive SQLite fault injection. |
| Concurrent existing-database writes | Existing V2 test: four writers × eight records, all successful, count 32. | New-database key-creation races and sustained >5-second contention not certified. |
| UTF-8 context boundary | A 256-byte budget at a Devanagari boundary returned 254 valid UTF-8 bytes, with matching `context_text_bytes`. | Relevant excerpt selection still fails as above; budget explicitly counts quote text, not serialized metadata overhead. |
| Filtered CJK merge/dedup | Native search with application `Notes` returned standalone and embedded Beijing records exactly once, excluding the other application. | No multilingual Recall@5 benchmark was run. |
| Encrypted reopen, wrong key, WAL crash recovery | Three selected existing integration tests passed, including process kill after committed insert and successful source recovery. | These are selected regressions, not every encryption/deletion/rotation/backup gate. |
| Bounded API behavior | Limits remain on request lines, record text, metadata, batch count, query terms, result count and context quote bytes. Failures return structured errors from the native main loop. | Throughput, maximum-history performance and broad adversarial resource bounds were not measured. |

## Additional contract ambiguity

`find_source` parses and validates a supplied `filters` object, but `engine/memory_query.cpp:51` does not apply its WHERE conditions. A dynamic request for a known source with `filters.application='NotTheSource'` still returned that source. No explicit API specification establishes whether `find_source` must honor filters, so this is **not promoted to a confirmed priority finding**. Either apply the accepted filters or reject them for that operation to avoid a misleading API contract. Filters are not authorization controls in this review.

## Reproduction commands and outputs

The six V2 tests were executed with:

```powershell
& '.venv/Scripts/python.exe' -m unittest discover -s tests -p test_memory_v2.py -v
```

Result: six tests passed in 3.301 seconds. Three model-free existing integration cases (`test_encrypted_reopen_dedup_immutability_and_source_search`, `test_consent_and_wrong_key_fail_closed`, `test_wal_contains_no_plaintext_and_recovers_after_process_crash`) also passed in 1.862 seconds when selected through `unittest.TestSuite`.

Minimal reproduction of the three findings, using the existing synthetic fixture helper and native CLI:

```powershell
@'
import json,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'tests'))
from test_memory_v2 import engine,record
with tempfile.TemporaryDirectory() as tmp:
    db=Path(tmp)/'fraction.db'
    print(engine(db,[record(timestamp='2020-06-01T00:00:00.100Z',original_timestamp='2020-06-01T00:00:00.100Z'),
      {'op':'search','query':'Orion','filters':{'from':'2020-06-01T00:00:00.200Z','to':'2020-06-01T00:00:00.800Z'}},
      {'op':'search','query':'Orion','filters':{'from':'2020-06-01T00:00:00.500Z'}},
      {'op':'search','query':'Orion','filters':{'to':'2020-06-01T00:00:00.500Z'}}]))
with tempfile.TemporaryDirectory() as tmp:
    rows=engine(Path(tmp)/'context.db',[record(text='irrelevant preface '*60+' Orion meeting at 09:00.'),
      {'op':'retrieve_context','query':'Orion','max_context_bytes':256}])
    print(rows[1]['not_found'],'Orion' in rows[1]['citations'][0]['quote'])
with tempfile.TemporaryDirectory() as tmp:
    base=record()
    for k in ['original_timestamp','observed_at','timezone','source_application','source_locator','consent_context','metadata','model_version']:
        base.pop(k,None)
    rows=engine(Path(tmp)/'hash.db',[base,{**base,'original_timestamp':None,'timezone':'','source_application':'',
      'source_locator':'','consent_context':{'mode':'explicit_api_import'},'metadata':{},'model_version':''}])
    print(rows[1])
'@ | & '.venv/Scripts/python.exe' -
```

Observed compact outputs from the executed review probes:

```json
{"within_second_range":{"error":"invalid_time_range","ok":false},"from_500ms_ids":["source-a"],"to_500ms_ids":[],"conflicting_fraction_accepted":true}
{"context_not_found":false,"quote_contains_query":false,"quote_bytes":256,"truncated":true}
{"equivalent_explicit_defaults_retry":{"error":"immutable_source_conflict","ok":false}}
{"late_conflict_batch_new_source_absent":true,"retained_original_count":1}
{"v1_source_text_preserved":true,"v1_sha256_preserved":true,"derived_count":1,"original_timestamp":null}
{"filtered_cjk_ids":["standalone","embedded"],"unique":true}
```

Not checked: full product compliance; semantic/entity/relationship/preference retrieval; actual private imports or capture; deletion propagation/sync; network privacy; retention policies; backups/key rotation; recovery from corrupted encrypted pages; interrupted migration failure injection; performance at 10,000+ records; mobile/Wear; model quality. No conclusion in this report substitutes for those gates.
