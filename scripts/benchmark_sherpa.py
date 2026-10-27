"""Native, upstream Dolphin CTC comparison after Whisper quality failures. No cloud APIs."""
import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import sys
import soundfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from benchmarks.process import measure
from benchmarks.metrics import error_rate
from scripts.benchmark import digest,percentile,write_csv


def main():
    p=argparse.ArgumentParser();p.add_argument('--holdout',action='store_true');args=p.parse_args()
    runtime=ROOT/'.tools/sherpa-runtime/sherpa-onnx-v2.0.0-win-x64-shared-MD-Release-no-tts'
    os.environ['PATH']=str(runtime/'lib')+os.pathsep+os.environ['PATH']
    exe=runtime/'bin/sherpa-onnx-offline.exe'
    locks=json.loads((ROOT/'third_party/sherpa-reference-lock.json').read_text())
    weight=next(x for x in locks['models'] if x['filename']=='model.int8.onnx')
    tokens=next(x for x in locks['models'] if x['filename']=='tokens.txt')
    if digest(ROOT/weight['path'])!=weight['sha256']:raise RuntimeError('Dolphin hash mismatch')
    manifest='fleurs-priority-holdout.json' if args.holdout else 'fleurs-smoke.json'
    samples=json.loads((ROOT/'data/fixtures'/manifest).read_text(encoding='utf-8'))['samples']
    samples=[x for x in samples if x['language'] in ['zh','hi']]
    folder=ROOT/'artifacts'/('sherpa-holdout' if args.holdout else 'sherpa-smoke');folder.mkdir(exist_ok=True)
    rows=[]
    for sample in samples:
        # Official file CLI consumes PCM WAV. Re-encoding preserves the original fixture separately.
        audio,sr=soundfile.read(ROOT/sample['path'],dtype='float32')
        path=folder/(sample['id']+'.wav');soundfile.write(path,audio,sr,subtype='PCM_16')
        command=[exe,'--tokens='+str(ROOT/tokens['path']),'--dolphin-model='+str(ROOT/weight['path']),
                 '--num-threads=2','--provider=cpu',path]
        result=measure(command,cwd=runtime/'bin',timeout=180)
        text='';failure=None
        try:
            if result['exit_code']!=0:raise RuntimeError('native exit '+str(result['exit_code']))
            parsed=[]
            for line in (result['stdout']+'\n'+result['stderr']).splitlines():
                if line.strip().startswith('{'):
                    try:parsed.append(json.loads(line.strip()))
                    except json.JSONDecodeError:pass
            prediction=next(x for x in parsed if 'text' in x)
            text=prediction['text']
        except Exception as exc:failure=str(exc)
        we,wc=error_rate(sample['reference'],text);ce,cc=error_rate(sample['reference'],text,chars=True)
        row={'model':'dolphin-small-ctc-int8','language':sample['language'],'fixture':sample['id'],
             'word_errors':we,'reference_words':wc,'character_errors':ce,'reference_characters':cc,
             'duration_s':sample['duration_s'],'failure':failure,'model_sha256':weight['sha256'],
             'original_fixture_sha256':sample['sha256'],'pcm16_fixture_sha256':digest(path),
             'measurement':{k:v for k,v in result.items() if k not in ['stdout','stderr']}}
        rows.append(row)
        (folder/(sample['id']+'.json')).write_text(json.dumps({**row,'reference':sample['reference'],
                 'hypothesis':text,'raw':result},ensure_ascii=False,indent=2),encoding='utf-8')
        print(sample['language'],f'WER={we/wc if wc else 0:.3f}',f'CER={ce/cc if cc else 0:.3f}',failure or 'scored',flush=True)
    groups=defaultdict(list)
    for row in rows:groups[row['language']].append(row)
    summary=[]
    for lang,group in sorted(groups.items()):
        summary.append({'model':'dolphin-small-ctc-int8','language':lang,'sample_count':len(group),
                        'wer':sum(x['word_errors'] for x in group)/sum(x['reference_words'] for x in group),
                        'cer':sum(x['character_errors'] for x in group)/sum(x['reference_characters'] for x in group),
                        'failure_count':sum(bool(x['failure']) for x in group),'model_bytes':weight['bytes'],
                        'p95_latency_ms':percentile([x['measurement']['wall_ms'] for x in group]),
                        'max_observed_wset_bytes':max(x['measurement']['sum_observed_process_peak_wset_bytes'] for x in group),
                        'max_observed_commit_bytes':max(x['measurement']['sum_observed_process_peak_commit_bytes'] for x in group),
                        'certification':'REQUIRES_REVIEW' if len(group)>=100 else 'EXPERIMENTAL_SMOKE_ONLY'})
    name='sherpa-holdout' if args.holdout else 'sherpa-smoke'
    write_csv(ROOT/'reports'/(name+'-by-language.csv'),summary)
    (ROOT/'reports'/(name+'-results.json')).write_text(json.dumps({'runs':rows,'summary':summary},indent=2),encoding='utf-8')
    if any(x['failure'] for x in rows):raise SystemExit(1)


if __name__=='__main__':main()
