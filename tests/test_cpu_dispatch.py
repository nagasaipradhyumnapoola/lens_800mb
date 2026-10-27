"""Runtime CPU dispatch and graceful degradation of in-process ASR (docs/LENS_V1_SPEC.md §15).

The engine is staged into a temporary directory with a chosen set of ggml CPU variant DLLs, so the baseline
(SSE2-only) path and the missing-runtime path are exercised on any development CPU. Only synthetic test data.
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
RELEASE=ROOT/'build/engine/Release'
AUDIO=ROOT/'third_party/whisper.cpp/samples/jfk.wav'
MODEL=ROOT/'models/ggerganov--whisper.cpp/ggml-tiny-q5_1.bin'
ASR_DLLS={'whisper.dll','ggml.dll','ggml-base.dll'}


def stage(folder,variants,with_runtime=True):
    for f in RELEASE.iterdir():
        name=f.name.lower()
        if f.suffix.lower()=='.dll' and (name.startswith('ggml-cpu-') or name in ASR_DLLS):continue
        if f.suffix.lower()=='.dll' or name=='lens-engine.exe':shutil.copy2(f,folder/f.name)
    if with_runtime:
        for name in ASR_DLLS:shutil.copy2(RELEASE/name,folder/name)
    for v in variants:shutil.copy2(RELEASE/f'ggml-cpu-{v}.dll',folder/f'ggml-cpu-{v}.dll')
    return folder/'lens-engine.exe'


def ask(exe,db,requests):
    proc=subprocess.run([str(exe),'--db',str(db)],input=''.join(json.dumps(r)+'\n' for r in requests),
                        encoding='utf-8',capture_output=True,timeout=300)
    return proc,[json.loads(x) for x in proc.stdout.splitlines() if x.startswith('{')]


def audio(**extra):
    return {'op':'ingest_audio','consent':True,'id':'audio-1','audio':str(AUDIO),'model':str(MODEL),'language':'en',
            'timestamp':'2026-10-26T04:00:00Z','device':'test-device','kind':'voice_note','provenance':'synthetic-test',**extra}


class CpuDispatch(unittest.TestCase):
    def test_selects_a_variant_on_this_machine(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe=stage(Path(tmp),[p.stem[len('ggml-cpu-'):] for p in RELEASE.glob('ggml-cpu-*.dll')])
            proc,rows=ask(exe,Path(tmp)/'memory.db',[audio()])
            self.assertEqual(proc.returncode,0,proc.stderr);self.assertTrue(rows[0]['ok'],rows[0])
            self.assertTrue(rows[0]['transcript']['cpu_backend'].startswith('ggml-cpu-'))

    def test_baseline_sse2_variant_transcribes(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe=stage(Path(tmp),['x64'])
            proc,rows=ask(exe,Path(tmp)/'memory.db',[audio(),{'op':'search','query':'country'}])
            self.assertEqual(proc.returncode,0,proc.stderr);self.assertTrue(rows[0]['ok'],rows[0])
            self.assertEqual(rows[0]['transcript']['cpu_backend'],'ggml-cpu-x64')
            self.assertIn('country',rows[0]['transcript']['text'].casefold())
            self.assertEqual(rows[1]['sources'][0]['id'],'audio-1')

    def test_missing_asr_runtime_degrades_without_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe=stage(Path(tmp),[],with_runtime=False)
            add={'op':'add','consent':True,'id':'text-1','text':'Meet Arun in Chennai at 15:00','language':'en',
                 'timestamp':'2026-10-26T04:00:00Z','device':'test-device','kind':'manual_import','provenance':'synthetic-test'}
            proc,rows=ask(exe,Path(tmp)/'memory.db',[audio(),add,{'op':'search','query':'Arun'}])
            self.assertEqual(proc.returncode,0,proc.stderr)
            self.assertEqual(rows[0]['error'],'asr_runtime_unavailable')
            self.assertTrue(rows[1]['ok']);self.assertEqual(rows[2]['sources'][0]['id'],'text-1')

    def test_no_cpu_variant_degrades_without_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe=stage(Path(tmp),[])
            proc,rows=ask(exe,Path(tmp)/'memory.db',[audio(),{'op':'stats'}])
            self.assertEqual(proc.returncode,0,proc.stderr)
            self.assertEqual(rows[0]['error'],'asr_runtime_unavailable');self.assertIn('source_count',rows[1])


if __name__=='__main__':unittest.main()
