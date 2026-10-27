"""Answerability data v2: teacher distillation (docs/LENS_MODEL.md, stage T2 — permitted teacher data).

A stronger public model (the leader of lens_model/eval/compare_answerability.py, e.g. Qwen3-Reranker-4B, Apache-2.0)
scores public training pairs; its scores are Platt-calibrated against the gold labels on the same pool and blended
into soft targets: y_soft = alpha * y_gold + (1 - alpha) * p_teacher. The student (Lens answerability head) trains
on y_soft with BCE, keeping its 118M-parameter / ~124 MB INT8 size inside the 800 MB system ceiling.
Pool (never a benchmark test split, never Lens fixtures, never personal data):
- a sample of v1 training pairs (SQuAD 2.0 train, TyDi train, IndicQA/XQuAD training splits, v1 synthetic kinds);
- MLQA validation (13 configs incl. de/ar/vi and cross-lingual; 0 paragraphs shared with MLQA test — checked).
Teacher scores are cached incrementally (resume after interruption).
Output: artifacts/lens-model/answerability-v2/train.jsonl (+ build-report.json)
Usage: .venv-train\\Scripts\\python.exe lens_model/data/build_distill.py --teacher qwen3-reranker-4b [--v1-sample 40000]
"""
import argparse
import collections
import json
from pathlib import Path
import random
import sys
import time
import numpy as np
import pyarrow.parquet as pq
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'lens_model/data'));sys.path.insert(0,str(ROOT/'lens_model/eval'))
from build_answerability import EXT,grams,most_similar,pairs,windows
import compare_answerability as ca
V1=ROOT/'artifacts/lens-model/answerability-v1'
OUT=ROOT/'artifacts/lens-model/answerability-v2'
CFGS=[f'mlqa.{l}.{l}' for l in ('en','es','hi','zh','de','ar','vi')]+['mlqa.en.hi','mlqa.hi.en','mlqa.en.zh','mlqa.zh.en','mlqa.en.es','mlqa.es.en']


def mlqa_validation(rng):
    out=[]
    for cfg in CFGS:
        ctx_lang,q_lang=cfg.split('.')[1:];rows=pq.read_table(EXT/f'mlqa/{cfg}.validation.parquet').to_pylist()
        lang=q_lang if q_lang==ctx_lang else f'{q_lang}>{ctx_lang}';contexts=sorted({r['context'] for r in rows});cg={c:grams(c) for c in contexts}
        for r in rows:
            a=r['answers'];start,text=a['answer_start'][0],a['text'][0];g=f"mlqa-dev:{cfg}:{r['id']}"
            out+=pairs(r['question'],r['context'],start,text,lang,'mlqa_validation',g,True,rng)
            if q_lang==ctx_lang:
                q=grams(r['question']);alt=[c for c in contexts if c!=r['context'] and text.strip() not in c]
                if alt:
                    ctx=max(alt,key=lambda c:len(q&cg[c]));w=most_similar(r['question'],ctx,windows(ctx))
                    if w:out.append({'q':r['question'],'e':ctx[w[0]:w[1]].strip(),'y':0,'lang':lang,'src':'mlqa_validation','group':g,'kind':'cross_paragraph_near_miss'})
    return out


def platt(s,y,iters=500):
    a,b=1.0,0.0
    for _ in range(iters):  # Newton steps on logistic loss of sigmoid(a*s+b)
        p=1/(1+np.exp(-(a*s+b)));g=np.array([((p-y)*s).sum(),(p-y).sum()]);w=p*(1-p)+1e-9
        H=np.array([[(w*s*s).sum(),(w*s).sum()],[(w*s).sum(),w.sum()]])+1e-6*np.eye(2);d=np.linalg.solve(H,g);a,b=a-d[0],b-d[1]
        if np.abs(d).max()<1e-8:break
    return float(a),float(b)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--teacher',required=True);ap.add_argument('--v1-sample',type=int,default=40000)
    ap.add_argument('--alpha',type=float,default=0.5);ap.add_argument('--batch',type=int,default=8);a=ap.parse_args()
    rng=random.Random(20261027);OUT.mkdir(parents=True,exist_ok=True)
    v1=[json.loads(l) for l in (V1/'train.jsonl').open(encoding='utf-8')];rng.shuffle(v1)
    pool=v1[:a.v1_sample]+mlqa_validation(rng)
    for i,r in enumerate(pool):r['pid']=i
    cache=OUT/f'teacher-{a.teacher}.jsonl';done={}
    if cache.exists():
        for l in cache.open(encoding='utf-8'):x=json.loads(l);done[x['pid']]=x['s']
    todo=sorted([r for r in pool if r['pid'] not in done],key=lambda r:len(r['q'])+len(r['e']))
    print(f'pool {len(pool)}  cached {len(done)}  to score {len(todo)}',flush=True)
    if todo:
        import torch;torch.set_num_threads(ca.THREADS)
        judge=ca.make(a.teacher);t=time.perf_counter()
        with cache.open('a',encoding='utf-8') as f:
            for k in range(0,len(todo),a.batch):
                b=todo[k:k+a.batch];s=judge.batch(b)
                for r,v in zip(b,s):f.write(json.dumps({'pid':r['pid'],'s':float(v)})+'\n');done[r['pid']]=float(v)
                if k//a.batch%200==0:
                    f.flush();el=time.perf_counter()-t;print(f'{k+len(b)}/{len(todo)} {el/60:.1f} min, eta {(len(todo)-k)*el/max(1,k+len(b))/60:.0f} min',flush=True)
    s=np.array([done[r['pid']] for r in pool]);y=np.array([float(r['y']) for r in pool]);A,B=platt(s,y);p=1/(1+np.exp(-(A*s+B)))
    for r,pt in zip(pool,p):r['y_gold']=r['y'];r['p_teacher']=float(pt);r['y']=a.alpha*r['y_gold']+(1-a.alpha)*float(pt)
    with (OUT/'train.jsonl').open('w',encoding='utf-8') as f:
        for r in pool:f.write(json.dumps({k:v for k,v in r.items() if k!='pid'},ensure_ascii=False)+'\n')
    disagree=[r for r in pool if abs(r['y_gold']-r['p_teacher'])>0.9]
    rep={'teacher':a.teacher,'alpha':a.alpha,'platt':{'a':A,'b':B},'pool':len(pool),'v1_sample':a.v1_sample,
         'by_src':dict(collections.Counter(r['src'] for r in pool)),'teacher_gold_disagreement_over_0.9':len(disagree),
         'disagreement_samples':[{k:r[k] for k in ('q','e','y_gold','p_teacher','kind','lang')} for r in disagree[:20]]}
    (OUT/'build-report.json').write_text(json.dumps(rep,indent=1,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in rep.items() if k!='disagreement_samples'},indent=1,ensure_ascii=False))


if __name__=='__main__':main()
