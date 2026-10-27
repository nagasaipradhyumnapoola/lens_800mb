"""Reproduce downloaded weights/runtimes from the committed lock, without refreshing pins."""
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen,Request
import zipfile
ROOT=Path(__file__).resolve().parents[1]


def main():
    locks=json.loads((ROOT/'third_party/model-lock.json').read_text(encoding='utf-8'))
    for rec in locks:
        path=ROOT/rec['path']
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest()!=rec['sha256']:
                raise RuntimeError(f"Existing artifact differs from lock; refusing overwrite: {path}")
            continue
        path.parent.mkdir(parents=True,exist_ok=True)
        if rec.get('source','').endswith('.whl'):
            wheel=path.parents[1]/rec['source']
            with zipfile.ZipFile(wheel) as z:raw=z.read('needle/libneedle3.dll')
        else:
            with urlopen(Request(rec['url'],headers={'User-Agent':'Lens-reproducible-build/0.1'}),timeout=180) as response:
                raw=response.read()
        if len(raw)!=rec['bytes'] or hashlib.sha256(raw).hexdigest()!=rec['sha256']:
            raise RuntimeError(f"Artifact digest mismatch: {path}")
        path.write_bytes(raw)
        print(rec['filename'],'verified',flush=True)


if __name__=='__main__':main()
