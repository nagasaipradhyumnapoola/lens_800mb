"""Spoken replies (lens-tts): misaki-lexicon phonemizer + Lens mixed-precision Kokoro-82M, one worker serving requests.
Models come from scripts/fetch_speech_models.py and scripts/export_kokoro.py; tests skip when they are not installed."""
import base64
import io
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
import psutil
import soundfile
ROOT=Path(__file__).resolve().parents[1]
REL=ROOT/'build/engine/Release'
KOKORO=ROOT/'models/onnx-community--Kokoro-82M-v1.0-ONNX'
MODEL=ROOT/'models/Lens--kokoro-82m-mixed-int8/model.onnx'
MISAKI=ROOT/'models/hexgrad--misaki'
ORT=ROOT/'.tools/ocr-runtime/onnxruntime.dll'
CANARY=ROOT/'models/csukuangfj--sherpa-onnx-nemo-canary-180m-flash-en-es-de-fr-int8'
SHERPA=ROOT/'.tools/sherpa-runtime/sherpa-onnx-v2.0.0-win-x64-shared-MD-Release-no-tts/lib/sherpa-onnx-c-api.dll'


def request(text,**extra):
    return {'text':text,'voice':str(KOKORO/'voices/af_heart.bin'),'runtime':str(ORT),'model':str(MODEL),'tokenizer':str(KOKORO/'tokenizer.json'),
            'lexicon':[str(MISAKI/'us_gold.json'),str(MISAKI/'us_silver.json')],'threads':4}|extra


def serve(requests,peak=None):
    """Runs one lens-tts worker over all requests; returns the parsed responses (and records the peak working set)."""
    p=subprocess.Popen([str(REL/'lens-tts.exe')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,encoding='utf-8')
    if peak is not None:
        def watch():
            proc=psutil.Process(p.pid)
            while p.poll() is None:
                try:peak[0]=max(peak[0],proc.memory_info().peak_wset)
                except psutil.Error:break
                time.sleep(0.02)
        threading.Thread(target=watch,daemon=True).start()
    out,_=p.communicate(''.join(json.dumps(r)+'\n' for r in requests),timeout=600)
    return [json.loads(l) for l in out.splitlines()],p.returncode


@unittest.skipUnless(MODEL.exists() and (MISAKI/'us_gold.json').exists() and ORT.exists(),'speech models not installed')
class SpokenReplies(unittest.TestCase):
    def test_numbers_symbols_and_names_are_read_as_words(self):
        rows,code=serve([request('Meet at 4:30, pay $12.50 (15%) in 2026. See github.com and GitHub; the 3rd item.')])
        self.assertEqual(code,0);r=rows[0];self.assertTrue(r['ok'],r);ph=' '.join(r['phonemes'])
        for spoken in ['fˈɔɹ θˈɜɹɾi','twˈɛlv dˈɑləɹz fˈɪfti sˈɛnts','pəɹsˈɛnt','twˈɛnti twˈɛnti sˈɪks','dˈɑt','θˈɜɹd']:self.assertIn(spoken,ph)
        self.assertNotIn('$',ph);self.assertNotIn('%',ph);self.assertEqual(r['unknown_words'],[])
        audio,rate=soundfile.read(io.BytesIO(base64.b64decode(r['audio_base64'])))
        self.assertEqual(rate,24000);self.assertAlmostEqual(len(audio)/rate,r['duration_s'],places=2);self.assertGreater(r['duration_s'],3)

    def test_worker_keeps_the_model_and_survives_bad_requests(self):
        rows,code=serve([request('First answer.'),request('   '),request('Second answer.',voice=str(KOKORO/'voices/none.bin')),request('Third answer.')])
        self.assertEqual([r['ok'] for r in rows],[True,False,False,True])
        self.assertEqual(rows[1]['error'],'empty_text');self.assertEqual(rows[2]['error'],'voice_unavailable')
        self.assertGreater(rows[0]['timing_ms']['model_load'],100);self.assertLess(rows[3]['timing_ms']['model_load'],5)  # loaded once
        self.assertEqual(code,1)  # some requests failed

    def test_long_reply_is_chunked_and_stays_under_the_ram_target(self):
        text=' '.join(['The paper you read in Chrome yesterday compared three retrieval methods, and the hybrid one won on every language.']*6)
        peak=[0];rows,code=serve([request(text)],peak);r=rows[0]
        self.assertEqual(code,0);self.assertGreater(len(r['phonemes']),2)  # sentence packing, not one 500-token chunk
        self.assertTrue(all(len(p)<=500 for p in r['phonemes']))
        self.assertLess(peak[0],500_000_000,peak[0])  # spec §15 working target (measured 394 MB on H0)

    @unittest.skipUnless((CANARY/'decoder.int8.onnx').exists() and SHERPA.exists(),'Canary not installed')
    def test_speech_is_intelligible_to_the_recogniser(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav=Path(tmp)/'reply.wav'
            rows,code=serve([request('The document you are looking for is the research paper you read in Chrome yesterday afternoon.',output=str(wav))])
            self.assertEqual(code,0,rows);self.assertNotIn('audio_base64',rows[0])
            asr={'consent':True,'audio':str(wav),'model_type':'canary','language':'en','model':str(CANARY/'encoder.int8.onnx'),
                 'decoder':str(CANARY/'decoder.int8.onnx'),'tokens':str(CANARY/'tokens.txt'),'library':str(SHERPA)}
            p=subprocess.run([str(REL/'lens-sherpa.exe')],input=json.dumps(asr)+'\n',capture_output=True,text=True,encoding='utf-8',timeout=120)
        heard=json.loads(p.stdout)['text'].lower()
        for word in ['document','research paper','chrome','yesterday afternoon']:self.assertIn(word,heard)


if __name__=='__main__':unittest.main()
