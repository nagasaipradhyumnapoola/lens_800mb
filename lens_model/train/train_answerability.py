"""Train the Lens-Core answerability head, pilot v0 (docs/LENS_MODEL.md, stage T2; CPU-capable).

Initialisation: cross-encoder/mmarco-mMiniLMv2-L12-H384-v1 (Apache-2.0 weights; the reranker Lens already ships), so a
successful head can replace it without adding a model to RAM. Objective: binary cross-entropy, label 1 = the evidence
window supports an answer to the question. The 250k-token embedding table (96M parameters) is frozen to keep optimizer
state small on 16 GB machines; the 12 transformer layers and the head are trained.
Data: artifacts/lens-model/answerability-v0 (lens_model/data/build_answerability.py). Held-out sets are evaluated only.
Usage: .venv-train\\Scripts\\python.exe lens_model/train/train_answerability.py [--epochs 1] [--max-steps N]
"""
import argparse
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import random
import time
import numpy as np
import psutil
import torch
from transformers import AutoModelForSequenceClassification,AutoTokenizer
ROOT=Path(__file__).resolve().parents[2]
INIT=ROOT/'models/cross-encoder--mmarco-mMiniLMv2-L12-H384-v1'
DATA=ROOT/'artifacts/lens-model/answerability-v0'
OUT=ROOT/'artifacts/lens-model/checkpoints'


def load(name,folder=None):return [json.loads(l) for l in ((folder or DATA)/f'{name}.jsonl').open(encoding='utf-8')]


def batches(rows,size,rng,shuffle=True):
    """Length-bucketed batches: shuffle, then sort within chunks of 50 batches so padding stays small on CPU."""
    idx=list(range(len(rows)))
    if shuffle:rng.shuffle(idx)
    chunk=size*50;out=[]
    for i in range(0,len(idx),chunk):
        part=sorted(idx[i:i+chunk],key=lambda k:len(rows[k]['q'])+len(rows[k]['e']))
        out+=[part[j:j+size] for j in range(0,len(part),size)]
    if shuffle:rng.shuffle(out)
    return out


def encode(tok,rows,ids,max_len):
    b=[rows[i] for i in ids]
    enc=tok([r['q'] for r in b],[r['e'] for r in b],truncation='longest_first',max_length=max_len,padding=True,return_tensors='pt')
    return enc,torch.tensor([float(r['y']) for r in b])


@torch.no_grad()
def scores(model,tok,rows,max_len,size=64):
    model.eval();out=np.zeros(len(rows),dtype=np.float32)
    for ids in batches(rows,size,None,shuffle=False):
        enc,_=encode(tok,rows,ids,max_len);out[ids]=model(**enc).logits[:,0].float().numpy()
    model.train();return out


def auc(y,s):
    o=np.argsort(s);r=np.empty(len(s));r[o]=np.arange(1,len(s)+1);pos=y==1;n1=pos.sum();n0=len(y)-n1
    return float((r[pos].sum()-n1*(n1+1)/2)/(n1*n0)) if n1 and n0 else None


def report(rows,s):
    y=np.array([r['y'] for r in rows]);out={'all':{'n':len(rows),'auc':auc(y,s)}}
    for key in sorted({r['lang'] for r in rows}|{f"kind:{r['kind']}" for r in rows}):
        sel=np.array([(r['lang']==key) if not key.startswith('kind:') else (r['kind']==key[5:]) for r in rows])
        ys,ss=y[sel],s[sel]
        out[key]={'n':int(sel.sum()),'auc':auc(ys,ss),'mean_score':float(ss.mean())}
    # supported-recall when 95% of unsupported pairs are rejected (threshold from these rows; descriptive only)
    neg=np.sort(s[y==0]);t=neg[int(math.ceil(0.95*len(neg)))-1] if len(neg) else 0.0
    out['all']['supported_kept_at_5pct_false_support']=float((s[y==1]>t).mean()) if (y==1).any() else None
    return out


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--epochs',type=float,default=1.0);ap.add_argument('--batch',type=int,default=32)
    ap.add_argument('--lr',type=float,default=3e-5);ap.add_argument('--max-len',type=int,default=192);ap.add_argument('--max-steps',type=int)
    ap.add_argument('--threads',type=int,default=8);ap.add_argument('--seed',type=int,default=20261027);ap.add_argument('--name',default='answerability-v0')
    ap.add_argument('--init',type=Path,default=INIT,help='checkpoint to start from (default: the shipped reranker)')
    ap.add_argument('--train-data',type=Path,default=DATA,help='folder holding train.jsonl (dev/held-out always from answerability-v0)')
    args=ap.parse_args();args.init=args.init.resolve() if args.init.exists() else args.init;args.train_data=args.train_data.resolve();torch.manual_seed(args.seed);rng=random.Random(args.seed);torch.set_num_threads(args.threads)
    tok=AutoTokenizer.from_pretrained(args.init);model=AutoModelForSequenceClassification.from_pretrained(args.init,num_labels=1)
    for p in model.base_model.embeddings.word_embeddings.parameters():p.requires_grad=False
    trainable=[p for p in model.parameters() if p.requires_grad]
    train,dev=load('train',args.train_data),load('dev');held={n:load(n) for n in ('indicqa_heldout','xquad_heldout')}
    plan=[b for e in range(math.ceil(args.epochs)) for b in batches(train,args.batch,rng)][:int(len(train)/args.batch*args.epochs)]
    if args.max_steps:plan=plan[:args.max_steps]
    opt=torch.optim.AdamW(trainable,lr=args.lr,weight_decay=0.01);warm=max(1,int(0.05*len(plan)))
    sched=torch.optim.lr_scheduler.LambdaLR(opt,lambda k:min((k+1)/warm,max(0.0,(len(plan)-k)/max(1,len(plan)-warm))))
    lossf=torch.nn.BCEWithLogitsLoss();proc=psutil.Process();log=[];peak=0
    dev_small=random.Random(1).sample(dev,min(2000,len(dev)))
    base={'dev':report(dev_small,scores(model,tok,dev_small,args.max_len))};print('init dev auc',base['dev']['all'],flush=True)
    model.train();t0=time.perf_counter()
    for step,ids in enumerate(plan,1):
        enc,y=encode(tok,train,ids,args.max_len)
        loss=lossf(model(**enc).logits[:,0],y);loss.backward()
        torch.nn.utils.clip_grad_norm_(trainable,1.0);opt.step();sched.step();opt.zero_grad(set_to_none=True)
        peak=max(peak,proc.memory_info().rss)
        if step%50==0 or step==len(plan):
            el=time.perf_counter()-t0;log.append({'step':step,'loss':float(loss),'elapsed_s':el,'rss_mb':proc.memory_info().rss/1e6})
            print(f'step {step}/{len(plan)} loss {float(loss):.4f} {el/step:.2f}s/step eta {(len(plan)-step)*el/step/60:.0f} min rss {proc.memory_info().rss/1e6:.0f} MB',flush=True)
    out=OUT/args.name;out.mkdir(parents=True,exist_ok=True);model.save_pretrained(out);tok.save_pretrained(out)
    final={'dev':report(dev,scores(model,tok,dev,args.max_len))}|{n:report(r,scores(model,tok,r,args.max_len)) for n,r in held.items()}
    meta={'created_utc':datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),'init':str(args.init.relative_to(ROOT)) if args.init.is_relative_to(ROOT) else str(args.init),'train_data':str(args.train_data.relative_to(ROOT)) if args.train_data.is_relative_to(ROOT) else str(args.train_data),
          'args':vars(args),'steps':len(plan),'train_rows':len(train),'train_seconds':time.perf_counter()-t0,'peak_rss_bytes':peak,
          'torch':torch.__version__,'frozen':'word_embeddings','baseline_init_dev_2000':base,'final':final,'log':log}
    (out/'training-report.json').write_text(json.dumps(meta,indent=1,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({k:{kk:vv for kk,vv in v.items() if kk=='all'} for k,v in final.items()},indent=1))


if __name__=='__main__':main()
