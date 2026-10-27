"""Compare upstream audio decoding inputs without changing models or hiding commit peaks."""
import json
from pathlib import Path
import sys
import soundfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from benchmarks.process import measure

fixtures=json.loads((ROOT/'data/fixtures/fleurs-smoke.json').read_text(encoding='utf-8'))['samples']
sample=next(x for x in fixtures if x['language']=='en')
audio,sr=soundfile.read(ROOT/sample['path'],dtype='float32')
converted=ROOT/'artifacts/en-pcm16.wav'
soundfile.write(converted,audio,sr,subtype='PCM_16')
rows=[]
for name,path in [('public-jfk',ROOT/'third_party/whisper.cpp/samples/jfk.wav'),
                  ('fleurs-float',ROOT/sample['path']),('fleurs-pcm16',converted)]:
    r=measure([ROOT/'build/whisper/bin/Release/whisper-cli.exe','-m',
               ROOT/'models/ggerganov--whisper.cpp/ggml-tiny-q5_1.bin',
               '-f',path,'-l','en','-ng','-bs','1','-bo','1','-t','4'],cwd=ROOT)
    rows.append({'case':name,**r})
    print(name,r['sum_observed_process_peak_wset_bytes'],r['sum_observed_process_peak_commit_bytes'],flush=True)
(ROOT/'reports/audio-memory-diagnostic.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
