"""Native-only UTF-8 C API measurements. This never executes extracted actions."""
import json
from pathlib import Path
import sys
from collections import defaultdict
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from benchmarks.process import measure
from benchmarks.metrics import field_scores
from scripts.benchmark import write_csv,percentile

def main():
    fixtures=json.loads((ROOT/'data/fixtures/extraction-smoke.json').read_text(encoding='utf-8'))['samples']
    tools=json.loads((ROOT/'data/fixtures/extraction-tools.json').read_text(encoding='utf-8'))
    runs=[]
    for sample in fixtures:
        req={'library':str(ROOT/'models/Cactus-Compute--needle3/windows-x86_64/libneedle3.dll'),
             'weights':str(ROOT/'models/Cactus-Compute--needle3/needle3.cact'),'tools':tools,'text':sample['text']}
        result=measure([ROOT/'build/engine/Release/lens-needle.exe'],cwd=ROOT,
                       input_data=(json.dumps(req,ensure_ascii=False)+'\n').encode('utf-8'))
        actual={};failure=None;malformed=False;calls=[]
        try:
            if result['exit_code']!=0:raise RuntimeError('native process failed')
            response=json.loads(result['stdout'])
            if response.get('success') is False:failure=response.get('error') or 'model returned failure'
            calls=response.get('function_calls',[])
            if calls:
                if len(calls)!=1 or calls[0].get('name')!='save_event':failure='wrong or extra action'
                actual=calls[0].get('arguments',{})
                if isinstance(actual,str):actual=json.loads(actual)
        except json.JSONDecodeError as exc:malformed=True;failure=str(exc)
        except Exception as exc:failure=str(exc)
        r={'fixture':sample['id'],'language':sample['language'],**field_scores(sample['expected'],actual),
           'predicted_action':bool(calls),'expected_action':bool(sample['expected']),'failure':failure,
           'malformed_json':malformed,'measurement':{k:v for k,v in result.items() if k not in ('stdout','stderr')}}
        runs.append(r)
        (ROOT/'artifacts'/('native-needle-'+sample['id']+'.json')).write_text(json.dumps({**r,'raw':result},indent=2),encoding='utf-8')
        print(sample['id'],f"F1={r['f1']:.3f}",failure or 'scored',flush=True)
    groups=defaultdict(list)
    for r in runs:groups[r['language']].append(r)
    rows=[]
    for lang,group in sorted(groups.items()):
        tp,fp,fn=[sum(x[k] for x in group) for k in ('tp','fp','fn')]
        pred=sum(x['predicted_action'] for x in group)
        correct=sum(x['predicted_action'] and x['expected_action'] and not x['failure'] for x in group)
        rows.append({'variant':'needle3-full-native-cpp-utf8','language':lang,'sample_count':len(group),
                     'field_f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None,
                     'precision':tp/(tp+fp) if tp+fp else 0,'recall':tp/(tp+fn) if tp+fn else 0,
                     'safe_routing_precision':correct/pred if pred else None,
                     'malformed_json_rate':sum(x['malformed_json'] for x in group)/len(group),
                     'failure_count':sum(bool(x['failure']) for x in group),
                     'p95_latency_ms':percentile([x['measurement']['wall_ms'] for x in group]),
                     'max_observed_wset_bytes':max(x['measurement']['sum_observed_process_peak_wset_bytes'] for x in group),
                     'max_observed_commit_bytes':max(x['measurement']['sum_observed_process_peak_commit_bytes'] for x in group),
                     'certification':'EXPERIMENTAL_SYNTHETIC_SMOKE_ONLY'})
    write_csv(ROOT/'reports/extraction-native.csv',rows)
    write_csv(ROOT/'reports/extraction.csv',rows)
    (ROOT/'reports/extraction-native-results.json').write_text(json.dumps({'runs':runs,'summary':rows},indent=2),encoding='utf-8')

if __name__=='__main__':main()
