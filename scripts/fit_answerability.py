"""Fit and cross-validate an answerability classifier on v1 + expansion rows (never on any holdout).

Label: 1 when the top-1 evidence is correct for an answerable question; 0 when the question has no valid
answer or the top-1 evidence is wrong. Features (scores only): top rerank logit, rerank margin to #2, top
centered cosine, cosine margin, keyword coverage of the top evidence, number of query units, same-language
flag, full literal match. Model: L2-regularized logistic regression (numpy). The decision threshold is chosen
on training folds for a target false-answer rate, then evaluated out of fold, reporting separately:
wrong answers to unanswerable/near-miss questions, wrong-evidence answers, and false rejections.
Usage: .venv\\Scripts\\python.exe scripts/fit_answerability.py <v1 rows.json> <expansion rows.json> [--target 0.05]
"""
import argparse
import json
import numpy as np
MODE='hybrid_rerank_rrf_c'
NAMES=['rerank','rerank_margin','cosine','cosine_margin','keyword_coverage','units','same_language','full_match']


def features(r):
    f=r.get('features') or [];top=f[0] if f else {};sec=f[1] if len(f)>1 else {}
    rr=top.get('rerank') if top.get('rerank') is not None else -10.0
    rr2=sec.get('rerank') if sec.get('rerank') is not None else rr-5.0
    cs=top.get('semantic') if top.get('semantic') is not None else 0.0
    cs2=sec.get('semantic') if sec.get('semantic') is not None else cs-0.2
    units=top.get('keyword_units') or 0
    cover=(top.get('keyword_hits') or 0)/units if units else 0.0
    same=1.0 if r['query_language'] in (top.get('language'),) else 0.0
    return [rr,rr-rr2,cs,cs-cs2,cover,min(units,12)/12,same,1.0 if r['full_keyword_match'] else 0.0]


def label(r):return 1 if r['relevant'] and r['rank']==1 else 0


def fit(X,y,l2=1.0,iters=300):
    mu,sd=X.mean(0),X.std(0)+1e-9;Z=(X-mu)/sd;Z=np.hstack([Z,np.ones((len(Z),1))]);w=np.zeros(Z.shape[1])
    for _ in range(iters):  # Newton steps
        p=1/(1+np.exp(-Z@w));g=Z.T@(p-y)+l2*np.r_[w[:-1],0];H=(Z.T*(p*(1-p)))@Z+l2*np.diag(np.r_[np.ones(len(w)-1),0])
        w-=np.linalg.solve(H,g)
    return mu,sd,w


def prob(model,X):
    mu,sd,w=model;Z=np.hstack([(X-mu)/sd,np.ones((len(X),1))]);return 1/(1+np.exp(-Z@w))


def choose_threshold(p,rows,target):
    neg=[i for i,r in enumerate(rows) if not r['relevant']]
    for t in np.linspace(0,1,1001):
        if sum(p[i]>=t for i in neg)/max(1,len(neg))<=target:return float(t)
    return 1.0


def evaluate(p,rows,t):
    ans=[i for i,r in enumerate(rows) if r['relevant']];neg=[i for i,r in enumerate(rows) if not r['relevant']]
    near=[i for i in neg if rows[i].get('subtype')=='near_miss']
    good=[i for i in ans if rows[i]['rank']==1];bad=[i for i in ans if rows[i]['rank']!=1]
    acc=lambda ids:sum(p[i]>=t for i in ids)
    return {'answerable':len(ans),'unanswerable':len(neg),'near_miss':len(near),
            'top1_correct_and_answered':acc(good)/len(ans) if ans else None,
            'false_rejection_of_correct_evidence':(len(good)-acc(good))/len(good) if good else None,
            'wrong_evidence_answered':acc(bad)/len(ans) if ans else None,
            'unanswerable_rejected':1-acc(neg)/len(neg) if neg else None,
            'near_miss_rejected':1-acc(near)/len(near) if near else None}


def group_of(r):
    """Related questions share a group: the evidence memory (answerable) or the memory a near-miss targets."""
    if r.get('group'):return r['group']
    rel=r['relevant']
    if rel:return rel[0] if isinstance(rel,list) else rel
    return r['id']


def main():
    ap=argparse.ArgumentParser();ap.add_argument('rows',nargs='+');ap.add_argument('--target',type=float,default=0.05);args=ap.parse_args()
    rows=[r for path in args.rows for r in json.load(open(path,encoding='utf-8')) if r['mode']==MODE]
    X=np.array([features(r) for r in rows]);y=np.array([label(r) for r in rows])
    groups=sorted({group_of(r) for r in rows});rng=np.random.default_rng(20261026)
    gfold={g:int(k) for g,k in zip(groups,rng.integers(0,5,len(groups)))}
    fold=np.array([gfold[group_of(r)] for r in rows]);p=np.zeros(len(rows));ts=[]
    for k in range(5):  # grouped out-of-fold probabilities; threshold chosen on training folds only
        tr,te=fold!=k,fold==k;m=fit(X[tr],y[tr])
        t=choose_threshold(prob(m,X[tr]),[rows[i] for i in np.where(tr)[0]],args.target);ts.append(t);p[te]=prob(m,X[te])
    t_cv=float(np.median(ts))
    splits=sorted({r['split'] for r in rows})
    sel=lambda s:[i for i,r in enumerate(rows) if r['split']==s]
    report={'mode':MODE,'rows':len(rows),'groups':len(groups),'target_false_answer_rate':args.target,'features':NAMES,'cv_thresholds':ts,
            'out_of_fold':{s:evaluate(p[sel(s)],[rows[i] for i in sel(s)],t_cv) for s in splits}|{'all':evaluate(p,rows,t_cv)}}
    base=np.array([1.0 if (r['full_keyword_match'] or (r['best_rerank'] if r['best_rerank'] is not None else -99)>=0.4
                           or (r['best_semantic'] if r['best_semantic'] is not None else -99)>=0.37) else 0.0 for r in rows])
    report['baseline_fixed_rule']={s:evaluate(base[sel(s)],[rows[i] for i in sel(s)],0.5) for s in splits}|{'all':evaluate(base,rows,0.5)}
    final=fit(X,y);tf=choose_threshold(prob(final,X),rows,args.target)
    report['final_model']={'mean':final[0].tolist(),'std':final[1].tolist(),'weights':final[2].tolist(),'threshold':tf,'in_sample':evaluate(prob(final,X),rows,tf)}
    print(json.dumps(report,indent=1))


if __name__=='__main__':main()
