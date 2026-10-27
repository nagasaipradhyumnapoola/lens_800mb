"""Pinned upstream alternative after real Mandarin/Hindi Whisper quality failures."""
import hashlib
import io
import json
from pathlib import Path
import tarfile
from urllib.request import urlopen
from fetch_models import fetch
ROOT=Path(__file__).resolve().parents[1]
REPO='csukuangfj/sherpa-onnx-dolphin-small-ctc-multi-lang-int8-2025-04-02'
URL='https://github.com/k2-fsa/sherpa-onnx/releases/download/v2.0.0/sherpa-onnx-v2.0.0-win-x64-shared-MD-Release-no-tts.tar.bz2'
SHA='98d8cf1c0e0bfb5768042e90ffe9591203855b8f4aabdcd5c154eb39b87a0707'


def main():
    lock_path=ROOT/'third_party/sherpa-reference-lock.json'
    locked=json.loads(lock_path.read_text(encoding='utf-8')) if lock_path.exists() else None
    target=ROOT/'.tools/sherpa-runtime';target.mkdir(parents=True,exist_ok=True)
    archive=target/'runtime.tar.bz2'
    if not archive.exists():
        with urlopen(URL,timeout=180) as f:archive.write_bytes(f.read())
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=SHA:raise RuntimeError('Sherpa runtime digest mismatch')
    with tarfile.open(archive) as tar:
        for m in tar:
            if m.isfile() and m.size>200000000:raise RuntimeError('Oversized archive entry')
        tar.extractall(target,filter='data')
    models=[]
    if locked:
        for record in locked['models']:
            path=ROOT/record['path']
            if not path.exists():
                with urlopen(record['url'],timeout=180) as f:raw=f.read()
                if len(raw)!=record['bytes'] or hashlib.sha256(raw).hexdigest()!=record['sha256']:
                    raise RuntimeError('Locked Dolphin download digest mismatch')
                path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            if path.stat().st_size!=record['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=record['sha256']:
                raise RuntimeError('Existing Dolphin artifact differs from lock; refusing overwrite')
            models.append(record)
    else:
        with urlopen(f'https://huggingface.co/api/models/{REPO}/revision/main?blobs=true',timeout=60) as f:meta=json.load(f)
        for item in meta['siblings']:
            if item['rfilename'] in ['model.int8.onnx','tokens.txt','README.md','LICENSE']:
                models.append(fetch(REPO,meta['sha'],item))
    # Original model license, explicitly covering code and weights, is Apache-2.0.
    if locked:source=locked['upstream_model_source_commit']
    else:
        with urlopen('https://api.github.com/repos/DataoceanAI/Dolphin/commits/HEAD',timeout=60) as f:source=json.load(f)['sha']
    with urlopen(f'https://raw.githubusercontent.com/DataoceanAI/Dolphin/{source}/LICENSE',timeout=60) as f:license_bytes=f.read()
    (ROOT/'third_party/licenses/DataoceanAI--Dolphin.txt').write_bytes(license_bytes)
    binaries=[]
    for p in target.rglob('*'):
        if p.suffix.lower() in ['.exe','.dll']:
            binaries.append({'path':p.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size})
    if locked:
        expected={r['path']:(r['bytes'],r['sha256']) for r in locked['runtime_artifacts']}
        actual={r['path']:(r['bytes'],r['sha256']) for r in binaries}
        if expected!=actual:raise RuntimeError('Sherpa extracted runtime differs from committed lock')
    else:lock_path.write_text(json.dumps({'runtime_url':URL,'runtime_sha256':SHA,
         'runtime_version':'2.0.0','runtime_artifacts':binaries,'models':models,'upstream_model_repository':'DataoceanAI/Dolphin',
         'upstream_model_source_commit':source,'license':'Apache-2.0'},indent=2),encoding='utf-8')
    print('Sherpa/Dolphin native reference pinned',flush=True)
    print('\n'.join(p.relative_to(ROOT).as_posix() for p in target.rglob('sherpa-onnx-offline.exe')))


if __name__=='__main__':main()
