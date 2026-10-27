"""Milestone 7 voice capture: consent gate, voice-activity segmentation and storage through the engine. The microphone
is replaced by --input-wav (public sample audio); real microphone capture is not exercised by tests (consent)."""
import base64
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
import wave
import numpy as np
import psutil
import soundfile
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


def jfk():
    with wave.open(str(JFK)) as w:return np.frombuffer(w.readframes(w.getnframes()),'<i2').astype(np.float64)/32768


def write_wav(path,x,rate=16000,channels=1):
    pcm=(np.clip(x,-1,32767/32768)*32768).astype('<i2')
    if channels==2:pcm=np.repeat(pcm,2)  # identical interleaved left/right
    with wave.open(str(path),'wb') as w:w.setnchannels(channels);w.setsampwidth(2);w.setframerate(rate);w.writeframes(pcm.tobytes())


def segments(p):return [json.loads(l)['metadata'] for l in p.stdout.splitlines()]


class VoiceNoise(unittest.TestCase):
    """VAD behaviour on synthetic noise around public speech (file input only; scripts/benchmark_voice.py measures it at scale)."""
    def noisy_session(self,tmp):
        rng=np.random.default_rng(1);speech=jfk();gap=np.zeros(5*16000)
        x=np.concatenate([gap,speech,gap,speech,gap]);x=x+rng.standard_normal(len(x))*10**(-40/20)  # steady noise, ~18 dB SNR
        wav=Path(tmp)/'noisy.wav';write_wav(wav,x)
        return wav,[(5.0,5.0+len(speech)/16000),(10.0+len(speech)/16000,10.0+2*len(speech)/16000)]

    def test_adaptive_vad_segments_speech_in_steady_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav,spans=self.noisy_session(tmp)
            p=voice('--consent','--model',MODEL,'--input-wav',wav);self.assertEqual(p.returncode,0,p.stderr);segs=segments(p)
            self.assertTrue(segs,p.stderr)
            for s in segs:  # every segment lies on speech: no noise-only captures, no 30 s capped noise segments
                self.assertTrue(any(s['stream_start_ms']/1000>=a-1 and s['stream_end_ms']/1000<=b+1 for a,b in spans),s)
                self.assertEqual(s['vad'],'adaptive')
            for a,b in spans:
                covered=sum(max(0,min(b,s['stream_end_ms']/1000)-max(a,s['stream_start_ms']/1000)) for s in segs)
                self.assertGreater(covered,.85*(b-a))

    def test_legacy_vad_captures_noise_as_speech(self):
        # The original fixed -45 dBFS detector, kept for comparison: steady -40 dBFS noise holds it open (30 s caps).
        with tempfile.TemporaryDirectory() as tmp:
            wav,_=self.noisy_session(tmp)
            p=voice('--consent','--model',MODEL,'--vad','legacy','--input-wav',wav);self.assertEqual(p.returncode,0,p.stderr)
            self.assertTrue(any(s['duration_ms']>=29900 for s in segments(p)))

    def test_hum_and_clicks_do_not_trigger(self):
        with tempfile.TemporaryDirectory() as tmp:
            t=np.arange(12*16000)/16000;x=sum(a*np.sin(2*np.pi*hz*t) for hz,a in [(50,.03),(100,.02),(150,.01)])
            x[[16000*4,16000*8]]=.9  # two single-sample clicks
            wav=Path(tmp)/'hum.wav';write_wav(wav,x)
            p=voice('--consent','--model',MODEL,'--input-wav',wav);self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(p.stdout,'')
            self.assertEqual(json.loads(p.stderr.splitlines()[-1])['segments'],0)

    def test_resampled_stereo_input_and_clipping_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav=Path(tmp)/'48k.wav';write_wav(wav,np.repeat(np.concatenate([np.zeros(16000),jfk(),np.zeros(16000)]),3),48000,2)
            p=voice('--consent','--model',MODEL,'--input-wav',wav);self.assertEqual(p.returncode,0,p.stderr);segs=segments(p)
            self.assertTrue(segs);self.assertAlmostEqual(sum(s['speech_ms'] for s in segs)/1000,9.5,delta=2.5)
            hot=Path(tmp)/'hot.wav';write_wav(hot,np.concatenate([np.zeros(16000),jfk()*30,np.zeros(16000)]))
            p=voice('--consent','--model',MODEL,'--input-wav',hot);self.assertEqual(p.returncode,0,p.stderr)
            self.assertGreater(sum(s['clipped_samples'] for s in segments(p)),1000);self.assertIn('"clipping"',p.stderr)

    def test_paced_input_streams_like_a_device(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav=Path(tmp)/'paced.wav';write_wav(wav,np.concatenate([np.zeros(2*16000),jfk(),np.zeros(16000)]))  # 14 s
            start=time.perf_counter();p=voice('--consent','--model',MODEL,'--pace','4','--input-wav',wav)
            self.assertEqual(p.returncode,0,p.stderr);self.assertGreaterEqual(time.perf_counter()-start,3.0)
            self.assertTrue(segments(p));self.assertIn('"pace":4.0',p.stderr)

    def test_long_file_is_streamed_with_bounded_memory(self):
        # Twelve minutes of quiet room noise then speech: the file is decoded incrementally, never held whole in memory.
        with tempfile.TemporaryDirectory() as tmp:
            rng=np.random.default_rng(2);x=np.concatenate([rng.standard_normal(12*60*16000)*10**(-65/20),jfk(),np.zeros(16000)])
            wav=Path(tmp)/'long.wav';write_wav(wav,x)
            proc=subprocess.Popen([str(REL/'lens-voice.exe'),'--consent','--model',str(MODEL),'--max-seconds','1000','--input-wav',str(wav)],
                                  stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
            peak=0;handle=psutil.Process(proc.pid);result={}
            reader=threading.Thread(target=lambda:result.update(zip(('out','err'),proc.communicate(timeout=120))));reader.start()
            while reader.is_alive():
                try:peak=max(peak,handle.memory_info().rss)
                except psutil.Error:break
                time.sleep(.02)
            reader.join();out,err=result['out'],result['err'];self.assertEqual(proc.returncode,0,err)
            self.assertLess(peak,40_000_000);self.assertEqual(len(out.splitlines()),1,err)
            self.assertAlmostEqual(json.loads(err.splitlines()[-1])['processed_seconds'],12*60+12,delta=1)

    def test_unknown_vad_is_refused(self):
        p=voice('--consent','--model',MODEL,'--vad','magic','--input-wav',JFK);self.assertEqual(p.returncode,2);self.assertEqual(p.stdout,'')

    def test_segments_never_exceed_twenty_seconds(self):
        with tempfile.TemporaryDirectory() as tmp:
            speech=jfk();x=np.concatenate([np.zeros(16000)]+[speech[16000:-16000]]*4+[np.zeros(16000)])  # ~36 s, few pauses
            wav=Path(tmp)/'long-talk.wav';write_wav(wav,x)
            p=voice('--consent','--model',MODEL,'--input-wav',wav);self.assertEqual(p.returncode,0,p.stderr);segs=segments(p)
            self.assertGreaterEqual(len(segs),2);self.assertTrue(all(s['duration_ms']<=20000 for s in segs),segs)


FLEURS=ROOT/'data/external/fleurs'
LIBRI=ROOT/'data/external/librispeech/extracted/LibriSpeech/test-clean'
BASE=ROOT/'models/ggerganov--whisper.cpp/ggml-base-q5_1.bin'
SHERPA=ROOT/'.tools/sherpa-runtime/sherpa-onnx-v2.0.0-win-x64-shared-MD-Release-no-tts/lib/sherpa-onnx-c-api.dll'
SPEAKER=ROOT/'models/k2-fsa--speaker-recognition/nemo_en_titanet_small.onnx'


def fleurs_clip(config,index=0):
    m=json.loads((FLEURS/config/'manifest.json').read_text(encoding='utf-8'))[index];return ROOT/m['path'],m['reference']


def engine(lines):
    with tempfile.TemporaryDirectory() as tmp:
        e=subprocess.run([str(REL/'lens-engine.exe'),'--db',str(Path(tmp)/'m.db')],input=lines,capture_output=True,text=True,encoding='utf-8',timeout=600)
    return [json.loads(l) for l in e.stdout.splitlines()]


@unittest.skipUnless(SHERPA.exists() and (FLEURS/'hi_in/manifest.json').exists(),'sherpa runtime or FLEURS audio not present')
class VoiceLanguages(unittest.TestCase):
    """Language identification restricted to the user's languages and per-language routing (public FLEURS clips)."""
    def test_hindi_and_mandarin_route_to_their_models(self):
        for config,lang,provider in [('hi_in','hi','sherpa-onnx-indicconformer-ctc'),('cmn_hans_cn','zh','sherpa-onnx-dolphin-ctc')]:
            wav,_=fleurs_clip(config)
            p=voice('--consent','--model',BASE,'--input-wav',wav);self.assertEqual(p.returncode,0,p.stderr)
            reqs=p.stdout.splitlines();self.assertTrue(reqs);self.assertIn(lang,json.loads(reqs[0])['asr_routes'])
            rows=engine(reqs[0]+'\n')
            self.assertTrue(rows[0]['ok'],rows[0]);t=rows[0]['transcript']
            self.assertEqual(t['language'],lang);self.assertEqual(t['provider'],provider);self.assertEqual(t['language_source'],'whisper_lid_restricted')

    def test_identified_language_stays_in_the_allowed_set(self):
        # Regression for the live test (ko/ml/ca detected for en/ta/te/hi speech): auto LID may only pick allowed languages.
        allowed='en,hi,ta,te'
        for config in ['ta_in','te_in','hi_in']:
            wav,_=fleurs_clip(config)
            p=voice('--consent','--model',BASE,'--languages',allowed,'--no-routes','--input-wav',wav);self.assertEqual(p.returncode,0,p.stderr)
            reqs=p.stdout.splitlines();self.assertTrue(reqs)
            self.assertEqual(json.loads(reqs[0])['allowed_languages'],allowed.split(','))
            for row in engine(''.join(r+'\n' for r in reqs)):
                if row.get('ok'):self.assertIn(row['transcript']['language'],allowed.split(','),row['transcript'])
                else:self.assertIn(row['error'],['no_speech_found','repetition_rejected','low_confidence_transcript'])


class VoiceFilter(unittest.TestCase):
    def test_noise_is_not_stored_as_a_transcript(self):
        # Low noise sent straight to the engine (no VAD): whisper's [BLANK_AUDIO]-style output must never be stored.
        with tempfile.TemporaryDirectory() as tmp:
            rng=np.random.default_rng(5);wav=Path(tmp)/'noise.wav';write_wav(wav,rng.standard_normal(4*16000)*10**(-60/20))
            audio=base64.b64encode(wav.read_bytes()).decode()
        req={'op':'ingest_audio','consent':True,'id':'voice-noise','audio_base64':audio,'model':str(MODEL),'language':'auto',
             'allowed_languages':['en','hi'],'timestamp':'2026-10-27T10:00:00Z','device':'test','kind':'voice_note','provenance':'test',
             'min_confidence':0.0}
        row=engine(json.dumps(req)+'\n')[0]
        self.assertFalse(row['ok'],row);self.assertIn(row['error'],['no_speech_found','repetition_rejected','low_confidence_transcript'])


@unittest.skipUnless(SHERPA.exists() and SPEAKER.exists() and LIBRI.exists(),'speaker model, sherpa runtime or LibriSpeech not present')
class VoiceOwner(unittest.TestCase):
    """Owner-only capture: segments from anyone but the enrolled speaker never leave lens-voice."""
    def utterances(self,speaker,n):
        files=sorted((LIBRI/speaker).rglob('*.flac'))[:n];return [soundfile.read(f,dtype='float64')[0] for f in files]

    def test_only_the_enrolled_speaker_is_emitted(self):
        speakers=sorted(p.name for p in LIBRI.iterdir());owner,other=speakers[0],speakers[1]
        with tempfile.TemporaryDirectory() as tmp:
            gap=np.zeros(int(1.5*16000));own=self.utterances(owner,9);oth=self.utterances(other,3)
            enrol=Path(tmp)/'enrol.wav';write_wav(enrol,np.concatenate([x for u in own[:6] for x in (u,gap)]))
            profile=Path(tmp)/'owner.profile'
            p=voice('--consent','--model',MODEL,'--enroll',profile,'--input-wav',enrol);self.assertEqual(p.returncode,0,p.stderr)
            self.assertIn('"enrolled"',p.stderr);raw=profile.read_bytes();self.assertNotIn(b'embedding',raw)  # DPAPI, not plaintext
            mixed=[own[6],oth[0],own[7],oth[1],own[8],oth[2]];session=Path(tmp)/'mixed.wav'
            write_wav(session,np.concatenate([gap]+[x for u in mixed for x in (u,gap)]))
            p=voice('--consent','--model',MODEL,'--speaker-profile',profile,'--input-wav',session);self.assertEqual(p.returncode,0,p.stderr)
            segs=segments(p);self.assertTrue(segs);self.assertTrue(all(s['speaker']['verified'] for s in segs))
            spans=[];t=1.5
            for u in mixed:spans.append((t,t+len(u)/16000));t+=len(u)/16000+1.5
            for s in segs:  # every emitted segment lies on an owner utterance (even indices)
                mid=(s['stream_start_ms']+s['stream_end_ms'])/2000
                self.assertTrue(any(a-.5<=mid<=b+.5 for i,(a,b) in enumerate(spans) if i%2==0),s)
            self.assertGreaterEqual(json.loads(p.stderr.splitlines()[-1])['speaker_rejected'],1)

    def test_owner_mode_refuses_without_a_profile(self):
        p=voice('--consent','--model',MODEL,'--require-owner','--input-wav',JFK);self.assertEqual(p.returncode,2);self.assertEqual(p.stdout,'')
        self.assertIn('speaker_profile_required',p.stderr)


if __name__=='__main__':unittest.main()
