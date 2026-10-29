"""Build-time only: fetch the English speech models at pinned revisions and verify every file against its upstream hash.

- ASR: NVIDIA Canary-180M-flash, sherpa-onnx INT8 export (CC-BY-4.0; en/es/de/fr, punctuation and capitalisation).
- TTS: Kokoro-82M v1.0 INT8 ONNX (Apache-2.0) with five English voices, and the misaki US English lexicons
  (Apache-2.0) that replace espeak-ng (GPL-3.0) as the phonemizer.
Records go to third_party/model-lock.json and models/manifest.lock.json (replacing older records of the same file);
licence texts and attribution go to third_party/licenses/.
Usage: .venv\\Scripts\\python.exe scripts/fetch_speech_models.py
"""
import hashlib
import json
from pathlib import Path
from urllib.request import Request,urlopen
from fetch_models import fetch
from fetch_ocr_models import merge
ROOT=Path(__file__).resolve().parents[1]
HF={'csukuangfj/sherpa-onnx-nemo-canary-180m-flash-en-es-de-fr-int8':['encoder.int8.onnx','decoder.int8.onnx','tokens.txt'],
    'onnx-community/Kokoro-82M-v1.0-ONNX':['onnx/model.onnx','onnx/model_quantized.onnx','config.json','tokenizer.json']+
        [f'voices/{v}.bin' for v in ('af_heart','af_bella','am_michael','bf_emma','bm_george')]}
MISAKI=['misaki/data/us_gold.json','misaki/data/us_silver.json','LICENSE']


def get(url):
    with urlopen(Request(url,headers={'User-Agent':'Lens-Micro-build/0.1'}),timeout=180) as f:return f.read()


def misaki():
    commit=json.loads(get('https://api.github.com/repos/hexgrad/misaki/commits/main'))['sha'];out=[]
    folder=ROOT/'models/hexgrad--misaki';folder.mkdir(parents=True,exist_ok=True)
    for name in MISAKI:
        blob=json.loads(get(f'https://api.github.com/repos/hexgrad/misaki/contents/{name}?ref={commit}'))['sha']
        url=f'https://raw.githubusercontent.com/hexgrad/misaki/{commit}/{name}';raw=get(url)
        if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=blob:raise SystemExit(f'git blob mismatch: {url}')
        target=folder/Path(name).name;target.write_bytes(raw)
        out.append({'repo':'github:hexgrad/misaki','revision':commit,'filename':name,'url':url,'path':target.relative_to(ROOT).as_posix(),
                    'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'upstream_verification':'git-blob-sha1','license':'Apache-2.0'})
        print(name,len(raw),flush=True)
    (ROOT/'third_party/licenses/hexgrad--misaki.txt').write_bytes((folder/'LICENSE').read_bytes())
    return out


def main():
    records=[]
    for repo,names in HF.items():
        meta=json.loads(get(f'https://huggingface.co/api/models/{repo}?blobs=true'))
        items={i['rfilename']:i for i in meta['siblings']}
        records+=[fetch(repo,meta['sha'],items[n])|{'license':'CC-BY-4.0' if 'canary' in repo else 'Apache-2.0'} for n in names]
    records+=misaki()
    (ROOT/'third_party/licenses/NVIDIA--canary-180m-flash.txt').write_text(
        'NVIDIA canary-180m-flash (https://huggingface.co/nvidia/canary-180m-flash), licensed under CC-BY-4.0\n'
        '(https://creativecommons.org/licenses/by/4.0/). ONNX INT8 export by the k2-fsa/sherpa-onnx project\n'
        '(https://huggingface.co/csukuangfj/sherpa-onnx-nemo-canary-180m-flash-en-es-de-fr-int8). Used unmodified.\n',encoding='utf-8')
    (ROOT/'third_party/licenses/hexgrad--Kokoro-82M.txt').write_text(
        'Kokoro-82M v1.0 (https://huggingface.co/hexgrad/Kokoro-82M), Apache-2.0; ONNX export by onnx-community\n'
        '(https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX). Used unmodified.\n',encoding='utf-8')
    for lock in (ROOT/'third_party/model-lock.json',ROOT/'models/manifest.lock.json'):merge(lock,records,lambda r:r['path'])
    print('pinned',len(records),'files')


if __name__=='__main__':main()
