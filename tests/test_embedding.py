"""Native e5 tokenizer/embedder parity against independent references (HF tokenizers + Python ONNX Runtime)."""
import json
from pathlib import Path
import subprocess
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
MODEL=ROOT/'models/intfloat--multilingual-e5-small/onnx'
TOOL=ROOT/'build/engine/Release/lens-embed.exe'
RUNTIME=ROOT/'.tools/ocr-runtime/onnxruntime.dll'
EDGE=['','  double  spaces ','Tab\there\nnewline','ＦＵＬＬ　ｗｉｄｔｈ ①②','é vs é','ﬁ ligature','emoji 👍🏽 family 👨‍👩‍👧',
      'क़ ज़ ड़ क्षि','నేను రేపు వస్తాను','நான் நாளை வருவேன்','‍zero width','Kal meeting hai with Rahul at 5pm',
      'مرحبا بالعالم','Привет, мир','こんにちは世界','안녕하세요','x'*3000,'﻿bom','a b　c']


def corpus():
    texts=[]
    for f in ['fleurs-smoke.json','fleurs-priority-holdout.json']:
        texts+=[s['reference'] for s in json.loads((ROOT/'data/fixtures'/f).read_text(encoding='utf-8'))['samples']]
    return texts+['query: '+t for t in texts[:40]]+['passage: '+t for t in texts[40:80]]+EDGE


def native(request):
    p=subprocess.run([str(TOOL)],input=json.dumps(request,ensure_ascii=False)+'\n',capture_output=True,encoding='utf-8',timeout=600)
    if p.returncode:raise AssertionError(p.stderr)
    return json.loads(p.stdout)['results']


class Embedding(unittest.TestCase):
    def test_native_token_ids_match_hugging_face_tokenizers(self):
        from tokenizers import Tokenizer
        hf=Tokenizer.from_file(str(MODEL/'tokenizer.json'))
        texts=corpus()
        ids=native({'mode':'tokens','tokenizer':str(MODEL/'tokenizer.json'),'texts':texts})
        mismatches=[t for t,mine in zip(texts,ids) if hf.encode(t).ids!=mine]
        self.assertGreater(len(texts),490)
        self.assertEqual(mismatches,[])

    def test_truncation_keeps_bos_and_eos_within_512(self):
        ids=native({'mode':'tokens','tokenizer':str(MODEL/'tokenizer.json'),'texts':['word '*2000],'max_tokens':512})[0]
        self.assertEqual((len(ids),ids[0],ids[-1]),(512,0,2))

    def test_native_embeddings_match_python_onnx_reference(self):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        hf=Tokenizer.from_file(str(MODEL/'tokenizer.json'))
        texts=['query: '+t for t in corpus()[:12]]+['passage: 明天下午三点在北京开会','passage: कल सुबह दस बजे बैठक है']
        model=MODEL/'model_qint8_avx512_vnni.onnx'
        mine=np.array(native({'mode':'embed','tokenizer':str(MODEL/'tokenizer.json'),'model':str(model),'runtime':str(RUNTIME),'texts':texts,'batch':5}))
        session=ort.InferenceSession(str(model),providers=['CPUExecutionProvider'])
        for text,vector in zip(texts,mine):
            ids=np.array([hf.encode(text).ids[:512]],dtype=np.int64);mask=np.ones_like(ids)
            hidden=session.run(None,{'input_ids':ids,'attention_mask':mask,'token_type_ids':np.zeros_like(ids)})[0][0]
            ref=hidden.mean(0);ref/=np.linalg.norm(ref)
            self.assertAlmostEqual(float(np.linalg.norm(vector)),1.0,places=4)
            self.assertGreater(float(vector@ref),0.9999,text)

    def test_cross_language_paraphrase_is_closer_than_unrelated_text(self):
        model=MODEL/'model_qint8_avx512_vnni.onnx'
        v=np.array(native({'mode':'embed','tokenizer':str(MODEL/'tokenizer.json'),'model':str(model),'runtime':str(RUNTIME),
            'texts':['query: when is the budget meeting with Wang Fang','passage: 明天下午三点在北京和王芳讨论预算','passage: 我的猫喜欢在窗台上睡觉']}))
        self.assertGreater(float(v[0]@v[1]),float(v[0]@v[2]))


RERANK=ROOT/'models/cross-encoder--mmarco-mMiniLMv2-L12-H384-v1'


class Reranking(unittest.TestCase):
    def test_native_pair_token_ids_match_hugging_face_tokenizers(self):
        from tokenizers import Tokenizer
        hf=Tokenizer.from_file(str(RERANK/'tokenizer.json'));hf.enable_truncation(512,strategy='longest_first')
        texts=corpus();queries=['When is the budget review?','¿Qué no puede comer Lena?','  spaced\tquery \n','मदुरै की ट्रेन कब है?','x'*900]
        mismatches=[]
        for q in queries:
            mine=native({'mode':'pairs','tokenizer':str(RERANK/'tokenizer.json'),'texts':[q]+texts})
            for passage,ids in zip(texts,mine):
                if hf.encode(q,passage).ids!=ids:mismatches.append((q,passage[:40]))
        self.assertEqual(mismatches,[])

    def test_native_rerank_scores_match_python_onnx_reference(self):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        hf=Tokenizer.from_file(str(RERANK/'tokenizer.json'));hf.enable_truncation(512,strategy='longest_first')
        model=RERANK/'onnx/model_qint8_avx512_vnni.onnx'
        query='When is the budget review with Wang Fang?'
        passages=['王芳说下周二上午十点在上海办公室开预算评审会。','My cat likes sleeping on the windowsill.','El vuelo IB 3170 a Madrid sale a las 18:40.']
        mine=native({'mode':'rerank','tokenizer':str(RERANK/'tokenizer.json'),'model':str(model),'runtime':str(RUNTIME),'texts':[query]+passages})
        session=ort.InferenceSession(str(model),providers=['CPUExecutionProvider'])
        for passage,score in zip(passages,mine):
            ids=np.array([hf.encode(query,passage).ids],dtype=np.int64)
            ref=float(session.run(None,{'input_ids':ids,'attention_mask':np.ones_like(ids)})[0][0][0])
            self.assertAlmostEqual(score,ref,places=3)
        self.assertGreater(mine[0],max(mine[1:]))


if __name__=='__main__':unittest.main()
