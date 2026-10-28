"""Trains the observer's tiny language-identification tables (engine/observer/lid_model_data.hpp; lens-lid-ngram-v1).

Character n-gram (1-4, word-padded) plus whole-word features, multinomial Naive Bayes, pruned and quantised to 8 bits.
Two groups: Latin script {en, es, fr, pt, de, id, hi-Latn, ta-Latn, te-Latn} and Devanagari {hi, mr}. Script
detection decides every other language without a model (docs/LENS_V1_SPEC.md §1a).

Training text (public, licensed, balanced: every class gets the same number of characters, so no language dominates):
- Belebele questions (facebook/belebele, CC BY-SA 4.0): the authored question field only, never `flores_passage`
  (FLEURS evaluation sentences come from FLORES, so passages are excluded to keep the evaluation clean).
  eng/spa/fra/por/deu/ind_Latn, hin_Latn (romanized Hindi), hin_Deva, mar_Deva.
- Romanized Hindi/Tamil/Telugu: Belebele hin_Deva/tam_Taml/tel_Telu questions transliterated word by word with
  Aksharantar pairs (ai4bharat/Aksharantar: manual pairs CC-BY 4.0, mined pairs CC0). Pairs whose source is
  Dakshina are excluded, so nothing from the Dakshina evaluation set enters training.
The generated table is a derivative of CC BY-SA 4.0 data and is distributed under CC BY-SA 4.0 with this attribution.
Usage: .venv\\Scripts\\python.exe scripts/train_observer_lid.py
"""
from collections import Counter,defaultdict
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import random
import re
import tarfile
import zipfile
ROOT=Path(__file__).resolve().parents[1]
BELEBELE=ROOT/'data/external/belebele';AKSHARANTAR=ROOT/'data/external/aksharantar'
OUT=ROOT/'engine/observer/lid_model_data.hpp'
LATIN=['en','es','fr','pt','de','id','hi-Latn','ta-Latn','te-Latn'];DEVA=['hi','mr']
MAX_FEATURES={'latin':14000,'deva':5000};SEED=20261028
# Training shares (docs/LENS_V1_SPEC.md §1a, 2026-10-28): English ~30%, no other language above ~12%, the Indian group
# at most ~30%. The Devanagari group only separates hi from mr, so its two classes are equal.
SHARES={'latin':{'en':0.30,'es':0.09,'fr':0.09,'pt':0.09,'de':0.09,'id':0.09,'hi-Latn':0.25/3,'ta-Latn':0.25/3,'te-Latn':0.25/3},
        'deva':{'hi':0.5,'mr':0.5}}
FLEURS=ROOT/'data/external/fleurs';DAKSHINA_TAR=ROOT/'data/external/dakshina/dakshina_dataset_v1.0.tar'


def is_latin(c):
    o=ord(c);return ('a'<=c<='z') or ('A'<=c<='Z') or (0xC0<=o<=0x24F and o not in (0xD7,0xF7)) or (0x1E00<=o<=0x1EFF)


def is_deva(c):o=ord(c);return 0x0900<=o<=0x097F and o not in (0x0964,0x0965) and not 0x0966<=o<=0x096F


def words(text,pred):  # runs of one script's letters, lower-cased (mirrors lid_detail::words in language_id.hpp)
    out=[];cur=''
    for c in text:
        if pred(c):cur+=c.lower()
        elif cur:out.append(cur);cur=''
    if cur:out.append(cur)
    return out


def features(ws):  # mirrors lid_detail::ngram_features
    for w in ws:
        p='_'+w+'_'
        for n in (1,2,3,4):
            for i in range(len(p)-n+1):
                g=p[i:i+n]
                if g!='_':yield g
        yield 'W:'+w


def fnv(s):
    h=1469598103934665603
    for b in s.encode('utf-8'):h^=b;h=(h*1099511628211)&0xFFFFFFFFFFFFFFFF
    return h


def questions(name,answers=False):  # authored fields only; `flores_passage` is never read
    rows=[json.loads(l) for l in (BELEBELE/f'{name}.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    keys=['question']+([f'mc_answer{i}' for i in range(1,5)] if answers else [])
    return [r[k] for r in rows for k in keys]


def tokens(s):return re.findall(r'\w+',s.lower())


def eval_grams():
    """Word 4-8-grams of every evaluation string (FLEURS test transcriptions of all configs; Dakshina dev and test,
    romanized and native, hi/ta/te). Training strings that share one are dropped (decontamination); evaluation
    strings themselves are never training text."""
    grams=set();n_strings=0
    def add(text):
        nonlocal n_strings
        n_strings+=1;t=tokens(text)
        for n in range(4,9):
            for i in range(len(t)-n+1):grams.add(hash(tuple(t[i:i+n])))
    for tsv in sorted(FLEURS.glob('*/test.tsv')):
        for row in tsv.read_text(encoding='utf-8').splitlines():
            parts=row.split('\t')
            if len(parts)>2:add(parts[2])
    with tarfile.open(DAKSHINA_TAR) as tar:
        for lang in ('hi','ta','te'):
            for split in ('dev','test'):
                for kind in ('roman','native'):
                    m=f'dakshina_dataset_v1.0/{lang}/romanized/{lang}.romanized.rejoined.{split}.{kind}.txt'
                    for line in tar.extractfile(m).read().decode('utf-8').splitlines():add(line)
    return grams,n_strings


def contaminated(text,grams):
    t=tokens(text)
    if len(t)<4:return False
    if len(t)<=8 and hash(tuple(t)) in grams:return True
    return any(hash(tuple(t[i:i+8])) in grams for i in range(len(t)-7))


def romanizer(lang):
    table=defaultdict(list);sources=Counter()
    with zipfile.ZipFile(AKSHARANTAR/f'{lang}.zip') as z:
        for member in (f'{lang}_train.json',):
            with z.open(member) as f:
                for line in f:
                    if not line.strip():continue
                    r=json.loads(line);sources[r['source']]+=1
                    if r['source']=='Dakshina':continue
                    table[r['native word']].append(r['english word'].lower())
    return table,dict(sources)


def transliterate(sentences,table,rng):
    out=[]
    for s in sentences:
        ws=[rng.choice(table[w]) for w in s.replace('?',' ').replace(',',' ').replace('।',' ').split() if w in table]
        if len(ws)>=2:out.append(' '.join(ws))
    return out


def main():
    rng=random.Random(SEED);prov={};grams,n_eval=eval_grams();dropped=Counter()
    def clean(code,texts):
        kept=[t for t in texts if not contaminated(t,grams)];dropped[code]+=len(texts)-len(kept);return kept
    data={code:clean(code,questions(name,answers=True)) for code,name in (('en','eng_Latn'),('es','spa_Latn'),('fr','fra_Latn'),('pt','por_Latn'),
          ('de','deu_Latn'),('id','ind_Latn'),('hi','hin_Deva'),('mr','mar_Deva'))}
    for code,lang,src in (('hi-Latn','hin','hin_Deva'),('ta-Latn','tam','tam_Taml'),('te-Latn','tel','tel_Telu')):
        table,sources=romanizer(lang);prov[f'aksharantar_{lang}']={'pairs_by_source':sources,'excluded_source':'Dakshina','native_words':len(table)}
        rom=transliterate(clean(code+':native',questions(src,answers=True)),table,rng)
        data[code]=clean(code,rom+(questions('hin_Latn',answers=True) if code=='hi-Latn' else []))
    prov['decontamination']={'eval_strings':n_eval,'rule':'drop a training string sharing a word 8-gram with an evaluation string, '
                             'or (4-8 words) contained whole in one','dropped':dict(dropped)}
    report={'created_utc':datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),'method':'lens-lid-ngram-v1','seed':SEED,'groups':{},'provenance':prov,
            'inputs':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(BELEBELE.glob('*.jsonl'))+sorted(AKSHARANTAR.glob('*.zip'))},
            'licenses':{'belebele':'CC BY-SA 4.0 (question and answer fields; passages never read)','aksharantar':'CC-BY 4.0 (manual) / CC0 (mined)','output':'CC BY-SA 4.0'}}
    groups={'latin':(LATIN,is_latin),'deva':(DEVA,is_deva)}
    code=['#pragma once','// GENERATED by scripts/train_observer_lid.py - do not edit. lens-lid-ngram-v1.',
          '// Char 1-4-gram + word Naive Bayes tables, 8-bit quantised log-probabilities (value*scale+offset).',
          '// Trained on Belebele questions (CC BY-SA 4.0) and Aksharantar transliteration pairs (CC-BY 4.0 / CC0);',
          '// this table is a derivative work distributed under CC BY-SA 4.0. Mix: en 30%, es/fr/pt/de/id 9% each, hi/ta/te-Latn 8.3% each.',
          '#include <cstddef>','#include <cstdint>','','namespace lens::observe::lid_model {']
    for gname,(labels,pred) in groups.items():
        shares=SHARES[gname]
        total=min(sum(len(s) for s in data[l])/shares[l] for l in labels)  # the largest mix that meets every share
        budget={l:int(shares[l]*total) for l in labels}
        counts={};totals={};used_chars={}
        for l in labels:
            sents=data[l][:];rng.shuffle(sents);c=Counter();used=0
            for s in sents:
                if used>=budget[l]:break
                used+=len(s);c.update(features(words(s,pred)))
            counts[l]=c;totals[l]=sum(c.values());used_chars[l]=used
        allf=Counter()
        for c in counts.values():allf.update(c)
        keep=[f for f,n in allf.most_common() if n>=3][:MAX_FEATURES[gname]]
        vocab=len(keep);alpha=0.5
        logp={f:[math.log((counts[l][f]+alpha)/(totals[l]+alpha*vocab)) for l in labels] for f in keep}
        lo=min(min(v) for v in logp.values());hi=max(max(v) for v in logp.values());scale=(hi-lo)/255
        rows=sorted(((fnv(f),[round((x-lo)/scale) for x in logp[f]]) for f in keep))
        assert len({k for k,_ in rows})==len(rows),'hash collision'
        mix=sum(used_chars.values())
        report['groups'][gname]={'labels':labels,'features':len(rows),'chars_per_class':used_chars,
                                 'share_of_mix':{l:round(used_chars[l]/mix,4) for l in labels},'strings_available':{l:len(data[l]) for l in labels},
                                 'bytes':len(rows)*(8+len(labels))+4*len(labels)}
        code.append(f'inline constexpr const char* {gname}_labels[]={{{",".join(json.dumps(l) for l in labels)}}};')
        code.append(f'inline constexpr int {gname}_classes={len(labels)};inline constexpr std::size_t {gname}_features={len(rows)};')
        code.append(f'inline constexpr float {gname}_scale={scale!r}f,{gname}_offset={lo!r}f;')
        code.append(f'inline constexpr float {gname}_log_prior[]={{{",".join(repr(round(math.log(shares[l]),6))+"f" for l in labels)}}};')
        code.append(f'inline constexpr std::uint64_t {gname}_keys[]={{')
        for i in range(0,len(rows),8):code.append(','.join(f'0x{k:016x}ull' for k,_ in rows[i:i+8])+',')
        code.append('};')
        code.append(f'inline constexpr std::uint8_t {gname}_values[]={{')
        for i in range(0,len(rows),16):code.append(','.join(','.join(str(v) for v in vals) for _,vals in rows[i:i+16])+',')
        code.append('};')
    code.append('}');code.append('')
    OUT.write_text('\n'.join(code),encoding='utf-8')
    rep=ROOT/'reports/observer';rep.mkdir(parents=True,exist_ok=True)
    report['output']={'path':str(OUT.relative_to(ROOT)),'sha256':hashlib.sha256(OUT.read_bytes()).hexdigest(),'source_bytes':OUT.stat().st_size}
    (rep/f"lid-train-{report['created_utc']}.json").write_text(json.dumps(report,indent=1,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('groups','output')},indent=1,ensure_ascii=False))


if __name__=='__main__':main()
