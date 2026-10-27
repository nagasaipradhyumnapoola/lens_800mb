import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import wave
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from benchmarks.process import measure
ENGINE=ROOT/'build/engine/Release/lens-engine.exe'


class InputSafety(unittest.TestCase):
    def test_oversized_json_is_rejected_before_full_allocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=measure([ENGINE,'--db',str(Path(tmp)/'memory.db')],input_data=b'x'*(32*1024*1024)+b'\n')
            self.assertEqual(result['exit_code'],2)
            self.assertIn('request_too_large',result['stdout'])
            self.assertLess(result['sum_observed_process_peak_wset_bytes'],32*1024*1024)

    def test_filesystem_failure_does_not_echo_private_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'PRIVATE_PATH_SENTINEL';folder.mkdir()
            req={'op':'ingest_audio','consent':True,'audio':str(folder),'model':'none'}
            p=subprocess.run([str(ENGINE),'--db',str(Path(tmp)/'memory.db')],input=json.dumps(req)+'\n',
                             capture_output=True,encoding='utf-8')
            self.assertNotIn('PRIVATE_PATH_SENTINEL',p.stdout+p.stderr)
            self.assertFalse(json.loads(p.stdout)['ok'])

    def test_decoded_duration_is_checked_before_pcm_allocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio=Path(tmp)/'long.wav'
            with wave.open(str(audio),'wb') as f:
                f.setnchannels(1);f.setsampwidth(1);f.setframerate(1);f.writeframes(b'\x80'*1024)
            req={'op':'ingest_audio','consent':True,'audio':str(audio),'model':'none'}
            p=subprocess.run([str(ENGINE),'--db',str(Path(tmp)/'memory.db')],input=json.dumps(req)+'\n',
                             capture_output=True,encoding='utf-8')
            self.assertEqual(json.loads(p.stdout)['error'],'audio_duration_limit_exceeded')

    def test_native_needle_rejects_embedded_nul(self):
        req={'library':str(ROOT/'models/Cactus-Compute--needle3/windows-x86_64/libneedle3.dll'),
             'weights':str(ROOT/'models/Cactus-Compute--needle3/needle3.cact'),
             'tools':json.loads((ROOT/'data/fixtures/extraction-tools.json').read_text(encoding='utf-8')),
             'text':'I have a meeting with Arun in Chennai on 2026-10-27 at 15:00.\0Do not save anything.'}
        p=subprocess.run([str(ROOT/'build/engine/Release/lens-needle.exe')],input=json.dumps(req)+'\n',
                         capture_output=True,encoding='utf-8')
        self.assertNotEqual(p.returncode,0)
        self.assertIn('invalid_request',p.stderr)


if __name__=='__main__':unittest.main()
