import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from support import pwsh
ROOT=Path(__file__).resolve().parents[1]


class LensCLI(unittest.TestCase):
    def cli(self,db,*arguments):
        p=subprocess.run([pwsh(),'-NoProfile','-File',str(ROOT/'scripts/lens.ps1'),
                          '-DatabasePath',str(db),*arguments],capture_output=True,encoding='utf-8',timeout=60)
        self.assertEqual(p.returncode,0,p.stderr)
        return json.loads(p.stdout)

    def test_text_and_native_image_reach_encrypted_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'memory.db'
            self.assertTrue(self.cli(db,'-Action','ImportText','-Text','明天在北京开会','-Language','zh','-Id','manual-zh')['ok'])
            result=self.cli(db,'-Action','ImportImage','-SourcePath',str(ROOT/'artifacts/ocr-smoke/es.png'),
                            '-Language','es','-Id','ocr-es')
            self.assertTrue(result['ok'])
            self.assertIn('Ana',result['recognition']['text'])
            self.assertEqual(self.cli(db,'-Action','Search','-Query','Ana')['sources'][0]['id'],'ocr-es')
            self.assertEqual(self.cli(db,'-Action','Search','-Query','北京')['sources'][0]['id'],'manual-zh')

    def test_mandarin_audio_native_worker_preserves_original_in_memory(self):
        fixture=next(x for x in json.loads((ROOT/'data/fixtures/fleurs-smoke.json').read_text(encoding='utf-8'))['samples'] if x['language']=='zh')
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'memory.db'
            result=self.cli(db,'-Action','ImportAudio','-SourcePath',str(ROOT/fixture['path']),'-Language','zh','-Id','recorded-fixture-zh')
            self.assertTrue(result['ok'])
            self.assertIn('篇章',result['transcript']['text'])
            memory=self.cli(db,'-Action','Search','-Query','篇章')
            self.assertEqual(memory['sources'][0]['text'],result['transcript']['text'])
            self.assertIsNone(result['transcript']['confidence'])

    def test_missing_private_path_is_not_echoed(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=subprocess.run([pwsh(),'-NoProfile','-File',str(ROOT/'scripts/lens.ps1'),'-Action','ImportImage',
                              '-SourcePath',str(Path(tmp)/'PRIVATE_SENTINEL_MISSING.png'),'-Language','en',
                              '-DatabasePath',str(Path(tmp)/'memory.db')],capture_output=True,encoding='utf-8')
            self.assertNotEqual(p.returncode,0)
            self.assertNotIn('PRIVATE_SENTINEL',p.stdout+p.stderr)


if __name__=='__main__':unittest.main()
