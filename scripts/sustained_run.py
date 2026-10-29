"""Sustained performance run (docs/LENS_V1_SPEC.md §15, demonstration 10): the complete background system under a
realistic load for N minutes, measured as the whole process tree.

Real components: lens-agent (consent on) → lens-observer (UI Automation, plus OCR fallback through the persistent
lens-ocr worker) → lens-engine (encrypted store, periodic consolidation and indexing). Load: an invisible synthetic text
window whose content changes every few seconds (UIA path) and an invisible GDI-painted window (OCR path) the observer
alternates between, plus a recall every 30 s. Nothing is shown on screen; no user window is observed.
Samples every 5 s: tree working set and private bytes (sum over agent + children), CPU seconds. Reports peak, the
growth between the first and last quarter (leak signal), crashes, records stored, recall latency, and the idle tree
after load stops. Writes reports/perf/sustained-<utc>.json.
Usage: .venv\\Scripts\\python.exe scripts/sustained_run.py [--minutes 30] [--snapshot]
(--snapshot runs from a temporary copy of build/engine/Release, so builds by other work are not blocked.)
CPU is accumulated per process across the agent restarts at each phase switch.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import psutil
ROOT=Path(__file__).resolve().parents[1]
REL=ROOT/'build/engine/Release'
sys.path.insert(0,str(ROOT/'tests'))
from test_agent import Pipe
WORDS='vendor contract renewal budget meeting roadmap hiring invoice launch review schedule partner design finance report'.split()


def tree(pid):
    try:procs=[psutil.Process(pid)]+psutil.Process(pid).children(recursive=True)
    except psutil.Error:return None
    ws=priv=cpu=0;names={};cpu_names={};priv_names={}
    for p in procs:
        try:
            m=p.memory_info();c=p.cpu_times();ws+=m.rss;priv+=m.private;cpu+=c.user+c.system;names[p.name()]=names.get(p.name(),0)+m.rss
            cpu_names[p.name()]=cpu_names.get(p.name(),0)+c.user+c.system;priv_names[p.name()]=priv_names.get(p.name(),0)+m.private
        except psutil.Error:pass
    return ws,priv,cpu,names,cpu_names,priv_names


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--minutes',type=float,default=30)
    ap.add_argument('--snapshot',action='store_true',help='run from a temporary copy of the binaries, so builds by other work are not blocked')
    args=ap.parse_args()
    global REL
    snapshot=None
    if args.snapshot:
        snapshot=Path(tempfile.mkdtemp(prefix='lens-sustained-bin-'));shutil.copytree(REL,snapshot/'Release',ignore=shutil.ignore_patterns('*.lib','*.pdb'));REL=snapshot/'Release'
    report_snapshot={'binaries':'snapshot copy' if snapshot else 'build/engine/Release',
                     'observer_sha256':__import__('hashlib').sha256((REL/'lens-observer.exe').read_bytes()).hexdigest()}
    rng=random.Random(20261027);report={'created_utc':datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),'minutes':args.minutes}
    text_app=subprocess.Popen([str(REL/'lens-observer-testapp.exe'),'--invisible','Sustained run notes','Synthetic label','Synthetic start'],
                              stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
    paint_app=subprocess.Popen([str(REL/'lens-observer-testapp.exe'),'--invisible','--paint','Synthetic canvas 0','Canvas'],
                               stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
    assert text_app.stdout.readline().strip()=='ready' and paint_app.stdout.readline().strip()=='ready'
    with tempfile.TemporaryDirectory() as tmp:
        name=f'lens-sustained-{uuid.uuid4().hex[:8]}'
        (Path(tmp)/'config.json').write_text(json.dumps({'observer':{'min_interval_ms':1000,'max_interval_ms':8000},'consolidate_minutes':5}),encoding='utf-8')
        def start_agent(follow):
            a=subprocess.Popen([str(REL/'lens-agent.exe'),'--data-dir',tmp,'--root',str(ROOT),'--pipe-name',name,'--observer-follow',f'pid:{follow}'],
                               stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            p=Pipe(name);p.ask({'op':'set_consent','observe_screen':True});return a,p
        agent,pipe=start_agent(text_app.pid)
        cpu_total={};cpu_prev={};samples=[];recalls=[];crashes=0;stop=False;t0=time.time();end=t0+args.minutes*60;phase_ocr=False;last_switch=t0
        def load():
            k=0
            while not stop:
                k+=1;text=' '.join(rng.choice(WORDS) for _ in range(12))
                text_app.stdin.write(f'set Synthetic update {k}: {text}\n');text_app.stdin.flush();text_app.stdout.readline()
                paint_app.stdin.write(f'set Synthetic canvas {k}: {text[:40]}\n');paint_app.stdin.flush();paint_app.stdout.readline()
                time.sleep(rng.uniform(3,8))
        loader=threading.Thread(target=load,daemon=True);loader.start()
        next_recall=time.time()+30
        while time.time()<end:
            if agent.poll() is not None:crashes+=1;pipe.close();agent,pipe=start_agent(paint_app.pid if phase_ocr else text_app.pid)
            if time.time()-last_switch>300:  # alternate UIA and OCR phases every 5 minutes (agent restart = new follow target)
                pipe.ask({'op':'shutdown'});pipe.close();agent.wait(timeout=60);phase_ocr=not phase_ocr;last_switch=time.time()
                agent,pipe=start_agent(paint_app.pid if phase_ocr else text_app.pid)
            s=tree(agent.pid)
            if s:
                # CPU accumulates per process name across agent restarts (a counter that went down is a new process).
                for n,c in s[4].items():cpu_total[n]=cpu_total.get(n,0)+(c-cpu_prev[n] if c>=cpu_prev.get(n,0) and n in cpu_prev else c)
                cpu_prev.clear();cpu_prev.update(s[4])
                samples.append({'t':round(time.time()-t0,1),'ws':s[0],'private':s[1],'cpu':sum(cpu_total.values()),'phase':'ocr' if phase_ocr else 'uia',
                                'by_process':s[3]})
            if time.time()>=next_recall:
                q=' '.join(rng.sample(WORDS,3));a=time.perf_counter();r=pipe.ask({'op':'recall','query':q,'limit':5})
                recalls.append({'ms':(time.perf_counter()-a)*1000,'ok':r.get('ok',False)});next_recall=time.time()+30
            time.sleep(5)
        stop=True;loader.join(timeout=20)
        status=pipe.ask({'op':'status'});stats=pipe.ask({'op':'stats'})
        time.sleep(75)  # retrieval models unload after 60 s idle; OCR worker after 30 s
        idle=tree(agent.pid)
        pipe.ask({'op':'shutdown'});pipe.close();agent.wait(timeout=60)
    for app in (text_app,paint_app):app.stdin.write('quit\n');app.stdin.flush();app.wait(timeout=10)
    ws=[s['ws'] for s in samples];pv=[s['private'] for s in samples];q=max(1,len(samples)//4)
    report.update({'samples':len(samples),'crashes':crashes,'peak_working_set_bytes':max(ws),'peak_private_bytes':max(pv),
        'median_working_set_bytes':statistics.median(ws),'first_quarter_median_ws':statistics.median(ws[:q]),'last_quarter_median_ws':statistics.median(ws[-q:]),
        'cpu_seconds':samples[-1]['cpu'] if samples else None,'mean_cpu_percent_of_one_core':(100*samples[-1]['cpu']/(samples[-1]['t'] or 1)) if samples else None,
        'mean_cpu_percent_by_process':{n:round(100*c/(samples[-1]['t'] or 1),2) for n,c in cpu_total.items()} if samples else None,
        'peak_working_set_by_process':{n:max(x['by_process'].get(n,0) for x in samples) for n in {n for x in samples for n in x['by_process']}},
        'idle_after_load':{'ws':idle[0],'private':idle[1],'by_process':idle[3],'private_by_process':idle[5]} if idle else None,**report_snapshot,
        'recalls':len(recalls),'recall_ok':sum(r['ok'] for r in recalls),'recall_ms_p50':statistics.median([r['ms'] for r in recalls]) if recalls else None,
        'recall_ms_p95':sorted(r['ms'] for r in recalls)[int(0.95*(len(recalls)-1))] if recalls else None,
        'final_status':status,'final_stats':{k:stats.get(k) for k in ('source_count','embedded_sources','compressed_sources','schema_version')},
        'within_500MB':max(ws)<=500_000_000 and max(pv)<=500_000_000,'trace':samples})
    if snapshot:shutil.rmtree(snapshot,ignore_errors=True)
    out=ROOT/'reports/perf';out.mkdir(parents=True,exist_ok=True)
    path=out/f"sustained-{report['created_utc']}.json";path.write_text(json.dumps(report,indent=1),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('trace','final_status')},indent=1));print(path)


if __name__=='__main__':main()
