"""Fit the answer/abstain rule on v1 (dev + inspected diagnosis split) with 2-fold cross-validation.

Never reads the sealed holdout. Rule family (two bounded, monotone parameters, no per-language knobs):
  AND: answer iff full literal match OR (rerank >= a AND centered_cosine >= b)
  OR : answer iff full literal match OR rerank >= a OR centered_cosine >= b
Objective: maximize top-1 correct evidence subject to unanswerable rejection >= 0.95 on the fitting fold
(falls back to best balanced accuracy when the constraint is unreachable). Reports out-of-fold results.
Usage: .venv\\Scripts\\python.exe scripts/calibrate_abstention.py <rows.json> [mode]
"""
import json
import sys
import numpy as np


def evaluate(rows,form,a,b):
    pos=[r for r in rows if r['relevant']];neg=[r for r in rows if not r['relevant']]
    def answers(r):
        if r['full_keyword_match']:return True
        ra=r['best_rerank'] is not None and r['best_rerank']>=a;cb=r['best_semantic'] is not None and r['best_semantic']>=b
        return (ra and cb) if form=='AND' else (ra or cb)
    return {'reject':sum(not answers(r) for r in neg)/len(neg),'top1':sum(1 for r in pos if r['rank']==1 and answers(r))/len(pos),
            'wrong_abstain':sum(not answers(r) for r in pos)/len(pos),'wrong_answer':sum(answers(r) for r in neg)/len(neg)}


def fit(rows):
    best=None
    for form in ('AND','OR'):
        for a in np.arange(-4,4.01,0.1):
            for b in np.arange(0.20,0.60,0.005):
                m=evaluate(rows,form,a,b);ok=m['reject']>=0.95
                key=(ok,m['top1'] if ok else (m['reject']+1-m['wrong_abstain'])/2)
                if best is None or key>best[0]:best=(key,form,round(float(a),2),round(float(b),3),m)
    return best[1:]


def main():
    rows=json.load(open(sys.argv[1],encoding='utf-8'));mode=sys.argv[2] if len(sys.argv)>2 else 'hybrid_rerank_c'
    rows=[r for r in rows if r['mode']==mode]
    out={'mode':mode,'folds':{}}
    for fit_split,eval_split in (('dev','test'),('test','dev')):
        form,a,b,m=fit([r for r in rows if r['split']==fit_split])
        out['folds'][f'fit_{fit_split}']={'rule':[form,a,b],'fit':m,'out_of_fold':evaluate([r for r in rows if r['split']==eval_split],form,a,b)}
    form,a,b,m=fit(rows)
    out['final']={'rule':[form,a,b],'fit_on':'v1 dev + inspected test','in_sample':m}
    print(json.dumps(out,indent=1))


if __name__=='__main__':main()
