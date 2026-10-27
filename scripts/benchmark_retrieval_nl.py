"""Natural-language multilingual retrieval benchmark for the native engine.

Corpus: data/fixtures/retrieval-nl/v1.json memories + seeded synthetic distractors that reuse the same
people/places (hard negatives) but never state the facts asked about. Compares the legacy keyword ops
(search / retrieve_context) with recall in keyword, semantic and hybrid modes. The abstention threshold
is fitted on the dev split only and then applied unchanged to the held-out test split.

Usage: .venv\\Scripts\\python.exe scripts/benchmark_retrieval_nl.py --scales 1000 10000 [--out reports/retrieval-nl]
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import subprocess
import threading
import time
import psutil
ROOT=Path(__file__).resolve().parents[1]
FIXTURES={'v1':ROOT/'data/fixtures/retrieval-nl/v1.json','holdout':ROOT/'data/fixtures/retrieval-nl/holdout.json',
          'expansion':ROOT/'data/fixtures/retrieval-nl/expansion.json',
          'acceptance':ROOT/'data/fixtures/retrieval-nl/acceptance.json',
          'nearmiss':ROOT/'data/fixtures/retrieval-nl/nearmiss-v1.json'}
FIXTURE=FIXTURES['v1']
HOLDOUT_LOG=ROOT/'reports/retrieval-nl/holdout-runs.log.txt'
ENGINE=ROOT/'build/engine/Release/lens-engine.exe'
RUNTIME=ROOT/'.tools/ocr-runtime/onnxruntime.dll'
LANGS=['en','zh','es','hi','ta','te']
MODES=['legacy_search','legacy_context','keyword','semantic','hybrid','hybrid_rerank','semantic_c','hybrid_c','hybrid_rerank_c','hybrid_rerank_rrf_c']
BASE=lambda mode:mode[:-2] if mode.endswith('_c') else mode  # *_c = same mode with language-identity centering

NAMES={'en':['Priya','Daniel','Sarah','Arjun','Tom','Lena','Marco','Ravi','Mia'],'zh':['王芳','张伟','陈静','刘洋','黄磊','周敏','赵磊','小王'],
       'es':['Lucía','Javier','Pablo','Sofía','Diego','Ana','Martín','Elena','Carmen'],'hi':['राहुल','प्रिया','अनीता','विकास','नेहा','सुरेश','मीना','गुप्ता जी'],
       'ta':['கார்த்திக்','மீனா','ராஜா','பிரியா','சுரேஷ்','விஜய்','லட்சுமி','அருண்'],'te':['శ్రీనివాస్','లక్ష్మి','కిరణ్','రవి','సుధ','ప్రసాద్','దివ్య']}
PLACES={'en':['Chennai','Goa','Koramangala','Singapore','the community hall'],'zh':['上海','北京','成都','深圳','海底捞'],
        'es':['Valencia','Madrid','Sevilla','Asturias','Malasaña'],'hi':['जयपुर','दिल्ली','नोएडा','लखनऊ','ऋषिकेश'],
        'ta':['சென்னை','மதுரை','திருச்சி','கோவை','தஞ்சாவூர்'],'te':['హైదరాబాద్','విజయవాడ','గుంటూరు','వైజాగ్','రాజమండ్రి']}
# Hard-negative templates: same people/places/vocabulary families, none states an answer to a fixture question.
TEMPLATES={
 'en':['{name} shared {n} photos from the weekend trip to {place}.','Read an article about urban gardening trends, item {n}.',
       '{name} liked the post about the cricket match score {n} runs.','Weather in {place}: {n} degrees and light rain in the evening.',
       'Listened to playlist number {n} while commuting near {place}.','{name} said hello in the group chat and sent a meme #{n}.',
       'Step count today was {n} steps around {place}.','Commit {n}: fixed typo in README for the docs site.',
       'Ordered groceries: rice, tomatoes and {n} bananas.','Traffic near {place} delayed the cab by {n} minutes.'],
 'zh':['{name}分享了{n}张周末去{place}旅行的照片。','读了一篇关于城市园艺的文章，第{n}篇。','{name}在群里发了一个表情包#{n}。',
       '{place}天气：{n}度，傍晚有小雨。','通勤路上听了第{n}个歌单。','今天在{place}附近走了{n}步。','提交{n}：修正了文档网站的错别字。',
       '买了菜：大米、西红柿和{n}个香蕉。','{place}附近堵车，出租车晚了{n}分钟。','{name}点赞了关于足球比赛比分{n}的帖子。'],
 'es':['{name} compartió {n} fotos del viaje de fin de semana a {place}.','Leí un artículo sobre jardinería urbana, número {n}.',
       '{name} saludó en el chat del grupo y envió un meme #{n}.','Tiempo en {place}: {n} grados y lluvia ligera por la tarde.',
       'Escuché la lista de reproducción {n} de camino a {place}.','Hoy caminé {n} pasos por {place}.','Commit {n}: corregí una errata en el README.',
       'Compra: arroz, tomates y {n} plátanos.','El tráfico cerca de {place} retrasó el taxi {n} minutos.','{name} dio me gusta al resultado del partido {n}.'],
 'hi':['{name} ने {place} की वीकेंड यात्रा की {n} तस्वीरें साझा कीं।','शहरी बागवानी पर एक लेख पढ़ा, संख्या {n}।','{name} ने ग्रुप चैट में मीम #{n} भेजा।',
       '{place} का मौसम: {n} डिग्री, शाम को हल्की बारिश।','{place} जाते समय प्लेलिस्ट {n} सुनी।','आज {place} में {n} कदम चले।',
       'कमिट {n}: डॉक्स साइट की वर्तनी ठीक की।','किराने का सामान: चावल, टमाटर और {n} केले।','{place} के पास जाम से कैब {n} मिनट लेट हुई।','{name} ने क्रिकेट स्कोर {n} वाली पोस्ट लाइक की।'],
 'ta':['{name} {place} வார இறுதி பயணத்தின் {n} புகைப்படங்களை பகிர்ந்தார்.','நகர்ப்புற தோட்டம் பற்றிய கட்டுரை எண் {n} படித்தேன்.',
       '{name} குழு அரட்டையில் மீம் #{n} அனுப்பினார்.','{place} வானிலை: {n} டிகிரி, மாலையில் லேசான மழை.','{place} செல்லும் வழியில் பாடல் தொகுப்பு {n} கேட்டேன்.',
       'இன்று {place} இல் {n} அடிகள் நடந்தேன்.','கமிட் {n}: ஆவண தளத்தில் எழுத்துப்பிழை சரி செய்தேன்.','மளிகை: அரிசி, தக்காளி மற்றும் {n} வாழைப்பழங்கள்.',
       '{place} அருகே போக்குவரத்து நெரிசலால் டாக்ஸி {n} நிமிடம் தாமதம்.','{name} கிரிக்கெட் ஸ்கோர் {n} பதிவை விரும்பினார்.'],
 'te':['{name} {place} వారాంతపు యాత్ర యొక్క {n} ఫోటోలు పంచుకున్నారు.','పట్టణ తోటపని గురించి వ్యాసం సంఖ్య {n} చదివాను.',
       '{name} గ్రూప్ చాట్‌లో మీమ్ #{n} పంపారు.','{place} వాతావరణం: {n} డిగ్రీలు, సాయంత్రం తేలికపాటి వర్షం.','{place} వెళ్తూ ప్లేలిస్ట్ {n} విన్నాను.',
       'ఈరోజు {place} లో {n} అడుగులు నడిచాను.','కమిట్ {n}: డాక్స్ సైట్‌లో అక్షర దోషం సరిచేశాను.','కిరాణా: బియ్యం, టమోటాలు మరియు {n} అరటిపండ్లు.',
       '{place} దగ్గర ట్రాఫిక్ వల్ల క్యాబ్ {n} నిమిషాలు ఆలస్యం.','{name} క్రికెట్ స్కోర్ {n} పోస్ట్‌ను లైక్ చేశారు.']}


def load(fixture=None):
    fixture=fixture or FIXTURE;fx=json.loads(fixture.read_text(encoding='utf-8'));holdout=fx.get('policy','').startswith('Sealed')
    memories,queries=[],[]
    if fx['name']=='lens-retrieval-nearmiss':
        # Near-miss negatives over the v1 corpus; group = the memory each question was written against.
        memories,_=load(FIXTURES['v1'])
        queries=[{'id':qid,'type':'unanswerable','subtype':'near_miss/'+sub,'language':lang,'query_language':lang,'query':text,
                  'relevant':None,'split':'nearmiss','group':'nl-'+group} for qid,lang,sub,text,group in fx['queries']]
        return memories,queries
    if fx['name']=='lens-retrieval-expansion' or fx.get('format')=='events':
        split='holdout' if holdout else 'expansion'
        # Cross-app/timeline set: per-memory app and timestamp; a question may have several valid evidence records.
        for mid,lang,app,stamp,text in fx['memories']:memories.append({'id':mid,'language':lang,'text':text,'app':app,'timestamp':stamp})
        for qid,lang,qtype,text,relevant in fx['queries']:
            queries.append({'id':qid,'type':'unanswerable' if not relevant else qtype,'subtype':qtype,'language':lang,'query_language':lang,
                            'query':text,'relevant':relevant or None,'split':split})
        return memories,queries
    for mid,lang,text,para,(clang,cross),exact,mix in fx['memories']:
        split='holdout' if holdout else ('dev' if int(mid.split('-')[1])<=6 else 'test')
        memories.append({'id':'nl-'+mid,'language':lang,'text':text})
        for qtype,qlang,qtext in [('paraphrase',lang,para),('cross_language',clang,cross),('exact',lang,exact)]+([('code_switch','mixed',mix)] if mix else []):
            queries.append({'id':f'{mid}-{qtype}','type':qtype,'language':lang,'query_language':qlang,'query':qtext,'relevant':'nl-'+mid,'split':split})
    for lang,items in fx['unanswerable'].items():
        for i,q in enumerate(items,1):
            queries.append({'id':f'{lang}-none-{i:02d}','type':'unanswerable','language':lang,'query_language':lang,'query':q,'relevant':None,
                            'split':'holdout' if holdout else ('dev' if i<=3 else 'test')})
    return memories,queries


def distractors(count,seed=20261026):
    rng=random.Random(seed);out=[];seen=set()
    while len(out)<count:
        lang=LANGS[len(out)%len(LANGS)];t=rng.choice(TEMPLATES[lang])
        text=t.format(name=rng.choice(NAMES[lang]),place=rng.choice(PLACES[lang]),n=rng.randint(2,99999))
        if text in seen:continue
        seen.add(text);out.append({'id':f'bg-{len(out):06d}','language':lang,'text':text})
    return out


def record(item,i):
    day=datetime(2025,1,1,tzinfo=timezone.utc).timestamp()+(i*7919)%(365*86400)
    extra={'source_application':item['app']} if item.get('app') else {}
    return {'op':'add','consent':True,'id':item['id'],'text':item['text'],'language':item['language'],**extra,
            'timestamp':item.get('timestamp') or datetime.fromtimestamp(day,timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),'device':'benchmark',
            'kind':'benchmark_fixture','provenance':'lens-retrieval-nl v1 synthetic benchmark; not user memory'}


VERIFIER_ARGS=[]  # set by --verifier: trained Lens answerability head (lens_model/)


class Engine:
    def __init__(self,db,model_id,model_file):
        lock=json.loads((ROOT/'third_party/embedding-lock.json').read_text(encoding='utf-8'))
        model=next(ROOT/f['path'] for f in lock['files'] if f['filename']==model_file)
        tok=next(ROOT/f['path'] for f in lock['files'] if f['filename']=='onnx/tokenizer.json')
        rlock=json.loads((ROOT/'third_party/reranker-lock.json').read_text(encoding='utf-8'))
        rmodel=next(ROOT/f['path'] for f in rlock['files'] if f['filename']=='onnx/model_qint8_avx512_vnni.onnx')
        rtok=next(ROOT/f['path'] for f in rlock['files'] if f['filename']=='tokenizer.json')
        self.p=subprocess.Popen([str(ENGINE),'--db',str(db),'--ort',str(RUNTIME),'--embedding-model',str(model),
            '--embedding-tokenizer',str(tok),'--embedding-id',model_id,'--reranker-model',str(rmodel),'--reranker-tokenizer',str(rtok)]+VERIFIER_ARGS,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            text=True,encoding='utf-8',bufsize=1)
        self.ps=psutil.Process(self.p.pid);self.peak_wset=0;self.peak_private=0;self._stop=False
        self.t=threading.Thread(target=self._sample,daemon=True);self.t.start()

    def _sample(self):
        while not self._stop and self.p.poll() is None:
            try:
                m=self.ps.memory_info();self.peak_wset=max(self.peak_wset,m.peak_wset);self.peak_private=max(self.peak_private,m.private)
            except psutil.Error:pass
            time.sleep(.02)

    def ask(self,req):
        self.p.stdin.write(json.dumps(req,ensure_ascii=False)+'\n');self.p.stdin.flush()
        line=self.p.stdout.readline()
        if not line:raise RuntimeError('engine exited: '+self.p.stderr.read())
        return json.loads(line)

    def close(self):
        self.p.stdin.close();self.p.wait(120);self._stop=True;self.t.join()


def progress(stage,done,total,start,engine,extra=''):
    elapsed=time.perf_counter()-start;rate=done/elapsed if elapsed>0 else 0
    eta=(total-done)/rate if rate>0 else float('nan')
    print(f'progress stage={stage} done={done}/{total} rate={rate:.1f}/s elapsed={elapsed:.0f}s eta={eta:.0f}s '
          f'engine_wset_mb={engine.ps.memory_info().rss/2**20:.0f} {extra}',flush=True)


def rank_of(response,mode,relevant):
    if mode=='legacy_context':ids=list(dict.fromkeys(c['source_id'] for c in response.get('citations',[])))
    elif mode=='legacy_search':ids=[s['id'] for s in response.get('sources',[])]
    else:ids=[r['source']['id'] for r in response.get('results',[])]
    wanted=relevant if isinstance(relevant,list) else [relevant]  # any valid evidence record counts
    hits=[ids.index(x)+1 for x in wanted if x in ids]
    return min(hits) if hits else None


def metrics(rows):
    ans=[r for r in rows if r['relevant']];out={'answerable':len(ans)}
    for k in (1,5,10):out[f'recall@{k}']=sum(1 for r in ans if r['rank'] and r['rank']<=k)/len(ans) if ans else None
    out['mrr@10']=sum(1/r['rank'] for r in ans if r['rank'] and r['rank']<=10)/len(ans) if ans else None
    out['ndcg@10']=sum(1/math.log2(r['rank']+1) for r in ans if r['rank'] and r['rank']<=10)/len(ans) if ans else None
    return out


def run_scale(n,memories,queries,folder,model_id,check_engine_default,model_file):
    folder.mkdir(parents=True,exist_ok=True);db=folder/'memory.db'
    if db.exists():raise RuntimeError(f'refusing to reuse {db}')
    corpus=memories+distractors(n-len(memories))
    # An "exact" query whose string occurs in several stored events cannot single out its labeled memory;
    # it is scored as exact_ambiguous instead of exact (all-answerable totals still include it).
    texts=[x['text'].lower() for x in corpus]
    queries=[dict(q,type='exact_ambiguous') if q['type']=='exact' and sum(q['query'].lower() in t for t in texts)>1 else q for q in queries]
    engine=Engine(db,model_id,model_file);result={'stored_events':len(corpus)}
    t=time.perf_counter();engine.ask({'op':'begin'})
    for i in range(0,len(corpus),128):
        r=engine.ask({'op':'import_batch','consent':True,'records':[record(x,i+k) for k,x in enumerate(corpus[i:i+128])]})
        if not r.get('ok'):raise RuntimeError(r)
        if (i//128)%100==0:progress('import',min(i+128,len(corpus)),len(corpus),t,engine,f'last_batch={i//128}')
    if engine.ask({'op':'commit'}).get('transaction')!='committed':raise RuntimeError('commit failed')
    result['import_s']=time.perf_counter()-t
    t=time.perf_counter();chunks=0
    while True:
        r=engine.ask({'op':'index','limit':4096})
        if not r.get('ok'):raise RuntimeError(r)
        chunks+=r['chunks'];progress('index',len(corpus)-r['pending_sources'],len(corpus),t,engine,f"chunks={chunks}")
        if r['pending_sources']==0:break
    result['index_s']=time.perf_counter()-t;result['index_ms_per_source']=result['index_s']*1000/len(corpus);result['vector_chunks']=chunks
    result['index_peak_wset_bytes']=engine.peak_wset;result['index_peak_private_bytes']=engine.peak_private
    rows=[];lat={m:[] for m in MODES};qstart=time.perf_counter()
    for qi,q in enumerate(queries):
        if qi%25==0:progress('query',qi,len(queries),qstart,engine,f'modes={len(MODES)}')
        for mode in MODES:
            if mode=='legacy_search':req={'op':'search','query':q['query'][:1024]}
            elif mode=='legacy_context':req={'op':'retrieve_context','query':q['query'][:1024]}
            elif BASE(mode) in ('hybrid_rerank','hybrid_rerank_rrf'):
                req={'op':'recall','query':q['query'],'mode':'hybrid','limit':10,'abstain':False,'rerank':True,'rerank_candidates':20,'interpret_time':False,'interpret_query':False,
                     'rerank_fusion':'rrf' if 'rrf' in mode else 'replace'}
            else:req={'op':'recall','query':q['query'],'mode':BASE(mode),'limit':10,'abstain':False,'rerank':False,'interpret_time':False,'interpret_query':False}
            if mode.endswith('_c'):req['center']=True
            elif req.get('op')=='recall':req['center']=False
            t=time.perf_counter()
            try:resp=engine.ask(req)
            except Exception as e:raise RuntimeError((q,mode,e))
            lat[mode].append((time.perf_counter()-t)*1000)
            rows.append({**q,'mode':mode,'ok':resp.get('ok',False),'error':resp.get('error'),
                         'rank':rank_of(resp,mode,q['relevant']) if q['relevant'] and resp.get('ok') else None,
                         'legacy_not_found':resp.get('not_found') if mode.startswith('legacy') else None,
                         'best_semantic':resp.get('best_semantic'),'best_rerank':resp.get('best_rerank'),
                         # Answerability features of the top two results (scores only, no content).
                         'features':[{'rerank':x['scores'].get('rerank'),'semantic':x['scores'].get('semantic'),'keyword_hits':x['scores'].get('keyword_hits'),
                                      'keyword_units':x['scores'].get('keyword_units'),'language':x['source']['language']} for x in resp.get('results',[])[:2]],'full_keyword_match':resp.get('full_keyword_match'),'returned':len(resp.get('results',resp.get('sources',resp.get('citations',[]))))})
    if check_engine_default:
        # The engine's built-in threshold must reproduce the benchmark's simulated hybrid abstention.
        result['engine_default_abstention']=[{'id':q['id'],'not_found':engine.ask({'op':'recall','query':q['query'],'mode':'hybrid','limit':10,'interpret_time':False,'interpret_query':False})['not_found']} for q in queries if q['split'] in ('test','holdout','expansion')]
    result['query_peak_wset_bytes']=engine.peak_wset;result['query_peak_private_bytes']=engine.peak_private
    stats=engine.ask({'op':'stats'});engine.close()
    result['latency_ms']={m:{'p50':statistics.median(v),'p95':sorted(v)[int(.95*(len(v)-1))],'p99':sorted(v)[int(.99*(len(v)-1))],'max':max(v)} for m,v in lat.items()}
    result['db_bytes']=sum(f.stat().st_size for f in folder.iterdir() if f.name.startswith('memory.db'))
    result['stats']=stats
    return result,rows


# Centered-mode abstention mirrors the engine defaults (engine/retrieval.cpp), fitted with
# scripts/calibrate_abstention.py on v1 dev + inspected split; they are not refitted per run.
CENTERED_RULE={'rerank':0.4,'cosine':0.37,'cosine_no_rerank':0.35}


def abstain(row,mode,tau):
    if mode in ('hybrid_rerank_c','hybrid_rerank_rrf_c'):
        return not (row['full_keyword_match'] or (row['best_rerank'] is not None and row['best_rerank']>=CENTERED_RULE['rerank'])
                    or (row['best_semantic'] is not None and row['best_semantic']>=CENTERED_RULE['cosine']))
    if mode in ('hybrid_c','semantic_c'):
        strong=row['best_semantic'] is not None and row['best_semantic']>=CENTERED_RULE['cosine_no_rerank']
        return not strong if mode=='semantic_c' else not (row['full_keyword_match'] or strong)
    mode=BASE(mode)
    if mode.startswith('legacy'):return bool(row['legacy_not_found'])
    if mode=='keyword':return not row['full_keyword_match']
    if mode=='semantic':return row['best_semantic'] is None or row['best_semantic']<tau
    if mode=='hybrid_rerank':return not row['full_keyword_match'] and (row['best_rerank'] is None or row['best_rerank']<tau)
    return not row['full_keyword_match'] and (row['best_semantic'] is None or row['best_semantic']<tau)


def calibrate(rows,mode):
    """Maximize balanced accuracy on dev: correct abstention on unanswerable, answering when evidence ranks top-10."""
    dev=[r for r in rows if r['split']=='dev' and r['mode']==mode]
    key='best_rerank' if BASE(mode)=='hybrid_rerank' else 'best_semantic'
    cands=sorted({round(r[key],4) for r in dev if r[key] is not None})
    best=(-1,0.0)
    for tau in cands:
        neg=[r for r in dev if not r['relevant']];pos=[r for r in dev if r['relevant'] and r['rank'] and r['rank']<=10]
        score=(sum(abstain(r,mode,tau) for r in neg)/len(neg)+sum(not abstain(r,mode,tau) for r in pos)/len(pos))/2
        if score>best[0]:best=(score,tau)
    return best[1],best[0]


def summarize(rows,taus,split='test'):
    out={}
    for mode in MODES:
        test=[r for r in rows if r['split']==split and r['mode']==mode];m={}
        for key,sel in [('all_answerable',lambda r:r['relevant']),*[(f'type:{t}',lambda r,t=t:r['type']==t) for t in ['exact','exact_ambiguous','paraphrase','cross_language','code_switch','cross_app','timeline','mixed']],
                        *[(f'language:{l}',lambda r,l=l:r['relevant'] and r['language']==l) for l in LANGS]]:
            m[key]=metrics([r for r in test if sel(r)])
        neg=[r for r in test if not r['relevant']];pos=[r for r in test if r['relevant']]
        tau=taus.get(mode,0.0)
        near=[r for r in neg if (r.get('subtype') or '').startswith('near_miss')]
        m['abstention']={'threshold':tau,'unanswerable':len(neg),'near_miss':len(near),
            'near_miss_correct_not_found_rate':sum(abstain(r,mode,tau) for r in near)/len(near) if near else None,'correct_not_found_rate':sum(abstain(r,mode,tau) for r in neg)/len(neg),
            'answerable_wrongly_abstained_rate':sum(abstain(r,mode,tau) for r in pos)/len(pos) if pos else None,
            'by_language':{l:sum(abstain(r,mode,tau) for r in neg if r['language']==l)/max(1,sum(1 for r in neg if r['language']==l)) for l in LANGS}}
        m['top1_correct_evidence_after_abstention']=sum(1 for r in pos if r['rank']==1 and not abstain(r,mode,tau))/len(pos) if pos else None
        m['errors']=sum(1 for r in test if not r['ok'])
        out[mode]=m
    return out


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--scales',type=int,nargs='+',default=[1000,10000]);ap.add_argument('--out',default='reports/retrieval-nl')
    ap.add_argument('--model',default='onnx/model_qint8_avx512_vnni.onnx',choices=['onnx/model_qint8_avx512_vnni.onnx','onnx/model.onnx'])
    ap.add_argument('--fixture',default='v1',choices=sorted(FIXTURES))
    ap.add_argument('--final',action='store_true',help='required for the sealed holdout')
    ap.add_argument('--modes',nargs='+',help='restrict to these modes (feature/diagnosis runs)')
    ap.add_argument('--split',default='all',choices=['all','dev'],help='dev = tuning experiments that never touch test queries')
    ap.add_argument('--rerank-threshold',type=float,help='fixed reranker abstention threshold; omit for dev calibration')
    ap.add_argument('--threshold',type=float,help='fixed abstention threshold (engine default); omit only for the dev calibration run')
    ap.add_argument('--verifier',type=Path,help='ONNX answerability head; its tokenizer.json must sit beside it')
    args=ap.parse_args()
    if args.verifier:VERIFIER_ARGS[:]=['--verifier-model',str(args.verifier),'--verifier-tokenizer',str(Path(args.verifier).parent/'tokenizer.json')]
    lock=json.loads((ROOT/'third_party/embedding-lock.json').read_text(encoding='utf-8'))
    sha=next(f['sha256'] for f in lock['files'] if f['filename']==args.model)
    model_id=f"intfloat/multilingual-e5-small@{lock['revision'][:12]}/{args.model}#sha256:{sha[:16]}"
    global MODES
    if args.modes:MODES=[m for m in MODES if m in args.modes]
    fixture=FIXTURES[args.fixture]
    if args.fixture in ('holdout','acceptance'):
        # Sealed holdout: final evaluation only, thresholds fixed in advance, every run logged.
        if not args.final or args.threshold is None or args.rerank_threshold is None or args.split!='all':
            raise SystemExit('holdout requires --final with fixed --threshold and --rerank-threshold')
    memories,queries=load(fixture);stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    if args.fixture in ('holdout','acceptance'):
        with HOLDOUT_LOG.open('a',encoding='utf-8') as log:
            log.write(f"{stamp} scales={args.scales} engine_sha256={hashlib.sha256(ENGINE.read_bytes()).hexdigest()} "
                      f"fixture_sha256={hashlib.sha256(fixture.read_bytes()).hexdigest()} threshold={args.threshold} rerank_threshold={args.rerank_threshold}"+chr(10))
    if args.split!='all':queries=[q for q in queries if q['split']==args.split]  # design experiments: dev only
    out=ROOT/args.out;out.mkdir(parents=True,exist_ok=True)
    engine_sha=hashlib.sha256(ENGINE.read_bytes()).hexdigest()
    # The engine-default check needs the default mode's rows; restricted --modes runs skip it.
    check=args.threshold is not None and args.rerank_threshold is not None and 'hybrid_rerank_c' in MODES
    for n in args.scales:
        result,rows=run_scale(n,memories,queries,ROOT/'artifacts'/f'retrieval-nl-{stamp}'/f'scale-{n}',model_id,check,args.model)
        if check:
            # The engine default is centered hybrid + rerank when a reranker is configured (as here).
            sim={r['id']:abstain(r,'hybrid_rerank_c',None) for r in rows if r['mode']=='hybrid_rerank_c' and r['split'] in ('test','holdout','expansion')}
            result['engine_default_matches_simulation']=all(sim[x['id']]==x['not_found'] for x in result.pop('engine_default_abstention'))
        scored={'holdout':'holdout','acceptance':'holdout','expansion':'expansion','nearmiss':'nearmiss'}.get(args.fixture,'dev' if args.split=='dev' else 'test')
        taus={m:(args.threshold if args.threshold is not None else calibrate(rows,m)[0]) for m in ('semantic','hybrid')}
        taus['hybrid_rerank']=args.rerank_threshold if args.rerank_threshold is not None else calibrate(rows,'hybrid_rerank')[0]
        for m in ('semantic_c','hybrid_c','hybrid_rerank_c','hybrid_rerank_rrf_c'):taus[m]='engine default rule '+json.dumps(CENTERED_RULE)
        report={'benchmark':'lens-retrieval-nl v1','created_utc':stamp,'scale':n,'engine_sha256':engine_sha,'model_id':model_id,
                'fixture':args.fixture,'fixture_sha256':hashlib.sha256(fixture.read_bytes()).hexdigest(),'queries_total':len(queries),
                'queries_test':sum(1 for q in queries if q['split']=='test'),'calibration_split':'dev','threshold_applied':taus,
                'calibration':({m:{'threshold':calibrate(rows,m)[0],'dev_balanced_accuracy':calibrate(rows,m)[1]} for m in ('semantic','hybrid','hybrid_rerank')} if args.fixture=='v1' else 'none (sealed holdout; fixed thresholds)'),
                **result,'test_results':summarize(rows,taus,scored),'scored_split':scored,
                'notes':'legacy_* ops return at most 5 sources, so their recall@10 equals recall@5. Abstention thresholds fitted on dev only. '
                         'type:exact covers exact strings unique in the stored corpus; non-unique ones are type:exact_ambiguous.'}
        (out/f'{stamp}-scale-{n}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        (out/f'{stamp}-scale-{n}-rows.json').write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8')
        brief={m:{k:report['test_results'][m]['all_answerable'][k] for k in ('recall@1','recall@10','mrr@10')}|{'abstain_ok':report['test_results'][m]['abstention']['correct_not_found_rate']} for m in MODES}
        print(n,json.dumps(brief),json.dumps(report['calibration']),flush=True)


if __name__=='__main__':main()
