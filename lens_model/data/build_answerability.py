"""Build the Lens-Core answerability training/evaluation pairs (docs/LENS_MODEL.md, stage T2) from licensed public QA data.

Each example is (question, evidence window, label): label 1 when the window contains the gold answer (supported),
0 when it does not. Evidence windows are one or two sentences (<= 320 characters), the size of a Lens memory snippet.
Negatives are hard by construction:
- answerable question + the most question-like window that does NOT contain the answer (relevant, unsupported);
- unanswerable question (SQuAD 2.0 adversarial, IndicQA "NO") + its most question-like window (near-miss).
Similarity is character-trigram containment of the question, which works for every script.

Sources (lens_model/manifest/datasets.json): SQuAD 2.0 (en, CC BY-SA 4.0), TyDi QA GoldP (9 languages incl. te,
Apache-2.0), IndicQA (hi/ta/te with unanswerables, CC BY 4.0), XQuAD (es/zh/hi, CC BY-SA 4.0; plus cross-paragraph
near-misses). IndicQA (by article) and XQuAD (by paragraph) are split 70% train / 30% held out as public evaluation
sets that are never trained on. Official validation splits are evaluation-only.
No personal data. Output: artifacts/lens-model/answerability-v0/{train,dev,indicqa_heldout,xquad_heldout}.jsonl
Usage: .venv-train\\Scripts\\python.exe lens_model/data/build_answerability.py [--squad 30000] [--tydi-per-lang 3000]
"""
import argparse
import hashlib
import json
from pathlib import Path
import random
import re
import pyarrow.parquet as pq
ROOT=Path(__file__).resolve().parents[2]
EXT=ROOT/'data/external'
OUT=ROOT/'artifacts/lens-model/answerability-v0'
SENT=re.compile(r'(?<=[.!?।॥。！？])\s+|(?<=[。！？])')
MAX_WINDOW=320


def sentences(text):
    out=[];pos=0
    for m in SENT.finditer(text):
        if m.end()>pos:out.append((pos,m.start() if m.start()>pos else m.end()));pos=m.end()
    if pos<len(text):out.append((pos,len(text)))
    return [(a,b) for a,b in out if text[a:b].strip()]


def windows(text):
    """One- and two-sentence windows as (start, end) character spans, each <= MAX_WINDOW characters."""
    s=sentences(text);out=[]
    for i,(a,b) in enumerate(s):
        if b-a<=MAX_WINDOW:out.append((a,b))
        if i+1<len(s) and s[i+1][1]-a<=MAX_WINDOW:out.append((a,s[i+1][1]))
        if b-a>MAX_WINDOW:  # very long sentence: fixed slices
            out+=[(k,min(b,k+MAX_WINDOW)) for k in range(a,b,MAX_WINDOW//2)]
    return out


def grams(text):
    t=re.sub(r'\s+',' ',text.casefold());return {t[i:i+3] for i in range(max(1,len(t)-2))}


def most_similar(question,text,spans,exclude=lambda s:False):
    q=grams(question);best=None;score=-1.0
    for s in spans:
        if exclude(s):continue
        g=grams(text[s[0]:s[1]]);v=len(q&g)/max(1,len(q))
        if v>score:best,score=s,v
    return best


def pairs(question,context,answer_start,answer_text,lang,src,group,answerable,rng):
    spans=windows(context);out=[]
    if not spans:return out
    ev=lambda s:context[s[0]:s[1]].strip()
    if answerable:
        end=answer_start+len(answer_text)
        holds=lambda s:s[0]<=answer_start and end<=s[1]
        pos=[s for s in spans if holds(s)]
        if not pos:return out
        p=min(pos,key=lambda s:s[1]-s[0]);out.append({'q':question,'e':ev(p),'y':1,'lang':lang,'src':src,'group':group,'kind':'supported'})
        neg=most_similar(question,context,spans,exclude=lambda s:s[0]<end and answer_start<s[1] or answer_text.strip() in context[s[0]:s[1]])
        if neg:out.append({'q':question,'e':ev(neg),'y':0,'lang':lang,'src':src,'group':group,'kind':'related_unsupported'})
    else:
        neg=most_similar(question,context,spans)
        if neg:out.append({'q':question,'e':ev(neg),'y':0,'lang':lang,'src':src,'group':group,'kind':'unanswerable_near_miss'})
    return out


def squad(split,limit,rng):
    t=pq.read_table(EXT/f'squad_v2/{split}.parquet').to_pylist();rng.shuffle(t);out=[]
    for r in t[:limit]:
        a=r['answers'];ok=bool(a['text'])
        out+=pairs(r['question'],r['context'],a['answer_start'][0] if ok else 0,a['text'][0] if ok else '','en','squad_v2',
                   'squad:'+r['title'],ok,rng)
    return out


TYDI_LANG={'english':'en','arabic':'ar','bengali':'bn','finnish':'fi','indonesian':'id','japanese':'ja','korean':'ko',
           'russian':'ru','swahili':'sw','telugu':'te','thai':'th'}


def tydi(split,per_lang,rng):
    t=pq.read_table(EXT/f'tydiqa_goldp/{split}.parquet').to_pylist();rng.shuffle(t);count={};out=[]
    for r in t:
        lang=TYDI_LANG.get(r['id'].split('-')[0])
        if not lang or count.get(lang,0)>=per_lang:continue
        a=r['answers'];count[lang]=count.get(lang,0)+1
        out+=pairs(r['question'],r['context'],a['answer_start'][0],a['text'][0],lang,'tydiqa_goldp','tydi:'+r['title'],True,rng)
    return out


def indicqa(rng):
    train,held=[],[]
    for lang in ('hi','ta','te'):
        data=json.loads((EXT/f'indicqa/indicqa.{lang}.json').read_text(encoding='utf-8'))['data']
        for k,article in enumerate(data):
            bucket=held if int(hashlib.sha256(f'{lang}:{k}'.encode()).hexdigest(),16)%10<3 else train
            for p in article['paragraphs']:
                for qa in p['qas']:
                    a=qa['answers'][0] if qa['answers'] else {'text':'','answer_start':None}
                    ok=bool(a['text'].strip()) and a['answer_start'] is not None
                    bucket+=pairs(qa['question'],p['context'],a['answer_start'] or 0,a['text'],lang,'indicqa',f'indicqa:{lang}:{k}',ok,rng)
    return train,held


def xquad(rng):
    """XQuAD es/zh/hi (answerable only; no article titles), split by paragraph 70/30. Adds cross-paragraph near-misses:
    the question paired with the most question-like window of the most question-like OTHER paragraph that does not
    contain the answer text (topically close, unsupported)."""
    train,held=[],[]
    for lang in ('es','zh','hi'):
        rows=pq.read_table(EXT/f'xquad/xquad.{lang}.parquet').to_pylist();contexts=sorted({r['context'] for r in rows})
        cgrams={c:grams(c) for c in contexts}
        for r in rows:
            key=hashlib.sha256(r['context'].encode()).hexdigest()[:12]
            bucket=held if int(key,16)%10<3 else train
            a=r['answers'];start,text=a['answer_start'][0],a['text'][0]
            bucket+=pairs(r['question'],r['context'],start,text,lang,'xquad',f'xquad:{lang}:{key}',True,rng)
            q=grams(r['question'])
            alt=[c for c in contexts if c!=r['context'] and text.strip() not in c]
            if not alt:continue
            ctx=max(alt,key=lambda c:len(q&cgrams[c]))
            w=most_similar(r['question'],ctx,windows(ctx))
            if w:bucket.append({'q':r['question'],'e':ctx[w[0]:w[1]].strip(),'y':0,'lang':lang,'src':'xquad',
                                'group':f'xquad:{lang}:{key}','kind':'cross_paragraph_near_miss'})
    return train,held


def write(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8') as f:
        for r in rows:f.write(json.dumps(r,ensure_ascii=False)+'\n')


def summary(rows):
    out={}
    for r in rows:
        k=f"{r['lang']}/{r['kind']}";out[k]=out.get(k,0)+1
    return dict(sorted(out.items()))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--squad',type=int,default=30000);ap.add_argument('--tydi-per-lang',type=int,default=3000)
    ap.add_argument('--seed',type=int,default=20261027);args=ap.parse_args();rng=random.Random(args.seed)
    ind_train,ind_held=indicqa(rng);xq_train,xq_held=xquad(rng)
    train=squad('train',args.squad,rng)+tydi('train',args.tydi_per_lang,rng)+ind_train+xq_train
    dev=squad('validation',3000,rng)+tydi('validation',300,rng)
    rng.shuffle(train)
    write(OUT/'train.jsonl',train);write(OUT/'dev.jsonl',dev)
    write(OUT/'indicqa_heldout.jsonl',ind_held);write(OUT/'xquad_heldout.jsonl',xq_held)
    report={'seed':args.seed,'train':len(train),'dev':len(dev),'indicqa_heldout':len(ind_held),'xquad_heldout':len(xq_held),
            'train_by_lang_kind':summary(train),'dev_by_lang_kind':summary(dev),'heldout_by_lang_kind':summary(ind_held+xq_held)}
    (OUT/'build-report.json').write_text(json.dumps(report,indent=1,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if not k.endswith('kind')},indent=1))


if __name__=='__main__':main()
