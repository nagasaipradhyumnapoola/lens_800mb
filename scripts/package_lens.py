"""Stage a self-contained Lens for Windows (docs/LENS_V1_SPEC.md §18; Milestone 9).

Layout (relative paths match the repository, so lens-agent resolves models from the same lock files):
  bin/        executables, runtime DLLs (SQLCipher, OpenSSL, zstd, whisper/ggml CPU variants), app-local MSVC CRT, ui/
  models/     only the models the product uses, each verified against its lock-file sha256
  .tools/ocr-runtime/onnxruntime.dll  (pinned ONNX Runtime, hash-verified)
  third_party/*-lock.json, third_party/licenses/, LICENSES.md
  manifest.json  every file with bytes and sha256, plus the installed footprint
Usage: .venv\\Scripts\\python.exe scripts/package_lens.py [--out dist/Lens] [--zip]
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1]
REL=ROOT/'build/engine/Release'
VERSION='0.3.0-dev'
EXES=['lens-agent.exe','lens-app.exe','lens-engine.exe','lens-mesh.exe','lens-observer.exe','lens-ocr.exe','lens-voice.exe','lens-sherpa.exe','lens-tts.exe']
DLLS=['sqlcipher.dll','libcrypto-3-x64.dll','libssl-3-x64.dll','zstd.dll','whisper.dll','ggml.dll','ggml-base.dll']
CRT=Path(r'C:\Program Files\Microsoft Visual Studio\18\Community\VC\Redist\MSVC\14.51.36231\x64\Microsoft.VC145.CRT')
OCR_MODELS=['PP-OCRv5_mobile_det','PP-OCRv6_tiny_rec','devanagari_PP-OCRv5_mobile_rec','ta_PP-OCRv5_mobile_rec','te_PP-OCRv5_mobile_rec']
WHISPER=['ggml-base-q5_1.bin','ggml-tiny-q5_1.bin']
# English speech: Canary-180M-flash (input, lens-sherpa route) and Kokoro + misaki (spoken replies, lens-tts)
SPEECH=['models/csukuangfj--sherpa-onnx-nemo-canary-180m-flash-en-es-de-fr-int8/','models/Lens--kokoro-82m-mixed-int8/','models/hexgrad--misaki/us_',
        'models/onnx-community--Kokoro-82M-v1.0-ONNX/tokenizer.json','models/onnx-community--Kokoro-82M-v1.0-ONNX/voices/']
SHERPA_LIBS=('/lib/sherpa-onnx-c-api.dll','/lib/onnxruntime.dll','/lib/onnxruntime_providers_shared.dll')


def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for chunk in iter(lambda:f.read(1<<20),b''):h.update(chunk)
    return h.hexdigest()


def lock_files():
    """(relative path, expected sha256) for every model/runtime artifact the product loads."""
    out=[]
    for name,keep in [('embedding-lock.json',{'onnx/model_qint8_avx512_vnni.onnx','onnx/tokenizer.json'}),('reranker-lock.json',{'onnx/model_qint8_avx512_vnni.onnx','tokenizer.json'})]:
        lock=json.loads((ROOT/'third_party'/name).read_text(encoding='utf-8'))
        out+=[(f['path'],f['sha256']) for f in lock['files'] if f['filename'] in keep]
    ocr=json.loads((ROOT/'third_party/ocr-runtime-lock.json').read_text(encoding='utf-8'))
    out+=[(a['path'],a['sha256']) for a in ocr['runtime_artifacts'] if a['path'].endswith('/onnxruntime.dll')]
    out+=[(e['path'],e['sha256']) for e in ocr['exports'] if e['model'] in OCR_MODELS]
    for e in json.loads((ROOT/'third_party/model-lock.json').read_text(encoding='utf-8')):
        if e.get('filename') in WHISPER or e['path'].startswith(tuple(SPEECH)):out.append((e['path'],e['sha256']))
    sherpa=json.loads((ROOT/'third_party/sherpa-reference-lock.json').read_text(encoding='utf-8'))
    out+=[(a['path'],a['sha256']) for a in sherpa['runtime_artifacts'] if a['path'].endswith(SHERPA_LIBS)]
    return out


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,default=ROOT/'dist/Lens');ap.add_argument('--zip',action='store_true');args=ap.parse_args()
    out=args.out
    if out.exists():shutil.rmtree(out)
    (out/'bin').mkdir(parents=True)
    for n in EXES+DLLS:shutil.copy2(REL/n,out/'bin'/n)
    for p in REL.glob('ggml-cpu-*.dll'):shutil.copy2(p,out/'bin'/p.name)
    for p in CRT.glob('*.dll'):shutil.copy2(p,out/'bin'/p.name)  # app-local Visual C++ runtime (redistributable)
    shutil.copytree(ROOT/'engine/app/ui',out/'bin/ui')
    missing=[]
    for rel,expected in lock_files():
        src=ROOT/rel
        if not src.exists() or sha(src)!=expected:missing.append(rel);continue
        dst=out/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
    if missing:sys.exit('artifact missing or hash mismatch: '+', '.join(missing))
    (out/'third_party').mkdir(exist_ok=True)
    for name in ['embedding-lock.json','reranker-lock.json','ocr-runtime-lock.json','model-lock.json','upstream-lock.json','build-lock.json','sherpa-reference-lock.json']:
        shutil.copy2(ROOT/'third_party'/name,out/'third_party'/name)
    shutil.copytree(ROOT/'third_party/licenses',out/'third_party/licenses')
    for doc in ['LICENSES.md']:
        if (ROOT/doc).exists():shutil.copy2(ROOT/doc,out/doc)
    shutil.copy2(ROOT/'scripts/install_lens.ps1',out/'install_lens.ps1');shutil.copy2(ROOT/'scripts/uninstall_lens.ps1',out/'uninstall_lens.ps1')
    files=sorted(p for p in out.rglob('*') if p.is_file())
    manifest={'product':'Lens','version':VERSION,'files':[{'path':p.relative_to(out).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)} for p in files]}
    manifest['installed_bytes']=sum(f['bytes'] for f in manifest['files'])
    by={}
    for f in manifest['files']:k=f['path'].split('/')[0] if not f['path'].startswith('models/') else '/'.join(f['path'].split('/')[:2]);by[k]=by.get(k,0)+f['bytes']
    manifest['bytes_by_part']=dict(sorted(by.items(),key=lambda x:-x[1]))
    (out/'manifest.json').write_text(json.dumps(manifest,indent=1),encoding='utf-8')
    print(json.dumps({'files':len(files),'installed_bytes':manifest['installed_bytes'],'bytes_by_part':manifest['bytes_by_part']},indent=1))
    if args.zip:print(shutil.make_archive(str(out),'zip',out))


if __name__=='__main__':main()
