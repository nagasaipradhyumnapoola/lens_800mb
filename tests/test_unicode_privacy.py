"""Regression tests: UTF-8 CLI output, stdin-only private input, encryption at rest, chunked atomic import."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from support import pwsh
ROOT=Path(__file__).resolve().parents[1]
ENGINE=ROOT/'build/engine/Release/lens-engine.exe'
SAMPLES={'zh':'明天下午三点在北京和王芳讨论预算','hi':'कल सुबह दस बजे अनुबंध पर हस्ताक्षर करना है',
         'ta':'நாளை காலை மருத்துவரை சந்திக்க வேண்டும்','te':'రేపు సాయంత్రం సమావేశం హైదరాబాద్‌లో జరుగుతుంది',
         'es':'La reunión con Lucía se movió al jueves por la mañana'}


class UnicodePrivacy(unittest.TestCase):
    def cli(self,db,*args,stdin=None):
        p=subprocess.run([pwsh(),'-NoProfile','-File',str(ROOT/'scripts/lens.ps1'),'-DatabasePath',str(db),*args],
                         input=stdin,capture_output=True,encoding='utf-8',timeout=90)
        self.assertEqual(p.returncode,0,p.stderr)
        return json.loads(p.stdout)

    def engine(self,db,*requests):
        wire=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in requests)
        p=subprocess.run([str(ENGINE),'--db',str(db)],input=wire,capture_output=True,encoding='utf-8',timeout=60)
        self.assertEqual(p.returncode,0,p.stderr)
        return [json.loads(line) for line in p.stdout.splitlines()]

    def record(self,n,text=None):
        return {'op':'add','consent':True,'id':f'tx-{n}','text':text or f'transaction record {n}','language':'en',
                'timestamp':'2026-01-02T03:04:05Z','device':'test','kind':'manual_import','provenance':'test'}

    def test_stdin_import_round_trips_non_latin_text_exactly_through_encrypted_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'memory.db'
            for language,text in SAMPLES.items():
                added=self.cli(db,'-Action','ImportText','-Language',language,'-Id',f'u-{language}',stdin=text+'\n')
                self.assertTrue(added['ok'])
            for language,text in SAMPLES.items():
                source=self.cli(db,'-Action','Source','-Id',f'u-{language}')['source']
                self.assertEqual(source['text'],text)
                self.assertEqual(source['language'],language)
            hit=self.cli(db,'-Action','Search',stdin='北京')
            self.assertEqual(hit['sources'][0]['id'],'u-zh')
            self.assertEqual(hit['sources'][0]['text'],SAMPLES['zh'])

    def test_plaintext_never_reaches_database_wal_or_key_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'memory.db'
            sentinel='गोपनीय-SENTINEL-秘密-'+'x'*32
            self.cli(db,'-Action','ImportText','-Language','hi','-Id','secret',stdin=sentinel)
            needle=sentinel.encode('utf-8')
            for f in Path(tmp).iterdir():
                self.assertNotIn(needle,f.read_bytes(),f.name)
                self.assertNotIn('SENTINEL'.encode(),f.read_bytes(),f.name)

    def test_stdin_input_is_required_when_text_argument_is_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=subprocess.run([pwsh(),'-NoProfile','-File',str(ROOT/'scripts/lens.ps1'),'-DatabasePath',str(Path(tmp)/'m.db'),
                              '-Action','ImportText','-Id','none'],stdin=subprocess.DEVNULL,capture_output=True,encoding='utf-8',timeout=60)
            # An empty stdin is not silently stored as an empty memory.
            self.assertNotEqual(p.returncode,0)

    def test_explicit_transaction_commits_and_poisoned_transaction_rolls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'memory.db'
            out=self.engine(db,{'op':'begin'},self.record(1),self.record(2),{'op':'commit'},{'op':'stats'})
            self.assertEqual(out[3]['transaction'],'committed');self.assertEqual(out[4]['source_count'],2)
            bad=self.record(4,'my password is hunter2')
            out=self.engine(db,{'op':'begin'},self.record(3),bad,{'op':'commit'},{'op':'stats'})
            self.assertFalse(out[2]['ok']);self.assertFalse(out[3]['ok'])
            self.assertEqual(out[3]['error'],'transaction_poisoned_rolled_back');self.assertEqual(out[4]['source_count'],2)
            out=self.engine(db,{'op':'begin'},self.record(5),{'op':'stats'})
            self.assertEqual(self.engine(db,{'op':'stats'})[0]['source_count'],2)  # exit without commit rolls back

    def importer(self,source,db):
        return subprocess.run([pwsh(),'-NoProfile','-File',str(ROOT/'scripts/import-history.ps1'),'-Format','WhatsApp',
                               '-SourcePath',str(source),'-DatabasePath',str(db),'-DateOrder','DMY','-SourceTimeZone','UTC'],
                              capture_output=True,encoding='utf-8',timeout=180)

    def test_large_whatsapp_export_imports_in_chunks_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'memory.db';source=Path(tmp)/'chat.txt'
            source.write_bytes(''.join(f'01/01/2020, 12:{n%60:02d} - Asha: नमस्ते synthetic message {n}\n' for n in range(300)).encode())
            p=self.importer(source,db)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            result=json.loads(p.stdout)
            self.assertEqual((result['imported'],result['records'],result['batches']),(300,300,3))
            self.assertEqual(self.engine(db,{'op':'stats'})[0]['source_count'],300)
            self.assertEqual(self.engine(db,{'op':'search','query':'synthetic message 299'})[0]['sources'][0]['text'],'नमस्ते synthetic message 299')

    def test_late_rejected_record_rolls_back_every_earlier_chunk(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'memory.db';source=Path(tmp)/'chat.txt'
            rows=[f'01/01/2020, 12:00 - Asha: message {n}' for n in range(300)]
            rows[280]='01/01/2020, 12:00 - Asha: the otp is 123456'
            source.write_bytes(('\n'.join(rows)+'\n').encode())
            p=self.importer(source,db)
            self.assertNotEqual(p.returncode,0)
            result=json.loads(p.stdout)
            self.assertFalse(result['ok']);self.assertEqual(result['imported'],0);self.assertFalse(result['partial'])
            self.assertEqual(self.engine(db,{'op':'stats'})[0]['source_count'],0)


if __name__=='__main__':unittest.main()
