"""English speech input: word error rate, real-time factor and memory of the shipped route (lens-sherpa + NVIDIA
Canary-180M-flash INT8, punctuation and capitalisation on), CPU only. Public audio only:
  - FLEURS en_us priority hold-out (data/fixtures/fleurs-priority-holdout.json, 100 clips; the set whisper base was
    measured on, reports/asr-holdout-en-results.json),
  - LibriSpeech test-clean, every utterance whose sha256(id) % 10 == 0 (~10%, fixed; data/external/librispeech).
WER uses benchmarks/metrics.py (NFC, case-folded, punctuation removed; no number normalisation), the same metric as the
whisper results. No tuning: the route's settings are the shipped ones.
Usage: .venv\\Scripts\\python.exe scripts/benchmark_asr_english.py [--limit N] [--sets fleurs,librispeech]
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from benchmarks.metrics import error_rate
from benchmarks.process import measure
CANARY=ROOT/'models/csukuangfj--sherpa-onnx-nemo-canary-180m-flash-en-es-de-fr-int8'
LIBRARY=ROOT/'.tools/sherpa-runtime/sherpa-onnx-v2.0.0-win-x64-shared-MD-Release-no-tts/lib/sherpa-onnx-c-api.dll'
WORKER=ROOT/'build/engine/Release/lens-sherpa.exe'
LIBRI=ROOT/'data/external/librispeech/extracted/LibriSpeech/test-clean'


def fleurs():
    d=json.loads((ROOT/'data/fixtures/fleurs-priority-holdout.json').read_text(encoding='utf-8'))
    for s in d['samples']:
        if s['language']=='en':yield s['id'],ROOT/s['path'],s['reference'],s['duration_s']


def librispeech():
    for trans in sorted(LIBRI.glob('*/*/*.trans.txt')):
        for line in trans.read_text(encoding='utf-8').splitlines():
            uid,text=line.split(' ',1)
            if int(hashlib.sha256(uid.encode()).hexdigest(),16)%10==0:yield uid,trans.parent/(uid+'.flac'),text,None


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--limit',type=int,default=0);ap.add_argument('--sets',default='fleurs,librispeech');args=ap.parse_args()
    import soundfile
    report={'created_utc':datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),'worker':'lens-sherpa canary (shipped route)','threads':2,
            'model_sha256':{f:hashlib.sha256((CANARY/f).read_bytes()).hexdigest() for f in ('encoder.int8.onnx','decoder.int8.onnx','tokens.txt')},
            'metric':'WER on benchmarks/metrics.py normalisation (case-folded, punctuation removed, no number normalisation)','sets':{}}
    for name in args.sets.split(','):
        rows=[];errors=words=0;audio_s=wall_s=0.0;peak=0
        for i,(uid,path,ref,dur) in enumerate(fleurs() if name=='fleurs' else librispeech()):
            if args.limit and i>=args.limit:break
            if dur is None:info=soundfile.info(str(path));dur=info.frames/info.samplerate
            req={'consent':True,'model_type':'canary','language':'en','audio':str(path),'model':str(CANARY/'encoder.int8.onnx'),
                 'decoder':str(CANARY/'decoder.int8.onnx'),'tokens':str(CANARY/'tokens.txt'),'library':str(LIBRARY)}
            r=measure([WORKER],timeout=300,input_data=(json.dumps(req)+'\n').encode())
            out=json.loads(r['stdout']) if r['exit_code']==0 and r.get('stdout') else {}
            hyp=out.get('text','');e,n=error_rate(ref,hyp);errors+=e;words+=n
            secs=r['wall_ms']/1000;audio_s+=dur;wall_s+=secs
            peak=max(peak,r['sum_observed_process_peak_wset_bytes'])
            rows.append({'id':uid,'wer':e/max(1,n),'words':n,'seconds':secs,'audio_s':dur,'reference':ref,'hypothesis':hyp,'exit_code':r['exit_code']})
            print(f"{name} {i+1:4d} WER so far {errors/max(1,words):.4f} ({uid})",flush=True)
        report['sets'][name]={'utterances':len(rows),'words':words,'wer':errors/max(1,words),'failures':sum(r['exit_code']!=0 for r in rows),
                              'real_time_factor_incl_load':wall_s/max(1e-9,audio_s),'peak_working_set_bytes':peak,'rows':rows}
    out=ROOT/'reports/voice'/f"asr-english-canary-{report['created_utc']}.json";out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=1),encoding='utf-8')
    print(json.dumps({k:{x:v[x] for x in ('utterances','wer','failures','real_time_factor_incl_load','peak_working_set_bytes')} for k,v in report['sets'].items()},indent=1));print(out)


if __name__=='__main__':main()
