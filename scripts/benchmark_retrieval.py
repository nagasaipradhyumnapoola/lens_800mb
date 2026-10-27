"""A labeled synthetic long-history exact-search benchmark, not a natural-language QA claim."""
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]

def main():
    folder=ROOT/'artifacts'/('retrieval-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    folder.mkdir(parents=True)
    requests=[];queries=[]
    for i in range(10000):
        if i<100:
            lang=['en','zh','es','hi'][i%4]
            anchor={'en':'AnchorMemory','zh':'北京记忆','es':'RecuerdoÚnico','hi':'दिल्लीस्मृति'}[lang]+str(i)
            text={'en':'Meeting source: ','zh':'会议原文：','es':'Fuente de reunión: ','hi':'बैठक का मूल स्रोत: '}[lang]+anchor
            queries.append({'query':anchor,'expected_id':'synthetic-'+str(i),'language':lang})
        else:lang='en';text=f'Unrelated distractor record {i} with tag filler{i}.'
        requests.append({'op':'add','consent':True,'id':'synthetic-'+str(i),'text':text,'language':lang,
                         'timestamp':'2026-10-26T00:00:00Z','device':'synthetic-benchmark','kind':'benchmark',
                         'provenance':'labeled synthetic retrieval fixture; not user memory'})
    requests += [{'op':'search','query':x['query']} for x in queries]
    requests += [{'op':'search','query':'ABSENT_SOURCE_9f5bdd'+str(i)} for i in range(20)]
    start=time.perf_counter()
    p=subprocess.run([str(ROOT/'build/engine/Release/lens-engine.exe'),'--db',str(folder/'memory.db')],
                     input=''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in requests),
                     text=True,encoding='utf-8',capture_output=True,timeout=300)
    if p.returncode:raise RuntimeError(p.stderr)
    rows=[json.loads(x) for x in p.stdout.splitlines()]
    inserts=rows[:10000];searches=rows[10000:10100];missing=rows[10100:]
    failures=[{'index':i,'result':r} for i,r in enumerate(inserts) if not r.get('ok')]
    scored=[]
    for expected,actual in zip(queries,searches):
        hit=any(x['id']==expected['expected_id'] for x in actual.get('sources',[]))
        scored.append({**expected,'hit_at_5':hit})
    result={'history_records':10000,'query_count':len(scored),'recall_at_5':sum(x['hit_at_5'] for x in scored)/len(scored),
            'unanswerable_queries':len(missing),'correct_not_found':sum(x.get('not_found',False) for x in missing),
            'insert_failure_count':len(failures),'failures':failures,'elapsed_s':time.perf_counter()-start,
            'dataset_kind':'Lens-authored synthetic anchor/substring retrieval; natural questions not validated',
            'by_language':{lang:sum(x['hit_at_5'] for x in scored if x['language']==lang)/25 for lang in ['en','zh','es','hi']},
            'queries':scored}
    (ROOT/'reports/memory-retrieval-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='queries'},ensure_ascii=True,indent=2))
    if failures or result['recall_at_5']<.9 or result['correct_not_found']!=20:raise SystemExit(1)

if __name__=='__main__':main()
