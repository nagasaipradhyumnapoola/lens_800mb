import json
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]


class NativeNeedle(unittest.TestCase):
    def test_native_adapter_extracts_explicit_english_fields_without_executing_action(self):
        exe=ROOT/'build/engine/Release/lens-needle.exe'
        self.assertTrue(exe.exists())
        request={'library':str(ROOT/'models/Cactus-Compute--needle3/windows-x86_64/libneedle3.dll'),
                 'weights':str(ROOT/'models/Cactus-Compute--needle3/needle3.cact'),
                 'tools':json.loads((ROOT/'data/fixtures/extraction-tools.json').read_text(encoding='utf-8')),
                 'text':'I have a meeting with Arun in Chennai on 2026-10-27 at 15:00.'}
        proc=subprocess.run([str(exe)],input=json.dumps(request,ensure_ascii=False)+'\n',
                            encoding='utf-8',capture_output=True,timeout=30)
        self.assertEqual(proc.returncode,0,proc.stderr)
        result=json.loads(proc.stdout)
        self.assertTrue(result['success'])
        self.assertEqual(result['function_calls'][0]['arguments'],
                         {'person':'Arun','date':'2026-10-27','time':'15:00','place':'Chennai'})


if __name__=='__main__':unittest.main()
