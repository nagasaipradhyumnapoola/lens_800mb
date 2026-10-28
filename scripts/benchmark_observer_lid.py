"""Language identification benchmark for screen observations (docs/LENS_V1_SPEC.md §1a; observer real-screen fix 4).

Compares the observer's identifier (`lens-observer --identify-language`, lens-lid-ngram-v1, embedded ~290 KB tables)
with a widely used open CPU identifier, fastText lid.176.ftz (evaluation only, never shipped), on the same strings.

Data (public, gitignored under data/external/, never personal):
- FLEURS test transcriptions (google/fleurs, CC-BY-4.0): the 17 quality-critical languages of §1a.
- Dakshina v1.0 romanized Wikipedia sentences (google-research-datasets/dakshina, CC BY-SA 4.0): hi, ta, te
  (gold hi-Latn / ta-Latn / te-Latn), using Dakshina's own dev and test files.
- Code-switching: synthetic concatenations of an English fragment and a romanized-Indic or native-Indic fragment drawn
  from the same split (gold "mixed" with both components). Synthetic by construction; no public licensed
  code-switched set is available locally (L3Cube HingCorpus is non-commercial, so not used here).
Buckets: short (a 5-40 character window cut at word boundaries, like screen labels and chat lines), sentence, and
paragraph (3-5 sentences). Balanced: the same number of strings per language and bucket.
Split: Dakshina dev/test as published; FLEURS sentences by a hash of the text (even = dev, odd = test). Only the dev
split may be used to adjust lexicons; the test split is reported. The lexicons were written before any of this data
was read.

Usage: .venv\\Scripts\\python.exe scripts/benchmark_observer_lid.py [--split test] [--per-bucket 150]
Writes reports/observer/lid-benchmark-<split>-<utc>.json (aggregate numbers only).
"""
import argparse
import collections
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import random
import subprocess
import tarfile
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1]
OBSERVER=ROOT/'build/engine/Release/lens-observer.exe'
FT_PY=ROOT/'.tools/lid-eval/Scripts/python.exe';FT_MODEL=ROOT/'.tools/lid-eval/models/lid.176.ftz'
FT_MODEL_SHA='8f3472cfe8738a7b6099e8e999c3cbfae0dcd15696aac7d7738a8039db603e83'
FLEURS={'en':'en_us','zh':'cmn_hans_cn','es':'es_419','ar':'ar_eg','fr':'fr_fr','pt':'pt_br','ru':'ru_ru','id':'id_id','de':'de_de',
        'ja':'ja_jp','hi':'hi_in','bn':'bn_in','te':'te_in','mr':'mr_in','ta':'ta_in','ur':'ur_pk','gu':'gu_in'}
DAKSHINA={'hi-Latn':'hi','ta-Latn':'ta','te-Latn':'te'}
DAKSHINA_TAR=ROOT/'data/external/dakshina/dakshina_dataset_v1.0.tar'
SOURCES={'fleurs':{'dataset':'google/fleurs','license':'CC-BY-4.0','files':'data/external/fleurs/<config>/test.tsv (transcription column)'},
         'dakshina':{'dataset':'google-research-datasets/dakshina v1.0','license':'CC BY-SA 4.0','files':'<lang>/romanized/<lang>.romanized.rejoined.{dev,test}.roman.txt'},
         'fasttext_lid176':{'model':'lid.176.ftz','license':'CC BY-SA 3.0','runtime':'fasttext-wheel 0.9.2 (MIT), isolated venv .tools/lid-eval',
                            'url':'https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz','sha256':FT_MODEL_SHA,'use':'evaluation only'}}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fleurs_sentences(lang,split):
    rows=(Path(ROOT/'data/external/fleurs'/FLEURS[lang]/'test.tsv').read_text(encoding='utf-8').splitlines())
    out=sorted({r.split('\t')[2].strip() for r in rows if r.count('\t')>=2})
    keep=0 if split=='dev' else 1
    return [s for s in out if s and int(hashlib.sha256(s.encode()).hexdigest(),16)%2==keep]


def dakshina_sentences(lang,split,tar):
    member=f'dakshina_dataset_v1.0/{lang}/romanized/{lang}.romanized.rejoined.{split}.roman.txt'
    return [l.strip() for l in tar.extractfile(member).read().decode('utf-8').splitlines() if l.strip()]


def short_window(s,rng):
    words=s.split()
    for _ in range(20):
        i=rng.randrange(len(words));out=''
        for w in words[i:]:
            if len(out)+len(w)+(1 if out else 0)>40:break
            out=(out+' '+w).strip()
        if 5<=len(out)<=40:return out
    return s[:40].strip()


def no_space_window(s,rng):  # zh/ja: a 5-40 character slice
    if len(s)<=5:return s
    n=rng.randint(5,min(40,len(s)));i=rng.randrange(0,len(s)-n+1);return s[i:i+n]


def build(split,per_bucket,seed=20261028):
    rng=random.Random(seed);items=[]
    pools={l:fleurs_sentences(l,split) for l in FLEURS}
    with tarfile.open(DAKSHINA_TAR) as tar:
        for gold,l in DAKSHINA.items():pools[gold]=dakshina_sentences(l,split,tar)
    for gold,pool in pools.items():
        rng.shuffle(pool);sents=pool[:per_bucket]
        for s in sents:items.append({'gold':gold,'bucket':'sentence','text':s})
        for k in range(per_bucket):
            s=pool[k%len(pool)];items.append({'gold':gold,'bucket':'short','text':no_space_window(s,rng) if gold in ('zh','ja') else short_window(s,rng)})
        for k in range(max(1,per_bucket//3)):
            items.append({'gold':gold,'bucket':'paragraph','text':' '.join(rng.sample(pool,min(len(pool),rng.randint(3,5))))})
    # Synthetic code-switching: an English fragment joined with a romanized or native Indic fragment.
    for other in ('hi-Latn','ta-Latn','te-Latn','hi'):
        for k in range(per_bucket):
            e=short_window(rng.choice(pools['en']),rng);o=short_window(rng.choice(pools[other]),rng)
            items.append({'gold':'mixed','components':sorted(['en',other]),'bucket':f'mixed:en+{other}','text':f'{e} {o}' if k%2 else f'{o} {e}'})
    return items,{k:len(v) for k,v in pools.items()}


def lens_predict(texts):
    t=time.perf_counter()
    p=subprocess.run([str(OBSERVER),'--identify-language'],input=''.join(json.dumps({'text':x},ensure_ascii=False)+'\n' for x in texts),
                     capture_output=True,encoding='utf-8',timeout=600)
    wall=time.perf_counter()-t;out=[json.loads(x) for x in p.stdout.splitlines()]
    assert p.returncode==0 and len(out)==len(texts),p.stderr
    return out,wall


FT_SCRIPT='''import fasttext,json,sys,time
m=fasttext.load_model(sys.argv[1]);texts=json.load(open(sys.argv[2],encoding="utf-8"));t=time.perf_counter()
out=[m.predict(x.replace("\\n"," "),k=2) for x in texts];wall=time.perf_counter()-t
json.dump({"wall":wall,"pred":[[l.replace("__label__","") for l in o[0]] for o in out],"prob":[[float(p) for p in o[1]] for o in out]},open(sys.argv[3],"w"))
'''


def fasttext_predict(texts):
    with tempfile.TemporaryDirectory() as tmp:
        tin=Path(tmp)/'in.json';tout=Path(tmp)/'out.json';script=Path(tmp)/'ft.py'
        tin.write_text(json.dumps(texts,ensure_ascii=False),encoding='utf-8');script.write_text(FT_SCRIPT,encoding='utf-8')
        subprocess.run([str(FT_PY),'-I',str(script),str(FT_MODEL),str(tin),str(tout)],check=True,capture_output=True,timeout=600)
        r=json.loads(tout.read_text(encoding='utf-8'));return r['pred'],r['wall']


def score(items,lens,ft):
    acc=collections.defaultdict(lambda:collections.Counter());conf={'lens':collections.defaultdict(collections.Counter),'fasttext':collections.defaultdict(collections.Counter)}
    for it,l,f in zip(items,lens,ft):
        g=it['gold'];b='mixed' if g=='mixed' else it['bucket'];key=(it['bucket'] if g=='mixed' else g,b);c=acc[key];c['n']+=1
        base=g.split('-')[0]
        if g=='mixed':
            comps=set(it['components'])
            c['lens_strict']+=l['language']=='mixed' and set(l['languages'])==comps
            c['lens_lenient']+=l['language'] in comps or (l['language']=='mixed' and bool(set(l['languages'])&comps))
            c['ft_strict']+=0  # a single-label identifier cannot report code-switching
            c['ft_lenient']+=f[0] in {x.split('-')[0] for x in comps}
            if not(l['language']=='mixed' and set(l['languages'])==comps):conf['lens'][it['bucket']][l['language']]+=1
        else:
            c['lens_strict']+=l['language']==g;c['lens_lenient']+=l['language'].split('-')[0]==base
            c['ft_strict']+=f[0]==g;c['ft_lenient']+=f[0]==base
            if l['language']!=g:conf['lens'][g][l['language']]+=1
            if f[0]!=base:conf['fasttext'][g][f[0]]+=1
    rows={}
    for (g,b),c in sorted(acc.items()):
        rows.setdefault(g,{})[b]={k:round(c[k]/c['n'],4) for k in ('lens_strict','lens_lenient','ft_strict','ft_lenient')}|{'n':c['n']}
    def macro(keys,metric,buckets):
        v=[rows[k][b][metric] for k in keys for b in buckets if b in rows.get(k,{})];return round(sum(v)/len(v),4) if v else None
    native=list(FLEURS);roman=list(DAKSHINA);mixed=[k for k in rows if k.startswith('mixed:')]
    summary={}
    for name,keys,buckets in (('native_17',native,('short','sentence','paragraph')),('romanized_hi_ta_te',roman,('short','sentence','paragraph')),
                              ('code_switched',mixed,('mixed',))):
        summary[name]={m:macro(keys,m,buckets) for m in ('lens_strict','lens_lenient','ft_strict','ft_lenient')}
        for b in buckets:summary[name][f'by_bucket_{b}']={m:macro(keys,m,(b,)) for m in ('lens_strict','ft_strict','ft_lenient')}
    top=lambda d:{g:dict(c.most_common(3)) for g,c in d.items()}
    return rows,summary,{'lens':top(conf['lens']),'fasttext':top(conf['fasttext'])}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--split',choices=('dev','test'),default='test');ap.add_argument('--per-bucket',type=int,default=150)
    a=ap.parse_args()
    assert sha(FT_MODEL)==FT_MODEL_SHA,'lid.176.ftz hash mismatch'
    items,pool_sizes=build(a.split,a.per_bucket);texts=[i['text'] for i in items]
    lens,lens_wall=lens_predict(texts);ft,ft_wall=fasttext_predict(texts)
    rows,summary,confusions=score(items,lens,ft)
    report={'created_utc':datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),'split':a.split,'per_bucket':a.per_bucket,'strings':len(items),
        'identifiers':{'lens':{'method':'lens-lid-ngram-v1','binary_sha256':sha(OBSERVER),'model_bytes':288000,
                               'ms_per_string':round(1000*lens_wall/len(items),4),'note':'includes process start and JSON I/O'},
                       'fasttext':{'model':'lid.176.ftz','model_bytes':FT_MODEL.stat().st_size,'ms_per_string':round(1000*ft_wall/len(items),4),
                                   'note':'Python binding, prediction loop only; no romanized or mixed labels exist in lid.176'}},
        'metrics':{'strict':'exact tag (hi-Latn must be hi-Latn; mixed must name both components)',
                   'lenient':'base language (hi-Latn counted correct as hi); for mixed, either component'},
        'summary':summary,'per_language':rows,'top_confusions':confusions,'pool_sizes':pool_sizes,'sources':SOURCES,
        'dakshina_tar_sha256':sha(DAKSHINA_TAR)}
    out=ROOT/'reports/observer';out.mkdir(parents=True,exist_ok=True)
    path=out/f"lid-benchmark-{a.split}-{report['created_utc']}.json";path.write_text(json.dumps(report,indent=1,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'summary':summary,'identifiers':report['identifiers']},indent=1));print(path)


if __name__=='__main__':main()
