"""Black-box native encryption/source-retrieval contract. Only synthetic test data."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "build/engine/Release/lens-engine.exe"


class EngineIntegration(unittest.TestCase):
    def run_engine(self, db, requests):
        self.assertTrue(EXE.exists(), "Native Lens engine has not been built")
        proc = subprocess.run([str(EXE), "--db", str(db)],
                              input="".join(json.dumps(x, ensure_ascii=False)+"\n" for x in requests),
                              encoding="utf-8", capture_output=True, timeout=30)
        rows = [json.loads(x) for x in proc.stdout.splitlines() if x.startswith("{")]
        return proc, rows

    def record(self, text="Meet Arun in Chennai at 15:00", **updates):
        return {"op":"add", "consent":True, "id":"test-source-1", "text":text,
                "language":"en", "timestamp":"2026-10-26T04:00:00Z", "device":"test-device",
                "kind":"manual_import", "provenance":"synthetic-integration-test", **updates}

    def test_encrypted_reopen_dedup_immutability_and_source_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp)/"memory.db"
            proc, rows = self.run_engine(db, [self.record(), self.record(),
                self.record("Overwrite source"), {"op":"search","query":"Arun"},
                {"op":"search","query":"nonexistent999"}])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(rows[0]["ok"])
            self.assertTrue(rows[1]["deduplicated"])
            self.assertEqual(rows[2]["error"], "immutable_source_conflict")
            self.assertEqual(rows[3]["sources"][0]["text"], "Meet Arun in Chennai at 15:00")
            self.assertEqual(rows[3]["sources"][0]["id"], "test-source-1")
            self.assertTrue(rows[4]["not_found"])
            self.assertNotIn(b"Meet Arun", db.read_bytes())
            self.assertFalse(db.read_bytes().startswith(b"SQLite format 3"))
            self.assertNotIn(b"Meet Arun", (Path(str(db)+".key")).read_bytes())
            proc, rows = self.run_engine(db, [{"op":"search","query":"Arun"}])
            self.assertEqual(len(rows[0]["sources"]), 1)

    def test_unicode_and_literal_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc, rows = self.run_engine(Path(tmp)/"memory.db", [
                self.record("明天15:00在北京开会", language="zh"),
                {"op":"search","query":"北京"}, {"op":"search","query":"%"},
                {"op":"search","query":"\" OR 1=1 --"}])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(rows[1]["sources"][0]["text"], "明天15:00在北京开会")
            self.assertTrue(rows[2]["not_found"])
            self.assertTrue(rows[3]["not_found"])

    def test_consent_and_wrong_key_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            a,b = Path(tmp)/"a.db",Path(tmp)/"b.db"
            proc,rows = self.run_engine(a,[self.record(consent=False),{"op":"stats"}])
            self.assertEqual(rows[0]["error"],"consent_required")
            self.assertEqual(rows[1]["source_count"],0)
            self.run_engine(b,[self.record()])
            shutil.copyfile(str(a)+".key",str(b)+".key")
            proc,rows = self.run_engine(b,[{"op":"stats"}])
            self.assertNotEqual(proc.returncode,0)
            self.assertNotIn("Meet Arun",proc.stdout+proc.stderr)

    def test_derived_record_requires_source_and_deletion_removes_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/"memory.db"
            proc,rows=self.run_engine(db,[self.record(),
                {"op":"derive","source_id":"missing","data":{"time":"15:00"},"confidence":.8,"model":"test"},
                {"op":"derive","source_id":"test-source-1","data":{"time":"15:00"},"confidence":.8,"model":"test"},
                {"op":"delete","id":"test-source-1","consent":True},
                {"op":"search","query":"Arun"},{"op":"stats"}])
            self.assertEqual(proc.returncode,0,proc.stderr)
            self.assertFalse(rows[1]["ok"])
            self.assertTrue(rows[2]["ok"])
            self.assertTrue(rows[4]["not_found"])
            self.assertEqual(rows[5]["derived_count"],0)

    def test_wal_contains_no_plaintext_and_recovers_after_process_crash(self):
        self.assertTrue(EXE.exists(),"Native Lens engine has not been built")
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'memory.db'
            sentinel='LENS_PRIVATE_SENTINEL_7f305b77'
            proc=subprocess.Popen([str(EXE),'--db',str(db)],stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
            try:
                proc.stdin.write(json.dumps(self.record(sentinel))+'\n');proc.stdin.flush()
                result=json.loads(proc.stdout.readline())
                self.assertTrue(result['ok'])
                for file in Path(tmp).iterdir():
                    if file.is_file():self.assertNotIn(sentinel.encode(),file.read_bytes(),str(file))
                self.assertTrue(Path(str(db)+'-wal').exists())
            finally:
                proc.kill();proc.communicate(timeout=10)
            reopened,rows=self.run_engine(db,[{'op':'search','query':sentinel}])
            self.assertEqual(reopened.returncode,0,reopened.stderr)
            self.assertEqual(rows[0]['sources'][0]['text'],sentinel)

    def test_native_audio_import_and_retrieval(self):
        with tempfile.TemporaryDirectory() as tmp:
            record=self.record(op='ingest_audio',audio=str(ROOT/'third_party/whisper.cpp/samples/jfk.wav'),
                               model=str(ROOT/'models/ggerganov--whisper.cpp/ggml-tiny-q5_1.bin'))
            record.pop('text')
            proc,rows=self.run_engine(Path(tmp)/'memory.db',[record,{'op':'search','query':'country'}])
            self.assertEqual(proc.returncode,0,proc.stderr)
            self.assertTrue(rows[0]['ok'],rows[0])
            self.assertIn('country',rows[0]['transcript']['text'].casefold())
            self.assertEqual(rows[1]['sources'][0]['text'],rows[0]['transcript']['text'])
            self.assertEqual(rows[1]['sources'][0]['timestamp'],'2026-10-26T04:00:00Z')

    def test_sensitive_fields_are_excluded_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc,rows=self.run_engine(Path(tmp)/'memory.db',[
                self.record('Your OTP verification code is 123456'),
                self.record('password: synthetic-secret'),
                self.record('密码：仅用于测试'),{'op':'stats'}])
            self.assertEqual(proc.returncode,0,proc.stderr)
            self.assertEqual([x['error'] for x in rows[:3]],['sensitive_content_excluded']*3)
            self.assertEqual(rows[3]['source_count'],0)
            self.assertNotIn('synthetic-secret',proc.stderr)

    def test_token_match_does_not_hide_chinese_substring_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc,rows=self.run_engine(Path(tmp)/'memory.db',[
                self.record('北京',id='standalone',language='zh'),
                self.record('明天在北京开会',id='embedded',language='zh'),
                {'op':'search','query':'北京'}])
            self.assertEqual(proc.returncode,0,proc.stderr)
            self.assertEqual({x['id'] for x in rows[2]['sources']},{'standalone','embedded'})


if __name__ == "__main__":
    unittest.main()
