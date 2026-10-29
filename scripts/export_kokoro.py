"""Build-time only: Lens mixed-precision Kokoro-82M export for CPU spoken replies (engine/tts_main.cpp).

Kokoro-82M v1.0 FP32 ONNX (Apache-2.0, pinned by scripts/fetch_speech_models.py) is statically quantized to INT8 in QDQ
form (per-channel weights, ONNX Runtime QLinear kernels) everywhere except the iSTFTNet waveform generator, which stays
FP32. Measured 2026-10-29 (G14, 4 threads, contended CPU): 310 -> 178 MB on disk at the FP32 speed, zero word errors when
its speech is transcribed back with Canary-180M-flash; quantizing the generator too was 1.7x faster but garbled words
("in Chrome" -> "and pronounced"), and the upstream dynamic INT8 export runs ~3x slower than FP32 (ConvInteger kernels).
Calibration: the fixed public phoneme sentences below (no personal data). Output models/Lens--kokoro-82m-mixed-int8/,
recorded in third_party/model-lock.json and models/manifest.lock.json.
Usage: .venv\\Scripts\\python.exe scripts/export_kokoro.py
"""
import hashlib
import json
from pathlib import Path
import tempfile
import numpy as np
import onnx
from onnxruntime.quantization import CalibrationDataReader,QuantFormat,QuantType,quantize_static
from onnxruntime.quantization.shape_inference import quant_pre_process
from fetch_ocr_models import merge
ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'models/onnx-community--Kokoro-82M-v1.0-ONNX'
OUT=ROOT/'models/Lens--kokoro-82m-mixed-int8'
CALIBRATION=['həlˈO! ju ɹˈid ði pˈApəɹ ˌɔn ɡˈɪthˈʌb jˈɛstəɹdˌA.','ɪt kˈɔst twˈɛlv dˈɑləɹz fˈɪfti sˈɛnts, əbˈWt fˌɪftˈin pəɹsˈɛnt.',
             'sˈi ɡˈɪthˈʌb dˈɑt kˈɑm fɔɹ dətˈAlz.','ðə mˈitɪŋ ɪz æt nˈIn θˈɜɹɾi ɪn ðə mˈɔɹnɪŋ.','wˈʌt dˈɪd aɪ ʧˈAnʤ lˈæst wˈik?',
             'aɪ fˈWnd θɹˈi fˈAlz ðæt mˈæʧ jʊɹ kwˈɛsʧən, bˌʌt ˈOnli wˈʌn ɪz fɹʌm ðɪs wˈik.','jɔɹ nˈɛkst mˈitɪŋ ɪz wɪð pɹˈiə æt tˈu pˌiˈɛm.']


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    vocab=json.loads((SRC/'tokenizer.json').read_text(encoding='utf-8'))['model']['vocab']
    style=np.fromfile(SRC/'voices/af_heart.bin',dtype=np.float32).reshape(-1,256)
    def feed(ph):
        ids=[vocab[c] for c in ph if c in vocab]
        return {'input_ids':np.array([[0]+ids+[0]],dtype=np.int64),'style':style[len(ids)][None],'speed':np.array([1.0],dtype=np.float32)}
    class Reader(CalibrationDataReader):
        def __init__(self):self.it=iter([feed(p) for p in CALIBRATION])
        def get_next(self):return next(self.it,None)
    OUT.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        pre=Path(tmp)/'pre.onnx';quant_pre_process(str(SRC/'onnx/model.onnx'),str(pre),skip_symbolic_shape=True)
        keep=[n.name for n in onnx.load(str(pre)).graph.node if '/decoder/generator' in n.name]
        quantize_static(str(pre),str(OUT/'model.onnx'),Reader(),quant_format=QuantFormat.QDQ,op_types_to_quantize=['Conv','ConvTranspose','MatMul'],
                        per_channel=True,activation_type=QuantType.QUInt8,weight_type=QuantType.QInt8,nodes_to_exclude=keep)
    model=OUT/'model.onnx'
    record={'repo':'derived','filename':'model.onnx','path':model.relative_to(ROOT).as_posix(),'bytes':model.stat().st_size,'sha256':sha(model),
            'derived_from':{'path':(SRC/'onnx/model.onnx').relative_to(ROOT).as_posix(),'sha256':sha(SRC/'onnx/model.onnx')},
            'method':'onnxruntime.quantization static QDQ INT8 (per-channel), waveform generator kept FP32','license':'Apache-2.0'}
    for lock in (ROOT/'third_party/model-lock.json',ROOT/'models/manifest.lock.json'):merge(lock,[record],lambda r:r['path'])
    print(record['path'],record['bytes'],record['sha256'])


if __name__=='__main__':main()
