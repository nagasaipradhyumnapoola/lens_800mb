"""Answerability data v1: targets the gaps found when v0 met Lens-shaped questions (docs/VERIFICATION.md):
(1) near-misses that ask about a DIFFERENT entity/attribute than the evidence holds, (2) keyword lookups that are not
questions, (3) question and evidence in different languages. Built only from the licensed public sources of v0, with
v0's held-out splits preserved (IndicQA by article, XQuAD by paragraph per language; a cross-lingual XQuAD pair is used
only if BOTH paragraphs were training data in v0). Lens fixtures are never used here.

New examples:
- substitution near-miss: an answerable question in which one token that also appears in its evidence is replaced by a
  same-language token absent from that evidence (taken from another training window) — label 0;
- keyword lookup: a 1-3 token span (2-4 characters for Chinese) present in the window — label 1; a span from another
  window of the same language that is absent — label 0;
- cross-lingual: XQuAD parallel questions (en/es/zh/hi) with the supporting window of another language — label 1 —
  and that language's related-but-unsupported window — label 0.
Plus a replay sample of v0 training pairs. Output: artifacts/lens-model/answerability-v1/train.jsonl (+ build report);
v0's dev and held-out files are reused unchanged for evaluation.
"""
import collections
import hashlib
import json
from pathlib import Path
import random
import re
import sys
import pyarrow.parquet as pq
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'lens_model/data'))
from build_answerability import EXT,pairs,windows
V0=ROOT/'artifacts/lens-model/answerability-v0'
OUT=ROOT/'artifacts/lens-model/answerability-v1'
HAN=re.compile(r'[一-鿿]')


def tokens(text,lang):
    if lang=='zh':return [m.group(0) for m in re.finditer(r'[一-鿿]{2,4}',text)]
    return [t.strip('.,;:!?()[]"\'¿¡।॥') for t in text.split()]


def substitution(row,pool,common,rng):
    q,e,lang=row['q'],row['e'],row['lang']
    if lang=='zh':
        cands=[q[i:i+2] for i in range(len(q)-1) if HAN.match(q[i]) and HAN.match(q[i+1]) and q[i:i+2] in e]
    else:
        cands=[t for t in tokens(q,lang) if len(t)>=3 and t in e and t.casefold() not in common[lang]]
    if not cands:return None
    old=rng.choice(cands)
    for _ in range(20):
        new=rng.choice(pool[lang])
        if new and new!=old and new not in e and new.casefold() not in common[lang] and (lang=='zh' or len(new)>=3):
            if old[:1].isupper():new=new[:1].upper()+new[1:]
            return {**row,'q':q.replace(old,new,1),'y':0,'kind':'substitution_near_miss','src':row['src']+'+substitution'}
    return None


def keyword(row,pool,common,rng,other):
    lang=row['lang'];toks=[t for t in tokens(row['e'],lang) if (len(t)>=4 or any(c.isdigit() for c in t)) and t.casefold() not in common[lang]]
    if not toks:return []
    i=rng.randrange(len(toks));span=' '.join(toks[i:i+rng.randint(1,3)]) if lang!='zh' else toks[i]
    out=[{**row,'q':span,'y':1,'kind':'keyword_present','src':row['src']+'+keyword'}]
    for _ in range(20):
        w=rng.choice(other[lang]);ot=[t for t in tokens(w,lang) if len(t)>=4 and t.casefold() not in common[lang]]
        if ot:
            s=rng.choice(ot)
            if s not in row['e']:out.append({**row,'q':s,'y':0,'kind':'keyword_absent','src':row['src']+'+keyword'});break
    return out


def in_v0_train(lang,context):
    key=hashlib.sha256(context.encode()).hexdigest()[:12]
    return int(key,16)%10>=3  # v0 xquad(): held out when <3


def cross_lingual(rng):
    data={l:{r['id']:r for r in pq.read_table(EXT/f'xquad/xquad.{l}.parquet').to_pylist()} for l in ('en','es','zh','hi')}
    out=[]
    for qid,en in data['en'].items():
        langs=[l for l in ('en','es','zh','hi') if in_v0_train(l,data[l][qid]['context'])]
        for ql in langs:
            for cl in langs:
                if ql==cl or rng.random()>0.5:continue
                q=data[ql][qid]['question'];c=data[cl][qid];a=c['answers']
                out+=[{**p,'lang':f'{ql}>{cl}','src':'xquad-cross'} for p in pairs(q,c['context'],a['answer_start'][0],a['text'][0],cl,'xquad-cross',f'xquad-x:{qid}',True,rng)]
    return out


def main():
    rng=random.Random(20261027)
    v0=[json.loads(l) for l in (V0/'train.jsonl').open(encoding='utf-8')]
    counts=collections.defaultdict(collections.Counter)
    for r in v0:
        for t in tokens(r['e'],r['lang']):counts[r['lang']][t.casefold()]+=1
    common={l:{t for t,_ in c.most_common(150)} for l,c in counts.items()}
    pool={l:[t for t,n in c.items() if n<=50 and (l=='zh' or len(t)>=3)] for l,c in counts.items()}
    other=collections.defaultdict(list)
    for r in v0:other[r['lang']].append(r['e'])
    positives=[r for r in v0 if r['y']==1];rng.shuffle(positives)
    subs=[s for s in (substitution(r,pool,common,rng) for r in positives[:30000]) if s]
    keys=[k for r in positives[30000:42000] for k in keyword(r,pool,common,rng,other)]
    cross=cross_lingual(rng)
    replay=rng.sample(v0,24000)
    train=subs+keys+cross+replay;rng.shuffle(train)
    OUT.mkdir(parents=True,exist_ok=True)
    with (OUT/'train.jsonl').open('w',encoding='utf-8') as f:
        for r in train:f.write(json.dumps(r,ensure_ascii=False)+'\n')
    report={'train':len(train),'substitution_near_miss':len(subs),'keyword':len(keys),'cross_lingual':len(cross),'replay_v0':len(replay),
            'by_kind':dict(collections.Counter(r['kind'] for r in train)),'samples':{k:next(r for r in train if r['kind']==k) for k in ('substitution_near_miss','keyword_present','keyword_absent')}}
    (OUT/'build-report.json').write_text(json.dumps(report,indent=1,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='samples'},indent=1,ensure_ascii=False))
    for k,v in report['samples'].items():print(k,'|',v['q'],'|',v['e'][:120])


if __name__=='__main__':main()
