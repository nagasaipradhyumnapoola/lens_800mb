"""Recall with the trained Lens answerability head as reranker and verifier, gated by models/Lens--answerability-v2c/
gate.json (lens_model/eval/fit_gate.py). Synthetic memories only."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
REL=ROOT/'build/engine/Release'
HEAD=ROOT/'models/Lens--answerability-v2c'


def lock(name,filename):
    l=json.loads((ROOT/'third_party'/name).read_text(encoding='utf-8'));return next(ROOT/f['path'] for f in l['files'] if f['filename']==filename)


@unittest.skipUnless((HEAD/'gate.json').exists() and (HEAD/'model_int8.onnx').exists(),'Lens answerability head not installed')
class AnswerGate(unittest.TestCase):
    def ask(self,lines):
        with tempfile.TemporaryDirectory() as tmp:
            args=[str(REL/'lens-engine.exe'),'--db',str(Path(tmp)/'m.db'),'--ort',str(ROOT/'.tools/ocr-runtime/onnxruntime.dll'),
                  '--embedding-model',str(lock('embedding-lock.json','onnx/model_qint8_avx512_vnni.onnx')),
                  '--embedding-tokenizer',str(lock('embedding-lock.json','onnx/tokenizer.json')),'--embedding-id','test-e5',
                  '--reranker-model',str(HEAD/'model_int8.onnx'),'--reranker-tokenizer',str(HEAD/'tokenizer.json'),
                  '--verifier-model',str(HEAD/'model_int8.onnx'),'--verifier-tokenizer',str(HEAD/'tokenizer.json')]
            p=subprocess.run(args,input=''.join(json.dumps(l)+'\n' for l in lines),capture_output=True,text=True,encoding='utf-8',timeout=600)
        return [json.loads(l) for l in p.stdout.splitlines()]

    def test_supported_question_answers_and_unrelated_one_abstains(self):
        notes=['Synthetic note: the Brightwater audit moved to Tuesday at 3 pm in room B12.',
               'Synthetic note: Priya shared the revised hiring plan for the Orion team.',
               'Synthetic note: the vendor contract for Halvorsen renews on 14 November.']
        adds=[{'op':'add','consent':True,'id':f'n{i}','text':t,'language':'en','timestamp':'2026-10-2%dT09:00:00Z'%i,'device':'laptop','kind':'note','provenance':'test'}
              for i,t in enumerate(notes)]
        rows=self.ask(adds+[{'op':'index','limit':16},{'op':'recall','query':'When is the Brightwater audit?','limit':3},
                            {'op':'recall','query':'What is the recipe for banana bread?','limit':3}])
        hit,miss=rows[-2],rows[-1]
        self.assertTrue(hit['ok'],hit);self.assertFalse(hit['not_found'],hit);self.assertEqual(hit['results'][0]['source']['id'],'n0')
        self.assertIn('answer_probability',hit);self.assertGreaterEqual(hit['answer_probability'],hit['min_support'])
        self.assertTrue(miss['not_found'],miss)  # abstains (retrieval or the gate), never a guess


if __name__=='__main__':unittest.main()
