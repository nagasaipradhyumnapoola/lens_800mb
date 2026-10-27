# Source-backed encrypted memory

The native SQLCipher store keeps immutable originals, language, UTC import timestamp, device,
source kind, provenance, SHA256 and confidence. Derived rows require a source foreign key and
store their own model/confidence metadata. Conflicting source IDs reject; identical observations
return their canonical stored ID. Original transcripts are not replaced with model summaries.

FTS5 phrase candidates and literal substring candidates merge with stable ordering and ID dedup.
This preserves Chinese substrings even when a separate FTS token match exists. Parameterized
queries retain Unicode and treat SQL punctuation literally. Up to five original sources return;
absent queries return not_found. This is source search, not semantic QA or inferred event answers.

Executed workload: 10,000 Lens-authored synthetic history records,
100 labeled anchor queries and 20 absent queries.
Recall@5 = 1.00; 20/20
correct not_found; insertion failures 0.
Each of English, Mandarin, Spanish and Hindi has 25 labeled queries and Recall@5 = 1.0.
Runtime was 18.85 seconds on this host. Full query evidence is in
memory-retrieval-results.json. Distinct synthetic anchors make this a bounded retrieval test;
it does not establish human conversational recall, entity resolution or natural-language answering.

The public JFK demo performs actual speech inference, closes/reopens encrypted storage and
retrieves the exact original text. Mandarin audio and Spanish OCR also reach encrypted memory
through the real PowerShell client in integration tests. All original timestamps in these file
imports represent import time; no claim is made about recording creation time.

Deletion cascades to derived rows and search indexes. Encryption and logical deletion do not
prove forensic erasure of filesystem snapshots or SSD media. Backup, key rotation, migrations
beyond schema v1, multi-device conflict resolution and encrypted synchronization remain pending.
