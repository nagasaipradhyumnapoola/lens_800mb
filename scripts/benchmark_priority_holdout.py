"""Evaluate selected per-language packs on 100 clips excluded from initial model selection."""
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]

def main():
    fetch=[sys.executable,str(ROOT/'scripts/fetch_fleurs.py'),'--per-language','100','--skip-first','2',
           '--languages','en_us','cmn_hans_cn','es_419','hi_in','--output','data/fixtures/fleurs-priority-holdout.json']
    subprocess.run(fetch,cwd=ROOT,check=True)
    for lang,model in [('en','ggml-base-q5_1.bin'),('zh','ggml-tiny-q5_1.bin'),
                       ('es','ggml-small-q5_1.bin'),('hi','ggml-small-q5_1.bin')]:
        subprocess.run([sys.executable,str(ROOT/'scripts/benchmark.py'),'--fixture-manifest',
                        'data/fixtures/fleurs-priority-holdout.json','--models',model,'--languages',lang,
                        '--language-mode','configured','--beam-size','1','--best-of','1',
                        '--report-name','asr-holdout-'+lang],cwd=ROOT,check=True)

if __name__=='__main__':main()
