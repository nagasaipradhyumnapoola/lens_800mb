"""File-driven voice capture evaluation (lens-voice -> lens-engine); never opens a microphone.

Public FLEURS test utterances (CC BY 4.0, data/external/fleurs) are concatenated into sessions with silences and mixed
with synthetic noise (white, pink, babble from FLEURS clips of non-evaluated languages, fan rumble with mains hum) at
fixed SNRs. lens-voice reads each session with --input-wav; its requests are relayed to a lens-engine on a temporary
encrypted database. Measured: VAD segmentation against reference speech regions (missed speech, false triggers,
non-speech captured), end-to-end WER/CER of the stored transcripts against FLEURS references, latency from speech end
to stored memory (paced runs only), and the working set / private bytes of lens-voice and lens-engine.

Clips are split by FLEURS sentence id (sha256 bucket): dev (~30%) is the only data used to choose VAD parameters
(`tune`); held-out sessions are only reported. Synthetic audio and temporary databases live in a temp directory and
are deleted; reports/voice/ keeps metrics and transcripts of public data only.

  python scripts/benchmark_voice.py vad --split dev --vad legacy|adaptive [--set k=v ...]
  python scripts/benchmark_voice.py tune                       (dev only)
  python scripts/benchmark_voice.py asr --split heldout --vad adaptive [--conditions ...]
  python scripts/benchmark_voice.py latency --vad adaptive     (pace 1.0, held-out)
  python scripts/benchmark_voice.py soak --minutes 32          (paced 1.0 long session, RSS sampled)
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import psutil
import shutil
import soundfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from benchmarks.metrics import error_rate
REL=ROOT/'build/engine/Release'
OUT=ROOT/'reports/voice'
WHISPER=ROOT/'models/ggerganov--whisper.cpp'
SR=16000
LANGS={'en':'en_us','es':'es_419','zh':'cmn_hans_cn','hi':'hi_in','ta':'ta_in','te':'te_in'}
# Founder language scope (docs/LENS_V1_SPEC.md 1a): 10 world + 7 Indian languages, FLEURS configs.
GLOBAL={'en':'en_us','zh':'cmn_hans_cn','es':'es_419','ar':'ar_eg','fr':'fr_fr','pt':'pt_br','ru':'ru_ru','id':'id_id','de':'de_de',
        'ja':'ja_jp','hi':'hi_in','bn':'bn_in','te':'te_in','mr':'mr_in','ta':'ta_in','ur':'ur_pk','gu':'gu_in'}
LANGS={**LANGS,**GLOBAL}
BABBLE_SOURCES=['de_de','fr_fr','pt_br','ja_jp','ko_kr','ar_eg']  # never evaluated here
TARGET_DB=-26.0  # nominal active speech level; SNR is relative to it
NOISES=['white','pink','babble','fan']
CONDITIONS=(['clean','raw_level','quiet','hot','resample48k']+[f'{n}{s}' for n in NOISES for s in (20,10,5)])
# Tuning start = result of round 1 (reports/voice/tune-dev-round1.log.txt); round 2 chose the band-pass and floor
# percentile, now the lens-voice defaults (reports/voice/vad-tuning-dev.json).
ADAPTIVE_DEFAULTS={'threshold-db':-65,'on-margin-db':8,'off-margin-db':4,'silence-ms':600,'min-speech-ms':150,'onset-ms':60,'tail-ms':500,
                   'hpf-hz':80,'lpf-hz':3000,'floor-percentile':20}


def db(x):return 20*np.log10(max(float(x),1e-12))
def rms(x):return float(np.sqrt(np.mean(np.square(x,dtype=np.float64)))) if len(x) else 0.0


def load(path):
    a,sr=soundfile.read(path,dtype='float32',always_2d=True);a=a.mean(axis=1)
    if sr!=SR:raise ValueError(f'{path}: {sr} Hz')
    return a


def frame_levels(x,n):
    k=len(x)//n;f=x[:k*n].reshape(k,n).astype(np.float64);return 10*np.log10(np.mean(f*f,axis=1)+1e-12)


def active_level(x):
    """RMS (dB) of 30 ms frames within 30 dB of the loudest frame: a simple active-speech level."""
    lv=frame_levels(x,480);act=lv[lv>lv.max()-30];return 10*np.log10(np.mean(10**(act/10)))


def speech_activity(x):
    """Reference speech from the clean clip: 10 ms frames within 35 dB of the loudest frame, gaps under 300 ms filled,
    islands under 50 ms dropped. Returns merged [start, end] intervals in seconds (FLEURS clips carry lead/trail silence)."""
    lv=frame_levels(x,160);on=lv>lv.max()-35;spans=[];i=0
    while i<len(on):
        if on[i]:
            j=i
            while j<len(on) and on[j]:j+=1
            spans.append([i*.01,j*.01]);i=j
        else:i+=1
    merged=[]
    for s in spans:
        if merged and s[0]-merged[-1][1]<.3:merged[-1][1]=s[1]
        else:merged.append(s)
    return [m for m in merged if m[1]-m[0]>=.05]


MAX_CLIPS=[None]  # --max-clips: same number of FLEURS clips per language (the first N archive members)


def clips(lang):
    folder=ROOT/'data/external/fleurs'/LANGS[lang]
    out=[]
    for m in json.loads((folder/'manifest.json').read_text(encoding='utf-8'))[:MAX_CLIPS[0]]:
        sid=m['id'].split('-')[2]
        bucket=int(hashlib.sha256(f'{lang}:{sid}'.encode()).hexdigest()[:8],16)%10
        out.append({'id':m['id'],'path':ROOT/m['path'],'reference':m['reference'],'sentence':sid,
                    'split':'dev' if bucket<3 else 'heldout','sha256':m['sha256']})
    return out


def shaped_noise(n,rng,exponent):
    """Gaussian noise with power spectrum ~ 1/f^exponent (0 white, 1 pink, 2 brown), unit RMS."""
    spec=np.fft.rfft(rng.standard_normal(n));f=np.fft.rfftfreq(n,1/SR);f[0]=f[1]
    y=np.fft.irfft(spec/f**(exponent/2),n);return y/rms(y)


_babble_cache={}
def babble(n,rng):
    if 'pool' not in _babble_cache:
        pool=[]
        for cfg in BABBLE_SOURCES:
            for m in json.loads((ROOT/'data/external/fleurs'/cfg/'manifest.json').read_text(encoding='utf-8'))[:2]:
                a=load(ROOT/m['path']);pool.append(a*10**((TARGET_DB-active_level(a))/20))
        _babble_cache['pool']=pool
    pool=_babble_cache['pool'];y=np.zeros(n)
    for talker in range(6):  # six overlapping talkers, each a looped random-offset stream
        stream=np.concatenate([pool[i] for i in rng.permutation(len(pool))]);start=rng.integers(len(stream))
        y+=np.resize(np.roll(stream,-start),n)
    return y/rms(y)


def fan(n,rng):
    t=np.arange(n)/SR
    rumble=shaped_noise(n,rng,2.0)  # low-frequency broadband air noise
    tones=sum(a*np.sin(2*np.pi*hz*t+rng.uniform(0,6.3)) for hz,a in [(50,1.0),(100,.6),(150,.4),(250,.2),(95,.8),(190,.4)])
    y=rumble+.8*tones/rms(tones);y*=1+.2*np.sin(2*np.pi*.5*t)  # mains hum + blade-pass tone, slow modulation
    return y/rms(y)


def noise(kind,n,rng):
    if kind=='white':return shaped_noise(n,rng,0)
    if kind=='pink':return shaped_noise(n,rng,1)
    if kind=='babble':return babble(n,rng)
    if kind=='fan':return fan(n,rng)
    raise ValueError(kind)


def parse_condition(c):
    for kind in NOISES:
        if c.startswith(kind):return kind,float(c[len(kind):])
    return None,None


def build_session(lang,items,condition,seed):
    """Concatenate clips with 1.2-4 s gaps (2 s lead/tail); returns (audio at 16 kHz, references, sample rate to write)."""
    rng=np.random.default_rng(seed);kind,snr=parse_condition(condition)
    level={'quiet':-46.0,'hot':-4.0}.get(condition,TARGET_DB)
    parts=[np.zeros(int(2*SR),np.float32)];refs=[];pos=len(parts[0])
    for item in items:
        a=load(item['path'])
        if condition!='raw_level':
            gain=level+rng.uniform(-4,4)-active_level(a)
            if condition!='hot':gain=min(gain,db(.89/max(np.abs(a).max(),1e-9)))  # only 'hot' clips
            a=a*10**(gain/20)
        act=[[pos/SR+a0,pos/SR+a1] for a0,a1 in speech_activity(a)]
        refs.append({'clip':item['id'],'speaker':item.get('speaker'),'sentence':item['sentence'],'reference':item['reference'],'start':act[0][0],'end':act[-1][1],'active':act,
                     'level_dbfs':round(float(active_level(a)),1)})
        parts.append(a.astype(np.float32));pos+=len(a)
        gap=np.zeros(int(rng.uniform(1.2,4.0)*SR),np.float32);parts.append(gap);pos+=len(gap)
    parts.append(np.zeros(int(2*SR),np.float32))
    audio=np.concatenate(parts).astype(np.float64)
    if kind:audio+=noise(kind,len(audio),rng)*10**((TARGET_DB-snr)/20)
    elif condition=='quiet':audio+=shaped_noise(len(audio),rng,1)*10**((level-25)/20)
    elif condition=='hot':audio+=shaped_noise(len(audio),rng,1)*10**((level-30)/20)
    audio+=rng.standard_normal(len(audio))*10**(-80/20)  # microphone self-noise; real input is never digital silence
    return audio,refs,(48000 if condition=='resample48k' else SR)


def write_wav(path,audio,rate):
    if rate!=SR:  # band-limited FFT resampling to 48 kHz stereo exercises lens-voice's decoder resampler
        n=int(round(len(audio)*rate/SR));spec=np.fft.rfft(audio);out=np.zeros(n//2+1,complex);out[:len(spec)]=spec
        audio=np.fft.irfft(out,n)*rate/SR;audio=np.stack([audio,audio],axis=1)
    soundfile.write(path,np.clip(audio,-1,32767/32768),rate,subtype='PCM_16')


def sessions(lang,split,per_session=8,limit=None):
    items=[c for c in clips(lang) if c['split']==split]
    groups=[items[i:i+per_session] for i in range(0,len(items),per_session)]
    groups=[g for g in groups if len(g)>=max(2,per_session//2)] or ([items] if items else [])
    return groups[:limit] if limit else groups


def voice_args(vad,params,lang,model,language_mode):
    a=['--consent','--model',model,'--vad',vad,'--device-name','benchmark','--max-seconds','100000',
       '--language','auto' if language_mode=='auto' else lang]
    for k,v in (params or {}).items():a+=[f'--{k}'] if k=='no-routes' else [f'--{k}',str(v)]
    return a


class Sampler(threading.Thread):
    """Working set and private bytes of named processes every 200 ms."""
    def __init__(self,procs):
        super().__init__(daemon=True);self.procs=procs;self.rows=[];self.stop=threading.Event();self.t0=time.perf_counter()
    def run(self):
        handles={}
        for k,p in self.procs.items():
            try:handles[k]=psutil.Process(p.pid)
            except psutil.Error:pass
        while not self.stop.is_set():
            row={'t':round(time.perf_counter()-self.t0,2)}
            for k,h in handles.items():  # a process and its children (lens-engine runs routed ASR in lens-sherpa)
                ws=pv=0
                try:procs=[h]+h.children(recursive=True)
                except psutil.Error:procs=[]
                for q in procs:
                    try:m=q.memory_info();ws+=m.rss;pv+=m.private
                    except psutil.Error:pass
                row[k+'_ws']=ws;row[k+'_private']=pv
            self.rows.append(row);self.stop.wait(.2)


def run_pipeline(wav,args,engine=True,pace=0.0,timeout=7200):
    """lens-voice on a file; each request relayed to lens-engine. Returns segments, responses and timings."""
    tmp=Path(tempfile.mkdtemp(prefix='lens-voice-bench-'))
    cmd=[str(REL/'lens-voice.exe'),*map(str,args),'--input-wav',str(wav)]+(['--pace',str(pace)] if pace else [])
    voice=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    eng=subprocess.Popen([str(REL/'lens-engine.exe'),'--db',str(tmp/'memory.db')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL) if engine else None
    sampler=Sampler({'voice':voice,**({'engine':eng} if eng else {})});sampler.start()
    status=[];t_record=[None]
    def read_err():
        for line in voice.stderr:
            try:ev=json.loads(line)
            except json.JSONDecodeError:continue
            if ev.get('event')=='recording' and t_record[0] is None:t_record[0]=time.perf_counter()
            status.append(ev)
    err=threading.Thread(target=read_err,daemon=True);err.start()
    segments=[];deadline=time.perf_counter()+timeout
    for line in voice.stdout:
        t_emit=time.perf_counter();req=json.loads(line);meta=req['metadata']
        seg={'start':meta['stream_start_ms']/1000,'end':meta['stream_end_ms']/1000,'speech_end':meta['speech_end_ms']/1000,
             'speech_ms':meta['speech_ms'],'speaker':meta.get('speaker'),'clipped':meta['clipped_samples'],'noise_floor':meta['noise_floor_dbfs'],'t_emit':t_emit}
        if eng:
            eng.stdin.write((json.dumps(req)+'\n').encode());eng.stdin.flush()
            resp=json.loads(eng.stdout.readline());seg['t_stored']=time.perf_counter();seg['asr_ms']=round((seg['t_stored']-t_emit)*1000)
            seg['ok']=resp.get('ok',False);seg['error']=resp.get('error')
            tr=resp.get('transcript') or {};seg['text']=tr.get('text','');seg['language']=tr.get('language')
            seg['provider']=tr.get('provider');seg['speaker']=meta.get('speaker');seg['token_probability']=tr.get('token_probability');seg['lid']=tr.get('language_identification')
        segments.append(seg)
        if time.perf_counter()>deadline:voice.kill();break
    voice.stdin.close();voice.wait(timeout=60);err.join(timeout=10)
    stats=None
    if eng:
        eng.stdin.write(b'{"op":"stats"}\n');eng.stdin.flush();stats=json.loads(eng.stdout.readline());eng.stdin.close();eng.wait(timeout=60)
    sampler.stop.set();sampler.join()
    shutil.rmtree(tmp,ignore_errors=True)
    return {'segments':segments,'status':status,'t_record':t_record[0],'ram':sampler.rows,'stats':stats,'exit_code':voice.returncode}


def overlap(a0,a1,b0,b1):return max(0.0,min(a1,b1)-max(a0,b0))


def score_vad(refs,segs,duration):
    """Missed speech = reference-active time outside every segment; an utterance is detected when >= 90% of its active
    time is inside segments; a false trigger is a segment touching no utterance (+-0.3 s); non-speech captured is
    segment time outside utterances widened by a 0.3 s lead / 0.8 s hangover collar."""
    def inside(a0,a1):return sum(overlap(a0,a1,s['start'],s['end']) for s in segs)
    speech=sum(a1-a0 for r in refs for a0,a1 in r['active']);covered=sum(min(inside(a0,a1),a1-a0) for r in refs for a0,a1 in r['active'])
    detected=sum(1 for r in refs if sum(min(inside(a0,a1),a1-a0) for a0,a1 in r['active'])>=.9*sum(a1-a0 for a0,a1 in r['active']))
    false_trig=sum(1 for s in segs if not any(overlap(r['start']-.3,r['end']+.3,s['start'],s['end'])>0 for r in refs))
    collar=[(r['start']-.3,r['end']+.8) for r in refs]
    nonspeech=duration-sum(b-a for a,b in collar)
    extra=sum((s['end']-s['start'])-sum(overlap(a,b,s['start'],s['end']) for a,b in collar) for s in segs)
    return {'reference_utterances':len(refs),'segments':len(segs),'detected_utterances':detected,
            'missed_speech_s':round(speech-covered,3),'speech_s':round(speech,3),
            'false_trigger_segments':false_trig,'nonspeech_captured_s':round(max(extra,0),3),'nonspeech_s':round(nonspeech,3),
            'capped_segments':sum(1 for s in segs if s['end']-s['start']>=29.9),'duration_s':round(duration,3)}


def aggregate_vad(rows):
    t=lambda k:sum(r[k] for r in rows)
    return {'sessions':len(rows),'utterances':t('reference_utterances'),'segments':t('segments'),
            'utterance_recall':round(t('detected_utterances')/max(t('reference_utterances'),1),4),
            'missed_speech':round(t('missed_speech_s')/max(t('speech_s'),1e-9),4),
            'nonspeech_captured':round(t('nonspeech_captured_s')/max(t('nonspeech_s'),1e-9),4),
            'false_triggers_per_10min':round(t('false_trigger_segments')/max(t('duration_s'),1e-9)*600,3),
            'capped_segments':t('capped_segments')}


def vad_cost(a):
    """Tuning objective (dev only): lost speech weighs three times captured non-speech; capped segments penalised."""
    return 3*a['missed_speech']+a['nonspeech_captured']+.02*a['capped_segments']/max(a['sessions'],1)


def session_files(langs,split,conditions,tmp,per_session=8,limit=None):
    for lang in langs:
        for gi,group in enumerate(sessions(lang,split,per_session,limit)):
            for cond in conditions:
                seed=int(hashlib.sha256(f'{lang}:{split}:{gi}:{cond}'.encode()).hexdigest()[:8],16)
                audio,refs,rate=build_session(lang,group,cond,seed)
                wav=Path(tmp)/f'{lang}-{split}-{gi}-{cond}.wav';write_wav(wav,audio,rate)
                yield lang,gi,cond,wav,refs,len(audio)/SR


def prepare(langs,split,conditions,tmp,per_session=8,limit=None):
    return list(session_files(langs,split,conditions,tmp,per_session,limit))


def evaluate_vad(langs,split,conditions,vad,params,per_session=8,limit=None,prepared=None,workers=3):
    """VAD only (no engine, no ASR); session files are built once and may be shared between trials."""
    def one(item):
        lang,gi,cond,wav,refs,dur=item
        r=run_pipeline(wav,voice_args(vad,params,lang,WHISPER/'ggml-base-q5_1.bin','auto'),engine=False)
        return {'language':lang,'session':gi,'condition':cond,**score_vad(refs,r['segments'],dur)}
    with tempfile.TemporaryDirectory(prefix='lens-voice-vad-') as tmp:
        items=prepared if prepared is not None else prepare(langs,split,conditions,tmp,per_session,limit)
        with ThreadPoolExecutor(workers) as pool:return list(pool.map(one,items))


def summarize(rows,keys):
    out={}
    for row in rows:out.setdefault(tuple(row[k] for k in keys),[]).append(row)
    return {'|'.join(k):aggregate_vad(v) for k,v in sorted(out.items())}


def model_for(lang,mode):
    if mode=='product':return WHISPER/'ggml-base-q5_1.bin'  # what lens-agent launches (language auto)
    return WHISPER/('ggml-small-q5_1.bin' if lang in ('es','zh','hi','ta','te') else 'ggml-base-q5_1.bin')


def asr_scores(refs,segs,lang):
    ref=' '.join(r['reference'] for r in refs);hyp=' '.join(s.get('text','') for s in segs if s.get('ok'))
    we,wc=error_rate(ref,hyp);ce,cc=error_rate(ref,hyp,chars=True)
    return {'word_errors':we,'reference_words':wc,'character_errors':ce,'reference_characters':cc,
            'stored':sum(1 for s in segs if s.get('ok')),'failed':sum(1 for s in segs if not s.get('ok')),
            'errors':sorted({s.get('error') for s in segs if not s.get('ok')}-{None}),'hypothesis':hyp,'reference':ref}


def latency(refs,segs,t_record,pace):
    out=[]
    for r in refs:
        hit=[s for s in segs if s['start']<=r['end']<=s['end']+.05 and 't_stored' in s] or \
            [s for s in segs if overlap(r['start'],r['end'],s['start'],s['end'])>0 and 't_stored' in s]
        if not hit:continue
        s=hit[-1];spoken=t_record+r['end']/pace
        out.append({'clip':r['clip'],'emit_ms':round((s['t_emit']-spoken)*1000),'stored_ms':round((s['t_stored']-spoken)*1000)})
    return out


def pct(v,p):
    v=sorted(v);return v[min(len(v)-1,int(round(p/100*(len(v)-1))))] if v else None


def ram_summary(rows):
    if not rows:return {}
    tot=[r.get('voice_ws',0)+r.get('engine_ws',0) for r in rows];priv=[r.get('voice_private',0)+r.get('engine_private',0) for r in rows]
    return {'samples':len(rows),'peak_sum_working_set_bytes':max(tot),'peak_sum_private_bytes':max(priv),
            'peak_voice_working_set_bytes':max(r.get('voice_ws',0) for r in rows),
            'peak_engine_working_set_bytes':max(r.get('engine_ws',0) for r in rows),
            'peak_engine_private_bytes':max(r.get('engine_private',0) for r in rows)}


def run_asr(langs,split,conditions,vad,params,mode,per_session,limit,pace=0.0,label='asr'):
    rows=[]
    with tempfile.TemporaryDirectory(prefix='lens-voice-asr-') as tmp:
        for lang,gi,cond,wav,refs,dur in session_files(langs,split,conditions,tmp,per_session,limit):
            args=voice_args(vad,params,lang,model_for(lang,mode),'auto' if mode=='product' else 'configured')
            t=time.perf_counter();r=run_pipeline(wav,args,engine=True,pace=pace);wall=time.perf_counter()-t
            row={'language':lang,'session':gi,'condition':cond,'vad':vad,'mode':mode,'pace':pace,'wall_s':round(wall,1),
                 **score_vad(refs,r['segments'],dur),**asr_scores(refs,r['segments'],lang),'ram':ram_summary(r['ram']),
                 'stored_observations':(r['stats'] or {}).get('source_count'),
                 'asr_ms':[s.get('asr_ms') for s in r['segments']],'detected_languages':[s.get('language') for s in r['segments']],
                 'segments_detail':[{k:s.get(k) for k in ('start','end','ok','error','text','language','provider','token_probability','lid','asr_ms')} for s in r['segments']]}
            if pace:row['latency']=latency(refs,r['segments'],r['t_record'],pace)
            rows.append(row);wav.unlink()
            print(lang,cond,vad,f"WER={row['word_errors']/max(row['reference_words'],1):.3f}",
                  f"CER={row['character_errors']/max(row['reference_characters'],1):.3f}",f"segs={row['segments']}",f"wall={wall:.0f}s",flush=True)
    return rows


def asr_table(rows):
    out={}
    for r in rows:out.setdefault((r['language'],r['condition'],r['vad'],r['mode']),[]).append(r)
    table=[]
    for (lang,cond,vad,mode),g in sorted(out.items()):
        t=lambda k:sum(x[k] for x in g)
        table.append({'language':lang,'condition':cond,'vad':vad,'mode':mode,'sessions':len(g),'utterances':t('reference_utterances'),
                      'segments':t('segments'),'stored':t('stored'),'failed':t('failed'),
                      'wer':round(t('word_errors')/max(t('reference_words'),1),4),'cer':round(t('character_errors')/max(t('reference_characters'),1),4),
                      **{k:v for k,v in aggregate_vad(g).items() if k in ('utterance_recall','missed_speech','nonspeech_captured','false_triggers_per_10min')},
                      'peak_sum_working_set_bytes':max(x['ram'].get('peak_sum_working_set_bytes',0) for x in g),
                      'p95_asr_ms':pct([a for x in g for a in x['asr_ms'] if a is not None],95)})
    return table


def write(name,obj):
    OUT.mkdir(parents=True,exist_ok=True);(OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=1),encoding='utf-8')


def provenance():
    def h(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
    return {'lens_voice_sha256':h(REL/'lens-voice.exe'),'lens_engine_sha256':h(REL/'lens-engine.exe'),
            'whisper_base_sha256':h(WHISPER/'ggml-base-q5_1.bin'),'dataset':'google/fleurs test, revision 70bb2e84b976b7e960aa89f1c648e09c59f894dd (CC BY 4.0)',
            'split_rule':'sha256(lang:sentence_id) bucket <3 of 10 = dev, else heldout','time':time.strftime('%Y-%m-%dT%H:%M:%S'),
            'git_head':subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True).stdout.strip()}


def parse_set(items):
    out={}
    for s in items or []:k,v=s.split('=',1);out[k]=float(v) if '.' in v else int(v)
    return out


def tune():
    """Coordinate descent over adaptive VAD parameters on dev sessions only (no ASR)."""
    grid={'hpf-hz':[80,120,200,300],'lpf-hz':[0,3000,4000],'floor-percentile':[5,10,20,30],
          'on-margin-db':[6,8,10,12,15],'off-margin-db':[3,4,6,8],'silence-ms':[400,600,800,1000],'min-speech-ms':[150,300,500],
          'onset-ms':[30,60,90,150],'threshold-db':[-70,-65,-60,-55,-50],'tail-ms':[150,300,500]}
    langs=['en','es','zh','hi'];best=dict(ADAPTIVE_DEFAULTS);log=[]
    tmp=tempfile.TemporaryDirectory(prefix='lens-voice-tune-');prepared=prepare(langs,'dev',CONDITIONS,tmp.name,limit=2)
    def cost(params):
        a=aggregate_vad(evaluate_vad(langs,'dev',CONDITIONS,'adaptive',params,prepared=prepared));c=vad_cost(a)
        log.append({'params':dict(params),'aggregate':a,'cost':round(c,5)});print(json.dumps(log[-1]),flush=True);return c
    best_cost=cost(best)
    for _ in range(2):
        changed=False
        for k,values in grid.items():
            for v in values:
                if v==best[k]:continue
                trial={**best,k:v};c=cost(trial)
                if c<best_cost-1e-6:best,best_cost,changed=trial,c,True
        if not changed:break
    legacy=aggregate_vad(evaluate_vad(langs,'dev',CONDITIONS,'legacy',{},prepared=prepared));tmp.cleanup()
    write('vad-tuning-dev.json',{'provenance':provenance(),'objective':'3*missed_speech + nonspeech_captured + 0.02*capped/session',
                                 'split':'dev','sessions_per_language':2,'conditions':CONDITIONS,'best':best,'best_cost':best_cost,
                                 'legacy_dev':legacy,'legacy_cost':vad_cost(legacy),'trials':log})
    print('best',best,best_cost,'legacy',vad_cost(legacy))


def soak(minutes,vad,params):
    """One paced (1.0x) session of >= `minutes` from all English clips, noise changing every few minutes, plus idle stretches."""
    rng=np.random.default_rng(7);items=clips('en');parts=[];refs=[];pos=0;n_target=int(minutes*60*SR)
    plan=['clean','pink20','fan10','babble10','white10','pink5','clean','fan20']
    with tempfile.TemporaryDirectory(prefix='lens-voice-soak-') as tmp:
        block=0
        while pos<n_target:
            cond=plan[block%len(plan)];chunk=[items[i] for i in rng.choice(len(items),8,replace=False)]
            audio,r,_=build_session('en',chunk,cond,int(rng.integers(1<<30)))
            if block%3==2:audio=np.concatenate([audio,build_idle(cond,int(120*SR),rng)])  # two minutes of room noise only
            for x in r:
                x['start']+=pos/SR;x['end']+=pos/SR;x['condition']=cond;x['active']=[[a0+pos/SR,a1+pos/SR] for a0,a1 in x['active']]
            refs+=r;parts.append(audio.astype(np.float32));pos+=len(audio);block+=1
        audio=np.concatenate(parts);wav=Path(tmp)/'soak.wav';write_wav(wav,audio,SR)
        args=voice_args(vad,params,'en',WHISPER/'ggml-base-q5_1.bin','auto')
        t=time.perf_counter();r=run_pipeline(wav,args,engine=True,pace=1.0,timeout=int(minutes*60*2+600));wall=time.perf_counter()-t
    segs=r['segments'];lat=latency(refs,segs,r['t_record'],1.0)
    ram=r['ram'];half=len(ram)//2
    def slope(key):  # bytes per minute, least squares over the second half (after warm-up)
        xs=np.array([x['t'] for x in ram[half:]]);ys=np.array([x[key] for x in ram[half:]],float)
        return float(np.polyfit(xs/60,ys,1)[0]) if len(xs)>2 else None
    idle_engine=[x['engine_ws'] for x in ram if x['engine_ws']<100e6]
    result={'provenance':provenance(),'vad':vad,'params':params,'stream_seconds':round(len(audio)/SR,1),'wall_seconds':round(wall,1),
            'exit_code':r['exit_code'],'stopped':[s for s in r['status'] if s.get('event')=='stopped'],
            'vad_scores':score_vad(refs,segs,len(audio)/SR),**{k:v for k,v in asr_scores(refs,segs,'en').items() if k not in ('hypothesis','reference')},
            'stored_observations':(r['stats'] or {}).get('source_count'),'ram':ram_summary(ram),
            'voice_ws_slope_bytes_per_min_second_half':slope('voice_ws'),'voice_private_slope_bytes_per_min_second_half':slope('voice_private'),
            'engine_idle_ws_first_last':[idle_engine[0],idle_engine[-1]] if idle_engine else None,
            'latency_ms':{'utterances':len(lat),'p50_stored':pct([x['stored_ms'] for x in lat],50),'p95_stored':pct([x['stored_ms'] for x in lat],95),
                          'max_stored':max([x['stored_ms'] for x in lat],default=None),'p50_emit':pct([x['emit_ms'] for x in lat],50)},
            'ram_series_every_10th':ram[::10]}
    write('soak.json',result);print(json.dumps({k:v for k,v in result.items() if k!='ram_series_every_10th'},indent=1))


def build_idle(cond,n,rng):
    kind,snr=parse_condition(cond);y=rng.standard_normal(n)*10**(-80/20)
    if kind:y=y+noise(kind,n,rng)*10**((TARGET_DB-snr)/20)
    return y


LIBRI=ROOT/'data/external/librispeech/extracted/LibriSpeech/test-clean'


def libri_speakers(split):
    """LibriSpeech test-clean (CC BY 4.0, openslr 12) speakers, split by sha256(speaker) bucket <3/10 = dev."""
    out={}
    for spk in sorted(LIBRI.iterdir()):
        if (int(hashlib.sha256(f'libri:{spk.name}'.encode()).hexdigest()[:8],16)%10<3)!=(split=='dev'):continue
        utts=[]
        for chap in sorted(spk.iterdir()):
            text=dict(l.split(' ',1) for l in (chap/f'{spk.name}-{chap.name}.trans.txt').read_text().splitlines())
            for f in sorted(chap.glob('*.flac')):utts.append({'id':f.stem,'path':f,'reference':text[f.stem],'sentence':f.stem,'speaker':spk.name})
        out[spk.name]=utts
    return out


def speaker_eval(split,threshold,conditions,owners=None):
    """Per owner: enrol on >= 20 s of their speech, then a session of 6 unseen owner utterances interleaved with 4 other
    LibriSpeech speakers and 2 FLEURS clips (other languages). Similarity per utterance = best overlapping segment."""
    spk=libri_speakers(split);rows=[];rng=np.random.default_rng(11)
    fleurs=[c for lang in ('en','es','zh','hi','ta','te') for c in clips(lang)]
    model=WHISPER/'ggml-base-q5_1.bin'
    with tempfile.TemporaryDirectory(prefix='lens-voice-spk-') as tmp:
        for owner in list(spk)[:owners]:
            utts=spk[owner];enrol=[];sec=0
            while sec<20 and len(enrol)<len(utts)-6:u=utts[len(enrol)];enrol.append(u);sec+=soundfile.info(str(u['path'])).duration
            audio,_,_=build_session('en',enrol,'clean',1);ewav=Path(tmp)/f'{owner}-enrol.wav';write_wav(ewav,audio,SR)
            prof=Path(tmp)/f'{owner}.profile'
            p=subprocess.run([str(REL/'lens-voice.exe'),'--consent','--model',str(model),'--enroll',str(prof),'--input-wav',str(ewav)],
                             capture_output=True,text=True,encoding='utf-8',timeout=600)
            if p.returncode!=0:rows.append({'owner':owner,'error':p.stderr[-300:]});continue
            others=[u for k,v in spk.items() if k!=owner for u in v]
            test=utts[len(enrol):len(enrol)+6];imp=[others[i] for i in rng.choice(len(others),4,replace=False)]
            imp+=[{**fleurs[i],'speaker':'fleurs'} for i in rng.choice(len(fleurs),2,replace=False)]
            order=test+imp;order=[order[i] for i in rng.permutation(len(order))]
            for cond in conditions:
                audio,refs,rate=build_session('en',order,cond,int(owner)+len(cond));wav=Path(tmp)/f'{owner}-{cond}.wav';write_wav(wav,audio,rate)
                r=run_pipeline(wav,['--consent','--model',model,'--speaker-profile',prof,'--speaker-threshold',threshold,'--max-seconds','100000'],engine=False)
                for ref in refs:
                    sims=[(sg['speaker'] or {}).get('similarity') for sg in r['segments'] if overlap(ref['start'],ref['end'],sg['start'],sg['end'])>0]
                    sims=[x for x in sims if x is not None]
                    rows.append({'owner':owner,'condition':cond,'utterance':ref['clip'],'target':ref['speaker']==owner,
                                 'impostor_source':None if ref['speaker']==owner else ('fleurs' if ref['speaker']=='fleurs' else 'librispeech'),
                                 'similarity':max(sims) if sims else None,'kept':bool(sims)})
                rows[-1]['voice_peak_ws']=max((x.get('voice_ws',0) for x in r['ram']),default=0)
                rejected=[st for st in r['status'] if st.get('event')=='speaker_rejected']
                wav.unlink()
    return rows


def far_frr(rows,t):
    tg=[r for r in rows if 'target' in r and r['target']];im=[r for r in rows if 'target' in r and not r['target']]
    acc=lambda r:r['similarity'] is not None and r['similarity']>=t
    return {'threshold':t,'targets':len(tg),'impostors':len(im),'frr':round(sum(not acc(r) for r in tg)/max(len(tg),1),4),
            'far':round(sum(acc(r) for r in im)/max(len(im),1),4),
            'far_fleurs':round(sum(acc(r) for r in im if r['impostor_source']=='fleurs')/max(sum(r['impostor_source']=='fleurs' for r in im),1),4)}


def speaker_command(split,threshold,conditions):
    rows=speaker_eval(split,str(threshold),conditions)
    sweep=[far_frr(rows,t/100) for t in range(0,90,2)]
    out={'provenance':{**provenance(),'speaker_model':'nemo_en_titanet_small.onnx sha256 ad4a1802485d8b34c722d2a9d04249662f2ece5d28a7a039063ca22f515a789e',
                       'speaker_data':'LibriSpeech test-clean (openslr 12, CC BY 4.0, md5 32fa31d27d2e1cad72775fee3f4849a9) + FLEURS impostors'},
         'split':split,'gate_threshold':threshold,'conditions':conditions,'sweep':sweep,
         'at_gate':far_frr(rows,threshold) if threshold>-1 else None,
         'by_condition':{c:far_frr([r for r in rows if r.get('condition')==c],threshold if threshold>-1 else .5) for c in conditions},
         'voice_peak_working_set_bytes':max((r.get('voice_peak_ws',0) for r in rows),default=0),'rows':rows}
    write(f'speaker-{split}.json',out)
    print(json.dumps({k:v for k,v in out.items() if k not in ('rows','sweep')},indent=1))
    for x in sweep:print(x)


def confidence(files):
    """Dev only: whisper mean token probability per stored segment vs whether the text is backed by the reference.
    A segment is garbage when it overlaps no reference speech or < 30% of its words occur in the overlapping
    references (hallucination, wrong language/script). Picks the highest threshold dropping <= 2% of good segments."""
    from benchmarks.metrics import normalize
    segs=[]
    for f in files:
        d=json.loads(Path(f).read_text(encoding='utf-8'))
        if d.get('split')!='dev':raise SystemExit(f'{f}: confidence is tuned on dev reports only')
        for r in d['rows']:
            refs=r.get('refs')
            for sg in r['segments_detail']:
                if not sg.get('ok') or sg.get('provider')!='whisper.cpp':continue
                words=normalize(sg['text']).split();ref=normalize(r['reference']).split() if r.get('reference') else []
                hit=sum(w in set(ref) for w in words)/max(len(words),1)
                segs.append({'p':sg['token_probability'],'good':hit>=.3,'condition':r['condition'],'language':r['language']})
    good=sorted(x['p'] for x in segs if x['good']);bad=[x['p'] for x in segs if not x['good']]
    best=0.0
    for t in [i/100 for i in range(0,80)]:
        if sum(p<t for p in good)<=.02*len(good):best=t
    out={'segments':len(segs),'good':len(good),'garbage':len(bad),'threshold':best,
         'garbage_rejected':round(sum(p<best for p in bad)/max(len(bad),1),4),'good_rejected':round(sum(p<best for p in good)/max(len(good),1),4),
         'note':'session-level reference word sets; a segment is checked against all words of its session reference'}
    write('confidence-dev.json',{'provenance':provenance(),'files':[str(f) for f in files],**out,'rows':segs});print(json.dumps(out,indent=1))


def lid_probabilities(model,max_clips=40):
    """Whisper language probabilities (all 99) per FLEURS clip of the 17 spec languages via lens-asr-probe --lid."""
    MAX_CLIPS[0]=max_clips;items=[(code,c) for code in GLOBAL for c in clips(code)]
    p=subprocess.run([str(REL/'lens-asr-probe.exe'),'--lid',str(model)],input=''.join(str(c['path'])+'\n' for _,c in items),
                     capture_output=True,text=True,encoding='utf-8',timeout=7200)
    rows=[json.loads(l) for l in p.stdout.splitlines() if l.startswith('{')]
    by={str(Path(r['file'])):r for r in rows}
    return [{'language':code,'clip':c['id'],'split':c['split'],'p':by[str(c['path'])]['p']} for code,c in items if 'p' in by.get(str(c['path']),{})]


def lid_predict(row,allowed,offsets):
    return max(allowed,key=lambda l:np.log(max(row['p'][l],1e-12))+offsets.get(l,0.0))


def lid_scores(rows,allowed,offsets):
    per={}
    for l in allowed:
        rs=[r for r in rows if r['language']==l]
        if rs:per[l]=round(sum(lid_predict(r,allowed,offsets)==l for r in rs)/len(rs),4)
    conf={}
    for r in rows:
        g=lid_predict(r,allowed,offsets)
        if g!=r['language']:conf[f"{r['language']}->{g}"]=conf.get(f"{r['language']}->{g}",0)+1
    return {'balanced_accuracy':round(float(np.mean(list(per.values()))),4),'per_language':per,'confusions':dict(sorted(conf.items(),key=lambda x:-x[1]))}


def lid_tune(rows,allowed):
    """Per-language log-prior offsets by coordinate ascent on dev balanced accuracy; ties keep the smaller |offset|."""
    off={l:0.0 for l in allowed};grid=[x/4 for x in range(-12,13)]
    best=lid_scores(rows,allowed,off)['balanced_accuracy']
    for _ in range(3):
        changed=False
        for l in allowed:
            for v in sorted(grid,key=abs):
                trial={**off,l:v};a=lid_scores(rows,allowed,trial)['balanced_accuracy']
                if a>best+1e-9:best,off,changed=a,trial,True
        if not changed:break
    return {l:v for l,v in off.items() if v},best


def lid_command(max_clips):
    allowed=list(GLOBAL);out={'provenance':provenance(),'allowed':allowed,'clips_per_language':max_clips,'models':{}}
    for name in ['ggml-base-q5_1.bin','ggml-small-q5_1.bin']:
        rows=lid_probabilities(WHISPER/name,max_clips);dev=[r for r in rows if r['split']=='dev'];held=[r for r in rows if r['split']=='heldout']
        off,dev_acc=lid_tune(dev,allowed)
        out['models'][name]={'dev_clips':len(dev),'heldout_clips':len(held),'offsets':off,
            'dev_before':lid_scores(dev,allowed,{}),'dev_after':lid_scores(dev,allowed,off),
            'heldout_before':lid_scores(held,allowed,{}),'heldout_after':lid_scores(held,allowed,off),'rows':rows}
        m=out['models'][name];print(name,'dev',m['dev_before']['balanced_accuracy'],'->',m['dev_after']['balanced_accuracy'],
              'heldout',m['heldout_before']['balanced_accuracy'],'->',m['heldout_after']['balanced_accuracy'],'offsets',off,flush=True)
        print(' heldout per-language after',m['heldout_after']['per_language'],flush=True)
        print(' heldout confusions after',list(m['heldout_after']['confusions'].items())[:8],flush=True)
    write('lid-calibration.json',out)


def fetch(per_language):
    """First `per_language` FLEURS test members per configured language via scripts/fetch_fleurs.py (pinned revision,
    per-file SHA-256; CC BY 4.0). Existing larger manifests are kept."""
    from scripts import fetch_fleurs
    fetch_fleurs.LANGS.update({cfg:code for code,cfg in GLOBAL.items()})
    for code,cfg in GLOBAL.items():
        try:print(cfg,len(fetch_fleurs.fetch_language(cfg,per_language)),flush=True)
        except Exception as exc:print(cfg,'FAILED',exc,flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['vad','tune','asr','latency','soak','speaker','fetch','confidence','lid'])
    p.add_argument('--files',nargs='*',default=[])
    p.add_argument('--per-language',type=int,default=40);p.add_argument('--max-clips',type=int,default=None)
    p.add_argument('--speaker-threshold',type=float,default=-1.0)
    p.add_argument('--split',default='dev',choices=['dev','heldout']);p.add_argument('--vad',default='adaptive',choices=['adaptive','legacy'])
    p.add_argument('--set',nargs='*');p.add_argument('--languages',nargs='*',default=['en','es','zh','hi'])
    p.add_argument('--conditions',nargs='*',default=CONDITIONS);p.add_argument('--mode',default='product',choices=['product','configured'])
    p.add_argument('--sessions',type=int,default=1);p.add_argument('--per-session',type=int,default=8)
    p.add_argument('--minutes',type=float,default=32);p.add_argument('--tag',default='')
    a=p.parse_args();params=parse_set(a.set);MAX_CLIPS[0]=a.max_clips
    if a.languages==['all']:a.languages=list(GLOBAL)
    if a.command=='tune':return tune()
    if a.command=='fetch':return fetch(a.per_language)
    if a.command=='confidence':return confidence(a.files)
    if a.command=='lid':return lid_command(a.max_clips or 40)
    if a.command=='soak':return soak(a.minutes,a.vad,params)
    if a.command=='speaker':return speaker_command(a.split,a.speaker_threshold,[c for c in a.conditions if c in ('clean','pink10','babble10','fan10')] or ['clean'])
    if a.split=='heldout' and a.command=='vad' and params:print('note: explicit parameters on held-out are reported, never tuned',flush=True)
    if a.command=='vad':
        rows=evaluate_vad(a.languages,a.split,a.conditions,a.vad,params,a.per_session,a.sessions or None)
        name=f'vad-{a.split}-{a.vad}{a.tag}.json'
        write(name,{'provenance':provenance(),'vad':a.vad,'params':params,'split':a.split,'overall':aggregate_vad(rows),
                    'by_condition':summarize(rows,['condition']),'by_language':summarize(rows,['language']),
                    'by_language_condition':summarize(rows,['language','condition']),'rows':rows})
        print(json.dumps({'overall':aggregate_vad(rows),'by_condition':summarize(rows,['condition'])},indent=1));return
    pace=1.0 if a.command=='latency' else 0.0
    rows=run_asr(a.languages,a.split,a.conditions,a.vad,params,a.mode,a.per_session,a.sessions,pace)
    name=f'{a.command}-{a.split}-{a.vad}-{a.mode}{a.tag}.json'
    out={'provenance':provenance(),'vad':a.vad,'params':params,'mode':a.mode,'split':a.split,'table':asr_table(rows),'rows':rows}
    if pace:
        lat=[x for r in rows for x in r.get('latency',[])]
        out['latency_ms']={'utterances':len(lat),'p50_stored':pct([x['stored_ms'] for x in lat],50),'p95_stored':pct([x['stored_ms'] for x in lat],95),
                           'max_stored':max([x['stored_ms'] for x in lat],default=None),'p50_emit':pct([x['emit_ms'] for x in lat],50),
                           'p95_emit':pct([x['emit_ms'] for x in lat],95)}
    write(name,out);print(json.dumps(out['table'],indent=1))


if __name__=='__main__':main()
