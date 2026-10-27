"""Compare dense retrieval embeddings on Lens-shaped and public multilingual retrieval (CPU, exact search).

Benchmarks:
- lens_nl:   Lens NL fixtures (v1 dev+test answerable queries, expansion cross-app/timeline/mixed) over the v1 + expansion
             memories plus 10,000 multilingual synthetic distractors (scripts/benchmark_retrieval_nl.py) — never the
             sealed holdout. Same-language, cross-language, romanized code-switch, paraphrase and exact queries.
- mlqa_ret:  MLQA test paragraph retrieval: 200 sampled questions per config against all distinct paragraphs of the
             config (capped at 1,500, the gold paragraphs always included); 7 monolingual + 6 cross-lingual configs.
Models (FP32 PyTorch, each with its documented pooling and prefixes):
  e5-small (the embedding Lens ships, INT8 in the engine), e5-base, e5-large-instruct, granite-278m (IBM),
  arctic-l-v2 (Snowflake), bge-m3, qwen3-embedding-0.6b.
Metrics: R@1, R@10, MRR@10 per benchmark and language; corpus and query throughput; peak working set.
Writes reports/lens-model/benchmark/retrieval-<model>.json; --summary writes retrieval-comparison.{json,md}.
Usage: .venv-train\\Scripts\\python.exe lens_model/eval/compare_retrieval.py --model NAME | --summary
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import random
import sys
import time
import numpy as np
import psutil
import pyarrow.parquet as pq
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import benchmark_retrieval_nl as bench
BASE=ROOT/'models/baselines'
REPORTS=ROOT/'reports/lens-model/benchmark'
EXT=ROOT/'data/external'
TASK='Given a question, retrieve the passage or personal memory that answers it'
THREADS=8
MODELS={  # folder, pooling, query template, passage template, max tokens
    'e5-small':('intfloat--multilingual-e5-small','mean','query: {}','passage: {}',512),
    'e5-base':('intfloat--multilingual-e5-base','mean','query: {}','passage: {}',512),
    'e5-large-instruct':('intfloat--multilingual-e5-large-instruct','mean','Instruct: '+TASK+'\nQuery: {}','{}',512),
    'bge-m3':('BAAI--bge-m3','cls','{}','{}',512),
    'granite-278m':('ibm-granite--granite-embedding-278m-multilingual','cls','{}','{}',512),
    'arctic-l-v2':('Snowflake--snowflake-arctic-embed-l-v2.0','cls','query: {}','{}',512),
    'qwen3-embedding-0.6b':('Qwen--Qwen3-Embedding-0.6B','last','Instruct: '+TASK+'\nQuery:{}','{}',512),
}
MLQA_MONO=[f'mlqa.{l}.{l}' for l in ('en','es','hi','zh','de','ar','vi')]
MLQA_CROSS=['mlqa.en.hi','mlqa.hi.en','mlqa.en.zh','mlqa.zh.en','mlqa.en.es','mlqa.es.en']


class Embedder:
    def __init__(self,name):
        import torch
        from transformers import AutoModel,AutoTokenizer
        folder,self.pool,self.qt,self.pt,self.max_len=MODELS[name];path=BASE/folder;self.torch=torch
        self.tok=AutoTokenizer.from_pretrained(path,padding_side='left' if self.pool=='last' else 'right')
        self.m=AutoModel.from_pretrained(path,torch_dtype=torch.float32).eval()
        self.weights_mb=sum(p.stat().st_size for p in [*path.glob('*.safetensors'),*path.glob('pytorch_model.bin')])/2**20

    def encode(self,texts,query,bs=16):
        tpl=self.qt if query else self.pt;order=np.argsort([len(t) for t in texts]);out=np.zeros((len(texts),self.m.config.hidden_size),dtype=np.float32)
        with self.torch.inference_mode():
            for k in range(0,len(texts),bs):
                ids=order[k:k+bs];enc=self.tok([tpl.format(texts[i]) for i in ids],padding=True,truncation=True,max_length=self.max_len,return_tensors='pt')
                h=self.m(**enc).last_hidden_state
                if self.pool=='mean':m=enc['attention_mask'].unsqueeze(-1).float();v=(h*m).sum(1)/m.sum(1)
                elif self.pool=='cls':v=h[:,0]
                else:v=h[:,-1]  # left padding: the last position is the final token
                out[ids]=self.torch.nn.functional.normalize(v.float(),dim=-1).numpy()
        return out


def ranks(q,d,relevant):
    s=q@d.T;out=[]
    for i,rel in enumerate(relevant):
        top=np.argsort(-s[i])[:100];hit=[k+1 for k,j in enumerate(top) if j in rel];out.append(hit[0] if hit else None)
    return out


def metrics(rk):
    n=len(rk);return {'n':n,'r@1':sum(1 for r in rk if r==1)/n,'r@10':sum(1 for r in rk if r and r<=10)/n,
                      'mrr@10':sum(1/r for r in rk if r and r<=10)/n}


def lens_nl():
    mem,qs=[],[]
    for f in ('v1','expansion'):
        m,q=bench.load(bench.FIXTURES[f]);mem+=m;qs+=[x for x in q if x.get('relevant')]
    corpus=mem+bench.distractors(10000);index={m['id']:i for i,m in enumerate(corpus)}
    rel=[{index[r] for r in (q['relevant'] if isinstance(q['relevant'],list) else [q['relevant']])} for q in qs]
    return [m['text'] for m in corpus],[q['query'] for q in qs],rel,[f"{q['type']}" for q in qs],[q['query_language'] for q in qs]


BELE={'eng_Latn':'en','zho_Hans':'zh','spa_Latn':'es','arb_Arab':'ar','fra_Latn':'fr','por_Latn':'pt','rus_Cyrl':'ru','ind_Latn':'id',
      'deu_Latn':'de','jpn_Jpan':'ja','hin_Deva':'hi','ben_Beng':'bn','tel_Telu':'te','mar_Deva':'mr','tam_Taml':'ta','urd_Arab':'ur',
      'guj_Gujr':'gu','hin_Latn':'hi-Latn','ben_Latn':'bn-Latn','urd_Latn':'ur-Latn'}
TARGET=['en','zh','es','ar','fr','pt','ru','id','de','ja','hi','bn','te','mr','ta','ur','gu']  # spec §1a


def belebele_sets(rng,n=200):
    """Belebele (CC BY-SA 4.0) passage retrieval: 200 questions per language against all 488 FLORES passages of that
    language; cross = the language's questions against the English passages. Same question sample in every language."""
    load=lambda c:[json.loads(l) for l in (EXT/f'belebele/{c}.jsonl').open(encoding='utf-8')]
    en=load('eng_Latn');pick=rng.sample(range(len(en)),n);keys=[(r['link'],r['question_number']) for r in en];out={}
    def build(qrows,prows):
        ps=list(dict.fromkeys(r['flores_passage'] for r in prows));idx={p:i for i,p in enumerate(ps)}
        return ps,[qrows[i]['question'] for i in pick],[{idx[prows[i]['flores_passage']]} for i in pick]
    for cfg,lang in BELE.items():
        by={(r['link'],r['question_number']):r for r in load(cfg)};rows=[by[k] for k in keys]
        out[lang]=build(rows,rows)
        if lang in ('zh','ar','ru','ja','hi','bn','te','fr','pt','ur'):out[f'{lang}>en']=build(rows,en)
    return out


def mlqa(cfg,rng):
    rows=pq.read_table(EXT/f'mlqa/{cfg}.test.parquet').to_pylist();rng.shuffle(rows);pick=rows[:200]
    ctx=list(dict.fromkeys([r['context'] for r in pick]+[r['context'] for r in rows]))[:1500];index={c:i for i,c in enumerate(ctx)}
    return ctx,[r['question'] for r in pick],[{index[r['context']]} for r in pick]


def run(name):
    import torch;torch.set_num_threads(THREADS)
    proc=psutil.Process();t=time.perf_counter();emb=Embedder(name);load_s=time.perf_counter()-t;rep={'model':name,'weights_mb':emb.weights_mb,'load_seconds':load_s,'benchmarks':{}}
    docs_n=0;docs_s=0.0;q_n=0;q_s=0.0
    corpus,queries,rel,types,langs=lens_nl()
    t=time.perf_counter();D=emb.encode(corpus,False);docs_s+=time.perf_counter()-t;docs_n+=len(corpus)
    t=time.perf_counter();Q=emb.encode(queries,True);q_s+=time.perf_counter()-t;q_n+=len(queries)
    rk=ranks(Q,D,rel);res={'all':metrics(rk)}
    for key,vals in (('type',types),('lang',langs)):
        for v in sorted(set(vals)):res[f'{key}:{v}']=metrics([r for r,x in zip(rk,vals) if x==v])
    rep['benchmarks']['lens_nl']=res;print(name,'lens_nl',{k:round(v,3) for k,v in res['all'].items()},flush=True)
    rng=random.Random(20261027);ml={}
    for cfg in MLQA_MONO+MLQA_CROSS:
        ctx,qs,rl=mlqa(cfg,rng)
        t=time.perf_counter();D=emb.encode(ctx,False);docs_s+=time.perf_counter()-t;docs_n+=len(ctx)
        t=time.perf_counter();Q=emb.encode(qs,True);q_s+=time.perf_counter()-t;q_n+=len(qs)
        ml[cfg]=metrics(ranks(Q,D,rl));print(name,cfg,{k:round(v,3) for k,v in ml[cfg].items()},flush=True)
    avg=lambda cfgs,k:float(np.mean([ml[c][k] for c in cfgs]))
    ml['mono_macro']={k:avg(MLQA_MONO,k) for k in ('r@1','r@10','mrr@10')};ml['cross_macro']={k:avg(MLQA_CROSS,k) for k in ('r@1','r@10','mrr@10')}
    rep['benchmarks']['mlqa_ret']=ml
    bl={}
    for key,(ctx,qs,rl) in belebele_sets(random.Random(20261028)).items():
        t=time.perf_counter();D=emb.encode(ctx,False);docs_s+=time.perf_counter()-t;docs_n+=len(ctx)
        t=time.perf_counter();Q=emb.encode(qs,True);q_s+=time.perf_counter()-t;q_n+=len(qs)
        bl[key]=metrics(ranks(Q,D,rl));print(name,'belebele',key,{k:round(v,3) for k,v in bl[key].items()},flush=True)
    mono=[l for l in TARGET if l in bl];cross=[k for k in bl if '>' in k];roman=[k for k in bl if k.endswith('-Latn')]
    for tag,keys in (('language_macro',mono),('cross_macro',cross),('romanized_macro',roman)):
        bl[tag]={k:float(np.mean([bl[x][k] for x in keys])) for k in ('r@1','r@10','mrr@10')}
    rep['benchmarks']['belebele_ret']=bl
    rep|={'created_utc':datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),'threads':THREADS,'docs_per_s':docs_n/docs_s,'queries_per_s':q_n/q_s,
          'peak_working_set_mb':proc.memory_info().peak_wset/2**20}
    REPORTS.mkdir(parents=True,exist_ok=True);(REPORTS/f'retrieval-{name}.json').write_text(json.dumps(rep,indent=1),encoding='utf-8')
    print(json.dumps({k:v for k,v in rep.items() if k!='benchmarks'},indent=1))


def summary():
    rows=[]
    for p in sorted(REPORTS.glob('retrieval-*.json')):
        if p.stem=='retrieval-comparison':continue
        r=json.loads(p.read_text(encoding='utf-8'));b=r['benchmarks']
        rows.append({'model':r['model'],'weights_mb':round(r['weights_mb']),'peak_ws_mb':round(r['peak_working_set_mb']),'docs_per_s':round(r['docs_per_s'],1),
                     'lens_nl':b['lens_nl']['all'],'lens_cross_language':b['lens_nl'].get('type:cross_language'),'lens_code_switch':b['lens_nl'].get('type:code_switch'),
                     'mlqa_mono':b['mlqa_ret']['mono_macro'],'mlqa_cross':b['mlqa_ret']['cross_macro'],
                     'global17':b.get('belebele_ret',{}).get('language_macro'),'global_cross':b.get('belebele_ret',{}).get('cross_macro'),
                     'romanized':b.get('belebele_ret',{}).get('romanized_macro')})
    rows.sort(key=lambda r:-(r['lens_nl']['mrr@10']+r['mlqa_mono']['mrr@10']+r['mlqa_cross']['mrr@10']+((r['global17'] or {}).get('mrr@10',0))))
    (REPORTS/'retrieval-comparison.json').write_text(json.dumps(rows,indent=1),encoding='utf-8')
    f=lambda m:f"{m['r@1']:.3f} / {m['r@10']:.3f} / {m['mrr@10']:.3f}" if m else '—'
    lines=['| model | weights MB | peak RAM MB | docs/s | Lens NL | Lens cross-language | Lens code-switch | MLQA mono | MLQA cross | 17-language (Belebele) | cross→en (Belebele) | romanized hi/bn/ur |','|---|---|---|---|---|---|---|---|---|---|---|---|']
    for r in rows:lines.append(f"| {r['model']} | {r['weights_mb']} | {r['peak_ws_mb']} | {r['docs_per_s']} | {f(r['lens_nl'])} | {f(r['lens_cross_language'])} | {f(r['lens_code_switch'])} | {f(r['mlqa_mono'])} | {f(r['mlqa_cross'])} | {f(r['global17'])} | {f(r['global_cross'])} | {f(r['romanized'])} |")
    md='Cells: R@1 / R@10 / MRR@10. Exact dense search, FP32, CPU.\n\n'+'\n'.join(lines)+'\n'
    (REPORTS/'retrieval-comparison.md').write_text(md,encoding='utf-8');print(md)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--model',choices=list(MODELS));ap.add_argument('--summary',action='store_true');a=ap.parse_args()
    summary() if a.summary else run(a.model)


if __name__=='__main__':main()
