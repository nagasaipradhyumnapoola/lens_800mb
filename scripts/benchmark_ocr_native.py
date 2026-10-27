"""Benchmark the shipped native OCR worker (lens-ocr.exe, mode=screen) on the rendered screen set.

Same metrics as scripts/ocr_reference.py (page CER, line accuracy at CER <= 0.05) plus the worker's own timings and
peak working set. Full screens (1280x800) and changed-region requests (one text line plus margin, the observer's
typical case) are measured separately. CPU only. Images are sent base64-encoded on stdin, never written by the worker.
Usage: .venv\\Scripts\\python.exe scripts/benchmark_ocr_native.py [--route auto|oracle] [--det v5|v6] [--threads 2]
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
from ocr_reference import ORACLE,edit,norm
M=ROOT/'models'
RUNTIME=ROOT/'.tools/ocr-runtime/onnxruntime.dll'
DET={'v5':(M/'PaddlePaddle--PP-OCRv5_mobile_det/inference.onnx',0.3,0.6,1.5),'v6':(M/'PaddlePaddle--PP-OCRv6_tiny_det/inference.onnx',0.2,0.4,1.4)}
REC={'general':'PP-OCRv6_tiny_rec','hi':'devanagari_PP-OCRv5_mobile_rec','ta':'ta_PP-OCRv5_mobile_rec','te':'te_PP-OCRv5_mobile_rec'}


def request(image_bytes,args,route,region=None):
    det,thresh,box_thresh,unclip=DET[args.det]
    req={'consent':True,'runtime':str(RUNTIME),'mode':'screen','detector':str(det),'det_thresh':thresh,'box_thresh':box_thresh,
         'unclip_ratio':unclip,'threads':args.threads,'route':route,'auto_threshold':args.auto_threshold,
         'recognizers':{k:{'model':str(M/f'PaddlePaddle--{v}/inference.onnx'),'dictionary':str(M/f'PaddlePaddle--{v}/ctc-dictionary.json')} for k,v in REC.items()},
         'image_base64':base64.b64encode(image_bytes).decode('ascii')}
    if region:req['region']=region
    t=time.perf_counter()
    p=subprocess.run([str(ROOT/'build/engine/Release/lens-ocr.exe')],input=json.dumps(req)+'\n',capture_output=True,text=True,encoding='utf-8',timeout=300)
    wall=(time.perf_counter()-t)*1000
    if p.returncode:raise RuntimeError(p.stderr)
    out=json.loads(p.stdout);out['wall_ms']=wall;return out


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--route',choices=['auto','oracle'],default='auto');ap.add_argument('--det',choices=['v5','v6'],default='v5')
    ap.add_argument('--threads',type=int,default=2);ap.add_argument('--auto-threshold',type=float,default=0.9);args=ap.parse_args()
    manifest=json.loads((ROOT/'artifacts/ocr-screens/v1/manifest.json').read_text(encoding='utf-8'));rows=[]
    for sc in manifest['scenarios']:
        raw=(ROOT/sc['image']).read_bytes()
        route=ORACLE.get(sc['language'],'auto') if args.route=='oracle' else 'auto'
        full=request(raw,args,route);lines=[' '.join(l['text'].split()) for l in full['lines']];gt=[norm(l) for l in sc['lines']]
        line_cer=[min((edit(g,p)/max(1,len(g)) for p in lines),default=1.0) for g in gt]
        page=edit('\n'.join(gt),'\n'.join(lines))/max(1,len('\n'.join(gt)))
        # changed-region request: the second detected line plus a 12 px margin
        b=full['lines'][min(1,len(full['lines'])-1)]['box'] if full['lines'] else [0,0,320,48]
        region=[max(0,b[0]-12),max(0,b[1]-12),min(full['width'],b[2]+12)-max(0,b[0]-12),min(full['height'],b[3]+12)-max(0,b[1]-12)]
        part=request(raw,args,route,region)
        rows.append({'name':sc['name'],'language':sc['language'],'page_cer':page,'line_accuracy':float(np.mean([c<=0.05 for c in line_cer])),
                     'full':{k:full[k] for k in ('timing_ms','wall_ms','peak_working_set_bytes','boxes')},
                     'region':{'size':region[2:],'timing_ms':part['timing_ms'],'wall_ms':part['wall_ms'],'peak_working_set_bytes':part['peak_working_set_bytes'],
                               'text':[l['text'] for l in part['lines']]},
                     'recognizers':sorted({l['recognizer'] for l in full['lines']}),'pred':lines})
        f=full['timing_ms'];r=part['timing_ms']
        print(f"{sc['name']:14s} pageCER {page:.3f} lineAcc {rows[-1]['line_accuracy']:.2f} full det {f['detect']:.0f}+rec {f['recognize']:.0f} ms "
              f"(wall {full['wall_ms']:.0f}) | region det {r['detect']:.0f}+rec {r['recognize']:.0f} ms (wall {part['wall_ms']:.0f}) peak {full['peak_working_set_bytes']/1e6:.0f} MB",flush=True)
    by={}
    for r in rows:by.setdefault(r['language'],[]).append(r)
    def pct(v,q):return float(np.percentile(v,q))
    compute=lambda r,k:r[k]['timing_ms']['detect']+r[k]['timing_ms']['recognize']
    summary={k:{'page_cer':float(np.mean([r['page_cer'] for r in v])),'line_accuracy':float(np.mean([r['line_accuracy'] for r in v]))} for k,v in by.items()}
    summary['latency_ms']={'full_compute_p50':pct([compute(r,'full') for r in rows],50),'full_compute_p95':pct([compute(r,'full') for r in rows],95),
                           'region_compute_p50':pct([compute(r,'region') for r in rows],50),'region_compute_p95':pct([compute(r,'region') for r in rows],95),
                           'region_wall_p50':pct([r['region']['wall_ms'] for r in rows],50),'full_wall_p50':pct([r['full']['wall_ms'] for r in rows],50)}
    summary['peak_working_set_mb_max']=max(r['full']['peak_working_set_bytes'] for r in rows)/1e6
    report={'created_utc':datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),'worker':'lens-ocr.exe mode=screen','det':args.det,'route':args.route,
            'threads':args.threads,'edge_version':manifest['edge_version'],'summary':summary,'rows':rows}
    out=ROOT/'reports/ocr-screens'/f"ocr-native-{args.det}-{args.route}-{report['created_utc']}.json";out.write_text(json.dumps(report,ensure_ascii=False,indent=1),encoding='utf-8')
    print(json.dumps(summary,indent=1));print(out)


if __name__=='__main__':main()
