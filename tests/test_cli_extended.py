import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from support import pwsh
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from benchmarks.metrics import error_rate
ROOT=Path(__file__).resolve().parents[1]


class ExtendedCLI(unittest.TestCase):
    def call(self,db,*args):
        p=subprocess.run([pwsh(),'-NoProfile','-File',str(ROOT/'scripts/lens.ps1'),'-DatabasePath',str(db),*args],
                         capture_output=True,encoding='utf-8',timeout=90)
        self.assertEqual(p.returncode,0,p.stderr)
        return json.loads(p.stdout)

    def test_hindi_import_uses_verified_indicconformer_and_retrieves_original(self):
        sample=next(s for s in json.loads((ROOT/'data/fixtures/fleurs-smoke.json').read_text(encoding='utf-8'))['samples'] if s['language']=='hi')
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'memory.db'
            value=self.call(db,'-Action','ImportAudio','-SourcePath',str(ROOT/sample['path']),'-Language','hi','-Id','hindi-fixture')
            self.assertEqual(value['transcript']['provider'],'sherpa-onnx-indicconformer-ctc')
            text=value['transcript']['text']
            # Compare with the independent reference, not only output-to-output (both could be equally corrupted).
            self.assertNotIn('?',text);self.assertNotIn('�',text)
            self.assertTrue(any('ऀ'<=c<='ॿ' for c in text),text)
            errors,length=error_rate(sample['reference'],text,chars=True)
            self.assertLessEqual(errors/length,0.25)
            source=self.call(db,'-Action','Source','-Id','hindi-fixture')['source']
            self.assertEqual(source['text'],value['transcript']['text'])
            self.assertTrue(source['model_version'].startswith('indicconformer-hi-120m-int8@'))
            self.assertIsNone(source['original_timestamp'])

    def test_historical_manual_metadata_timeline_context_and_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'memory.db'
            self.call(db,'-Action','ImportText','-Id','historic-note','-Text','Arun discussed the Orion project.',
                      '-Language','en','-OriginalTimestamp','2020-03-04T09:00:00+05:30',
                      '-SourceTimeZone','Asia/Kolkata','-SourceApplication','Notes')
            source=self.call(db,'-Action','Source','-Id','historic-note')['source']
            self.assertEqual(source['original_timestamp'],'2020-03-04T09:00:00+05:30')
            self.assertEqual(source['source_application'],'Notes')
            self.assertEqual(len(self.call(db,'-Action','Timeline','-SourceApplication','Notes')['sources']),1)
            self.assertTrue(self.call(db,'-Action','Search','-Query','Orion','-SourceApplication','Absent')['not_found'])
            self.assertIn('Orion',self.call(db,'-Action','Context','-Query','What did Arun say about Orion?')['citations'][0]['quote'])


if __name__=='__main__':unittest.main()
