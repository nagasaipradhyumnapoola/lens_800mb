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


BELE={'eng_Latn':'en','zho_Hans':'zh','spa_Latn':'es','arb_Arab':'ar','fra_Latn':'fr','por_Latn':'pt','rus_Cyrl':'ru','ind_Latn':'id',
      'deu_Latn':'de','jpn_Jpan':'ja','hin_Deva':'hi','ben_Beng':'bn','tel_Telu':'te','mar_Deva':'mr','tam_Taml':'ta','urd_Arab':'ur',
      'guj_Gujr':'gu','hin_Latn':'hi-Latn','ben_Latn':'bn-Latn','urd_Latn':'ur-Latn'}
BELE_CROSS={k:BELE[k] for k in ('zho_Hans','arb_Arab','rus_Cyrl','jpn_Jpan','hin_Deva','ben_Beng','tel_Telu','fra_Latn')}


def belebele(configs,per_lang,rng,cross):
    """Belebele (CC BY-SA 4.0; FLORES passages, parallel across languages). Pair = (question, passage): 1 for the
    question's own passage, 0 for the most question-like OTHER passage (chosen once on English, so every language gets
    the same hard negative). cross=True pairs the question in the language with the ENGLISH passages and vice versa."""
    load=lambda c:[json.loads(l) for l in (EXT/f'belebele/{c}.jsonl').open(encoding='utf-8')]
    en=load('eng_Latn');passages=sorted({r['flores_passage'] for r in en});pg={p:grams(p) for p in passages}
    neg=[max((p for p in passages if p!=r['flores_passage']),key=lambda p:len(grams(r['question'])&pg[p])) for r in en]
    neg_idx=[next(i for i,x in enumerate(en) if x['flores_passage']==n) for n in neg]
    pick=rng.sample(range(len(en)),per_lang);out=[]
    for cfg,lang in configs.items():
        by={(r['link'],r['question_number']):r for r in load(cfg)};rows=[by[(r['link'],r['question_number'])] for r in en]  # align to English order
        for i in pick:
            variants=[(rows,rows,lang)] if not cross else [(rows,en,f'{lang}>en'),(en,rows,f'en>{lang}')]
            for qs,ps,tag in variants:
                g=f'belebele:{cfg}:{i}'
                out+=[{'q':qs[i]['question'],'e':ps[i]['flores_passage'],'y':1,'lang':tag,'src':'belebele','group':g,'kind':'supported','id':f'{cfg}:{i}'},
                      {'q':qs[i]['question'],'e':ps[neg_idx[i]]['flores_passage'],'y':0,'lang':tag,'src':'belebele','group':g,'kind':'other_passage_near_miss','id':f'{cfg}:{i}'}]
    return out


def xquad_world(langs,per_lang,rng):
    """XQuAD ru/ar/de (CC BY-SA 4.0): never used by any Lens training."""
    out=[]
    for lang in langs:
        rows=pq.read_table(EXT/f'xquad/xquad.{lang}.parquet').to_pylist();rng.shuffle(rows)
        for r in rows[:per_lang]:
            a=r['answers'];out+=[{**p,'id':r['id']} for p in pairs(r['question'],r['context'],a['answer_start'][0],a['text'][0],lang,'xquad','xquad-w:'+r['id'],True,rng)]
    return out


def indicqa_more(langs,per_lang,rng):
    """IndicQA bn/mr/gu (CC BY 4.0, with unanswerable questions): never used by any Lens training."""
    out=[]
    for lang in langs:
        qas=[(qa,p['context']) for art in json.loads((EXT/f'indicqa/indicqa.{lang}.json').read_text(encoding='utf-8'))['data'] for p in art['paragraphs'] for qa in p['qas']]
        rng.shuffle(qas)
        for qa,ctx in qas[:per_lang]:
            a=qa['answers'][0] if qa['answers'] else {'text':'','answer_start':None};ok=bool(a['text'].strip()) and a['answer_start'] is not None
            out+=[{**p,'id':str(qa.get('id'))} for p in pairs(qa['question'],ctx,a['answer_start'] or 0,a['text'],lang,'indicqa','indicqa-m:'+str(qa.get('id')),ok,rng)]
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
    rng2=random.Random(20261028)  # global sets (2026-10-27 scope, spec §1a) use their own stream: existing samples stay identical
    sets|={'belebele_global':belebele(BELE,80,rng2,cross=False),'belebele_cross':belebele(BELE_CROSS,60,rng2,cross=True),
           'xquad_world':xquad_world(('ru','ar','de'),150,rng2),'indicqa_more':indicqa_more(('bn','mr','gu'),150,rng2)}
    for name,rows in sets.items():
        with (OUT/f'{name}.jsonl').open('w',encoding='utf-8') as f:
            for i,r in enumerate(rows):f.write(json.dumps({'set':name,'idx':i,**r},ensure_ascii=False)+'\n')
        c=collections.Counter(r['y'] for r in rows)
        print(f'{name:16s} {len(rows):5d} pairs  pos {c[1]:4d} neg {c[0]:4d}  langs',dict(collections.Counter(r['lang'] for r in rows)))


if __name__=='__main__':main()
