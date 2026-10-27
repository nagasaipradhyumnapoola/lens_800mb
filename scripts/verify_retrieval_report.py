"""Independent recomputation of a retrieval-nl report from its raw per-query rows (no harness code reused)."""
import json,math,sys
from pathlib import Path


def check(report_path):
    rep=json.loads(Path(report_path).read_text(encoding='utf-8'))
    rows=json.loads(Path(str(report_path).replace('.json','-rows.json')).read_text(encoding='utf-8'))
    bad=[]
    for mode,res in rep['test_results'].items():
        test=[r for r in rows if r['mode']==mode and r['split']==rep.get('scored_split','test')]
        ans=[r for r in test if r['relevant']]
        if not ans:mine={}  # negatives-only fixture (near-miss): only abstention is checked
        else:mine={'recall@1':sum(1 for r in ans if r['rank']==1)/len(ans),
              'recall@10':sum(1 for r in ans if r['rank'] is not None and r['rank']<=10)/len(ans),
              'mrr@10':sum(1/r['rank'] for r in ans if r['rank'] is not None and r['rank']<=10)/len(ans),
              'ndcg@10':sum(1/math.log2(r['rank']+1) for r in ans if r['rank'] is not None and r['rank']<=10)/len(ans)}
        for k,v in mine.items():
            if abs(v-res['all_answerable'][k])>1e-12:bad.append((mode,k,v,res['all_answerable'][k]))
        tau=res['abstention']['threshold'];neg=[r for r in test if not r['relevant']]
        def abstains(r):
            if mode.startswith('legacy'):return bool(r['legacy_not_found'])
            if mode.endswith('_c') and isinstance(tau,str):  # fixed engine rule (current reports)
                rule=json.loads(tau[tau.index('{'):])  # constants recorded in the report, logic re-implemented here
                reranked=mode in ('hybrid_rerank_c','hybrid_rerank_rrf_c')
                cos=r['best_semantic'] is not None and r['best_semantic']>=(rule['cosine'] if reranked else rule['cosine_no_rerank'])
                if mode=='semantic_c':return not cos
                rr=reranked and r['best_rerank'] is not None and r['best_rerank']>=rule['rerank']
                return not (r['full_keyword_match'] or rr or cos)
            if mode=='keyword':return not r['full_keyword_match']
            base=mode[:-2] if mode.endswith('_c') else mode  # older reports: calibrated threshold per centered mode
            score=r.get('best_rerank') if base=='hybrid_rerank' else r['best_semantic']
            below=score is None or score<tau
            return below if base=='semantic' else (not r['full_keyword_match'] and below)
        rate=sum(abstains(r) for r in neg)/len(neg)
        if abs(rate-res['abstention']['correct_not_found_rate'])>1e-12:bad.append((mode,'abstention',rate,res['abstention']['correct_not_found_rate']))
        if any(not r['ok'] for r in test):bad.append((mode,'engine_errors',sum(1 for r in test if not r['ok']),0))
    counts={m:sum(1 for r in rows if r['mode']==m) for m in rep['test_results']}
    return rep['scale'],len(rows),counts,bad,rep.get('engine_default_matches_simulation')


if __name__=='__main__':
    failed=False
    for path in sys.argv[1:]:
        scale,n,counts,bad,engine_match=check(path)
        print(f'scale={scale} rows={n} per_mode={set(counts.values())} mismatches={bad} engine_default_matches_simulation={engine_match}')
        failed|=bool(bad) or engine_match is False
    raise SystemExit(1 if failed else 0)
