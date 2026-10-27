"""Offline experiment: does a dedicated verifier separate supported answers from relevant-but-unsupported
evidence? Uses only v1 (dev + inspected), expansion and near-miss data — never a holdout.

1. Builds 10k-event corpora with the native engine (v1 corpus shared by v1 and near-miss questions; expansion),
   or reopens them with --reuse (retrieved evidence is cached there as rows-evidence.json).
2. Retrieves top-3 evidence with the engine default (centered hybrid + rerank), abstention off.
3. Scores (question, top-1 evidence) via Python ONNX Runtime with one verifier:
   qa:  deepset/xlm-roberta-base-squad2-distilled INT8 (onnx-community export); score = best span - no-answer.
   nli: MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli, local INT8 export (per-channel, FFN output MatMuls
        kept FP32); premise = evidence, hypothesis = question; features = entailment and contradiction log-probs.
   lens: a trained Lens-Core answerability head (lens_model/), ONNX from --lens-model; feature = support logit.
   scores: any judge's precomputed scores from lens_model/eval/compare_answerability.py (--scores).
4. Grouped 5-fold CV (group = evidence memory) for the threshold at a target false-answer rate; reports wrong
   answers, wrong-evidence answers and false rejections separately, plus model RAM and per-pair latency.
   --merge-qa adds the QA score from an earlier rows file (same deterministic retrieval) for combined variants.
Usage: .venv\\Scripts\\python.exe scripts/experiment_answer_verifier.py [--verifier qa|nli|lens|scores] [--lens-model ONNX] [--scores JSONL] [--reuse DIR] [--target 0.05]
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import time
import numpy as np
import onnxruntime as ort
import psutil
from tokenizers import Tokenizer
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import benchmark_retrieval_nl as bench
import fit_answerability as fa
QA_DIR=ROOT/'models/onnx-community--xlm-roberta-base-squad2-distilled-ONNX'
NLI_DIR=ROOT/'models/MoritzLaurer--multilingual-MiniLMv2-L6-mnli-xnli/onnx'


def retrieve(fixture_names,base,reuse):
    cache=base/'rows-evidence.json'
    if reuse and cache.exists():return json.loads(cache.read_text(encoding='utf-8'))
    out=[];lock=json.loads((ROOT/'third_party/embedding-lock.json').read_text(encoding='utf-8'))
    sha=next(f['sha256'] for f in lock['files'] if f['filename']=='onnx/model_qint8_avx512_vnni.onnx')
    model_id=f"intfloat/multilingual-e5-small@{lock['revision'][:12]}/onnx/model_qint8_avx512_vnni.onnx#sha256:{sha[:16]}"
    for corpus_name,names in fixture_names.items():
        memories,_=bench.load(bench.FIXTURES[corpus_name]);corpus=memories+bench.distractors(10000-len(memories))
        db=base/corpus_name/'memory.db';db.parent.mkdir(parents=True,exist_ok=reuse)
        engine=bench.Engine(db,model_id,'onnx/model_qint8_avx512_vnni.onnx')
        if not reuse:
            engine.ask({'op':'begin'})
            for i in range(0,len(corpus),128):engine.ask({'op':'import_batch','consent':True,'records':[bench.record(x,i+k) for k,x in enumerate(corpus[i:i+128])]})
            engine.ask({'op':'commit'})
        while engine.ask({'op':'index','limit':4096})['pending_sources']:pass
        for name in names:
            _,queries=bench.load(bench.FIXTURES[name])
            if name=='v1':queries=[q for q in queries if q['split'] in ('dev','test')]
            for q in queries:
                r=engine.ask({'op':'recall','query':q['query'],'mode':'hybrid','limit':3,'abstain':False,'interpret_time':False,'interpret_query':False})
                res=r.get('results',[]);ids=[x['source']['id'] for x in res]
                rel=q['relevant'] if isinstance(q['relevant'],list) or q['relevant'] is None else [q['relevant']]
                rank=min([ids.index(x)+1 for x in (rel or []) if x in ids],default=None)
                out.append({**q,'set':name,'rank':rank,'evidence':[x['evidence']['quote'] for x in res],
                            'rerank':[x['scores'].get('rerank') for x in res],'semantic':[x['scores'].get('semantic') for x in res],
                            'full_keyword_match':r.get('full_keyword_match'),'best_rerank':r.get('best_rerank'),'best_semantic':r.get('best_semantic')})
        engine.close()
    cache.write_text(json.dumps(out,ensure_ascii=False),encoding='utf-8')
    return out


class QA:
    name='deepset/xlm-roberta-base-squad2-distilled INT8 (onnx-community 484112f)'
    features=['qa']

    def __init__(self):
        proc=psutil.Process();before=proc.memory_info().rss;t=time.perf_counter()
        opts=ort.SessionOptions();opts.intra_op_num_threads=4
        self.s=ort.InferenceSession(str(QA_DIR/'onnx/model_int8.onnx'),opts,providers=['CPUExecutionProvider'])
        self.tok=Tokenizer.from_file(str(QA_DIR/'tokenizer.json'));self.tok.enable_truncation(384,strategy='only_second')
        self.load_s=time.perf_counter()-t;self.load_rss=proc.memory_info().rss-before;self.lat=[]
        self.inputs=[i.name for i in self.s.get_inputs()]

    def score(self,question,context):
        enc=self.tok.encode(question,context);ids=np.array([enc.ids],dtype=np.int64)
        feeds={'input_ids':ids,'attention_mask':np.ones_like(ids)}
        if 'token_type_ids' in self.inputs:feeds['token_type_ids']=np.zeros_like(ids)
        t=time.perf_counter();start,end=self.s.run(None,feeds)[:2];self.lat.append((time.perf_counter()-t)*1000)
        s,e=start[0],end[0];ctx=[i for i,sid in enumerate(enc.sequence_ids) if sid==1]
        if not ctx:return [-99.0]
        null=s[0]+e[0];best=-1e9;lo,hi=ctx[0],ctx[-1]
        top_s=lo+np.argsort(s[lo:hi+1])[::-1][:20];top_e=lo+np.argsort(e[lo:hi+1])[::-1][:20]
        for i in top_s:
            for j in top_e:
                if i<=j<=i+30:best=max(best,s[i]+e[j])
        return [float(best-null)]


class NLI:
    name='MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli 0a71e92 INT8 (per-channel, FFN output FP32)'
    features=['nli_entail','nli_contra']

    def __init__(self):
        proc=psutil.Process();before=proc.memory_info().rss;t=time.perf_counter()
        opts=ort.SessionOptions();opts.intra_op_num_threads=4
        self.s=ort.InferenceSession(str(NLI_DIR/'model_int8_pc_ffnout_fp32.onnx'),opts,providers=['CPUExecutionProvider'])
        self.tok=Tokenizer.from_file(str(NLI_DIR/'tokenizer.json'));self.tok.enable_truncation(256,strategy='only_first')
        self.load_s=time.perf_counter()-t;self.load_rss=proc.memory_info().rss-before;self.lat=[]

    def score(self,question,evidence):
        ids=np.array([self.tok.encode(evidence,question).ids],dtype=np.int64)
        t=time.perf_counter();l=self.s.run(None,{'input_ids':ids,'attention_mask':np.ones_like(ids)})[0][0]
        self.lat.append((time.perf_counter()-t)*1000);lp=l-l.max()-np.log(np.exp(l-l.max()).sum())
        return [float(lp[0]),float(lp[2])]


class Lens:
    features=['lens_support']

    def __init__(self,model):
        proc=psutil.Process();before=proc.memory_info().rss;t=time.perf_counter()
        opts=ort.SessionOptions();opts.intra_op_num_threads=4
        self.s=ort.InferenceSession(str(model),opts,providers=['CPUExecutionProvider'])
        self.tok=Tokenizer.from_file(str(Path(model).parent/'tokenizer.json'));self.tok.enable_truncation(192,strategy='longest_first')
        self.load_s=time.perf_counter()-t;self.load_rss=proc.memory_info().rss-before;self.lat=[]
        self.name=f'Lens-Core answerability ({Path(model).parent.name}/{Path(model).name})'

    def score(self,question,evidence):
        ids=np.array([self.tok.encode(question,evidence).ids],dtype=np.int64)
        t=time.perf_counter();l=self.s.run(None,{'input_ids':ids,'attention_mask':np.ones_like(ids)})[0][0]
        self.lat.append((time.perf_counter()-t)*1000);return [float(l[0])]


class Scores:
    """Precomputed judge scores (lens_model/eval/compare_answerability.py) for the lens_harness pairs."""
    features=['judge']

    def __init__(self,path):
        self.map={r['id']:r['score'] for r in map(json.loads,Path(path).open(encoding='utf-8')) if r['set']=='lens_harness'}
        self.name=f'precomputed judge scores ({Path(path).stem})';self.load_s=0.0;self.load_rss=0;self.lat=[0.0];self.key=None

    def score(self,question,evidence):return [float(self.map[self.key])]


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--target',type=float,default=0.05)
    ap.add_argument('--verifier',choices=['qa','nli','lens','scores'],default='qa');ap.add_argument('--reuse',type=Path)
    ap.add_argument('--lens-model',type=Path);ap.add_argument('--scores',type=Path)
    ap.add_argument('--merge-qa',type=Path);args=ap.parse_args()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    rows=retrieve({'v1':['v1','nearmiss'],'expansion':['expansion']},args.reuse or ROOT/'artifacts'/f'verifier-{stamp}',bool(args.reuse))
    v=QA() if args.verifier=='qa' else NLI() if args.verifier=='nli' else Scores(args.scores) if args.verifier=='scores' else Lens(args.lens_model);nf=len(v.features)
    for r in rows:
        if args.verifier=='scores':v.key=f"{r['set']}:{r['id']}"
        r['verifier']=v.score(r['query'],r['evidence'][0]) if r['evidence'] else [-99.0]*nf
    peak=psutil.Process().memory_info().peak_wset
    if args.verifier=='qa':
        for r in rows:r['qa']=r['verifier'][:1]
    if args.merge_qa:
        qa={(r['set'],r['id']):r['qa'] for r in json.loads(args.merge_qa.read_text(encoding='utf-8'))}
        for r in rows:r['qa']=qa[(r['set'],r['id'])]
    for r in rows:r['mode']=fa.MODE;r['split']=r['set'] if r['set']!='v1' else r['split']
    X=np.array([r['verifier']+[(r['best_rerank'] if r['best_rerank'] is not None else -10),(r['best_semantic'] or 0),
                1.0 if r['full_keyword_match'] else 0.0]+([r['qa'][0] if r['qa'] else -99.0] if args.merge_qa else []) for r in rows])
    y=np.array([1 if r['relevant'] and r['rank']==1 else 0 for r in rows])
    groups=sorted({fa.group_of(r) for r in rows});rng=np.random.default_rng(20261026)
    gfold={g:int(k) for g,k in zip(groups,rng.integers(0,5,len(groups)))};fold=np.array([gfold[fa.group_of(r)] for r in rows])
    report={'created_utc':stamp,'verifier':v.name,'features':v.features,
            'load_seconds':v.load_s,'load_rss_bytes':v.load_rss,'process_peak_working_set_bytes':peak,
            'latency_ms':{'p50':float(np.percentile(v.lat,50)),'p95':float(np.percentile(v.lat,95)),'p99':float(np.percentile(v.lat,99))},
            'target_false_answer_rate':args.target,'variants':{},'curves':{}}
    sets=sorted({r['split'] for r in rows});sel=lambda s:[i for i,r in enumerate(rows) if r['split']==s]
    vc=list(range(nf));fc=[nf,nf+1,nf+2]
    variants=[(f'{args.verifier}_only',vc),(f'{args.verifier}+rerank+cosine+literal',vc+fc),('rerank+cosine+literal (no verifier)',fc)]
    if args.merge_qa:variants+=[('qa+rerank+cosine+literal',[nf+3]+fc),(f'qa+{args.verifier}+rerank+cosine+literal',[nf+3]+vc+fc)]
    for name,cols in variants:
        p=np.zeros(len(rows));ts=[]
        for k in range(5):
            tr,te=fold!=k,fold==k;m=fa.fit(X[tr][:,cols],y[tr])
            t=fa.choose_threshold(fa.prob(m,X[tr][:,cols]),[rows[i] for i in np.where(tr)[0]],args.target);ts.append(t);p[te]=fa.prob(m,X[te][:,cols])
        t=float(np.median(ts))
        report['variants'][name]={s:fa.evaluate(p[sel(s)],[rows[i] for i in sel(s)],t) for s in sets}|{'all':fa.evaluate(p,rows,t)}
        report['curves'][name]=[{'threshold':float(c)}|fa.evaluate(p,rows,float(c)) for c in np.linspace(0.1,0.95,18)]
    tag=args.scores.stem if args.verifier=='scores' else args.verifier
    out=ROOT/'reports/retrieval-nl/dev-experiments'/f'answer-verifier-{tag}-{stamp}.json'
    out.write_text(json.dumps(report,indent=1,default=float),encoding='utf-8')
    (out.with_suffix('.rows.json')).write_text(json.dumps([{k:v for k,v in r.items() if k!='evidence'} for r in rows],ensure_ascii=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('variants','curves')},indent=1))
    for name,res in report['variants'].items():
        print('==',name)
        for s,m in res.items():print(f'  {s:10s}',{k:(round(float(x),3) if isinstance(x,float) else x) for k,x in m.items() if x is not None})


if __name__=='__main__':main()
