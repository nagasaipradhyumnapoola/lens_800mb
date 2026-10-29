"""Pin a trained Lens model for the product: copy its deployable files into models/Lens--<name>/ and record each file
(sha256, bytes, provenance) in third_party/model-lock.json and models/manifest.lock.json, where lens-agent and
scripts/package_lens.py verify them. Training reports travel with the weights; no training data is copied.
Usage: .venv\\Scripts\\python.exe lens_model/export/pin_model.py <source folder> <name> <file> [<file> ...]
  e.g. lens_model/export/pin_model.py artifacts/lens-model/onnx/answerability-v2c answerability-v2c model_int8.onnx tokenizer.json quantization-report.json
"""
import hashlib
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from fetch_ocr_models import merge


def main():
    src,name,files=Path(sys.argv[1]),sys.argv[2],sys.argv[3:]
    if not files:raise SystemExit(__doc__)
    out=ROOT/'models'/f'Lens--{name}';out.mkdir(parents=True,exist_ok=True);records=[]
    for f in files:
        if (src/f).resolve()!=(out/f).resolve():shutil.copy2(src/f,out/f)  # files written in place (gate.json) are only recorded
        raw=(out/f).read_bytes()
        records.append({'repo':'derived','filename':f,'path':(out/f).relative_to(ROOT).as_posix(),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
                        'derived_from':str(src.relative_to(ROOT) if src.is_relative_to(ROOT) else src),'license':'Lens (all rights reserved); base model licence in third_party/licenses'})
        print(records[-1]['path'],records[-1]['bytes'],records[-1]['sha256'][:16])
    for lock in (ROOT/'third_party/model-lock.json',ROOT/'models/manifest.lock.json'):merge(lock,records,lambda r:r['path'])


if __name__=='__main__':main()
