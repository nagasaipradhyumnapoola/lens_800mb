"""Portable-core smoke test (Linux, macOS): the real engine on synthetic data only — encrypted store with the OS keyring,
add, keyword and semantic recall with the pinned models, export, backup, restore, and a spoken reply when Kokoro is
installed. Exit code 0 only when every step passes. Usage: python3 ci/linux/smoke.py <bin folder>
"""
import json
import os
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
    if not cond:raise SystemExit(1)


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
        check(ask({'op':'set_consent','observe_screen':True}).get('ok') and not ask({'op':'status'})['observer_running'],'observe consent accepted; no observer on this OS yet')
        d=ask({'op':'diagnostics'});names=[p['name'] for p in d.get('processes',[])]
        check(d.get('ok') and 'lens-agent' in names and 'lens-engine' in names and d['memory']['working_set']>0,
              f"diagnostics process tree {names}, {d.get('memory',{}).get('working_set',0)/1e6:.0f} MB working set")
        if s.get('semantic')=='verified' and (ROOT/'models/Lens--kokoro-82m-mixed-int8/model.onnx').exists():
            r=ask({'op':'speak','text':'The demo is on Thursday.'})
            check(r.get('ok') and ask({'op':'diagnostics'})['ocr_hold']==['speech'],'agent spoken reply with the governor holding OCR')
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
    agent_check()
    sys.path.insert(0,str(ROOT/'ci'));import ocr_parity
    if ORT and (BIN/'lens-ocr').exists() and ocr_parity.available():
        cer,rows=ocr_parity.run(BIN/'lens-ocr',ORT)
        check(cer<=0.03,f"screen OCR, English hard-screen dev set: page CER {cer:.4f} on {len(rows)} screens, peak {max(r['peak_bytes'] for r in rows)/1e6:.0f} MB")
    print('smoke: all passed')


if __name__=='__main__':main()
