"""Storage benchmark for observer-shaped workloads (docs/LENS_V1_SPEC.md §9: measure before compressing).

Workload (synthetic, public text only — SQuAD 2.0 and TyDi GoldP contexts; no personal data): an 8-hour "day" of
observer records in the exact shape lens-observer emits. Documents are read and scrolled (a 12-line window moving
through the text), edited (small insertions), and chats grow line by line; every material change is a new record,
so consecutive records of one window are near-duplicates, as on a real desktop.

Measures through the real engine (SQLCipher, FTS5, metadata; optional e5 index): database bytes per observation and
per day, then zstd (1.5.7) ratios on the same texts: per record, per record with a trained dictionary, and as a delta
against the previous version of the same window (previous text as prefix dictionary).
Usage: .venv\\Scripts\\python.exe scripts/benchmark_storage.py [--records 4000] [--index]
"""
import argparse
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import time
import pyarrow.parquet as pq
import zstandard as zstd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
EXT=ROOT/'data/external'


def corpus(rng):
    sq=[r['context'] for r in pq.read_table(EXT/'squad_v2/validation.parquet',columns=['context']).to_pylist()]
    ty=[r['context'] for r in pq.read_table(EXT/'tydiqa_goldp/validation.parquet',columns=['context']).to_pylist()]
    docs=sorted(set(sq))+sorted(set(ty));rng.shuffle(docs);return docs


def lines_of(text,width=90):
    words=text.split();out=[];cur=''
    for w in words:
        if len(cur)+len(w)+1>width:out.append(cur);cur=w
        else:cur=(cur+' '+w).strip()
    if cur:out.append(cur)
    return out


def workload(n,rng):
    docs=corpus(rng);apps=[('chrome.exe','{} - Google Chrome'),('winword.exe','{} - Word'),('code.exe','{} - Visual Studio Code'),
                           ('acrobat.exe','{}.pdf - Adobe Acrobat'),('whatsapp.exe','WhatsApp'),('outlook.exe','Inbox - Outlook')]
    t=datetime(2026,10,27,9,0,tzinfo=timezone.utc);records=[];d=0
    while len(records)<n:
        app,title_fmt=rng.choice(apps);doc=lines_of(docs[d%len(docs)]+' '+docs[(d+1)%len(docs)]);d+=2
        title=title_fmt.format(doc[0][:40]);chrome=['File  Edit  View  Help',title]
        if app=='whatsapp.exe':  # chat: grows a line at a time
            for k in range(3,min(len(doc),18)):
                records.append((app,title,'\n'.join(chrome+doc[:k][-12:]),t));t+=timedelta(seconds=rng.randint(20,90))
        else:
            pos=0;view=doc[:]
            for _ in range(rng.randint(4,14)):
                if rng.random()<0.35 and view:  # edit: insert a few words in a visible line
                    k=min(len(view)-1,pos+rng.randint(0,11));view[k]=view[k]+' '+' '.join(rng.sample(doc[0].split(),min(3,len(doc[0].split()))))
                else:pos=min(max(0,len(view)-12),pos+rng.randint(1,6))  # scroll
                records.append((app,title,'\n'.join(chrome+view[pos:pos+12]),t));t+=timedelta(seconds=rng.randint(15,120))
        t+=timedelta(seconds=rng.randint(30,300))
    return records[:n]


def engine_requests(records):
    for i,(app,title,text,t) in enumerate(records):
        yield {'op':'add','consent':True,'id':f'sim-{i:06d}','text':text,'language':'und','timestamp':t.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
               'device':'sim','kind':'screen_observation','provenance':'storage-benchmark synthetic','source_application':app,
               'source_locator':'window:'+title,'consent_context':{'mode':'observer_explicit_consent'},'metadata':{'window_title':title,'capture':'uia'}}


def db_size(db):return sum(p.stat().st_size for p in db.parent.glob(db.name+'*') if not p.name.endswith('.key'))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--records',type=int,default=4000);ap.add_argument('--index',action='store_true')
    ap.add_argument('--train-after',type=int,default=0,help='train a zstd dictionary after this many records (0 = never)');args=ap.parse_args()
    rng=random.Random(20261027);records=workload(args.records,rng)
    span_h=(records[-1][3]-records[0][3]).total_seconds()/3600;texts=[r[2] for r in records];raw=sum(len(x.encode()) for x in texts)
    with tempfile.TemporaryDirectory() as tmp:
        db=Path(tmp)/'memory.db';cmd=[str(ROOT/'build/engine/Release/lens-engine.exe'),'--db',str(db)]
        if args.index:
            import benchmark_retrieval_nl as bench
            lock=json.loads((ROOT/'third_party/embedding-lock.json').read_text(encoding='utf-8'))
            sha=next(f['sha256'] for f in lock['files'] if f['filename']=='onnx/model_qint8_avx512_vnni.onnx')
            e=bench.Engine(db,f"intfloat/multilingual-e5-small@{lock['revision'][:12]}#sha256:{sha[:16]}",'onnx/model_qint8_avx512_vnni.onnx')
            t0=time.perf_counter()
            for r in engine_requests(records):assert e.ask(r).get('ok'),'add failed'
            while e.ask({'op':'index','limit':4096})['pending_sources']:pass
            ingest_s=time.perf_counter()-t0;e.close()
        else:
            t0=time.perf_counter();reqs=list(engine_requests(records))
            if args.train_after:reqs.insert(args.train_after,{'op':'train_text_dictionary','samples':2000,'dictionary_bytes':65536})
            reqs.append({'op':'stats'})
            p=subprocess.run(cmd,input=''.join(json.dumps(r)+'\n' for r in reqs),capture_output=True,text=True,encoding='utf-8',timeout=3600)
            ingest_s=time.perf_counter()-t0;assert all(json.loads(l).get('ok') for l in p.stdout.splitlines()),p.stdout[-500:]
            stats=json.loads(p.stdout.splitlines()[-1])
        size=db_size(db)
    c=zstd.ZstdCompressor(level=3);per=sum(len(c.compress(x.encode())) for x in texts)
    dict_data=zstd.train_dictionary(65536,[x.encode() for x in texts[:max(200,len(texts)//4)]])
    cd=zstd.ZstdCompressor(level=3,dict_data=dict_data);per_dict=sum(len(cd.compress(x.encode())) for x in texts[len(texts)//4:])
    raw_tail=sum(len(x.encode()) for x in texts[len(texts)//4:])
    last={};delta=0
    for app,title,text,_ in records:
        prev=last.get((app,title))
        if prev:
            cdelta=zstd.ZstdCompressor(level=3,dict_data=zstd.ZstdCompressionDict(prev.encode(),dict_type=zstd.DICT_TYPE_RAWCONTENT))
            delta+=len(cdelta.compress(text.encode()))
        else:delta+=len(c.compress(text.encode()))
        last[(app,title)]=text
    report={'created_utc':datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),'records':len(records),'span_hours':span_h,'indexed':args.index,
            'train_after':args.train_after,'engine_stats':None if args.index else {k:stats.get(k) for k in ('schema_version','compressed_sources','compressed_text_bytes','text_dictionaries')},
            'raw_text_bytes':raw,'db_bytes':size,'db_bytes_per_record':size/len(records),'raw_bytes_per_record':raw/len(records),
            'db_bytes_per_8h_day':size/span_h*8,'ingest_seconds':ingest_s,
            'zstd':{'per_record_ratio':raw/per,'trained_dictionary_ratio':raw_tail/per_dict,'delta_vs_previous_version_ratio':raw/delta,'level':3,'zstd':zstd.ZSTD_VERSION}}
    out=ROOT/'reports/storage';out.mkdir(parents=True,exist_ok=True)
    (out/f"storage-{'indexed' if args.index else 'text'}-{report['created_utc']}.json").write_text(json.dumps(report,indent=1),encoding='utf-8')
    print(json.dumps(report,indent=1))


if __name__=='__main__':main()
