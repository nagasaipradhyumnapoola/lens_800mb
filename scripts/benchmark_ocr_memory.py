"""Measure the persistent OCR worker's memory on a large high-DPI synthetic screen (no real screen is read).

Renders an authored mixed-script page with headless Microsoft Edge (no window, temporary profile) at 1707x1067 CSS px
and device scale 1.5, i.e. a 2560x1600 bitmap like a 150%-DPI laptop panel, then drives `lens-ocr --serve` the way the
observer does: full screen (auto routing), a changed band, the full screen again, then idle. After each request the
worker's working set and private bytes are sampled (psutil), plus the worker's own peak working set.
Target (coordinating session, 2026-10-27): worker peak <= ~150 MB.
Output: reports/ocr-screens/ocr-memory-<UTC>.json
Usage: .venv\\Scripts\\python.exe scripts/benchmark_ocr_memory.py [--threads 2] [--te Lens--te_PP-OCRv5_mobile_rec_screen]
"""
import argparse
import base64
from datetime import datetime,timezone
import html
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import psutil
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from make_ocr_screens import EDGE,TEXT
M=ROOT/'models'


def large_screen(css=(1707,1067),scale=1.5):
    lines=[TEXT[l][i] for i in range(6) for l in ('en','te','zh','hi','es','ta')]
    doc=('<!doctype html><html><head><meta charset="utf-8"><style>body{margin:24px 40px;background:#fff;color:#222;'
         'font-family:"Segoe UI","Microsoft YaHei","Nirmala UI";font-size:13px;line-height:1.75;column-count:2}</style></head><body>'
         +''.join(f'<div>{html.escape(l)}</div>' for l in lines)+'</body></html>')
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
        src=Path(profile)/'s.html';png=Path(profile)/'s.png';src.write_text(doc,encoding='utf-8')
        subprocess.run([str(EDGE),'--headless=new','--disable-gpu','--hide-scrollbars','--no-first-run','--disable-extensions',
                        f'--user-data-dir={profile}',f'--force-device-scale-factor={scale}',f'--window-size={css[0]},{css[1]}',f'--screenshot={png}',
                        src.as_uri()],capture_output=True,timeout=180,check=True)
        return png.read_bytes()


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--threads',type=int,default=2);ap.add_argument('--te',default='PaddlePaddle--te_PP-OCRv5_mobile_rec');ap.add_argument('--det-pixels',type=int,default=409600)
    ap.add_argument('--css',type=int,nargs=2,default=[1707,1067]);ap.add_argument('--scale',type=float,default=1.5)
    args=ap.parse_args()
    import cv2,numpy as np
    raw=large_screen(args.css,args.scale);h,w=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR).shape[:2]
    rec={'general':'PaddlePaddle--PP-OCRv6_tiny_rec','hi':'PaddlePaddle--devanagari_PP-OCRv5_mobile_rec','ta':'PaddlePaddle--ta_PP-OCRv5_mobile_rec','te':args.te}
    base={'consent':True,'runtime':str(ROOT/'.tools/ocr-runtime/onnxruntime.dll'),'mode':'screen','route':'auto','threads':args.threads,'det_pixels':args.det_pixels,
          'detector':str(M/'PaddlePaddle--PP-OCRv5_mobile_det/inference.onnx'),
          'recognizers':{k:{'model':str(M/v/'inference.onnx'),'dictionary':str(M/v/'ctc-dictionary.json')} for k,v in rec.items()},
          'image_base64':base64.b64encode(raw).decode('ascii')}
    p=subprocess.Popen([str(ROOT/'build/engine/Release/lens-ocr.exe'),'--serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                       stderr=subprocess.DEVNULL,text=True,encoding='utf-8',bufsize=1)
    proc=psutil.Process(p.pid);steps=[]

    def sample(name,r=None):
        mi=proc.memory_info();row={'step':name,'working_set_mb':mi.wset/1e6,'private_mb':mi.private/1e6,'peak_working_set_mb':mi.peak_wset/1e6}
        if r is not None:row.update({'ok':r.get('ok'),'lines':len(r.get('lines',[])),'timing_ms':r.get('timing_ms'),
                                     'recognizers':sorted({l['recognizer'] for l in r.get('lines',[])})})
        steps.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)

    def ask(req):p.stdin.write(json.dumps(req)+'\n');p.stdin.flush();return json.loads(p.stdout.readline())
    time.sleep(0.5);sample('started')
    sample('full_1',ask(base))
    sample('band',ask({**base,'region':[0,h//3,w,h//6],'drop_edge_boxes':True}))
    sample('full_2',ask(base))
    time.sleep(3);sample('idle_3s')
    p.stdin.close();p.wait(timeout=60)
    report={'created_utc':datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),'screen':[w,h],'device_scale':args.scale,'threads':args.threads,'det_pixels':args.det_pixels,
            'te_recognizer':args.te,'steps':steps,'peak_working_set_mb':max(s['peak_working_set_mb'] for s in steps)}
    out=ROOT/'reports/ocr-screens'/f"ocr-memory-{report['created_utc']}.json";out.write_text(json.dumps(report,ensure_ascii=False,indent=1),encoding='utf-8')
    print('peak',round(report['peak_working_set_mb']),'MB',out)


if __name__=='__main__':main()
