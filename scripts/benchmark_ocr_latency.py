"""Serve-mode OCR latency: the observer's persistent `lens-ocr --serve` worker, warm, on dev screens.

For each dev screen (optionally --only languages) the worker answers a full-screen request and then a changed-band
request (the second detected line +- 32 px, full width, drop_edge_boxes) --repeat times; the compute time reported by
the worker (detect + recognize, model loads excluded) and the request wall time are summarised. Requests to a warm
worker are what the observer sends, unlike benchmark_ocr_native.py which starts a process per request.
Output: reports/ocr-screens/ocr-latency-<UTC>.json
Usage: .venv\\Scripts\\python.exe scripts/benchmark_ocr_latency.py [--only en,te] [--repeat 5] [--te Lens--te_PP-OCRv5_mobile_rec_screen]
"""
import argparse
import base64
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
import time
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from benchmark_ocr_native import DET,M,REC,RTL,RUNTIME,SETS


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--only');ap.add_argument('--repeat',type=int,default=5);ap.add_argument('--threads',type=int,default=2)
    ap.add_argument('--te',default='Lens--te_PP-OCRv5_mobile_rec_screen');ap.add_argument('--set',choices=list(SETS),default='dev');args=ap.parse_args()
    det,thresh,box_thresh,unclip=DET['v5'];rec={**REC,'te':args.te}
    base={'consent':True,'runtime':str(RUNTIME),'mode':'screen','detector':str(det),'det_thresh':thresh,'box_thresh':box_thresh,'unclip_ratio':unclip,
          'threads':args.threads,'route':'auto',
          'recognizers':{k:{'model':str(M/v/'inference.onnx'),'dictionary':str(M/v/'ctc-dictionary.json'),'rtl':k in RTL} for k,v in rec.items()}}
    p=subprocess.Popen([str(ROOT/'build/engine/Release/lens-ocr.exe'),'--serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                       text=True,encoding='utf-8',bufsize=1)

    def ask(req):
        t=time.perf_counter();p.stdin.write(json.dumps(req)+'\n');p.stdin.flush();r=json.loads(p.stdout.readline())
        if not r.get('ok'):raise RuntimeError(r)
        r['wall_ms']=(time.perf_counter()-t)*1000;return r
    rows=[];manifest=json.loads(SETS[args.set].read_text(encoding='utf-8'))
    for sc in manifest['scenarios']:
        if args.only and sc['language'] not in args.only.split(','):continue
        image=base64.b64encode((ROOT/sc['image']).read_bytes()).decode('ascii')
        full=ask({**base,'image_base64':image});b=full['lines'][min(1,len(full['lines'])-1)]['box'] if full['lines'] else [0,0,1,48]
        y0=max(0,b[1]-32);band=[0,y0,full['width'],min(full['height'],b[3]+32)-y0]
        for i in range(args.repeat):
            f=ask({**base,'image_base64':image}) if i else full;r=ask({**base,'image_base64':image,'region':band,'drop_edge_boxes':True})
            rows.append({'name':sc['name'],'language':sc['language'],'full_compute_ms':f['timing_ms']['detect']+f['timing_ms']['recognize'],
                         'full_wall_ms':f['wall_ms'],'band_compute_ms':r['timing_ms']['detect']+r['timing_ms']['recognize'],'band_wall_ms':r['wall_ms'],
                         'band_load_ms':r['timing_ms']['recognizer_load']+r['timing_ms']['detector_load']})
        print(sc['name'],'band p50',round(np.median([x['band_compute_ms'] for x in rows if x['name']==sc['name']])),'ms',flush=True)
    p.stdin.close();p.wait(timeout=60)
    q=lambda k,v:float(np.percentile([x[k] for x in rows],v))
    summary={f'{k}_p{v}':q(k,v) for k in ('band_compute_ms','band_wall_ms','full_compute_ms','full_wall_ms') for v in (50,95)}
    report={'created_utc':datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),'set':args.set,'only':args.only,'repeat':args.repeat,
            'threads':args.threads,'te_recognizer':args.te,'summary':summary,'rows':rows}
    out=ROOT/'reports/ocr-screens'/f"ocr-latency-{report['created_utc']}.json";out.write_text(json.dumps(report,indent=1),encoding='utf-8')
    print(json.dumps(summary,indent=1));print(out)


if __name__=='__main__':main()
