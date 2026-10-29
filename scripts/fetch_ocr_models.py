"""Build-time only: fetch PaddleOCR recognisers at a pinned Hugging Face revision and export them to ONNX.

Each file is checked against the repository's LFS sha256 (or git blob sha1) before use, recorded in
third_party/model-lock.json and models/manifest.lock.json (replacing any older record of the same file), exported with
the same pinned paddle2onnx 2.1.0 tool and flags as scripts/prepare_native_ocr.py, and its export (inference.onnx,
ctc-dictionary.json) pinned in third_party/ocr-runtime-lock.json. Licence: Apache-2.0 (checked from the model card).
Usage: .venv\\Scripts\\python.exe scripts/fetch_ocr_models.py [repo-name ...]
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from urllib.request import Request,urlopen
import yaml
ROOT=Path(__file__).resolve().parents[1]
DEFAULT=['arabic_PP-OCRv5_mobile_rec','cyrillic_PP-OCRv5_mobile_rec','latin_PP-OCRv5_mobile_rec','PP-OCRv5_mobile_rec']
FILES=('inference.json','inference.pdiparams','inference.yml')


def get(url):
    with urlopen(Request(url,headers={'User-Agent':'Lens-Micro-build/0.1'}),timeout=180) as f:return f.read()


def sha(raw):return hashlib.sha256(raw).hexdigest()


def fetch(name):
    repo='PaddlePaddle/'+name;meta=json.loads(get(f'https://huggingface.co/api/models/{repo}?blobs=true'))
    licence=(meta.get('cardData') or {}).get('license')
    if licence!='apache-2.0':raise SystemExit(f'{repo}: licence {licence!r} is not Apache-2.0')
    folder=ROOT/'models'/repo.replace('/','--');folder.mkdir(parents=True,exist_ok=True);records=[]
    for item in meta['siblings']:
        if item['rfilename'] not in FILES:continue
        url=f"https://huggingface.co/{repo}/resolve/{meta['sha']}/{item['rfilename']}";target=folder/item['rfilename']
        raw=target.read_bytes() if target.exists() else get(url)
        expected=(item.get('lfs') or {}).get('sha256')
        if expected and sha(raw)!=expected:raise SystemExit(f'sha256 mismatch: {url}')
        if not expected and hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=item['blobId']:raise SystemExit(f'blob mismatch: {url}')
        target.write_bytes(raw)
        records.append({'repo':repo,'revision':meta['sha'],'filename':item['rfilename'],'url':url,'path':target.relative_to(ROOT).as_posix(),
                        'bytes':len(raw),'sha256':sha(raw),'upstream_verification':'lfs-sha256' if expected else 'git-blob-sha1','license':'Apache-2.0'})
        print(name,item['rfilename'],len(raw),flush=True)
    if len(records)!=len(FILES):raise SystemExit(f'{repo}: missing files')
    return folder,records


def export(name,folder):
    output=folder/'inference.onnx'
    subprocess.run([str(ROOT/'.tools/ocr-convert/Scripts/python.exe'),'-m','paddle2onnx.command','--model_dir',str(folder),
                    '--model_filename','inference.json','--params_filename','inference.pdiparams','--save_file',str(output),
                    '--opset_version','17','--optimize_tool','None'],cwd=ROOT,check=True,capture_output=True)
    config=yaml.safe_load((folder/'inference.yml').read_text(encoding='utf-8'));outputs=[output]
    if 'character_dict' in config['PostProcess']:  # recognisers only; detectors have no dictionary
        dict_path=folder/'ctc-dictionary.json';outputs.append(dict_path)
        dict_path.write_text(json.dumps(['blank']+config['PostProcess']['character_dict']+[' '],ensure_ascii=False),encoding='utf-8')
    return [{'model':name,'path':a.relative_to(ROOT).as_posix(),'bytes':a.stat().st_size,'sha256':sha(a.read_bytes()),
             'source_config_sha256':sha((folder/'inference.yml').read_bytes()),'source_weights_sha256':sha((folder/'inference.pdiparams').read_bytes()),
             'exporter':'paddle2onnx 2.1.0, PaddlePaddle 3.1.1, ONNX opset 17, optimize_tool=None'} for a in outputs]


def merge(path,new,key):
    text=path.read_bytes().decode('utf-8').replace('\r\n','\n');old=json.loads(text)
    second=text.split('\n')[1];indent=len(second)-len(second.lstrip(' '))  # keep each lock file's own layout
    items=old if isinstance(old,list) else old['exports'];keys={key(r) for r in new}
    items[:]=[r for r in items if key(r) not in keys]+new
    path.write_bytes((json.dumps(old,indent=indent,ensure_ascii=False)+('\n' if text.endswith('\n') else '')).encode('utf-8'))


def main():
    names=sys.argv[1:] or DEFAULT;fetched=[];exports=[]
    for name in names:
        folder,records=fetch(name);fetched+=records;exports+=export(name,folder)
    for lock in (ROOT/'third_party/model-lock.json',ROOT/'models/manifest.lock.json'):merge(lock,fetched,lambda r:r['path'])
    merge(ROOT/'third_party/ocr-runtime-lock.json',exports,lambda r:r['path'])
    print('pinned',len(fetched),'files,',len(exports),'exports')


if __name__=='__main__':main()
