"""Answerability benchmark sets for comparing the Lens model with public models (Qwen and others).

Every set is (question, evidence window, label) with the same construction as training (lens_model/data/
build_answerability.py): label 1 = the window contains the gold answer; 0 = a related window of the same paragraph
without it, an unanswerable question's closest window, or the closest window of another paragraph.
Sets (deterministic samples, seed 20261027):
- mlqa_mono:  MLQA test en/es/hi/zh/de/ar/vi (CC BY-SA 3.0). Never used by any Lens training or selection — the clean
              public set. de/ar/vi are languages Lens was never trained on (ar only via TyDi).
- mlqa_cross: MLQA test with question and context in different languages (en<->hi, en<->zh, en<->es).
- xquad_heldout, indicqa_heldout: the v0 public held-out splits (never trained on; XQuAD paragraphs have parallel
              versions in other languages that may have been trained on — reported, not hidden).
- squad2_dev, tydi_dev: official validation splits (v0 dev; used only to pick checkpoints, never for gradients).
- lens_harness: the Lens verifier harness (question, top-1 retrieved evidence from the native engine at 10k scale;
              label = the top-1 memory is the relevant one). Dev/inspected Lens fixtures only, never the sealed holdout.
Output: artifacts/lens-model/bench/<set>.jsonl
Usage: .venv-train\\Scripts\\python.exe lens_model/eval/build_benchmarks.py [--harness DIR]
"""
import argparse
import collections
import json
from pathlib import Path
import random
import sys
import pyarrow.parquet as pq
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'lens_model/data'))
from build_answerability import EXT,grams,most_similar,pairs,windows
V0=ROOT/'artifacts/lens-model/answerability-v0'
OUT=ROOT/'artifacts/lens-model/bench'


def mlqa(configs,per_config,rng,cross_paragraph):
    out=[]
    for cfg in configs:
        ctx_lang,q_lang=cfg.split('.')[1:];rows=pq.read_table(EXT/f'mlqa/{cfg}.test.parquet').to_pylist();rng.shuffle(rows)
        contexts=sorted({r['context'] for r in rows});cg={c:grams(c) for c in contexts} if cross_paragraph else {}
        lang=q_lang if q_lang==ctx_lang else f'{q_lang}>{ctx_lang}'
        for r in rows[:per_config]:
            a=r['answers'];start,text=a['answer_start'][0],a['text'][0]
            out+=[{**p,'id':r['id']} for p in pairs(r['question'],r['context'],start,text,lang,'mlqa',f"mlqa:{cfg}:{r['id']}",True,rng)]
            if cross_paragraph:
                q=grams(r['question']);alt=[c for c in contexts if c!=r['context'] and text.strip() not in c]
                if alt:
                    ctx=max(alt,key=lambda c:len(q&cg[c]));w=most_similar(r['question'],ctx,windows(ctx))
                    if w:out.append({'q':r['question'],'e':ctx[w[0]:w[1]].strip(),'y':0,'lang':lang,'src':'mlqa','group':f"mlqa:{cfg}:{r['id']}",
                                     'kind':'cross_paragraph_near_miss','id':r['id']})
    return out


def sample(path,n,rng,where=lambda r:True):
    rows=[json.loads(l) for l in path.open(encoding='utf-8')];rows=[r for r in rows if where(r)]
    groups=collections.defaultdict(list)
    for r in rows:groups[r['group']+'|'+r['q']].append(r)  # keep a question's pairs together
    keys=sorted(groups);rng.shuffle(keys);out=[]
    for k in keys:
        if len(out)>=n:break
        out+=groups[k]
    return out


def harness(folder):
    out=[]
    for r in json.loads((folder/'rows-evidence.json').read_text(encoding='utf-8')):
        if not r['evidence']:continue
        out.append({'q':r['query'],'e':r['evidence'][0],'y':1 if r['relevant'] and r['rank']==1 else 0,'lang':r.get('language','?'),
                    'src':'lens_harness','group':r['set'],'kind':r['set'],'id':f"{r['set']}:{r['id']}"})
    return out


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--harness',type=Path,default=ROOT/'artifacts/verifier-20261026T165918Z')
    args=ap.parse_args();rng=random.Random(20261027);OUT.mkdir(parents=True,exist_ok=True)
    sets={'mlqa_mono':mlqa([f'mlqa.{l}.{l}' for l in ('en','es','hi','zh','de','ar','vi')],120,rng,True),
          'mlqa_cross':mlqa(['mlqa.en.hi','mlqa.hi.en','mlqa.en.zh','mlqa.zh.en','mlqa.en.es','mlqa.es.en'],110,rng,False),
          'xquad_heldout':sample(V0/'xquad_heldout.jsonl',900,rng),
          'indicqa_heldout':sample(V0/'indicqa_heldout.jsonl',900,rng),
          'squad2_dev':sample(V0/'dev.jsonl',800,rng,lambda r:r['src']=='squad_v2'),
          'tydi_dev':sample(V0/'dev.jsonl',800,rng,lambda r:r['src']=='tydiqa_goldp'),
          'lens_harness':harness(args.harness)}
    for name,rows in sets.items():
        with (OUT/f'{name}.jsonl').open('w',encoding='utf-8') as f:
            for i,r in enumerate(rows):f.write(json.dumps({'set':name,'idx':i,**r},ensure_ascii=False)+'\n')
        c=collections.Counter(r['y'] for r in rows)
        print(f'{name:16s} {len(rows):5d} pairs  pos {c[1]:4d} neg {c[0]:4d}  langs',dict(collections.Counter(r['lang'] for r in rows)))


if __name__=='__main__':main()
