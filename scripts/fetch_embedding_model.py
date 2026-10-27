"""Fetch retrieval model ONNX/tokenizer files at an immutable revision and write/verify their lock.

Usage: python scripts/fetch_embedding_model.py [embedding|reranker]

First run (no lock entry) records size+SHA256 and checks LFS files against the Hub's published SHA256.
Later runs refuse any artifact whose bytes differ from the committed lock.
"""
import hashlib
import http.client
import json
from pathlib import Path
from urllib.request import urlopen,Request
ROOT=Path(__file__).resolve().parents[1]
import sys
MODELS={
 'embedding':dict(repo='intfloat/multilingual-e5-small',revision='614241f622f53c4eeff9890bdc4f31cfecc418b3',license='MIT',
   files=['onnx/model.onnx','onnx/model_qint8_avx512_vnni.onnx','onnx/sentencepiece.bpe.model','onnx/tokenizer.json',
          'onnx/tokenizer_config.json','onnx/special_tokens_map.json','onnx/config.json','1_Pooling/config.json','README.md'],
   lock='third_party/embedding-lock.json'),
 'reranker':dict(repo='cross-encoder/mmarco-mMiniLMv2-L12-H384-v1',revision='1427fd652930e4ba29e8149678df786c240d8825',license='Apache-2.0',
   files=['onnx/model_qint8_avx512_vnni.onnx','tokenizer.json','tokenizer_config.json','special_tokens_map.json',
          'config.json','README.md'],lock='third_party/reranker-lock.json')}
CHOICE=MODELS[sys.argv[1] if len(sys.argv)>1 else 'embedding']
REPO=CHOICE['repo'];REVISION=CHOICE['revision'];FILES=CHOICE['files'];LOCK=ROOT/CHOICE['lock']
TARGET=ROOT/'models'/REPO.replace('/','--')


def get(url,attempts=4):
    for attempt in range(attempts):
        try:
            with urlopen(Request(url,headers={'User-Agent':'Lens-reproducible-build/0.1'}),timeout=900) as r:return r.read()
        except (OSError,http.client.IncompleteRead):
            if attempt==attempts-1:raise


def main():
    meta=json.loads(get(f'https://huggingface.co/api/models/{REPO}/revision/{REVISION}?blobs=true'))
    published={s['rfilename']:(s.get('lfs') or {}).get('sha256') for s in meta['siblings']}
    lock=json.loads(LOCK.read_text(encoding='utf-8')) if LOCK.exists() else None
    known={r['filename']:r for r in lock['files']} if lock else {}
    records=[]
    for name in FILES:
        path=TARGET/name
        url=f'https://huggingface.co/{REPO}/resolve/{REVISION}/{name}'
        raw=path.read_bytes() if path.exists() else get(url)
        digest=hashlib.sha256(raw).hexdigest()
        if published.get(name) and published[name]!=digest:raise RuntimeError(f'Hub LFS digest mismatch: {name}')
        if name in known and (known[name]['sha256']!=digest or known[name]['bytes']!=len(raw)):
            raise RuntimeError(f'Artifact differs from committed lock: {name}')
        if not path.exists():
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        records.append({'filename':name,'url':url,'path':path.relative_to(ROOT).as_posix(),'bytes':len(raw),'sha256':digest,
                        'upstream_verification':'lfs-sha256' if published.get(name) else 'recorded-on-first-fetch'})
        print(name,len(raw),digest,flush=True)
    if not lock:
        LOCK.write_text(json.dumps({'schema_version':1,'repo':REPO,'revision':REVISION,'license_spdx':CHOICE['license'],
            'license_source':f'https://huggingface.co/{REPO}/blob/{REVISION}/README.md (model card license)',
            'files':records},indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
