"""Recreate a training report for a saved checkpoint whose run ended before writing it (the v1 run hit a path bug
after save_pretrained, now fixed in train_answerability.py). Evaluates the checkpoint on the same dev and held-out
sets the trainer uses and parses the step log; marked `recovered: true`.
Usage: .venv-train\\Scripts\\python.exe lens_model/train/finish_report.py --name answerability-v1 --log artifacts/lens-model/logs/answerability-v1.log
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import sys
import torch
from transformers import AutoModelForSequenceClassification,AutoTokenizer
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'lens_model/train'))
import train_answerability as ta


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--name',required=True);ap.add_argument('--log',type=Path,required=True);ap.add_argument('--threads',type=int,default=8)
    ap.add_argument('--max-len',type=int,default=192);a=ap.parse_args();torch.set_num_threads(a.threads)
    ck=ta.OUT/a.name;tok=AutoTokenizer.from_pretrained(ck);model=AutoModelForSequenceClassification.from_pretrained(ck)
    dev=ta.load('dev');held={n:ta.load(n) for n in ('indicqa_heldout','xquad_heldout')}
    final={'dev':ta.report(dev,ta.scores(model,tok,dev,a.max_len))}|{n:ta.report(r,ta.scores(model,tok,r,a.max_len)) for n,r in held.items()}
    text=a.log.read_text(encoding='utf-8',errors='replace')
    log=[{'step':int(m[0]),'loss':float(m[1]),'s_per_step':float(m[2]),'rss_mb':float(m[3])} for m in re.findall(r'step (\d+)/\d+ loss ([\d.]+) ([\d.]+)s/step eta \d+ min rss (\d+) MB',text)]
    init=re.search(r'init dev auc (\{.*\})',text)
    meta={'created_utc':datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),'recovered':True,'log_file':str(a.log),'init_dev_2000':init.group(1) if init else None,
          'steps':log[-1]['step'] if log else None,'final':final,'log':log,'torch':torch.__version__}
    (ck/'training-report.json').write_text(json.dumps(meta,indent=1,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({k:{kk:vv for kk,vv in v.items() if kk=='all'} for k,v in final.items()},indent=1))


if __name__=='__main__':main()
