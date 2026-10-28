"""Owner-consented real-screen run (docs/LENS_V1_SPEC.md §20 demonstrations 1 and 10 on the development laptop).

Runs the real lens-agent with screen-observation consent on the owner's actual desktop for N minutes while they work
normally (UIA first, OCR fallback, default privacy exclusions). The memory database lives in a temporary folder and is
deleted at the end. Only aggregate numbers are written to the repository report (reports/perf/real-screen-<utc>.json):
whole-tree RAM and CPU, observations stored/failed, UIA vs OCR share, duplicate rate, languages, recall latency.
Per-application counts and recall evidence (personal) go only to --private-out (outside the repository) for the owner.
Usage: .venv\\Scripts\\python.exe scripts/real_screen_run.py --minutes 30 --private-out <scratch file>
"""
import argparse
import collections
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import shutil
import statistics
import sys
import tempfile
import time
import uuid
import psutil
ROOT=Path(__file__).resolve().parents[1]
REL=ROOT/'build/engine/Release'
sys.path.insert(0,str(ROOT/'tests'))
from test_agent import Pipe
sys.path.insert(0,str(ROOT/'scripts'))
from sustained_run import tree
QUERIES=['what was I reading in the browser','what was I working on in the code editor','what command did I run in the terminal',
         'what document did I have open','what was the last chat about']


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--minutes',type=float,default=30);ap.add_argument('--private-out',type=Path,required=True);a=ap.parse_args()
    import subprocess
    start=datetime.now(timezone.utc);tmp=Path(tempfile.mkdtemp(prefix='lens-real-screen-'));name=f'lens-real-{uuid.uuid4().hex[:8]}'
    agent=subprocess.Popen([str(REL/'lens-agent.exe'),'--data-dir',str(tmp),'--root',str(ROOT),'--pipe-name',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    report={'created_utc':start.strftime('%Y%m%dT%H%M%SZ'),'minutes':a.minutes,'consent':'owner-approved real-screen run 2026-10-27'};private={}
    try:
        pipe=Pipe(name);assert pipe.ask({'op':'set_consent','observe_screen':True})['observe_screen']
        samples=[];statuses=[];end=time.time()+a.minutes*60;t0=time.time();cpu_total={};cpu_prev={}
        while time.time()<end:
            s=tree(agent.pid)
            if s:
                # CPU accumulates per process name, so a worker that exits (OCR, models) keeps its CPU in the total.
                for n,c in s[4].items():cpu_total[n]=cpu_total.get(n,0)+(c-cpu_prev[n] if n in cpu_prev and c>=cpu_prev[n] else c)
                cpu_prev.clear();cpu_prev.update(s[4])
                samples.append({'t':round(time.time()-t0,1),'ws':s[0],'private':s[1],'cpu':sum(cpu_total.values()),'by_process':s[3],'private_by_process':s[5]})
            if len(samples)%6==0:st=pipe.ask({'op':'status'});statuses.append({'t':round(time.time()-t0,1),**{k:st.get(k) for k in ('observed','stored','failed','observer_running')}})
            time.sleep(5)
        status=pipe.ask({'op':'status'});stats=pipe.ask({'op':'stats'})
        items=[];m=start-timedelta(minutes=1)
        while m<datetime.now(timezone.utc)+timedelta(minutes=1):  # page the timeline minute by minute (limit 100 per page)
            r=pipe.ask({'op':'timeline','limit':100,'filters':{'from':m.strftime('%Y-%m-%dT%H:%M:%SZ'),'to':(m+timedelta(minutes=1)).strftime('%Y-%m-%dT%H:%M:%SZ')}})
            items+=r.get('results') or r.get('sources') or [];m+=timedelta(minutes=1)
        obs=[x for x in items if x.get('kind')=='screen_observation'];texts=[x.get('text') or '' for x in obs]
        recalls=[]
        for q in QUERIES:
            t=time.perf_counter();r=pipe.ask({'op':'recall','query':q,'limit':3});ms=(time.perf_counter()-t)*1000
            res=r.get('results',[]);recalls.append({'ms':ms,'ok':r.get('ok'),'abstained':not res})
            private.setdefault('recall',[]).append({'query':q,'top':[{'app':x['source'].get('source_application'),'locator':x['source'].get('source_locator'),
                                                                     'quote':(x.get('evidence') or {}).get('quote','')[:160]} for x in res]})
        ws=[s['ws'] for s in samples];pv=[s['private'] for s in samples];q4=max(1,len(samples)//4)
        prov=collections.Counter((x.get('provenance') or '').split()[-1] for x in obs)
        report.update({'samples':len(samples),'peak_working_set_mb':max(ws)/2**20,'peak_private_mb':max(pv)/2**20,'median_working_set_mb':statistics.median(ws)/2**20,
            'first_quarter_median_ws_mb':statistics.median(ws[:q4])/2**20,'last_quarter_median_ws_mb':statistics.median(ws[-q4:])/2**20,
            'mean_cpu_percent_of_one_core':100*(samples[-1]['cpu']-samples[0]['cpu'])/max(1,samples[-1]['t']-samples[0]['t']),
            'mean_cpu_percent_by_process':{n:round(100*c/max(1,samples[-1]['t']),2) for n,c in cpu_total.items()},
            'peak_private_by_process_mb':{k:max(x['private_by_process'].get(k,0) for x in samples)/2**20 for k in {k for x in samples for k in x['private_by_process']}},
            'peak_by_process_mb':{k:max(s['by_process'].get(k,0) for s in samples)/2**20 for k in {k for s in samples for k in s['by_process']}},
            'observed':status.get('observed'),'stored':status.get('stored'),'failed':status.get('failed'),'screen_observations':len(obs),
            'capture_paths':dict(prov),'distinct_applications':len({x.get('source_application') for x in obs}),
            'exact_duplicate_texts':len(texts)-len(set(texts)),'languages':dict(collections.Counter(x.get('language') for x in obs)),
            'median_chars':statistics.median([len(t) for t in texts]) if texts else 0,'embedded_sources':stats.get('embedded_sources'),
            'recall_ms_p50':statistics.median([r['ms'] for r in recalls]),'recalls_answered':sum(not r['abstained'] for r in recalls),'recalls':len(recalls),
            'status_trace':statuses,'within_800MB':max(ws)<=800*2**20 and max(pv)<=800*2**20,
            'concurrent_load':'a CPU model-training job and other sessions were running on the same laptop'})
        private['applications']=dict(collections.Counter(x.get('source_application') for x in obs).most_common())
        pipe.ask({'op':'set_consent','observe_screen':False});time.sleep(75)
        idle=tree(agent.pid);report['idle_after_ws_mb']=idle[0]/2**20 if idle else None
        pipe.ask({'op':'shutdown'});pipe.close();agent.wait(timeout=60)
    finally:
        if agent.poll() is None:agent.kill()
        shutil.rmtree(tmp,ignore_errors=True);report['database_deleted']=not tmp.exists()
    out=ROOT/'reports/perf';out.mkdir(parents=True,exist_ok=True);path=out/f"real-screen-{report['created_utc']}.json"
    path.write_text(json.dumps(report,indent=1),encoding='utf-8');a.private_out.write_text(json.dumps(private,indent=1,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='status_trace'},indent=1));print(path)


if __name__=='__main__':main()
