"""Score every answerability judge on the same benchmark pairs (lens_model/eval/build_benchmarks.py) and compare.

Judges (CPU only, the Lens deployment target):
  lens-v0-int8, lens-v1-int8, mmarco-int8, qa-xlmr-int8 — ONNX Runtime, the deployed form (run in .venv)
  lens-v0, lens-v1, mmarco                                   — PyTorch FP32 of the same weights (.venv-train)
  qwen3-reranker-0.6b, qwen3-reranker-4b                     — official yes/no reranker format, task instruction
  bge-reranker-v2-m3                                         — cross-encoder logit
  qwen2.5-1.5b-instruct, qwen3-1.7b, qwen3-4b                — zero-shot instruct judges (thinking off; 4B models in bf16):
                                                               score = log P(yes|Yes) - log P(no|No) for the next token
Same pairs, same text, no per-judge tuning beyond the documented prompt. Metrics per set and language: ROC AUC,
average precision, and recall of supported pairs at 5% false support (TPR@5%FPR). Efficiency: weights on disk, RSS
after load, peak working set, single-pair latency (64 fixed pairs, batch 1) with 8 threads.
Writes artifacts/lens-model/bench/scores/<judge>.jsonl and reports/lens-model/benchmark/<judge>.json;
--summary writes reports/lens-model/benchmark/answerability-comparison.{json,md} from all judge reports.
Usage: <venv>\\Scripts\\python.exe lens_model/eval/compare_answerability.py --judge NAME [--limit N]
       .venv-train\\Scripts\\python.exe lens_model/eval/compare_answerability.py --summary
"""
import argparse
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import time
import numpy as np
import psutil
ROOT=Path(__file__).resolve().parents[2]
BENCH=ROOT/'artifacts/lens-model/bench'
REPORTS=ROOT/'reports/lens-model/benchmark'
BASE=ROOT/'models/baselines'
CKPT=ROOT/'artifacts/lens-model/checkpoints'
ONNX=ROOT/'artifacts/lens-model/onnx'
SETS=['mlqa_mono','mlqa_cross','xquad_heldout','indicqa_heldout','belebele_global','belebele_cross','xquad_world','indicqa_more',
      'squad2_dev','tydi_dev','lens_harness']
CLEAN=['mlqa_mono','mlqa_cross','xquad_heldout','indicqa_heldout','belebele_global','belebele_cross','xquad_world','indicqa_more']
# spec §1a quality-critical languages: every one counts equally in the language macro
LANGS=['en','zh','es','ar','fr','pt','ru','id','de','ja','hi','bn','te','mr','ta','ur','gu']
MAXLEN=384  # cross-encoders: room for Belebele's full passages; the same for every encoder judge
THREADS=8
TASK='Given a question, judge whether the document contains the answer to the question'
JUDGE_PROMPT=('Read the passage and decide whether it contains the answer to the question.\n\nPassage: {e}\n\nQuestion: {q}\n\n'
              'Does the passage contain the answer to the question? Answer only yes or no.')


def dir_mb(paths):return sum(p.stat().st_size for p in paths)/2**20


class OnnxCrossEncoder:
    def __init__(self,model,tokenizer,max_len,qa=False):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        o=ort.SessionOptions();o.intra_op_num_threads=THREADS
        self.s=ort.InferenceSession(str(model),o,providers=['CPUExecutionProvider']);self.inputs=[i.name for i in self.s.get_inputs()]
        self.tok=Tokenizer.from_file(str(tokenizer));self.tok.enable_truncation(max_len,strategy='only_second' if qa else 'longest_first')
        self.qa=qa;self.weights_mb=dir_mb([Path(model)])

    def one(self,q,e):
        enc=self.tok.encode(q,e);ids=np.array([enc.ids],dtype=np.int64);feeds={'input_ids':ids,'attention_mask':np.ones_like(ids)}
        if 'token_type_ids' in self.inputs:feeds['token_type_ids']=np.array([enc.type_ids],dtype=np.int64) if not self.qa else np.zeros_like(ids)
        out=self.s.run(None,feeds)
        if not self.qa:return float(out[0][0][0])
        s,t=out[0][0],out[1][0];ctx=[i for i,sid in enumerate(enc.sequence_ids) if sid==1]
        if not ctx:return -99.0
        null=s[0]+t[0];lo,hi=ctx[0],ctx[-1];best=-1e9
        for i in lo+np.argsort(s[lo:hi+1])[::-1][:20]:
            for j in lo+np.argsort(t[lo:hi+1])[::-1][:20]:
                if i<=j<=i+30:best=max(best,s[i]+t[j])
        return float(best-null)

    def batch(self,rows):return [self.one(r['q'],r['e']) for r in rows]  # INT8: one sequence per inference


class TorchCrossEncoder:
    def __init__(self,folder,max_len):
        import torch
        from transformers import AutoModelForSequenceClassification,AutoTokenizer
        self.torch=torch;self.tok=AutoTokenizer.from_pretrained(folder);self.max_len=max_len
        self.m=AutoModelForSequenceClassification.from_pretrained(folder,torch_dtype=torch.float32).eval()
        self.weights_mb=dir_mb(Path(folder).glob('*.safetensors'))

    def batch(self,rows):
        with self.torch.inference_mode():
            enc=self.tok([r['q'] for r in rows],[r['e'] for r in rows],truncation='longest_first',max_length=self.max_len,padding=True,return_tensors='pt')
            return self.m(**enc).logits[:,0].float().tolist()


class TorchYesNo:
    """Causal LM scored on the next token: log P(yes-variants) - log P(no-variants)."""
    def __init__(self,folder,reranker):
        import torch
        from transformers import AutoModelForCausalLM,AutoTokenizer
        self.torch=torch;self.tok=AutoTokenizer.from_pretrained(folder,padding_side='left');self.reranker=reranker
        self.weights_mb=dir_mb(Path(folder).glob('*.safetensors'))
        self.dtype='bfloat16' if self.weights_mb>4000 else 'float32'  # 4B in FP32 needs 16 GB; bf16 halves it (AVX-512 BF16 on H0)
        self.m=AutoModelForCausalLM.from_pretrained(folder,torch_dtype=getattr(torch,self.dtype)).eval()
        words=(['yes'],['no']) if reranker else (['yes','Yes'],['no','No'])
        self.yes=[self.tok.convert_tokens_to_ids(w) for w in words[0]];self.no=[self.tok.convert_tokens_to_ids(w) for w in words[1]]
        assert all(isinstance(i,int) and i>=0 for i in self.yes+self.no)
        self.qwen3='qwen3' in folder.name.lower()

    def text(self,r):
        if self.reranker:
            return ('<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. '
                    'Note that the answer can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n'
                    f"<Instruct>: {TASK}\n<Query>: {r['q']}\n<Document>: {r['e']}<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n")
        msgs=[{'role':'user','content':JUDGE_PROMPT.format(q=r['q'],e=r['e'])}]
        kw={'enable_thinking':False} if self.qwen3 else {}
        return self.tok.apply_chat_template(msgs,tokenize=False,add_generation_prompt=True,**kw)

    def batch(self,rows):
        with self.torch.inference_mode():
            enc=self.tok([self.text(r) for r in rows],padding=True,truncation=True,max_length=1024,return_tensors='pt',add_special_tokens=False)
            lp=self.torch.log_softmax(self.m(**enc).logits[:,-1,:].float(),dim=-1)
            return (self.torch.logsumexp(lp[:,self.yes],dim=-1)-self.torch.logsumexp(lp[:,self.no],dim=-1)).tolist()


def make(name):
    qa_dir=ROOT/'models/onnx-community--xlm-roberta-base-squad2-distilled-ONNX';mm=ROOT/'models/cross-encoder--mmarco-mMiniLMv2-L12-H384-v1'
    table={
        'lens-v0-int8':lambda:OnnxCrossEncoder(ONNX/'answerability-v0/model_int8.onnx',ONNX/'answerability-v0/tokenizer.json',MAXLEN),
        'lens-v1-int8':lambda:OnnxCrossEncoder(ONNX/'answerability-v1/model_int8.onnx',ONNX/'answerability-v1/tokenizer.json',MAXLEN),
        'mmarco-int8':lambda:OnnxCrossEncoder(mm/'onnx/model_qint8_avx512_vnni.onnx',mm/'tokenizer.json',MAXLEN),
        'qa-xlmr-int8':lambda:OnnxCrossEncoder(qa_dir/'onnx/model_int8.onnx',qa_dir/'tokenizer.json',384,qa=True),
        'lens-v0':lambda:TorchCrossEncoder(CKPT/'answerability-v0',MAXLEN),
        'lens-v1':lambda:TorchCrossEncoder(CKPT/'answerability-v1',MAXLEN),
        'mmarco':lambda:TorchCrossEncoder(mm,MAXLEN),
        'bge-reranker-v2-m3':lambda:TorchCrossEncoder(BASE/'BAAI--bge-reranker-v2-m3',512),
        'qwen3-reranker-0.6b':lambda:TorchYesNo(BASE/'Qwen--Qwen3-Reranker-0.6B',True),
        'qwen3-reranker-4b':lambda:TorchYesNo(BASE/'Qwen--Qwen3-Reranker-4B',True),
        'qwen2.5-1.5b-instruct':lambda:TorchYesNo(BASE/'Qwen--Qwen2.5-1.5B-Instruct',False),
        'qwen3-1.7b':lambda:TorchYesNo(BASE/'Qwen--Qwen3-1.7B',False),
        'qwen3-4b':lambda:TorchYesNo(BASE/'Qwen--Qwen3-4B',False),
    }
    return table[name]()


def auc(y,s):
    o=np.argsort(s,kind='mergesort');r=np.empty(len(s));r[o]=np.arange(1,len(s)+1)
    for v in np.unique(s):  # average ranks for ties
        m=s==v
        if m.sum()>1:r[m]=r[m].mean()
    pos=y==1;n1=pos.sum();n0=len(y)-n1
    return float((r[pos].sum()-n1*(n1+1)/2)/(n1*n0)) if n1 and n0 else None


def ap(y,s):
    o=np.argsort(-s,kind='mergesort');yy=y[o];tp=np.cumsum(yy);prec=tp/np.arange(1,len(yy)+1)
    return float((prec*yy).sum()/max(1,yy.sum())) if yy.sum() else None


def tpr_at(y,s,fpr=0.05):
    neg=np.sort(s[y==0])[::-1];pos=s[y==1]
    if not len(neg) or not len(pos):return None
    k=int(math.floor(fpr*len(neg)));t=neg[k] if k<len(neg) else -np.inf  # strictly above the (k+1)-th highest negative
    return float((pos>t).mean())


def metrics(y,s):return {'n':int(len(y)),'pos':int(y.sum()),'auc':auc(y,s),'ap':ap(y,s),'tpr@5fpr':tpr_at(y,s)}


def run(name,limit):
    proc=psutil.Process();before=proc.memory_info().rss;t0=time.perf_counter()
    try:
        import torch;torch.set_num_threads(THREADS)
    except ImportError:pass
    judge=make(name);load_s=time.perf_counter()-t0;load_rss=proc.memory_info().rss-before
    rows=[json.loads(l) for s in SETS for l in (BENCH/f'{s}.jsonl').open(encoding='utf-8')]
    if limit:rows=[r for s in SETS for r in [x for x in rows if x['set']==s][:limit]]
    probe=[rows[i] for i in np.random.default_rng(7).choice(len(rows),min(64,len(rows)),replace=False)];lat=[]
    for r in probe[:4]:judge.batch([r])  # warm-up
    for r in probe:
        t=time.perf_counter();judge.batch([r]);lat.append((time.perf_counter()-t)*1000)
    order=sorted(range(len(rows)),key=lambda i:len(rows[i]['q'])+len(rows[i]['e']));scores=np.zeros(len(rows));bs=8;t=time.perf_counter()
    for k in range(0,len(order),bs):
        ids=order[k:k+bs];scores[ids]=judge.batch([rows[i] for i in ids])
        if k//bs%100==0:print(f'{name} {k}/{len(rows)} {time.perf_counter()-t:.0f}s',flush=True)
    total_s=time.perf_counter()-t
    out=BENCH/'scores';out.mkdir(parents=True,exist_ok=True)
    if not limit:
        with (out/f'{name}.jsonl').open('w',encoding='utf-8') as f:
            for r,s in zip(rows,scores):f.write(json.dumps({'set':r['set'],'idx':r['idx'],'id':r.get('id'),'score':float(s)})+'\n')
    y=np.array([r['y'] for r in rows]);res={}
    for s in SETS:
        m=np.array([r['set']==s for r in rows])
        if not m.any():continue
        res[s]=metrics(y[m],scores[m])|{'by_lang':{l:metrics(y[m&ln],scores[m&ln]) for l in sorted({r['lang'] for r in rows if r['set']==s})
                                                     for ln in [np.array([r['lang']==l for r in rows])]}}
    cl=np.array([r['set'] in CLEAN for r in rows]);lang_m={}
    for l in LANGS:
        m=cl&np.array([r['lang']==l for r in rows])
        if m.any() and len(set(y[m]))==2:lang_m[l]=metrics(y[m],scores[m])
    res['by_language_clean']=lang_m
    rep={'judge':name,'created_utc':datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),'pairs':len(rows),'limit':limit,'threads':THREADS,
         'weights_mb':judge.weights_mb,'dtype':getattr(judge,'dtype','float32' if not name.endswith('int8') else 'int8'),'load_seconds':load_s,'load_rss_mb':load_rss/2**20,'peak_working_set_mb':proc.memory_info().peak_wset/2**20,
         'latency_ms_batch1':{'p50':float(np.percentile(lat,50)),'p95':float(np.percentile(lat,95))},'throughput_pairs_per_s':len(rows)/total_s,'sets':res}
    if not limit:
        REPORTS.mkdir(parents=True,exist_ok=True);(REPORTS/f'{name}.json').write_text(json.dumps(rep,indent=1),encoding='utf-8')
    print(json.dumps({k:v for k,v in rep.items() if k!='sets'},indent=1))
    for s,m in res.items():
        if s=='by_language_clean':print('  17-language macro AUC',round(float(np.mean([v['auc'] for v in m.values()])),3) if m else None,len(m),'languages');continue
        print(f"  {s:16s} auc {m['auc']:.3f}  ap {m['ap']:.3f}  tpr@5fpr {m['tpr@5fpr']:.3f}")


def summary():
    reps={p.stem:json.loads(p.read_text(encoding='utf-8')) for p in sorted(REPORTS.glob('*.json')) if p.stem!='answerability-comparison'}
    harness={}
    for p in REPORTS.glob('*.harness.json'):harness[p.name.split('.harness')[0]]=json.loads(p.read_text(encoding='utf-8'))
    reps={k:v for k,v in reps.items() if 'sets' in v}
    clean=CLEAN;table=[]
    for name,r in reps.items():
        row={'judge':name,'weights_mb':round(r['weights_mb']),'peak_ws_mb':round(r['peak_working_set_mb']),'p50_ms':round(r['latency_ms_batch1']['p50'],1)}
        for s in SETS:
            if s in r['sets']:row[s]={k:r['sets'][s][k] for k in ('auc','tpr@5fpr')}
        row['heldout_macro_auc']=float(np.mean([r['sets'][s]['auc'] for s in clean if s in r['sets']]))
        row['heldout_macro_tpr@5fpr']=float(np.mean([r['sets'][s]['tpr@5fpr'] for s in clean if s in r['sets']]))
        bl=r['sets'].get('by_language_clean',{})
        row['language_macro_auc']=float(np.mean([bl[l]['auc'] for l in LANGS if l in bl])) if bl else None
        row['languages_covered']=len(bl);row['by_language_auc']={l:round(bl[l]['auc'],3) for l in LANGS if l in bl}
        if name in harness:row['lens_harness_answered@5%false']=harness[name]
        table.append(row)
    table.sort(key=lambda r:-(r.get('language_macro_auc') or r['heldout_macro_auc']))
    (REPORTS/'answerability-comparison.json').write_text(json.dumps(table,indent=1),encoding='utf-8')
    head='| judge | weights MB | peak RAM MB | p50 ms | '+' | '.join(SETS)+' | held-out macro AUC | held-out macro TPR@5%FPR | 17-language macro AUC |'
    lines=[head,'|'+'---|'*(7+len(SETS))]
    for r in table:
        cells=[f"{r[s]['auc']:.3f} / {r[s]['tpr@5fpr']:.3f}" if s in r else '—' for s in SETS]
        lines.append(f"| {r['judge']} | {r['weights_mb']} | {r['peak_ws_mb']} | {r['p50_ms']} | "+' | '.join(cells)+f" | {r['heldout_macro_auc']:.3f} | {r['heldout_macro_tpr@5fpr']:.3f} | {(r['language_macro_auc'] or 0):.3f} ({r['languages_covered']}) |")
    md='Cells: ROC AUC / recall of supported pairs at 5% false support. Held-out macro = mean over the never-trained sets ('+', '.join(CLEAN)+'). 17-language macro = mean AUC over the spec §1a languages on those sets (each language equal).\n\n'+'\n'.join(lines)+'\n'
    (REPORTS/'answerability-comparison.md').write_text(md,encoding='utf-8');print(md)


def main():
    ap_=argparse.ArgumentParser();ap_.add_argument('--judge');ap_.add_argument('--limit',type=int,default=0);ap_.add_argument('--summary',action='store_true')
    a=ap_.parse_args()
    if a.summary:summary()
    else:run(a.judge,a.limit)


if __name__=='__main__':main()
