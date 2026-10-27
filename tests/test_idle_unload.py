"""Idle model unloading (docs/LENS_V1_SPEC.md §15): retrieval models are released after a quiet period and
reload transparently on the next request. Only synthetic test data."""
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import psutil
ROOT=Path(__file__).resolve().parents[1]
ENGINE=ROOT/'build/engine/Release/lens-engine.exe'
LOCK=json.loads((ROOT/'third_party/embedding-lock.json').read_text(encoding='utf-8'))
MODEL=next(ROOT/f['path'] for f in LOCK['files'] if f['filename']=='onnx/model_qint8_avx512_vnni.onnx')
TOKENIZER=next(ROOT/f['path'] for f in LOCK['files'] if f['filename']=='onnx/tokenizer.json')
ORT=ROOT/'.tools/ocr-runtime/onnxruntime.dll'
RECORD={'op':'add','consent':True,'id':'a','text':'Meet Arun in Chennai at 15:00','language':'en',
        'timestamp':'2026-10-26T04:00:00Z','device':'test','kind':'k','provenance':'synthetic-test'}


class IdleUnload(unittest.TestCase):
    def start(self,db,*extra):
        p=subprocess.Popen([str(ENGINE),'--db',str(db),'--ort',str(ORT),'--embedding-model',str(MODEL),'--embedding-tokenizer',
                            str(TOKENIZER),'--embedding-id','test-e5',*extra],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE,text=True,encoding='utf-8',bufsize=1)
        self.addCleanup(lambda:(p.poll() is None and (p.stdin.close(),p.wait(timeout=30))))
        return p

    def ask(self,p,req):
        p.stdin.write(json.dumps(req)+'\n');p.stdin.flush();return json.loads(p.stdout.readline())

    def private_mb(self,p):return psutil.Process(p.pid).memory_info().private/1e6

    def test_models_unload_after_idle_and_reload_on_demand(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=self.start(Path(tmp)/'m.db','--model-idle-unload-ms','1500')
            self.ask(p,RECORD);self.ask(p,{'op':'index'})
            first=self.ask(p,{'op':'recall','query':'where do I meet Arun','mode':'semantic','abstain':False})
            loaded=self.private_mb(p);self.assertGreater(loaded,80)
            time.sleep(3.5)
            idle=self.private_mb(p);self.assertLess(idle,40,f'loaded {loaded:.0f} MB, idle {idle:.0f} MB')
            again=self.ask(p,{'op':'recall','query':'where do I meet Arun','mode':'semantic','abstain':False})
            self.assertEqual(first['results'][0]['source']['id'],again['results'][0]['source']['id'])
            self.assertGreater(self.private_mb(p),80)
            p.stdin.close();self.assertEqual(p.wait(timeout=30),0)

    def test_zero_keeps_models_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=self.start(Path(tmp)/'m.db','--model-idle-unload-ms','0')
            self.ask(p,RECORD);self.ask(p,{'op':'index'})
            loaded=self.private_mb(p);time.sleep(2.0)
            self.assertGreater(self.private_mb(p),loaded*0.8)
            self.assertTrue(self.ask(p,{'op':'unload_models'})['unloaded'])
            p.stdin.close();self.assertEqual(p.wait(timeout=30),0)

    def test_invalid_value_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for bad in ('-1','10x','',):
                r=subprocess.run([str(ENGINE),'--db',str(Path(tmp)/'m.db'),'--model-idle-unload-ms',bad],input='',
                                 capture_output=True,text=True,timeout=30)
                self.assertEqual(r.returncode,2,bad)


if __name__=='__main__':unittest.main()
