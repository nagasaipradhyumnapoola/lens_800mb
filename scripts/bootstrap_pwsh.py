"""Place the pinned PowerShell 7 runtime under .tools/ from the vcpkg cache or the official release.

The archive is verified against the committed lock (size, SHA-512, SHA-256) before extraction.
Nothing is installed system-wide; an existing install directory is reused only if pwsh.exe exists.
"""
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen,Request
import zipfile
ROOT=Path(__file__).resolve().parents[1]


def main():
    lock=json.loads((ROOT/'third_party/pwsh-lock.json').read_text(encoding='utf-8'))
    target=ROOT/lock['install_path']
    if (target/'pwsh.exe').is_file():
        print('pwsh present',target/'pwsh.exe');return
    cached=ROOT/'third_party/vcpkg/downloads'/lock['archive']
    if cached.is_file():raw=cached.read_bytes()
    else:
        with urlopen(Request(lock['url'],headers={'User-Agent':'Lens-reproducible-build/0.1'}),timeout=600) as response:
            raw=response.read()
    if len(raw)!=lock['bytes'] or hashlib.sha512(raw).hexdigest()!=lock['sha512'] or hashlib.sha256(raw).hexdigest()!=lock['sha256']:
        raise RuntimeError('PowerShell archive digest mismatch; refusing to extract')
    staging=target.with_name(target.name+'.partial')
    if staging.exists():raise RuntimeError(f'Remove incomplete staging directory first: {staging}')
    archive=ROOT/'.tools'/lock['archive']
    archive.parent.mkdir(parents=True,exist_ok=True);archive.write_bytes(raw)
    try:
        with zipfile.ZipFile(archive) as z:z.extractall(staging)
    finally:archive.unlink()
    staging.rename(target)
    print('pwsh verified',target/'pwsh.exe')


if __name__=='__main__':main()
