"""A time-bounded real native ASR/store/retrieval workload, not simulated timings."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import statistics
import subprocess
import sys
import threading
import shutil
import time
import psutil

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.benchmark import percentile,digest


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--seconds',type=int,default=1800)
    args=parser.parse_args()
    folder=ROOT/'artifacts'/('endurance-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    folder.mkdir(parents=True)
    runtime=folder/'runtime';runtime.mkdir()
    for p in (ROOT/'build/engine/Release').iterdir():
        if p.suffix.lower() in ('.exe','.dll'):shutil.copy2(p,runtime/p.name)
    exe=runtime/'lens-engine.exe'
    initial_engine_sha=digest(exe)
    proc=subprocess.Popen([str(exe),'--db',str(folder/'memory.db')],stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',bufsize=1)
    samples=[];cycles=[];failures=[];done=threading.Event();start=time.perf_counter()
    timestamp=datetime.now(timezone.utc).isoformat()
    request={'op':'ingest_audio','consent':True,'id':'endurance-public-jfk',
             'audio':str(ROOT/'third_party/whisper.cpp/samples/jfk.wav'),
             'model':str(ROOT/'models/ggerganov--whisper.cpp/ggml-base-q5_1.bin'),'language':'en',
             'timestamp':timestamp,'device':'windows-development-fixture','kind':'public_audio_import',
             'provenance':'public JFK audio, repeated native workload; no private capture'}
    def send(j):
        proc.stdin.write(json.dumps(j)+'\n');proc.stdin.flush()
        line=proc.stdout.readline()
        if not line:raise RuntimeError('native process ended unexpectedly')
        result=json.loads(line)
        if not result.get('ok'):raise RuntimeError(str(result))
        return result
    def workload():
        try:
            while time.perf_counter()-start<args.seconds:
                tick=time.perf_counter()
                ingest=send(request)
                search=send({'op':'search','query':'country'})
                if search['not_found'] or search['sources'][0]['text']!=ingest['transcript']['text']:
                    raise RuntimeError('source retrieval mismatch')
                cycles.append((time.perf_counter()-tick)*1000)
                if len(cycles)%25==0:print('completed_cycles',len(cycles),'elapsed_s',round(time.perf_counter()-start),flush=True)
                time.sleep(.2)
            stats=send({'op':'stats'})
            if stats['source_count']!=1:raise RuntimeError('repeated observation deduplication failed')
        except Exception as exc:failures.append(str(exc))
        finally:
            try:proc.stdin.close()
            except OSError:pass
            done.set()
    worker=threading.Thread(target=workload,daemon=True);worker.start()
    while proc.poll() is None:
        rss=private=peak_rss=peak_commit=0;count=0
        try:
            root=psutil.Process(proc.pid)
            for p in [root]+root.children(recursive=True):
                try:
                    m=p.memory_info();count+=1;rss+=m.rss;private+=m.private
                    peak_rss+=m.peak_wset;peak_commit+=m.peak_pagefile
                except psutil.Error:pass
        except psutil.Error:pass
        samples.append({'elapsed_s':time.perf_counter()-start,'tree_rss':rss,'tree_private':private,
                        'sum_live_process_peak_wset':peak_rss,'sum_live_process_peak_commit':peak_commit,'processes':count})
        if time.perf_counter()-start>args.seconds+180:
            failures.append('workload timeout');proc.kill();break
        time.sleep(.02)
    worker.join(timeout=10)
    stderr=proc.stderr.read()
    elapsed=time.perf_counter()-start
    report={'duration_requested_s':args.seconds,'duration_measured_s':elapsed,'completed_cycles':len(cycles),
            'failure_count':len(failures),'failures':failures,'exit_code':proc.returncode,
            'p95_cycle_ms':percentile(cycles),'average_cycle_ms':statistics.mean(cycles) if cycles else None,
            'peak_sampled_tree_wset_bytes':max((x['tree_rss'] for x in samples),default=None),
            'peak_sampled_tree_private_bytes':max((x['tree_private'] for x in samples),default=None),
            'peak_observed_os_wset_bytes':max((x['sum_live_process_peak_wset'] for x in samples),default=None),
            'peak_observed_os_commit_bytes':max((x['sum_live_process_peak_commit'] for x in samples),default=None),
            'maximum_observed_process_count':max((x['processes'] for x in samples),default=None),
            'sampling_interval_ms':20,'sample_count':len(samples),'engine_sha256':initial_engine_sha,
            'binary_unchanged':digest(exe)==initial_engine_sha,'isolated_runtime_directory':str(runtime),
            'fixture':'public JFK 11-second WAV, model unloaded/reloaded for each cycle',
            'model_sha256':digest(ROOT/'models/ggerganov--whisper.cpp/ggml-base-q5_1.bin'),
            'stderr_empty':not stderr,'passes_requested_duration':elapsed>=args.seconds and not failures and proc.returncode==0}
    (folder/'samples.json').write_text(json.dumps(samples),encoding='utf-8')
    (ROOT/'reports/windows-endurance.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    raise SystemExit(0 if report['passes_requested_duration'] else 1)


if __name__=='__main__':main()
