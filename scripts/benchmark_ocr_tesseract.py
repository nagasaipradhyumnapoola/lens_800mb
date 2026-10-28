"""Comparison only: Tesseract 5.4.0 (Apache-2.0, LSTM tessdata_best) on the same OCR screen sets and metric.

Tesseract is the UB-Mannheim Windows build extracted (not installed) into .tools/tesseract; tessdata_best models
(Apache-2.0) at the commit in .tools/tessdata_best/COMMIT. Language selection is oracle (the screen's language plus
eng, which reads the Latin/digit tokens such as "B12"; mixed screens get all their languages), page segmentation
--psm 3, OMP_THREAD_LIMIT=2 to match the Lens worker's 2 threads. Metric as scripts/benchmark_ocr_native.py (page CER
on NFC text, ZWNJ/ZWJ removed, empty lines dropped). Wall time per screen includes process start and model load; peak
working set is sampled every 10 ms. Owner approval to run the binary: 2026-10-28.
Output: reports/ocr-screens/ocr-tesseract-<set>-<UTC>.json
Usage: .venv\\Scripts\\python.exe scripts/benchmark_ocr_tesseract.py [--set dev|heldout] [--only te,ar]
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import numpy as np
import psutil
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from benchmark_ocr_native import SETS,metric_text
from ocr_reference import edit
EXE=ROOT/'.tools/tesseract/tesseract.exe'
DATA=ROOT/'.tools/tessdata_best'
LANG={'en':'eng','zh':'chi_sim','es':'spa','hi':'hin','ta':'tam','te':'tel','fr':'fra','pt':'por','de':'deu','id':'ind','ru':'rus',
      'ja':'jpn','ar':'ara','ur':'urd','bn':'ben','mr':'mar','gu':'guj'}
MIXED={'mixed-global':['ru','ja','fr','bn','de','gu','pt','mr','id','en'],'mixed':['te','en','hi','zh','ta','es']}


def langs(sc):
    if sc['language']!='mixed':return '+'.join(dict.fromkeys([LANG[sc['language']],'eng']))
    key='mixed-global' if sc['name'].startswith('mixed-global') else 'mixed'
    return '+'.join(LANG[l] for l in MIXED[key])


def run(image,lang):
    t=time.perf_counter();peak=0
    p=subprocess.Popen([str(EXE),str(image),'stdout','--tessdata-dir',str(DATA),'-l',lang,'--psm','3'],stdout=subprocess.PIPE,
                       stderr=subprocess.DEVNULL,env={**os.environ,'OMP_THREAD_LIMIT':'2'})
    proc=psutil.Process(p.pid)
    while p.poll() is None:
        try:peak=max(peak,proc.memory_info().peak_wset)
        except psutil.Error:pass
        time.sleep(0.01)
    out=p.stdout.read().decode('utf-8');p.stdout.close()
    return out,(time.perf_counter()-t)*1000,peak


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--set',choices=list(SETS),default='dev');ap.add_argument('--only');args=ap.parse_args()
    manifest=json.loads(SETS[args.set].read_text(encoding='utf-8'));rows=[]
    for sc in manifest['scenarios']:
        if args.only and sc['language'] not in args.only.split(','):continue
        lang=langs(sc);text,ms,peak=run(ROOT/sc['image'],lang)
        pred=[metric_text(l) for l in text.splitlines() if metric_text(l)];gt=[metric_text(l) for l in sc['lines']]
        page=edit('\n'.join(gt),'\n'.join(pred))/max(1,len('\n'.join(gt)))
        line_cer=[min((edit(g,p)/max(1,len(g)) for p in pred),default=1.0) for g in gt]
        rows.append({'name':sc['name'],'language':sc['language'],'tesseract_langs':lang,'page_cer':page,
                     'line_accuracy':float(np.mean([c<=0.05 for c in line_cer])),'wall_ms':ms,'peak_working_set_bytes':peak,'pred':pred})
        print(f"{sc['name']:22s} pageCER {page:.3f} {ms:.0f} ms peak {peak/1e6:.0f} MB",flush=True)
    by={}
    for r in rows:by.setdefault(r['language'],[]).append(r)
    summary={k:{'page_cer':float(np.mean([r['page_cer'] for r in v])),'line_accuracy':float(np.mean([r['line_accuracy'] for r in v])),
                'wall_ms_p50':float(np.median([r['wall_ms'] for r in v]))} for k,v in by.items()}
    summary['peak_working_set_mb_max']=max(r['peak_working_set_bytes'] for r in rows)/1e6
    version=subprocess.run([str(EXE),'--version'],capture_output=True,text=True).stdout.splitlines()[0]
    report={'created_utc':datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),'engine':version,'set':args.set,'only':args.only,
            'manifest_sha256':hashlib.sha256(SETS[args.set].read_bytes()).hexdigest(),'tessdata_best_commit':(DATA/'COMMIT').read_text().strip(),
            'exe_sha256':hashlib.sha256(EXE.read_bytes()).hexdigest(),'psm':3,'threads':2,
            'metric':'page CER on NFC text, ZWNJ/ZWJ removed, empty lines dropped','summary':summary,'rows':rows}
    out=ROOT/'reports/ocr-screens'/f"ocr-tesseract-{args.set}-{report['created_utc']}.json";out.write_text(json.dumps(report,ensure_ascii=False,indent=1),encoding='utf-8')
    print(json.dumps({k:round(v['page_cer']*100,2) if isinstance(v,dict) else v for k,v in summary.items()}));print(out)


if __name__=='__main__':main()
