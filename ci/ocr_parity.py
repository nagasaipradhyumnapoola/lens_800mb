"""Screen OCR parity across operating systems: runs one lens-ocr build on the English hard-screen dev set with the shipped
configuration (PP-OCRv5 mobile detector 0.3/0.6/1.5, PP-OCRv6 tiny recogniser, Lens row assembly) and reports page CER
with the metric of scripts/benchmark_ocr_native.py (NFC, ZWNJ/ZWJ removed, whitespace collapsed). Standard library only,
so it runs in the Linux container and on macOS runners. Dev split only (artifacts/ocr-screens/en-hard-dev).
Usage: python3 ci/ocr_parity.py <lens-ocr executable> <ONNX Runtime library> [--max-cer 0.03] [--limit N]
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import unicodedata
ROOT=Path(__file__).resolve().parents[1]
M=ROOT/'models'
SET=ROOT/'artifacts/ocr-screens/en-hard-dev/manifest.json'
DET=M/'PaddlePaddle--PP-OCRv5_mobile_det/inference.onnx'
REC=M/'PaddlePaddle--PP-OCRv6_tiny_rec'


def edit(a,b):
    prev=list(range(len(b)+1))
    for i,ca in enumerate(a,1):
        cur=[i]+[0]*len(b)
        for j,cb in enumerate(b,1):cur[j]=min(prev[j]+1,cur[j-1]+1,prev[j-1]+(ca!=cb))
        prev=cur
    return prev[-1]


def metric_text(s):return unicodedata.normalize('NFC',' '.join(s.replace('‌','').replace('‍','').split()))


def available():return SET.exists() and DET.exists() and (REC/'inference.onnx').exists()


def run(worker,runtime,limit=0):
    """Mean page CER and per-screen rows; one --serve worker for the whole set, as the observer uses it."""
    scenarios=json.loads(SET.read_text(encoding='utf-8'))['scenarios'];scenarios=scenarios[:limit] if limit else scenarios
    p=subprocess.Popen([str(worker),'--serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,encoding='utf-8')
    rows=[]
    try:
        for sc in scenarios:
            raw=(ROOT/sc['image']).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=sc['sha256']:raise SystemExit(f"{sc['image']} does not match its manifest sha256")
            req={'consent':True,'runtime':str(runtime),'mode':'screen','detector':str(DET),'det_thresh':0.3,'box_thresh':0.6,'unclip_ratio':1.5,
                 'threads':2,'route':'general','recognizers':{'general':{'model':str(REC/'inference.onnx'),'dictionary':str(REC/'ctc-dictionary.json')}},
                 'image_base64':base64.b64encode(raw).decode('ascii')}
            p.stdin.write(json.dumps(req)+'\n');p.stdin.flush();out=json.loads(p.stdout.readline())
            if not out.get('ok'):raise SystemExit(f"{sc['name']}: {out.get('error')}")
            gt='\n'.join(metric_text(l) for l in sc['lines']);pred='\n'.join(metric_text(l['text']) for l in out['lines'])
            rows.append({'name':sc['name'],'page_cer':edit(gt,pred)/max(1,len(gt)),'peak_bytes':out['peak_working_set_bytes']})
    finally:
        p.stdin.close();p.wait(timeout=60)
    return sum(r['page_cer'] for r in rows)/len(rows),rows


def main():
    ap=argparse.ArgumentParser();ap.add_argument('worker');ap.add_argument('runtime');ap.add_argument('--max-cer',type=float,default=0.03)
    ap.add_argument('--limit',type=int,default=0);args=ap.parse_args()
    if not available():raise SystemExit('OCR models or the en-hard-dev set are not installed')
    cer,rows=run(args.worker,args.runtime,args.limit)
    for r in rows:print(f"{r['name']:24s} page CER {r['page_cer']:.4f} peak {r['peak_bytes']/1e6:.0f} MB")
    print(json.dumps({'screens':len(rows),'page_cer':cer,'peak_mb_max':max(r['peak_bytes'] for r in rows)/1e6}))
    if cer>args.max_cer:raise SystemExit(f'page CER {cer:.4f} above {args.max_cer}')


if __name__=='__main__':main()
