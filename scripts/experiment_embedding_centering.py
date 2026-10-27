"""Offline dev experiment: does removing the language-identity component of e5 embeddings improve retrieval?

Runs on the v1 fixture's dev + inspected-test (diagnosis) splits only — never the sealed holdout. Embeds the
10k-event corpus with the shipped INT8 model through Python ONNX Runtime (token-identical to the native
engine), then compares semantic ranking under: raw cosine; global mean-centering; per-script-group
centering; and CSLS hubness correction. Usage: .venv\\Scripts\\python.exe scripts/experiment_embedding_centering.py
"""
import json
from pathlib import Path
import sys
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import benchmark_retrieval_nl as bench
MODEL=ROOT/'models/intfloat--multilingual-e5-small/onnx'


def script_group(text):
    """Coarse script of a text, the only language signal available for a query at run time."""
    counts={}
    for ch in text:
        cp=ord(ch)
        g=('han' if 0x3400<=cp<=0x9FFF else 'deva' if 0x0900<=cp<=0x097F else 'taml' if 0x0B80<=cp<=0x0BFF else
           'telu' if 0x0C00<=cp<=0x0C7F else 'latn' if ch.isalpha() and cp<0x0250 else None)
        if g:counts[g]=counts.get(g,0)+1
    return max(counts,key=counts.get) if counts else 'latn'


def main(n=10000):
    tok=Tokenizer.from_file(str(MODEL/'tokenizer.json'))
    sess=ort.InferenceSession(str(MODEL/'model_qint8_avx512_vnni.onnx'),providers=['CPUExecutionProvider'])
    def emb(text):
        ids=np.array([tok.encode(text).ids[:512]],dtype=np.int64)
        h=sess.run(None,{'input_ids':ids,'attention_mask':np.ones_like(ids),'token_type_ids':np.zeros_like(ids)})[0][0]
        v=h.mean(0);return v/np.linalg.norm(v)
    memories,queries=bench.load()
    corpus=memories+bench.distractors(n-len(memories))
    cache=ROOT/f'artifacts/centering-experiment-{n}.npy'
    if cache.exists():P=np.load(cache)
    else:
        P=np.stack([emb('passage: '+x['text']) for x in corpus]);cache.parent.mkdir(exist_ok=True);np.save(cache,P)
    pg=np.array([script_group(x['text']) for x in corpus]);ids=[x['id'] for x in corpus]
    qs=[q for q in queries if q['split'] in ('dev','test') and q['relevant']]
    Q=np.stack([emb('query: '+q['query']) for q in qs]);qg=np.array([script_group(q['query']) for q in qs])
    norm=lambda M:M/np.linalg.norm(M,axis=1,keepdims=True)
    gmean=P.mean(0)
    means={g:P[pg==g].mean(0) for g in set(pg)}
    variants={}
    variants['raw']=Q@P.T
    variants['global_center']=norm(Q-gmean)@norm(P-gmean).T
    Pc=norm(np.stack([P[i]-means[pg[i]] for i in range(len(P))]))
    Qc=norm(np.stack([Q[i]-means.get(qg[i],gmean) for i in range(len(Q))]))
    variants['script_center']=Qc@Pc.T
    # Fixed reference means from public FLEURS transcripts (independent of the fixture and of user data).
    ref={}
    for folder,group in [('en_us','latn'),('es_419','latn'),('cmn_hans_cn','han'),('hi_in','deva'),('ta_in','taml'),('te_in','telu')]:
        lines=[l.split('	')[2] for l in (ROOT/'data/external/fleurs'/folder/'test.tsv').read_text(encoding='utf-8').splitlines() if l.count('	')>=2]
        ref.setdefault(group,[]).extend(lines[:200 if group!='latn' else 100])
    pm={g:np.stack([emb('passage: '+t) for t in v]).mean(0) for g,v in ref.items()}
    qm={g:np.stack([emb('query: '+t) for t in v]).mean(0) for g,v in ref.items()}
    gp=np.stack(list(pm.values())).mean(0);gq=np.stack(list(qm.values())).mean(0)
    Pr=norm(np.stack([P[i]-pm.get(pg[i],gp) for i in range(len(P))]))
    variants['ref_center_same']=norm(np.stack([Q[i]-pm.get(qg[i],gp) for i in range(len(Q))]))@Pr.T
    variants['ref_center_qmeans']=norm(np.stack([Q[i]-qm.get(qg[i],gq) for i in range(len(Q))]))@Pr.T
    # CSLS: 2cos - r_P (mean cos of each passage to its 10 nearest queries from a fixed generic probe set).
    probes=np.stack([emb('query: '+t) for t in ['What happened?','When is it?','Who said that?','Where is it?','How much was it?',
        '什么时候？','¿Cuándo es?','कब है?','எப்போது?','ఎప్పుడు?','What did I read?','Why did it fail?']])
    rP=np.sort(P@probes.T,axis=1)[:,-10:].mean(1)
    variants['csls']=2*(Q@P.T)-rP[None,:]
    report={}
    for name,S in variants.items():
        order=np.argsort(-S,axis=1)[:,:10]
        per={}
        for i,q in enumerate(qs):
            top=[ids[j] for j in order[i]];rank=top.index(q['relevant'])+1 if q['relevant'] in top else None
            for key in ['all',q['split'],'lang:'+q['language'],'type:'+q['type'],'qlang:'+q['query_language']]:
                d=per.setdefault(key,[0,0,0]);d[0]+=1;d[1]+=rank==1;d[2]+=rank is not None
        report[name]={k:{'n':v[0],'R@1':round(v[1]/v[0],3),'R@10':round(v[2]/v[0],3)} for k,v in sorted(per.items())}
    out=ROOT/'reports/retrieval-nl/dev-experiments/embedding-centering.json'
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps({'corpus_events':n,'splits':'v1 dev + inspected test (diagnosis)',
        'model':'e5-small INT8','results':report},ensure_ascii=False,indent=1),encoding='utf-8')
    keys=['all','dev','test','lang:en','lang:zh','lang:es','lang:hi','lang:ta','lang:te','type:paraphrase','type:cross_language','type:code_switch','type:exact']
    print('variant'.ljust(15)+''.join(k.replace('lang:','').replace('type:','')[:10].rjust(12) for k in keys))
    for name,r in report.items():
        print(name.ljust(15)+''.join(f"{r[k]['R@1']:.2f}/{r[k]['R@10']:.2f}".rjust(12) for k in keys))


if __name__=='__main__':main(int(sys.argv[1]) if len(sys.argv)>1 else 10000)
