"""Classify every scored query of a retrieval report into separate error types (no blended metric).

Answerable questions, judged for the default mode (hybrid + rerank, centered unless --mode says otherwise):
  correct            rank 1 and answered
  false_abstention   rank 1 but the abstention rule rejected it
  reranking_error    not rank 1 after reranking, although the pre-rerank hybrid list had it in its top 10
  retrieval_miss     not in the pre-rerank hybrid top 10 (candidate generation failed)
Unanswerable questions: correct_rejection or wrong_answer.
Reports counts per language and query type. Reads report + rows only; it does not tune anything.
Usage: .venv\\Scripts\\python.exe scripts/error_taxonomy.py <report.json> [--mode hybrid_rerank_c]
"""
import argparse
from collections import Counter,defaultdict
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import benchmark_retrieval_nl as bench


def classify(rows,mode,split):
    pre='hybrid_c' if mode.endswith('_c') else 'hybrid'  # first-stage list before the cross-encoder
    by={(r['id'],r['mode']):r for r in rows}
    tau=-1.8282 if mode=='hybrid_rerank' else None
    out=[]
    for r in rows:
        if r['mode']!=mode or r['split']!=split:continue
        rejected=bench.abstain(r,mode,tau)
        if not r['relevant']:kind='correct_rejection' if rejected else 'wrong_answer'
        elif r['rank']==1:kind='false_abstention' if rejected else 'correct'
        else:
            p=by.get((r['id'],pre))
            kind='reranking_error' if p and p['rank'] and p['rank']<=10 else 'retrieval_miss'
        out.append((r,kind))
    return out


def main():
    ap=argparse.ArgumentParser();ap.add_argument('report');ap.add_argument('--mode',default='hybrid_rerank_c');args=ap.parse_args()
    rep=json.loads(Path(args.report).read_text(encoding='utf-8'))
    rows=json.loads(Path(args.report.replace('.json','-rows.json')).read_text(encoding='utf-8'))
    split=rep.get('scored_split','test');result=classify(rows,args.mode,split)
    total=Counter(k for _,k in result);lang=defaultdict(Counter);qtype=defaultdict(Counter)
    for r,k in result:lang[r['language']][k]+=1;qtype[r['type']][k]+=1
    summary={'report':args.report,'mode':args.mode,'split':split,'scale':rep.get('scale'),'totals':dict(total),
             'by_language':{k:dict(v) for k,v in sorted(lang.items())},'by_type':{k:dict(v) for k,v in sorted(qtype.items())}}
    print(json.dumps(summary,indent=1,ensure_ascii=False))


if __name__=='__main__':main()
