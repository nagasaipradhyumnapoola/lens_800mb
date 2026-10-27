"""Build-time only: official Paddle2ONNX export + pinned Microsoft ORT C++ SDK/runtime."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from urllib.request import urlopen
import zipfile
import yaml
ROOT=Path(__file__).resolve().parents[1]
ORT_COMMIT='2d924974ef147392ced8409d36bd6d2e7fcc8a74'


def sha(raw):return hashlib.sha256(raw).hexdigest()


def main():
    runtime=ROOT/'.tools/ocr-runtime';runtime.mkdir(parents=True,exist_ok=True)
    records=[]
    with urlopen('https://pypi.org/pypi/onnxruntime/1.24.4/json',timeout=60) as f:meta=json.load(f)
    wheel=next(x for x in meta['urls'] if 'cp312-cp312-win_amd64.whl' in x['filename'])
    path=runtime/wheel['filename']
    if not path.exists():
        with urlopen(wheel['url'],timeout=180) as f:path.write_bytes(f.read())
    if sha(path.read_bytes())!=wheel['digests']['sha256']:raise RuntimeError('ORT wheel hash mismatch')
    with zipfile.ZipFile(path) as archive:
        for member in ['onnxruntime/capi/onnxruntime.dll','onnxruntime/capi/onnxruntime_providers_shared.dll']:
            raw=archive.read(member);target=runtime/Path(member).name;target.write_bytes(raw)
            records.append({'path':target.relative_to(ROOT).as_posix(),'sha256':sha(raw),'bytes':len(raw),'wheel_member':member})
    include=runtime/'include';include.mkdir(exist_ok=True)
    for name in ['onnxruntime_c_api.h','onnxruntime_cxx_api.h','onnxruntime_cxx_inline.h','onnxruntime_float16.h','onnxruntime_ep_c_api.h']:
        url=f'https://raw.githubusercontent.com/microsoft/onnxruntime/{ORT_COMMIT}/include/onnxruntime/core/session/{name}'
        with urlopen(url,timeout=60) as f:raw=f.read()
        (include/name).write_bytes(raw)
        records.append({'path':(include/name).relative_to(ROOT).as_posix(),'url':url,'sha256':sha(raw),'bytes':len(raw)})
    for name in ['LICENSE','ThirdPartyNotices.txt']:
        url=f'https://raw.githubusercontent.com/microsoft/onnxruntime/{ORT_COMMIT}/{name}'
        with urlopen(url,timeout=60) as f:raw=f.read()
        (ROOT/'third_party/licenses'/('onnxruntime-'+name+'.txt')).write_bytes(raw)
    exports=[]
    for model in ['PP-OCRv6_tiny_rec','devanagari_PP-OCRv5_mobile_rec','ta_PP-OCRv5_mobile_rec','te_PP-OCRv5_mobile_rec',
                  'PP-OCRv5_mobile_det','PP-OCRv6_tiny_det']:
        folder=ROOT/'models'/('PaddlePaddle--'+model)
        output=folder/'inference.onnx'
        command=[str(ROOT/'.tools/ocr-convert/Scripts/python.exe'),'-m','paddle2onnx.command',
                 '--model_dir',str(folder),'--model_filename','inference.json','--params_filename','inference.pdiparams',
                 '--save_file',str(output),'--opset_version','17','--optimize_tool','None']
        subprocess.run(command,cwd=ROOT,check=True)
        artifacts=[output]
        if model.endswith('_rec'):  # recognisers carry a CTC dictionary; detectors do not
            config=yaml.safe_load((folder/'inference.yml').read_text(encoding='utf-8'))
            dictionary=['blank']+config['PostProcess']['character_dict']+[' ']
            dict_path=folder/'ctc-dictionary.json'
            dict_path.write_text(json.dumps(dictionary,ensure_ascii=False),encoding='utf-8');artifacts.append(dict_path)
        for artifact in artifacts:
            exports.append({'model':model,'path':artifact.relative_to(ROOT).as_posix(),'bytes':artifact.stat().st_size,
                            'sha256':sha(artifact.read_bytes()),'source_config_sha256':sha((folder/'inference.yml').read_bytes()),
                            'source_weights_sha256':sha((folder/'inference.pdiparams').read_bytes()),
                            'exporter':'paddle2onnx 2.1.0, PaddlePaddle 3.1.1, ONNX opset 17, optimize_tool=None'})
    (ROOT/'third_party/ocr-runtime-lock.json').write_text(json.dumps({'onnxruntime_version':'1.24.4',
        'source_commit':ORT_COMMIT,'wheel_url':wheel['url'],'wheel_sha256':wheel['digests']['sha256'],
        'runtime_artifacts':records,'exports':exports},indent=2),encoding='utf-8')
    print('Pinned native OCR runtime and model exports',flush=True)


if __name__=='__main__':main()
