"""Portable-core smoke test (Linux, macOS): the real engine on synthetic data only — encrypted store with the OS keyring,
add, keyword and semantic recall with the pinned models, export, backup, restore, and a spoken reply when Kokoro is
installed. Exit code 0 only when every step passes. Usage: python3 ci/linux/smoke.py <bin folder>
"""
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[2]
BIN=Path(sys.argv[1]).resolve()
ORT=next(iter(sorted([*BIN.glob('libonnxruntime.so*'),*BIN.glob('libonnxruntime*.dylib')])),None)
# Models are not in Git: CI runs the storage, keyring, export/backup/restore and keyword steps; a checkout with the
# pinned models also runs semantic recall and a spoken reply.
if ORT and not (ROOT/'models/intfloat--multilingual-e5-small').exists():ORT=None


def lock(name,filename):
    l=json.loads((ROOT/'third_party'/name).read_text(encoding='utf-8'));return next(ROOT/f['path'] for f in l['files'] if f['filename']==filename)


def engine(db,lines,semantic=True):
    args=[str(BIN/'lens-engine'),'--db',str(db)]
    if semantic and ORT:
        head=ROOT/'models/Lens--answerability-v2c'
        args+=['--ort',str(ORT),'--embedding-model',str(lock('embedding-lock.json','onnx/model_qint8_avx512_vnni.onnx')),
               '--embedding-tokenizer',str(lock('embedding-lock.json','onnx/tokenizer.json')),'--embedding-id','smoke-e5']
        if (head/'model_int8.onnx').exists():args+=['--reranker-model',str(head/'model_int8.onnx'),'--reranker-tokenizer',str(head/'tokenizer.json')]
    p=subprocess.run(args,input=''.join(json.dumps(l)+'\n' for l in lines),capture_output=True,text=True,timeout=900)
    if p.returncode:raise SystemExit(f'engine exited {p.returncode}: {p.stderr[-500:]}')
    return [json.loads(l) for l in p.stdout.splitlines()]


def check(cond,what):
    print(('PASS ' if cond else 'FAIL ')+what,flush=True)
    if not cond:
        if os.environ.get('GITHUB_ACTIONS'):print(f'::error title=smoke test failed::{what}',flush=True)  # readable without the job log
        raise SystemExit(1)


def observer_check():
    """lens-observer on a virtual display: reads the synthetic GTK window through AT-SPI, never its password field,
    and stores only what changed after an edit."""
    obs,app=BIN/'lens-observer',BIN/'lens-observer-testapp'
    if obs.exists():  # every OS: the language labeller, and no capture without consent
        p=subprocess.run([str(obs),'--identify-language'],input='{"text":"The quarterly budget review moved to Friday afternoon."}\n',capture_output=True,text=True,timeout=60)
        check(p.returncode==0 and json.loads(p.stdout.splitlines()[0])['language']=='en','observer language labeller')
        p=subprocess.run([str(obs)],capture_output=True,text=True,timeout=60)
        check(p.returncode==2 and 'consent_required' in p.stderr,'observer refuses to start without consent')
        if sys.platform=='darwin':  # refuses without Accessibility access; with it (CI runners grant it) starts and stops cleanly
            p=subprocess.run([str(obs),'--consent'],input='',capture_output=True,text=True,timeout=60)
            refused=p.returncode==1 and 'accessibility_unavailable' in p.stderr
            ran=p.returncode==0 and '"started"' in p.stderr and '"stopped"' in p.stderr
            check(refused or ran,'observer '+('refuses without Accessibility permission' if refused else 'starts with Accessibility permission and stops on EOF'))
    if not (obs.exists() and app.exists() and shutil.which('Xvfb')):return
    import threading,time
    display=':97';x=subprocess.Popen(['Xvfb',display,'-screen','0','1280x800x24','-nolisten','tcp'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    env={**os.environ,'DISPLAY':display,'GSK_RENDERER':'cairo','GTK_A11Y':'atspi'};procs=[x]
    try:
        time.sleep(1.5)
        t=subprocess.Popen([str(app),'Observer test window','Synthetic label','Synthetic observer note: the Larkspur review is on Friday.'],
                           stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,env=env);procs.append(t)
        check(t.stdout.readline().strip()=='ready','synthetic GTK window on the virtual display')
        with tempfile.TemporaryDirectory() as tmp:
            cfg=Path(tmp)/'observer.json';cfg.write_text(json.dumps({'min_interval_ms':300,'max_interval_ms':1000,'settle_ms':0}),encoding='utf-8')
            o=subprocess.Popen([str(obs),'--consent','--follow',f'pid:{t.pid}','--config',str(cfg)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL,text=True,env=env);procs.append(o)
            records=[];threading.Thread(target=lambda:[records.append(json.loads(l)) for l in o.stdout if l.startswith('{')],daemon=True).start()
            def wait_for(word,seconds=20):
                end=time.time()+seconds
                while time.time()<end:
                    if any(word in r.get('text','') for r in records):return True
                    time.sleep(0.2)
                return False
            check(wait_for('Larkspur review is on Friday'),f"observer reads the window through AT-SPI ({len(records)} record(s))")
            check(not any('Synthetic secret' in r.get('text','') for r in records),'password field never read')
            r0=records[0];check(r0['op']=='add' and r0['kind']=='screen_observation' and r0['metadata']['capture']=='uia','observation record format')
            t.stdin.write('set Synthetic observer note: the Larkspur review is on Friday.\\nAgenda: budget and hiring.\n');t.stdin.flush();t.stdout.readline()
            check(wait_for('budget and hiring'),'an edit is captured')
            check(not any('Synthetic secret' in r.get('text','') for r in records),'password field still never read')
            o.stdin.write('stop\n');o.stdin.flush();o.wait(timeout=20)
            check(o.returncode==0,'observer stopped cleanly')
    finally:
        for p in reversed(procs):
            if p.poll() is None:p.kill()


def agent_check():
    """lens-agent as the app talks to it: the user-only Unix socket, engine pass-through, diagnostics and shutdown."""
    import socket
    with tempfile.TemporaryDirectory() as tmp:
        tmp=Path(tmp);run=tmp/'run';run.mkdir(mode=0o700)
        env={**os.environ,'LENS_RUNTIME_DIR':str(run)}
        agent=subprocess.Popen([str(BIN/'lens-agent'),'--data-dir',str(tmp/'data'),'--root',str(ROOT),'--pipe-name','lens-smoke'],
                               env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
        sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);path=str(run/'lens-smoke.sock')
        for _ in range(150):
            try:sock.connect(path);break
            except OSError:
                if agent.poll() is not None:raise SystemExit(f'agent exited {agent.returncode}: {agent.stderr.read()[-500:]}')
                import time;time.sleep(0.2)
        f=sock.makefile('rwb',buffering=0)
        def ask(req):f.write((json.dumps(req)+'\n').encode());line=f.readline();return json.loads(line) if line else {}
        s=ask({'op':'status'});check(s.get('ok') and s.get('observe_screen') is False,f"agent status over the Unix socket (semantic: {s.get('semantic','')[:40]})")
        check(oct((run/'lens-smoke.sock').stat().st_mode&0o777)=='0o600','agent socket is owner-only (0600)')
        add={'op':'add','consent':True,'id':'a1','text':'Synthetic note: the Larkspur demo is on Thursday.','language':'en',
             'timestamp':'2026-10-30T09:00:00Z','device':'linux','kind':'note','provenance':'smoke'}
        check(ask(add).get('ok') and ask({'op':'search','query':'Larkspur','limit':3})['sources'][0]['id']=='a1','agent passes add and search to the engine')
        on=ask({'op':'set_consent','observe_screen':True}).get('ok') and ask({'op':'status'})['observer_running']==(BIN/'lens-observer').exists()
        off=ask({'op':'set_consent','observe_screen':False}).get('ok') and not ask({'op':'status'})['observer_running']
        check(on and off,'agent starts the observer on consent and stops it when consent is withdrawn')
        d=ask({'op':'diagnostics'});names=[p['name'] for p in d.get('processes',[])]
        check(d.get('ok') and 'lens-agent' in names and 'lens-engine' in names and d['memory']['working_set']>0,
              f"diagnostics process tree {names}, {d.get('memory',{}).get('working_set',0)/1e6:.0f} MB working set")
        if s.get('semantic')=='verified' and (ROOT/'models/Lens--kokoro-82m-mixed-int8/model.onnx').exists():
            r=ask({'op':'speak','text':'The demo is on Thursday.'})
            check(r.get('ok') and ask({'op':'diagnostics'})['ocr_hold']==['speech'],'agent spoken reply with the governor holding OCR')
        app=BIN/'lens-app'
        if app.exists() and (sys.platform=='darwin' or shutil.which('xvfb-run')):  # the app against this agent
            # Linux: a virtual display; WebKit's bubblewrap sandbox cannot start in an unprivileged container (on outside tests).
            cmd=[str(app),'--self-test','--pipe-name','lens-smoke']
            if sys.platform!='darwin':cmd=['xvfb-run','-a']+cmd
            p=subprocess.run(cmd,capture_output=True,text=True,timeout=300,
                             env={**env,'WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS':'1','LIBGL_ALWAYS_SOFTWARE':'1'} if sys.platform!='darwin' else env)
            r=next((json.loads(l) for l in p.stdout.splitlines() if l.startswith('{')),{})
            bad=[v for v,x in r.get('views',{}).items() if x.get('errors') or x.get('exception')]
            check(r.get('ok') and not bad,f"app self-test ({'WKWebView' if sys.platform=='darwin' else 'GTK 4 + WebKitGTK'}): {len(r.get('views',{}))} views, ready {r.get('ready_ms')} ms, errors {r.get('errors')} {bad}")
        check(ask({'op':'shutdown'}).get('ok'),'agent shutdown');f.close();sock.close()
        check(agent.wait(timeout=60)==0,'agent exited cleanly');agent.stderr.close()


def main():
    notes=['Synthetic note: the Brightwater audit moved to Tuesday at 3 pm in room B12.','Synthetic note: Priya shared the revised hiring plan.']
    add=[{'op':'add','consent':True,'id':f'n{i}','text':t,'language':'en','timestamp':'2026-10-2%dT09:00:00Z'%i,'device':'linux','kind':'note','provenance':'smoke'} for i,t in enumerate(notes)]
    with tempfile.TemporaryDirectory() as tmp:
        tmp=Path(tmp);db=tmp/'m.db'
        rows=engine(db,add+[{'op':'stats'},{'op':'search','query':'Brightwater','limit':3}],semantic=False)
        check(all(r.get('ok') for r in rows),'add + stats + keyword search');check(rows[-1]['sources'][0]['id']=='n0','keyword search finds the note')
        check(db.exists() and (Path(str(db)+'.key')).exists() or any(tmp.glob('*.key')),'database and wrapped key file written')
        check(b'Brightwater' not in db.read_bytes(),'database file is encrypted (no plaintext)')
        if ORT:
            rows=engine(db,[{'op':'index','limit':16},{'op':'recall','query':'When is the audit?','limit':3}])
            check(rows[-1].get('ok') and rows[-1]['results'] and rows[-1]['results'][0]['source']['id']=='n0','semantic recall with ONNX Runtime')
        rows=engine(db,[{'op':'export','consent':True,'path':str(tmp/'export.jsonl')},{'op':'backup','path':str(tmp/'backup.db')}],semantic=False)
        check(rows[0].get('ok') and rows[0]['exported']==2,'plaintext export written');check(rows[1].get('ok'),'encrypted backup written')
        rows=engine(db,[{'op':'restore','backup_path':str(tmp/'backup.db'),'target_path':str(tmp/'restored.db')}],semantic=False)
        check(rows[0].get('ok'),'restore verified backup into a new database')
        rows=engine(tmp/'restored.db',[{'op':'search','query':'hiring','limit':3}],semantic=False)
        check(rows[0].get('ok') and rows[0]['sources'] and rows[0]['sources'][0]['id']=='n1','restored database opens and searches')
        kokoro=ROOT/'models/Lens--kokoro-82m-mixed-int8/model.onnx'
        if ORT and kokoro.exists():
            k=ROOT/'models/onnx-community--Kokoro-82M-v1.0-ONNX';m=ROOT/'models/hexgrad--misaki'
            req={'text':'Your audit moved to Tuesday at 3 pm.','voice':str(k/'voices/af_heart.bin'),'runtime':str(ORT),'model':str(kokoro),
                 'tokenizer':str(k/'tokenizer.json'),'lexicon':[str(m/'us_gold.json'),str(m/'us_silver.json')],'threads':4}
            p=subprocess.run([str(BIN/'lens-tts')],input=json.dumps(req)+'\n',capture_output=True,text=True,timeout=600)
            r=json.loads(p.stdout.splitlines()[0]) if p.stdout else {}
            check(r.get('ok') and r.get('duration_s',0)>1.5,f"spoken reply synthesised ({r.get('duration_s')} s, RTF {r.get('real_time_factor')})")
    whisper=ROOT/'models/ggerganov--whisper.cpp/ggml-base-q5_1.bin';jfk=ROOT/'third_party/whisper.cpp/samples/jfk.wav'
    if (BIN/'lens-voice').exists() and whisper.exists() and jfk.exists():  # voice capture (file input) -> engine ingest_audio
        p=subprocess.run([str(BIN/'lens-voice'),'--consent','--model',str(whisper),'--input-wav',str(jfk),'--language','en','--no-routes'],
                         capture_output=True,text=True,timeout=300)
        reqs=[json.loads(l) for l in p.stdout.splitlines() if l.startswith('{')]
        check(p.returncode==0 and reqs and all(r['op']=='ingest_audio' and r['audio_base64'] for r in reqs),f'lens-voice segments speech ({len(reqs)} segment(s))')
        with tempfile.TemporaryDirectory() as tmp:
            rows=engine(Path(tmp)/'v.db',reqs+[{'op':'search','query':'country','limit':3}],semantic=False)
            check(all(r.get('ok') for r in rows) and rows[-1]['sources'],'voice note transcribed by whisper and stored')
    observer_check()
    agent_check()
    sys.path.insert(0,str(ROOT/'ci'));import ocr_parity
    if ORT and (BIN/'lens-ocr').exists() and ocr_parity.available():
        cer,rows=ocr_parity.run(BIN/'lens-ocr',ORT)
        check(cer<=0.03,f"screen OCR, English hard-screen dev set: page CER {cer:.4f} on {len(rows)} screens, peak {max(r['peak_bytes'] for r in rows)/1e6:.0f} MB")
    print('smoke: all passed')


if __name__=='__main__':main()
