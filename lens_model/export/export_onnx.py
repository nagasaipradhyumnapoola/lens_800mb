"""Export a trained Lens-Core cross-mode checkpoint to ONNX (FP32), then quantize it to INT8 for CPU deployment.

Step 1 (training venv): FP32 export with dynamic batch/sequence axes, inputs input_ids + attention_mask, output logits.
Step 2 (runtime venv, --quantize): dynamic INT8, per-channel weights; MatMuls whose quantization error exceeds a bound are
kept FP32 (the FFN-output activation outliers found in MiniLMv2 models, docs/VERIFICATION.md). Parity against FP32 is
measured on the held-out pairs and written next to the model; the engine's one-sequence-per-inference rule applies.
Usage:
  .venv-train\\Scripts\\python.exe lens_model/export/export_onnx.py --checkpoint artifacts/lens-model/checkpoints/answerability-v0
  .venv\\Scripts\\python.exe lens_model/export/export_onnx.py --quantize artifacts/lens-model/onnx/answerability-v0
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
ROOT=Path(__file__).resolve().parents[2]


def export(checkpoint):
    import torch
    from transformers import AutoModelForSequenceClassification,AutoTokenizer
    out=ROOT/'artifacts/lens-model/onnx'/checkpoint.name;out.mkdir(parents=True,exist_ok=True)
    model=AutoModelForSequenceClassification.from_pretrained(checkpoint).eval();tok=AutoTokenizer.from_pretrained(checkpoint)
    enc=tok(['example question'],['example evidence sentence.'],return_tensors='pt')
    torch.onnx.export(model,(enc['input_ids'],enc['attention_mask']),str(out/'model.onnx'),input_names=['input_ids','attention_mask'],
                      output_names=['logits'],dynamic_axes={'input_ids':{0:'batch',1:'sequence'},'attention_mask':{0:'batch',1:'sequence'},
                      'logits':{0:'batch'}},opset_version=17,dynamo=False)
    for f in ('tokenizer.json','config.json','tokenizer_config.json','special_tokens_map.json'):
        if (checkpoint/f).exists():shutil.copy2(checkpoint/f,out/f)
    print(out/'model.onnx')


def quantize(folder,max_pairs=600,bound=0.15):
    import numpy as np
    import onnx
    import onnxruntime as ort
    from onnxruntime.quantization import QuantType,quantize_dynamic
    from tokenizers import Tokenizer
    tok=Tokenizer.from_file(str(folder/'tokenizer.json'));tok.enable_truncation(192,strategy='longest_first')
    rows=[json.loads(l) for l in (ROOT/'artifacts/lens-model/answerability-v0/xquad_heldout.jsonl').open(encoding='utf-8')][:max_pairs//2]
    rows+=[json.loads(l) for l in (ROOT/'artifacts/lens-model/answerability-v0/indicqa_heldout.jsonl').open(encoding='utf-8')][:max_pairs//2]
    def run(path,subset=rows):
        s=ort.InferenceSession(str(path),providers=['CPUExecutionProvider'])
        out=[]
        for r in subset:
            ids=np.array([tok.encode(r['q'],r['e']).ids],dtype=np.int64)
            out.append(float(s.run(None,{'input_ids':ids,'attention_mask':np.ones_like(ids)})[0][0][0]))
        return np.array(out)
    ref=run(folder/'model.onnx');probe=rows[:40];ref_probe=ref[:40]
    graph=onnx.load(str(folder/'model.onnx'),load_external_data=False)
    inits={t.name for t in graph.graph.initializer}
    mm=[n.name for n in graph.graph.node if n.op_type=='MatMul' and any(i in inits for i in n.input)]
    tmp=folder/'probe_int8.onnx';sensitive=[]
    for name in mm:  # quantize one MatMul at a time; keep FP32 the ones that move logits by more than the bound
        quantize_dynamic(str(folder/'model.onnx'),str(tmp),weight_type=QuantType.QInt8,per_channel=True,op_types_to_quantize=['MatMul'],
                         nodes_to_exclude=[x for x in mm if x!=name])
        err=float(np.abs(run(tmp,probe)-ref_probe).max())
        if err>bound:sensitive.append({'node':name,'max_logit_error':err})
    tmp.unlink(missing_ok=True)
    final=folder/'model_int8.onnx'
    quantize_dynamic(str(folder/'model.onnx'),str(final),weight_type=QuantType.QInt8,per_channel=True,op_types_to_quantize=['MatMul','Gather'],
                     nodes_to_exclude=[x['node'] for x in sensitive])
    q=run(final);agree=float(((q>0)==(ref>0)).mean())
    corr=float(np.corrcoef(q,ref)[0,1])
    meta={'fp32_sha256':hashlib.sha256((folder/'model.onnx').read_bytes()).hexdigest(),'int8_sha256':hashlib.sha256(final.read_bytes()).hexdigest(),
          'int8_bytes':final.stat().st_size,'kept_fp32':sensitive,'parity_pairs':len(rows),'sign_agreement':agree,'pearson':corr,
          'max_abs_logit_error':float(np.abs(q-ref).max()),'mean_abs_logit_error':float(np.abs(q-ref).mean())}
    (folder/'quantization-report.json').write_text(json.dumps(meta,indent=1),encoding='utf-8');print(json.dumps(meta,indent=1))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--checkpoint',type=Path);ap.add_argument('--quantize',type=Path);args=ap.parse_args()
    if args.checkpoint:export(args.checkpoint)
    if args.quantize:quantize(args.quantize)


if __name__=='__main__':main()
