"""Source-backed native memory contracts from restored product brief; synthetic inputs only."""
import concurrent.futures
import ctypes
import hashlib
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / 'build/engine/Release/lens-engine.exe'


def engine(db, requests):
    p = subprocess.run([str(EXE), '--db', str(db)],
                       input=''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in requests),
                       capture_output=True, encoding='utf-8', timeout=45)
    if p.returncode:
        raise AssertionError('Native test process failed: ' + p.stderr)
    return [json.loads(line) for line in p.stdout.splitlines()]


def record(id='source-a', **updates):
    value = {'op': 'add', 'consent': True, 'id': id,
             'text': 'Arun said the Orion project meeting starts at 09:00.',
             'language': 'en', 'timestamp': '2020-06-01T09:00:00+05:30',
             'device': 'synthetic-device', 'kind': 'chat_import', 'provenance': 'synthetic-export-v1',
             'original_timestamp': '2020-06-01T09:00:00+05:30',
             'observed_at': '2026-10-26T05:00:00Z', 'timezone': 'Asia/Kolkata',
             'source_application': 'WhatsApp export', 'source_locator': 'export/message/17',
             'consent_context': {'mode': 'user_selected_export', 'scope': 'fixture-chat'},
             'metadata': {'sender': 'Arun', 'importer_version': '1'}}
    value.update(updates)
    return value


def schema_sql_for_synthetic_db(db, sql):
    """Build a genuine v1 encrypted fixture with the upstream SQLCipher API; never log its key."""
    assert Path(db).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
    class Blob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]
    encrypted = Path(str(db) + '.key').read_bytes()
    buf = (ctypes.c_ubyte * len(encrypted)).from_buffer_copy(encrypted)
    incoming, plain = Blob(len(encrypted), buf), Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    crypt.CryptUnprotectData.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    crypt.CryptUnprotectData.restype = wintypes.BOOL
    if not crypt.CryptUnprotectData(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(plain)):
        raise AssertionError('Synthetic fixture key unavailable')
    try:
        with os.add_dll_directory(str(EXE.parent)):
            lib = ctypes.CDLL(str(EXE.parent / 'sqlcipher.dll'))
            lib.sqlite3_open_v2.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_int, ctypes.c_void_p]
            lib.sqlite3_key.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
            lib.sqlite3_exec.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
            lib.sqlite3_close.argtypes = [ctypes.c_void_p]
            handle = ctypes.c_void_p()
            assert lib.sqlite3_open_v2(str(db).encode(), ctypes.byref(handle), 2, None) == 0
            try:
                assert lib.sqlite3_key(handle, plain.pbData, plain.cbData) == 0
                assert lib.sqlite3_exec(handle, sql.encode(), None, None, None) == 0
            finally:
                lib.sqlite3_close(handle)
    finally:
        ctypes.memset(plain.pbData, 0, plain.cbData)
        free = ctypes.WinDLL('kernel32').LocalFree
        free.argtypes = [ctypes.c_void_p]
        free(plain.pbData)


class MemoryV2(unittest.TestCase):
    def test_original_and_observation_metadata_survive_reopen_and_dedup(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'memory.db'
            self.assertTrue(engine(db, [record()])[0]['ok'])
            result = engine(db, [{'op': 'search', 'query': 'Orion'}])[0]['sources'][0]
            self.assertEqual(result.get('observed_at'), '2026-10-26T05:00:00Z')
            for key in ['original_timestamp', 'timezone', 'source_application', 'source_locator', 'consent_context', 'metadata']:
                self.assertEqual(result.get(key), record()[key])
            rows = engine(db, [record(observed_at='2026-10-27T05:00:00Z'), {'op': 'stats'}])
            self.assertTrue(rows[0]['deduplicated'])
            self.assertEqual(rows[1]['source_count'], 1)
            conflict = engine(db, [record(source_locator='different-source')])[0]
            self.assertEqual(conflict.get('error'), 'immutable_source_conflict')

    def test_time_application_device_and_kind_filters_apply_to_all_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'memory.db'
            rows = engine(db, [record(), record('source-b', timestamp='2020-06-02T08:00:00Z',
                       original_timestamp='2020-06-02T08:00:00Z', source_application='Notes'),
                {'op': 'search', 'query': 'Orion', 'filters': {'from': '2020-06-02T00:00:00Z',
                  'to': '2020-06-03T00:00:00Z', 'application': 'Notes', 'device': 'synthetic-device', 'kind': 'chat_import'}},
                {'op': 'search', 'query': 'Orion', 'filters': {'application': 'Absent'}},
                {'op': 'search', 'query': 'Orion', 'filters': {'from': '2020-06-01T03:30:00Z',
                                                                           'to': '2020-06-01T03:30:01Z'}}])
            self.assertEqual([x['id'] for x in rows[2]['sources']], ['source-b'])
            self.assertTrue(rows[3]['not_found'])
            self.assertEqual([x['id'] for x in rows[4]['sources']], ['source-a'])

    def test_batch_import_is_atomic_and_validates_timestamps_before_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'memory.db'
            rows = engine(db, [{'op': 'import_batch', 'consent': True,
                'records': [record(), record('bad', timestamp='2020-99-01T00:00:00Z')]}, {'op': 'stats'},
                {'op': 'import_batch', 'consent': True, 'records': [record(), record('source-c', text='明天开会。')]},
                {'op': 'stats'}])
            self.assertFalse(rows[0]['ok'])
            self.assertEqual(rows[1]['source_count'], 0)
            self.assertTrue(rows[2]['ok'], rows[2])
            self.assertEqual(rows[3]['source_count'], 2)

    def test_context_returns_exact_source_quotes_and_abstains_for_missing_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = engine(Path(tmp) / 'memory.db', [record(),
                {'op': 'retrieve_context', 'query': 'What did Arun say about the Orion project?'},
                {'op': 'retrieve_context', 'query': 'unobserved-expedition-7749'},
                {'op': 'find_source', 'id': 'source-a'},
                {'op': 'timeline', 'filters': {'application': 'WhatsApp export'}}])
            self.assertTrue(rows[1]['ok'], rows[1])
            self.assertEqual(rows[1]['answer_kind'], 'source_quotes')
            self.assertEqual(rows[1]['citations'][0]['quote'], record()['text'])
            self.assertTrue(rows[2]['not_found'])
            self.assertEqual(rows[3]['source']['id'], 'source-a')
            self.assertEqual(rows[4]['sources'][0]['id'], 'source-a')

    def test_v1_migration_preserves_source_and_marks_unknown_original_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'memory.db'
            legacy = record()
            for name in ['original_timestamp', 'observed_at', 'timezone', 'source_application',
                         'source_locator', 'consent_context', 'metadata']:
                legacy.pop(name)
            engine(db, [legacy])
            schema_sql_for_synthetic_db(db, 'DROP TABLE IF EXISTS source_metadata; DROP TABLE IF EXISTS schema_migrations; PRAGMA user_version=1;')
            rows = engine(db, [{'op': 'stats'}, {'op': 'search', 'query': 'Orion'}])
            self.assertEqual(rows[0]['schema_version'], 8)
            source = rows[1]['sources'][0]
            self.assertEqual(source['text'], legacy['text'])
            self.assertIsNone(source['original_timestamp'])
            self.assertEqual(source['consent_context']['mode'], 'legacy_unrecorded')

    def test_existing_database_concurrent_writes_preserve_all_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'memory.db'
            engine(db, [{'op': 'stats'}])
            def write_group(group):
                return engine(db, [record(f'{group}-{i}', text=f'concurrency {group} {i}') for i in range(8)])
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(write_group, range(4)))
            self.assertTrue(all(r['ok'] for group in results for r in group), results)
            self.assertEqual(engine(db, [{'op': 'stats'}])[0]['source_count'], 32)

    def test_subsecond_filters_and_original_timestamp_conflicts_are_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = record(timestamp='2020-06-01T00:00:00.100Z', original_timestamp='2020-06-01T00:00:00.100Z')
            rows = engine(Path(tmp) / 'memory.db', [r,
                {'op': 'search', 'query': 'Orion', 'filters': {'from': '2020-06-01T00:00:00.200Z', 'to': '2020-06-01T00:00:00.800Z'}},
                {'op': 'search', 'query': 'Orion', 'filters': {'to': '2020-06-01T00:00:00.500Z'}},
                {**r, 'id': 'wrong-time', 'original_timestamp': '2020-06-01T00:00:00.900Z'}])
            self.assertTrue(rows[1].get('not_found'), rows[1])
            self.assertEqual(rows[2]['sources'][0]['id'], 'source-a')
            self.assertEqual(rows[3].get('error'), 'conflicting_source_timestamp')

    def test_context_budget_keeps_the_matching_evidence_and_utf8_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = 'unrelated preface ' * 80 + 'Orion 明天开会。' + ' trailing content' * 40
            rows = engine(Path(tmp) / 'memory.db', [record(text=text),
                {'op': 'retrieve_context', 'query': 'Orion', 'max_context_bytes': 256}])
            self.assertFalse(rows[1]['not_found'])
            self.assertIn('Orion', rows[1]['citations'][0]['quote'])
            self.assertIn(rows[1]['citations'][0]['quote'], text)
            self.assertLessEqual(len(rows[1]['citations'][0]['quote'].encode()), 256)

    def test_equivalent_optional_defaults_deduplicate_and_source_filters_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            value = record()
            for key in ['original_timestamp', 'observed_at', 'timezone', 'source_application', 'source_locator', 'consent_context', 'metadata']:
                value.pop(key)
            rows = engine(Path(tmp) / 'memory.db', [value,
                {**value, 'original_timestamp': None, 'timezone': '', 'source_application': '', 'source_locator': '',
                 'model_version': '', 'consent_context': {'mode': 'explicit_api_import'}, 'metadata': {}},
                {'op': 'find_source', 'id': 'source-a', 'filters': {'application': 'Missing'}}])
            self.assertTrue(rows[1].get('deduplicated'), rows[1])
            self.assertTrue(rows[2]['not_found'])

    def test_unicode_fts_matches_retain_matching_context_excerpts(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows=engine(Path(tmp)/'memory.db',[record(text='Café discussion.'),
                record('german',text='MÜNCHEN discussion.'),
                {'op':'retrieve_context','query':'cafe'}, {'op':'retrieve_context','query':'münchen'}])
            self.assertFalse(rows[2]['not_found'])
            self.assertIn('Café',rows[2]['citations'][0]['quote'])
            self.assertFalse(rows[3]['not_found'])
            self.assertIn('MÜNCHEN',rows[3]['citations'][0]['quote'])

    def test_v2_metadata_hash_migration_preserves_sha_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'memory.db';r=record()
            engine(db,[r])
            payload={name:r[name] for name in ['text','language','timestamp','device','kind','provenance']}
            payload['confidence']=1.0
            for name in ['original_timestamp','timezone','source_application','source_locator','consent_context','metadata']:
                payload[name]=r[name]
            old_hash=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            schema_sql_for_synthetic_db(db, '''
DROP TRIGGER source_metadata_immutable;
ALTER TABLE source_metadata RENAME TO metadata_interim;
CREATE TABLE source_metadata(source_id TEXT PRIMARY KEY REFERENCES observations(id) ON DELETE CASCADE,
original_timestamp TEXT,observed_at TEXT NOT NULL,timezone TEXT NOT NULL,source_application TEXT NOT NULL,
source_locator TEXT NOT NULL,consent_context TEXT NOT NULL,metadata TEXT NOT NULL,event_seconds INTEGER,model_version TEXT NOT NULL);
INSERT INTO source_metadata SELECT source_id,original_timestamp,observed_at,timezone,source_application,
source_locator,consent_context,metadata,event_seconds,model_version FROM metadata_interim;
DROP TABLE metadata_interim;
CREATE TRIGGER source_metadata_immutable BEFORE UPDATE ON source_metadata BEGIN SELECT RAISE(ABORT,'immutable'); END;
DELETE FROM schema_migrations WHERE version>2;
DROP TRIGGER observations_immutable;
UPDATE observations SET sha256='''+"'"+old_hash+"'"+''';
CREATE TRIGGER observations_immutable BEFORE UPDATE ON observations BEGIN SELECT RAISE(ABORT,'immutable'); END;
PRAGMA user_version=2;''')
            rows=engine(db,[{'op':'find_source','id':'source-a'},r,{**r,'id':'same-other-id'},{'op':'stats'}])
            self.assertEqual(rows[0]['source']['sha256'],old_hash)
            self.assertTrue(rows[1].get('deduplicated'),rows[1])
            self.assertEqual(rows[2].get('id'),'source-a',rows[2])
            self.assertEqual(rows[3]['source_count'],1)


if __name__ == '__main__':
    unittest.main()
