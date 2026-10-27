"""Combined-workload RAM profile: retrieval, ASR and OCR workers run concurrently, then serially.

Measures the whole Lens process set (sum of working set and of private bytes across live Lens processes,
sampled every 20 ms, plus each process's OS peak working set). Uses public FLEURS audio and the synthetic
OCR crop fixtures only. Usage: .venv\\Scripts\\python.exe scripts/profile_combined.py [--out reports/ram]
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import psutil
ROOT=Path(__file__).resolve().parents[1]
REL=ROOT/'build/engine/Release'
LIMIT=800_000_000  # founder ceiling for the complete background system (docs/LENS_V1_SPEC.md §15)


def lock(name,filename):
    data=json.loads((ROOT/'third_party'/name).read_text(encoding='utf-8'))
    items=data['files'] if 'files' in data else data.get('models',data) if isinstance(data,dict) else data
    return next(ROOT/x['path'] for x in items if x['filename']==filename)


def fleurs(language):
    samples=json.loads((ROOT/'data/fixtures/fleurs-smoke.json').read_text(encoding='utf-8'))['samples']
    return str(ROOT/next(s['path'] for s in samples if s['language']==language))


def workloads(db):
    ort=str(ROOT/'.tools/ocr-runtime/onnxruntime.dll')
    retrieval_args=[str(REL/'lens-engine.exe'),'--db',str(db),'--ort',ort,'--embedding-model',str(lock('embedding-lock.json','onnx/model_qint8_avx512_vnni.onnx')),
                    '--embedding-tokenizer',str(lock('embedding-lock.json','onnx/tokenizer.json')),'--embedding-id','profile-e5',
                    '--reranker-model',str(lock('reranker-lock.json','onnx/model_qint8_avx512_vnni.onnx')),'--reranker-tokenizer',str(lock('reranker-lock.json','tokenizer.json'))]
    recall=''.join(json.dumps({'op':'recall','query':q})+'\n' for q in ['When is the budget review?','¿Qué no puede comer Lena?','मदुरै की ट्रेन कब है?']*5)
    whisper=json.dumps({'op':'ingest_audio','consent':True,'id':'p-en','audio':fleurs('en'),'model':str(ROOT/'models/ggerganov--whisper.cpp/ggml-base-q5_1.bin'),
                        'language':'en','timestamp':'2026-01-01T00:00:00Z','device':'profile','kind':'audio_import','provenance':'public FLEURS fixture'})+'\n'
    sherpa_lock=json.loads((ROOT/'third_party/sherpa-reference-lock.json').read_text(encoding='utf-8'))
    library=str(ROOT/next(a['path'] for a in sherpa_lock['runtime_artifacts'] if a['path'].endswith('/lib/sherpa-onnx-c-api.dll')))
    dolphin=next(ROOT/m['path'] for m in sherpa_lock['models'] if m['filename']=='model.int8.onnx')
    tokens=next(ROOT/m['path'] for m in sherpa_lock['models'] if m['filename']=='tokens.txt')
    sherpa=json.dumps({'consent':True,'audio':fleurs('zh'),'model':str(dolphin),'tokens':str(tokens),'library':library,'language':'zh','model_type':'dolphin'})+'\n'
    ocr_dir=ROOT/'models/PaddlePaddle--PP-OCRv6_tiny_rec'
    ocr=json.dumps({'consent':True,'runtime':ort,'model':str(ocr_dir/'inference.onnx'),'dictionary':str(ocr_dir/'ctc-dictionary.json'),
                    'image':str(ROOT/'artifacts/ocr-smoke/es.png')})+'\n'
    return [('retrieval',retrieval_args,recall),('asr_whisper_base',[str(REL/'lens-engine.exe'),'--db',str(db.with_name('asr.db'))],whisper),
            ('asr_dolphin_zh',[str(REL/'lens-sherpa.exe')],sherpa),('ocr_ppocrv6',[str(REL/'lens-ocr.exe')],ocr)]


def run(scenario,jobs):
    procs=[];samples=[];peak_ws=peak_priv=0;per={};stop=False
    def sample():
        nonlocal peak_ws,peak_priv
        while not stop:
            ws=priv=0
            for name,p in procs:
                try:
                    m=psutil.Process(p.pid).memory_info();ws+=m.rss;priv+=m.private
                    per[name]=max(per.get(name,0),m.peak_wset)
                except psutil.Error:pass
            peak_ws,peak_priv=max(peak_ws,ws),max(peak_priv,priv);time.sleep(.02)
    t=threading.Thread(target=sample,daemon=True);t.start();start=time.perf_counter();results={}
    def launch(name,args,stdin):
        p=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
        procs.append((name,p));out,err=p.communicate(stdin,timeout=600)
        results[name]={'exit':p.returncode,'ok_lines':sum('"ok":true' in x for x in out.splitlines()),'stderr':err.strip()[:200]}
    if scenario=='concurrent':
        threads=[threading.Thread(target=launch,args=j) for j in jobs]
        for x in threads:x.start()
        for x in threads:x.join()
    else:
        for j in jobs:launch(*j)
    stop=True;t.join()
    return {'scenario':scenario,'wall_s':time.perf_counter()-start,'peak_sum_working_set_bytes':peak_ws,'peak_sum_private_bytes':peak_priv,
            'per_process_os_peak_working_set_bytes':per,'results':results,
            'within_limit_working_set':peak_ws<=LIMIT,'within_limit_private':peak_priv<=LIMIT}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',default='reports/ram');args=ap.parse_args()
    out=ROOT/args.out;out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        db=Path(tmp)/'memory.db'
        seed=subprocess.run(workloads(db)[0][1],input=json.dumps({'op':'add','consent':True,'id':'s','text':'Budget review moved to Friday.','language':'en',
            'timestamp':'2026-01-01T00:00:00Z','device':'profile','kind':'k','provenance':'synthetic'})+'\n'+json.dumps({'op':'index'})+'\n',capture_output=True,text=True,encoding='utf-8')
        if seed.returncode:raise RuntimeError(seed.stderr)
        report={'created_utc':datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),'limit_bytes':LIMIT,
                'note':'Observation (Milestone 3) does not exist yet; its share is not included.',
                'runs':[run('concurrent',workloads(db)),run('serial',workloads(db))]}
    path=out/f"combined-{report['created_utc']}.json";path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    for r in report['runs']:
        print(r['scenario'],'peak_ws_MB=%.0f peak_private_MB=%.0f'%(r['peak_sum_working_set_bytes']/1e6,r['peak_sum_private_bytes']/1e6),
              {k:round(v/1e6) for k,v in r['per_process_os_peak_working_set_bytes'].items()},{k:v['exit'] for k,v in r['results'].items()})
    print(path)


if __name__=='__main__':main()
