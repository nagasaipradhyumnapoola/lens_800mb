"""Lens-style answerability data (docs/LENS_MODEL.md, stage T2): short personal memories like the ones Lens stores (screen
text, chat lines, mail, notes, calendar entries) with an answerable question, a near-miss question that changes one
detail the memory does not support (person, day, time, place, number, action), and an unrelated question.

Generated locally by an open instruct model (default Qwen3-1.7B, Apache-2.0; thinking off) from seed topics and
synthetic names only — never Lens fixtures, never personal data. Leakage guard: an item is dropped when any of its texts
shares a 5-word sequence with a Lens retrieval fixture (v1, expansion, near-miss, acceptance or the sealed holdout) or
reuses a fixture's named entities. Languages per spec §1a priority: en first, then hi, zh, es.
Labels: answerable 1, near-miss and unrelated 0 (gold); teacher soft labels are added by build_distill-style scoring.
Output: artifacts/lens-model/lens-style/items.jsonl and pairs.jsonl (q, e, y, lang, kind, src="lens_style")
Status (2026-10-30): a 48-item trial with Qwen3-1.7B gave malformed near-miss/answerable questions; not used for training
(docs/VERIFICATION.md "Answerability head v3").
Usage: .tools\\venv-train-cuda\\Scripts\\python.exe lens_model/data/build_lens_style.py [--items 3000]
"""
import argparse
import hashlib
import json
from pathlib import Path
import random
import re
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'artifacts/lens-model/lens-style'
MODEL=ROOT/'models/baselines/Qwen--Qwen3-1.7B'
FIXTURES=[ROOT/'data/fixtures/retrieval-nl'/n for n in ('v1.json','expansion.json','nearmiss-v1.json','acceptance.json','holdout.json')]
KINDS=['chat message','work email excerpt','calendar entry','meeting note','text on a web page','task in a to-do app','receipt or order confirmation',
       'notification','message in a team channel','line from a document being edited','travel booking','school or course notice',
       'doctor or dentist appointment','bank or bill reminder','recipe or shopping list','sports or hobby plan']
TOPICS=['a product launch','a dentist visit','a flight change','a rent payment','a birthday party','a code review','a client invoice','a gym class',
        'a parent-teacher meeting','a package delivery','a conference talk','a car service','a book club','a job interview','a hackathon',
        'a server outage','a wedding','a tax filing','a visa appointment','a team offsite','a concert','a lab report','a hiring plan','a garden project']
LANGS=[('en',0.55),('hi',0.15),('zh',0.15),('es',0.15)]
LANG_NAME={'en':'English','hi':'Hindi','zh':'Simplified Chinese','es':'Spanish'}
PROMPT=('Write one realistic {kind} in {lang} about {topic}, as it would appear on someone\'s phone or laptop screen. Use invented '
        'names (not Priya, not Orion) and concrete details: a person, a day or date, a time, a place or a number.\n'
        'Then write three questions in {lang} the owner might ask later:\n'
        '1. "answerable": asks for a detail the text states, worded differently from the text.\n'
        '2. "near_miss": looks almost the same but changes exactly one detail (another person, day, place, number or action), so the '
        'text does NOT answer it.\n'
        '3. "unrelated": a question on a different subject the text does not answer.\n'
        'Reply with JSON only: {{"memory": "...", "answerable": "...", "near_miss": "...", "unrelated": "..."}}')


def fixture_guard():
    texts=[]
    for f in FIXTURES:
        if not f.exists():continue
        d=json.loads(f.read_text(encoding='utf-8'))
        def walk(x):
            if isinstance(x,str):texts.append(x)
            elif isinstance(x,list):[walk(v) for v in x]
            elif isinstance(x,dict):[walk(v) for v in x.values()]
        walk(d)
    grams=set();names=set()
    for t in texts:
        w=t.lower().split();grams.update(' '.join(w[i:i+5]) for i in range(len(w)-4))
        names.update(re.findall(r'\b[A-Z][a-z]{3,}\b',t))
    return grams,names


def leaks(item,grams,names):
    for t in item.values():
        if not isinstance(t,str):continue
        w=t.lower().split()
        if any(' '.join(w[i:i+5]) in grams for i in range(len(w)-4)):return True
        if set(re.findall(r'\b[A-Z][a-z]{3,}\b',t))&names-{'Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday','January','February',
            'March','April','June','July','August','September','October','November','December','Please','Thanks','Hello','Dear','Team','Meeting'}:return True
    return False


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--items',type=int,default=3000);ap.add_argument('--batch',type=int,default=24)
    ap.add_argument('--seed',type=int,default=20261031);a=ap.parse_args()
    import torch
    from transformers import AutoModelForCausalLM,AutoTokenizer
    rng=random.Random(a.seed);torch.manual_seed(a.seed);OUT.mkdir(parents=True,exist_ok=True)
    tok=AutoTokenizer.from_pretrained(MODEL,padding_side='left');m=AutoModelForCausalLM.from_pretrained(MODEL,dtype=torch.bfloat16).eval().to('cuda')
    grams,names=fixture_guard();items=[];dropped={'parse':0,'leak':0,'shape':0}
    langs=[l for l,_ in LANGS];weights=[w for _,w in LANGS]
    while len(items)<a.items:
        specs=[{'kind':rng.choice(KINDS),'topic':rng.choice(TOPICS),'lang':rng.choices(langs,weights)[0]} for _ in range(a.batch)]
        texts=[tok.apply_chat_template([{'role':'user','content':PROMPT.format(kind=s['kind'],topic=s['topic'],lang=LANG_NAME[s['lang']])}],
                                       tokenize=False,add_generation_prompt=True,enable_thinking=False) for s in specs]
        enc=tok(texts,return_tensors='pt',padding=True).to('cuda')
        with torch.inference_mode():out=m.generate(**enc,max_new_tokens=260,do_sample=True,temperature=0.9,top_p=0.95,pad_token_id=tok.pad_token_id)
        for s,o in zip(specs,out[:,enc['input_ids'].shape[1]:]):
            raw=tok.decode(o,skip_special_tokens=True);j=raw[raw.find('{'):raw.rfind('}')+1]
            try:x=json.loads(j)
            except Exception:dropped['parse']+=1;continue
            if not all(isinstance(x.get(k),str) and 8<=len(x[k])<=400 for k in ('memory','answerable','near_miss','unrelated')) or x['answerable']==x['near_miss']:
                dropped['shape']+=1;continue
            if leaks(x,grams,names):dropped['leak']+=1;continue
            x.update(s);x['id']=hashlib.sha256(x['memory'].encode()).hexdigest()[:16];items.append(x)
        print(len(items),'items',dropped,flush=True)
    items=items[:a.items]
    with (OUT/'items.jsonl').open('w',encoding='utf-8') as f:
        for x in items:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    with (OUT/'pairs.jsonl').open('w',encoding='utf-8') as f:
        for x in items:
            for kind,y in (('answerable',1),('near_miss',0),('unrelated',0)):
                f.write(json.dumps({'q':x[kind],'e':x['memory'],'y':y,'lang':x['lang'],'kind':'lens_'+kind,'src':'lens_style','group':x['id']},ensure_ascii=False)+'\n')
    (OUT/'build-report.json').write_text(json.dumps({'items':len(items),'dropped':dropped,'model':MODEL.name,'seed':a.seed,
        'by_lang':{l:sum(x['lang']==l for x in items) for l in langs}},indent=1),encoding='utf-8')
    print('wrote',OUT)


if __name__=='__main__':main()
