# Independent memory V3 follow-up — 2026-10-26

The three original memory V2 repro cases now pass on fresh V3 records. **Two confirmed P2 defects remain**: V2 fingerprint compatibility after migration and Unicode-aware context anchoring. These findings concern this bounded memory contract; this report does not certify the full product or its release gates.

Implementation, tests and old reports were not edited. Probes used only synthetic temporary encrypted databases and the existing native CLI. No model inference, private records, downloads, installations, commits or subagents were used. The only additional file written outside this report is the explicitly authorized, hash-verified MIT license notice described below.

## Snapshot

Reviewed `engine/store.cpp`, `engine/sql.hpp`, `engine/memory_query.cpp`, the nine `tests/test_memory_v2.py` cases, the prior V2 snapshot documented in `memory-v2-review.md`, the parent's green verification log, and the current model license lock. Line references apply to these file hashes:

| Artifact | SHA256 |
|---|---|
| `engine/store.cpp` | `0a293da0c9d62ae14d8935f6a5b1b86b3b73677afbf2ec1dc7febcbc9d994afd` |
| `engine/sql.hpp` | `a734d32be208abe5eda61475af300eb1d3fc2bea5dae082591b5988b8b5acbae` |
| `engine/memory_query.cpp` | `0e4f02b4fb65186280c9761f35d74f890e83a613067d054137cd8640caa25a01` |
| Tested native `lens-engine.exe` | `4c347645160c3f6f2d110bce37767c5f4fd92c437dcd7f6d204d050196d71d7e` |

Applicable authoritative requirements remain `docs/product-requirements.md`: original timestamps/time zones/content hashes at 950–954, retained source recoverability at 962, explicit migrations and deduplication at 970–978, multilingual retrieval at 1089, relevant excerpts at 1099, and evidence-grounded responses at 1118–1124.

## Original findings independently rechecked

| Previous defect | Current result |
|---|---|
| Fractional time filters truncate precision | Fixed for the original repro. A source at `.100Z` is excluded by `[.200Z,.800Z)` and `from=.500Z`, included by `to=.500Z`, and a conflicting original time `.900Z` is rejected. |
| Context budget loses a single matching term near the end | Fixed for the original repro. Query `Orion` after 60 irrelevant preface repeats returns a bounded excerpt containing `Orion`; its `byte_offset` selects the exact original bytes. |
| Omitted versus explicit metadata defaults conflict on fresh records | Fixed for fresh V3 records. The identical explicit defaults retry reports `deduplicated:true`. Migrated V2 records remain affected as described below. |
| `find_source` accepted but ignored filters | Fixed in the probe: a mismatched application filter returns `not_found:true`. |

Additional precision probe: `2020-06-01T09:00:00.123456789+05:30` and `2020-06-01T03:30:00.123456789Z` are accepted as the same source instant, and the one-nanosecond range `[.123456789Z,.123456790Z)` retrieves the record. The fixed-length UTC key avoids overflow from storing nanoseconds since epoch and maintains lexicographic order for its accepted year range.

Executed independently:

```powershell
& '.venv/Scripts/python.exe' -m unittest discover -s tests -p test_memory_v2.py -v
```

Result: **nine tests passed in 3.823 seconds**. The CLI/Hindi tests reported by the parent were not rerun, because this follow-up did not require model execution.

## P2 — Migrated V2 fingerprints lack a compatible canonical lookup

**Code:** V2→V3 migration at `engine/store.cpp:68`–76 adds and fills `event_key` while retaining observation hashes. New writes at lines 114–119 hash every normalized optional default. Existing-record lookup at line 122 accepts the new canonical hash or, only for an unextended request, the old V1 base hash. The cross-ID lookup at line 125 has the same two shapes. Neither recognizes the V2 shape containing only the optional fields originally supplied.

**Synthetic migration probe:** created one encrypted record using the existing fixture helper, then reconstructed a V2 database by removing only the V3 `event_key` index/column/migration row and setting `user_version=2`. Its `observations.sha256` was set to the exact algorithm reviewed in V2: base immutable fields plus only supplied optional fields, sorted compact UTF-8 JSON, SHA256. This is an explicitly synthesized legacy fixture, not a claim that a V2 executable was run during this follow-up. The common `record()` fixture supplies original time, timezone, application, locator, consent context and metadata, while omitting model version.

Observed after opening it with V3:

```json
{
  "schema_version":3,
  "retained_sha_unchanged":true,
  "retained_text_unchanged":true,
  "same_id_retry":{"error":"immutable_source_conflict","ok":false},
  "different_id_retry":{"deduplicated":false,"id":"retry-other-id","ok":true},
  "final_source_count":2
}
```

The legacy V2 SHA256 was `98da992d97799bb125de800da6d4263fe80a5914d81f3c7e89d030cc658730d7`; V3 computed `91cd223ccfbfb273b4bdbba983ead3f9f3334139108424f51963e94732b96543` for the same source data. Original text and fingerprint remain recoverable, so this is **not source loss**. It is a migration/deduplication regression: an unchanged retry fails, and the same evidence under another proposed ID is duplicated. A batch containing the retry can also fail atomically despite unchanged evidence.

**Fix direction:** preserve the original evidence hash while maintaining a separately versioned canonical deduplication fingerprint/alias for migrated rows, or compare normalized retained immutable fields on existing-ID lookup and provide an indexed canonical lookup for cross-ID deduplication. Do not solve this by accepting mismatched hashes without checking metadata or by silently replacing original evidence hashes. Test the actual V2 optional-field shape and both identical-ID/different-ID retries, not just V1 migration and fresh V3 default normalization.

## P2 — Context anchoring discards valid Unicode FTS matches

**Code:** `engine/memory_query.cpp:70` retrieves via FTS5 `unicode61`. In context assembly, line 83 lowercases only ASCII bytes; line 84 uses literal `std::string::find` for the normalized query terms. Line 85 drops the source when no literal anchor is found. This anchor matching is weaker than the Unicode case/diacritic equivalences that selected the source.

**Confirmed native probes:**

| Retained exact source text | Query | `search` source count | `retrieve_context` result |
|---|---|---:|---|
| `Café discussion.` | `cafe` | 1 | `not_found:true`, no citations |
| `MÜNCHEN discussion.` | `münchen` | 1 | `not_found:true`, no citations |

Both examples are short enough to fit the default context budget entirely. The full source exists and is found by the same native engine; only context extraction hides it. This is a user-visible false abstention and a regression introduced by the anchor fix, affecting ordinary multilingual/diacritic queries.

**Fix direction:** locate evidence using the same tokenization/normalization semantics that produced the FTS match, while mapping the selected excerpt to exact original bytes. FTS5 snippet/highlight facilities are one upstream option. Literal byte searches can remain the fallback for literal substring candidates. A source must not disappear merely because FTS matched an accented or Unicode-cased equivalent. Add both probes as regression cases and preserve UTF-8 excerpt/offset/budget assertions.

Minimal native reproduction:

```powershell
@'
import json,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'tests'))
from test_memory_v2 import engine,record
for text,query in [('Caf\u00e9 discussion.','cafe'),('M\u00dcNCHEN discussion.','m\u00fcnchen')]:
    with tempfile.TemporaryDirectory() as tmp:
        rows=engine(Path(tmp)/'unicode.db',[record(text=text),
            {'op':'search','query':query},{'op':'retrieve_context','query':query}])
        print(json.dumps({'search_count':len(rows[1]['sources']),
            'context_not_found':rows[2]['not_found'],'citations':len(rows[2]['citations'])}))
'@ | & '.venv/Scripts/python.exe' -
```

Each iteration returned `{"search_count":1,"context_not_found":true,"citations":0}` on the reviewed binary.

## MIT notice verified and retained

The exact cached raw notice was already available at:

`models/parismitaglobalsolutions--indicconformer-sherpa-onnx/AI4Bharat-LICENSE-MIT.txt`

Verified its SHA256 against `third_party/indic-hindi-lock.json`, then copied its bytes with create-new semantics to the authorized path:

`third_party/licenses/AI4Bharat--IndicConformerASR.txt`

Result: **1,067 bytes**, SHA256 **`e5bc20552aeac6e99c3d2811f90695868e9918d9b8e0c69ebd70828f7dfda60f`**, identical to the lock and cached original. No network fetch was necessary. The pinned origin remains the lock's [AI4Bharat MIT license](https://raw.githubusercontent.com/AI4Bharat/IndicConformerASR/3a4c52d0e9168746a2df0da841c6ca5fbb6f18d9/LICENSE).

Not checked here: whole-product compliance, all import adapters, capture/sync/action policies, corrupt-database recovery, interrupted V3 migration fault injection, long-history performance, target-device memory, model quality or all privacy/release gates. The two confirmed P2 findings remain open for this snapshot.
