"""Milestone 7 voice capture: consent gate, voice-activity segmentation and storage through the engine. The microphone
is replaced by --input-wav (public sample audio); real microphone capture is not exercised by tests (consent)."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import wave
ROOT=Path(__file__).resolve().parents[1]
REL=ROOT/'build/engine/Release'
JFK=ROOT/'third_party/whisper.cpp/samples/jfk.wav'
MODEL=ROOT/'models/ggerganov--whisper.cpp/ggml-tiny-q5_1.bin'


def two_utterances(path):
    """jfk.wav, 1.5 s of silence, jfk.wav again (16 kHz mono 16-bit)."""
    with wave.open(str(JFK)) as w:params=w.getparams();frames=w.readframes(w.getnframes())
    with wave.open(str(path),'wb') as out:
        out.setparams(params);out.writeframes(frames+b'\x00\x00'*int(params.framerate*1.5)+frames)


def voice(*args,input_text=''):
    return subprocess.run([str(REL/'lens-voice.exe'),*map(str,args)],input=input_text,capture_output=True,text=True,encoding='utf-8',timeout=120)


class Voice(unittest.TestCase):
    def test_requires_consent(self):
        p=voice('--model',MODEL,'--input-wav',JFK);self.assertEqual(p.returncode,2);self.assertEqual(p.stdout,'')
        self.assertIn('consent_required',p.stderr)

    def test_segments_utterances_and_stores_transcripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav=Path(tmp)/'two.wav';two_utterances(wav)
            p=voice('--consent','--model',MODEL,'--language','en','--device-name','test-device','--input-wav',wav)
            self.assertEqual(p.returncode,0,p.stderr)
            reqs=[json.loads(l) for l in p.stdout.splitlines()];self.assertEqual(len(reqs),2,p.stderr)
            for r in reqs:
                self.assertEqual(r['op'],'ingest_audio');self.assertTrue(r['consent']);self.assertEqual(r['kind'],'voice_note')
                self.assertNotIn('audio',r);self.assertGreater(r['metadata']['duration_ms'],9000)
            self.assertNotIn('country',p.stderr)  # status carries counts and levels only
            db=Path(tmp)/'memory.db'
            e=subprocess.run([str(REL/'lens-engine.exe'),'--db',str(db)],input=p.stdout+json.dumps({'op':'search','query':'country'})+'\n',
                             capture_output=True,text=True,encoding='utf-8',timeout=300)
            rows=[json.loads(l) for l in e.stdout.splitlines()]
            self.assertTrue(rows[0]['ok'],rows[0]);self.assertIn('country',rows[0]['transcript']['text'].casefold())
            self.assertTrue(rows[1]['ok'],rows[1]);self.assertNotEqual(reqs[0]['id'],reqs[1]['id'])  # said twice: two memories
            self.assertTrue(rows[-1]['sources']);self.assertEqual(rows[-1]['sources'][0]['kind'],'voice_note')
            self.assertFalse(any(Path(tmp).glob('*.wav.*')))

    def test_silence_produces_no_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav=Path(tmp)/'silence.wav'
            with wave.open(str(wav),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\x00\x00'*16000*3)
            p=voice('--consent','--model',MODEL,'--input-wav',wav);self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(p.stdout,'')


if __name__=='__main__':unittest.main()
