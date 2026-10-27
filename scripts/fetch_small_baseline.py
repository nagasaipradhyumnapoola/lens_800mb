"""Fetch a stronger, development comparison after Tiny/Base quality failures."""
import json
from pathlib import Path
from fetch_models import fetch

ROOT=Path(__file__).resolve().parents[1]
meta=json.loads((ROOT/'artifacts/ggerganov--whisper.cpp-metadata.json').read_text())
item=next(x for x in meta['siblings'] if x['rfilename']=='ggml-small-q5_1.bin')
record=fetch('ggerganov/whisper.cpp',meta['sha'],item)
path=ROOT/'third_party/model-lock.json'
locks=json.loads(path.read_text())
locks=[x for x in locks if x['path']!=record['path']]+[record]
path.write_text(json.dumps(locks,indent=2)+'\n',encoding='utf-8')
