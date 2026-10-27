"""Record measured standalone-native crop recognition scores and memory."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.benchmark_ocr import CASES
from scripts.benchmark import write_csv
from benchmarks.metrics import error_rate
from benchmarks.process import measure


def main():
    rows=[]
    for lang,script,model,text,_font in CASES:
        folder=ROOT/'models'/('PaddlePaddle--'+model)
        req={'consent':True,'runtime':str(ROOT/'.tools/ocr-runtime/onnxruntime.dll'),'model':str(folder/'inference.onnx'),
             'dictionary':str(folder/'ctc-dictionary.json'),'image':str(ROOT/'artifacts/ocr-smoke'/(lang+'.png'))}
        result=measure([ROOT/'build/engine/Release/lens-ocr.exe'],cwd=ROOT,input_data=(json.dumps(req)+'\n').encode())
        prediction='';failure=None
        try:
            if result['exit_code']!=0:raise RuntimeError('native exit '+str(result['exit_code']))
            prediction=json.loads(result['stdout'])['text']
        except Exception as exc:failure=str(exc)
        ce,cc=error_rate(text,prediction,chars=True)
        rows.append({'language':lang,'script':script,'model':model,'sample_count':1,'cer':ce/cc,
                     'exact_match':text==prediction,'failure':failure,'fixture_kind':'synthetic text crop',
                     'max_observed_wset_bytes':result['sum_observed_process_peak_wset_bytes'],
                     'max_observed_commit_bytes':result['sum_observed_process_peak_commit_bytes'],
                     'wall_ms':result['wall_ms'],'scope':'native text recognition; no screenshot detector',
                     'certification':'EXPERIMENTAL_SYNTHETIC_SMOKE_ONLY'})
        (ROOT/'artifacts'/('native-ocr-'+lang+'.json')).write_text(json.dumps({'reference':text,'hypothesis':prediction,
                 'result':result},ensure_ascii=False,indent=2),encoding='utf-8')
    for lang,script in [('ta','Tamil'),('te','Telugu'),('bn','Bengali'),('kn','Kannada'),('ml','Malayalam')]:
        rows.append({k:({'language':lang,'script':script,'sample_count':0,'failure':'NOT TESTED','certification':'PENDING'}.get(k)) for k in rows[0]})
    write_csv(ROOT/'reports/ocr-by-script.csv',rows)
    (ROOT/'reports/native-ocr-results.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    print(json.dumps(rows[:4],indent=2))


if __name__=='__main__':main()
