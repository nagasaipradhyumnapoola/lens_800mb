"""Fit the engine's answer gate (gate.json beside the verifier model, read by engine/store.cpp recall).

Features per question: the Lens answerability head's support logit on the top-1 evidence, the best rerank logit, the
best centred cosine and the full-literal-match flag — exactly as scripts/experiment_answer_verifier.py records them
(its .rows.json). Model: scripts/fit_answerability.py's standardised L2 logistic regression. Threshold: the lowest
probability that answers at most --target of the unanswerable questions in the fitting data.
Fitting data: the v1 dev split and the near-miss set only (the tuning rule: CLAUDE.md, docs/LENS_V1_SPEC.md §19);
v1 test and expansion are reported as validation; the sealed holdout is never read.
Usage: .venv\\Scripts\\python.exe lens_model/eval/fit_gate.py <rows.json> <model folder> [--target 0.05]
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import fit_answerability as fa
FIT={'dev','nearmiss'}


def features(r):
    return [r['verifier'][0],r['best_rerank'] if r['best_rerank'] is not None else -10.0,r['best_semantic'] or 0.0,1.0 if r['full_keyword_match'] else 0.0]


def main():
    ap=argparse.ArgumentParser();ap.add_argument('rows',type=Path);ap.add_argument('folder',type=Path);ap.add_argument('--target',type=float,default=0.05)
    args=ap.parse_args()
    rows=json.loads(args.rows.read_text(encoding='utf-8'))
    if any(r['split']=='holdout' for r in rows):raise SystemExit('holdout rows present; refusing')
    fit=[r for r in rows if r['split'] in FIT]
    X=np.array([features(r) for r in fit]);y=np.array([fa.label(r) for r in fit])
    mu,sd,w=fa.fit(X,y);t=fa.choose_threshold(fa.prob((mu,sd,w),X),fit,args.target)
    report={}
    for s in sorted({r['split'] for r in rows}):
        part=[r for r in rows if r['split']==s];report[s]=fa.evaluate(fa.prob((mu,sd,w),np.array([features(r) for r in part])),part,t)
    gate={'features':['support','best_rerank','best_semantic','full_keyword_match'],'mean':mu.tolist(),'std':sd.tolist(),'weights':w[:-1].tolist(),
          'bias':float(w[-1]),'threshold':t,'target_false_answer_rate':args.target,'fitted_on':sorted(FIT),'rows':len(fit),
          'source_rows':str(args.rows.relative_to(ROOT)) if args.rows.is_relative_to(ROOT) else str(args.rows),
          'created_utc':datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),'evaluation':report}
    (args.folder/'gate.json').write_text(json.dumps(gate,indent=1,default=float),encoding='utf-8')
    for s,m in report.items():print(f'{s:10s}',{k:(round(float(v),3) if isinstance(v,float) else v) for k,v in m.items() if v is not None})
    print('threshold',round(t,3),'->',args.folder/'gate.json')


if __name__=='__main__':main()
