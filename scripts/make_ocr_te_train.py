"""Synthetic Telugu text-line data for fine-tuning the Telugu screen recogniser (development only).

Text is generated programmatically from Telugu orthography (consonant clusters with vattus — ra-vattu weighted up —,
vowel signs, anusvara, halant endings) mixed with digits, short Latin tokens and punctuation, including genuine
"(" and "[" so brackets stay distinguishable from the Nirmala UI ra-vattu hook. No corpus, no personal data, no
sentence from the dev or held-out screen sets. Lines are rendered by headless Microsoft Edge (no window, isolated
temporary profile) on tall 1280-px pages in Nirmala UI (Regular/Semilight/Bold) and Noto Sans Telugu (OFL, training
only; .tools/ocr-train-fonts), random sizes 11-28 px, light/dark/coloured themes. Nirmala Text is NOT used: it is
reserved for the held-out set. Line boxes come from the shipped detector, PP-OCRv5_mobile_det with lens-ocr's
axis-aligned DB post-processing (mirrored below without recognition; identical boxes to the worker on dev screens),
so crops match inference; each crop is stored with a 6-px margin and its exact box for jitter at training time.
Output: artifacts/ocr-train/te-v1/crops/, lines.jsonl and manifest.json (seed, fonts with sha256, counts).
Usage: .venv\\Scripts\\python.exe scripts/make_ocr_te_train.py [--pages 400] [--seed 7]
"""
import argparse
import asyncio
import base64
import hashlib
import html
import json
from pathlib import Path
import random
import subprocess
import tempfile
import time
import unicodedata
import aiohttp
import onnxruntime as ort
import cv2
import numpy as np
from make_ocr_screens import EDGE,edge_version
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/ocr-train/te-v1'
M=ROOT/'models'
FONTS=ROOT/'.tools/ocr-train-fonts'
TE=M/'PaddlePaddle--te_PP-OCRv5_mobile_rec'
CONS='కఖగఘచఛజఝటఠడఢణతథదధనపఫబభమయరలవశషసహళ'+'కగచజటడతదనపబమయరలవసళ'*2  # common consonants weighted up
RARE='ఙఞఱ'
VOWELS='అఆఇఈఉఊఋఎఏఐఒఓఔ'
SIGNS='ాిీుూృెేైొోౌ'
VIRAMA='\u0c4d'
LATIN=['B12','PDF','OK','Wi-Fi','email','Lens','USB','Q3','SMS','UPI','ID','app','Zoom','Excel','A4','GST','PIN','HD']
PUNCT=[',','.',':','?','!',';','-']
THEMES=[('#ffffff','#1f2328'),('#fafafa','#333333'),('#1e1f22','#e6e6e6'),('#0d1117','#c9d1d9'),('#fff8e1','#3e2723'),
        ('#e8f0fe','#1a237e'),('#efeae2','#111111'),('#263238','#eceff1'),('#f3e5f5','#4a148c'),('#ffffff','#5f6368')]


def cluster(rng):
    c=rng.choice(CONS) if rng.random()>0.03 else rng.choice(RARE)
    if rng.random()<0.4:
        r=rng.random()
        second='ర' if r<0.38 else 'య' if r<0.52 else c if r<0.66 else 'వ' if r<0.72 else rng.choice('నమల') if r<0.82 else rng.choice(CONS)
        c+=VIRAMA+second
        if rng.random()<0.05:c+=VIRAMA+'ర'
    return c


def word(rng):
    out=''
    for i in range(rng.choice([1,2,2,3,3,3,4,4,5])):
        if i==0 and rng.random()<0.12:out+=rng.choice(VOWELS)
        else:
            out+=cluster(rng)
            if rng.random()<0.68:out+=rng.choice(SIGNS)
        if rng.random()<0.12:out+='ం'
        elif rng.random()<0.01:out+=rng.choice('ఃఁ')
    if rng.random()<0.16:out+=rng.choice(CONS)+VIRAMA
    return out


def token(rng):
    r=rng.random()
    if r<0.07:return rng.choice([str(rng.randint(0,99)),f'{rng.randint(1,99)},{rng.randint(0,999):03d}',f'{rng.randint(1,12)}:{rng.randint(0,59):02d}',
                                 str(rng.randint(1990,2030)),f'{rng.randint(1,99)}.{rng.randint(0,99):02d}',f'{rng.randint(1,100)}%'])
    if r<0.12:return rng.choice(LATIN)
    return word(rng)


def line(rng):
    words=[token(rng) for _ in range(rng.randint(2,8))]
    if rng.random()<0.08:
        i=rng.randrange(len(words));o,c=rng.choice([('(',')'),('[',']'),('"','"')]);words[i]=o+words[i]+c
    for i in range(len(words)-1):
        if rng.random()<0.1:words[i]+=rng.choice(PUNCT[:3])
    if rng.random()<0.5:words[-1]+=rng.choice(PUNCT)
    return ' '.join(words)


def page(rng,height):
    bg,fg=rng.choice(THEMES);faces=[]
    rows=[];y=24
    while True:
        size=rng.choice([11,12,13,14,14,15,16,16,17,18,18,20,22,24,26,28]);step=int(size*rng.uniform(2.3,2.9))
        if y+step>height-24:break
        face=rng.choice(['nirmala','nirmala','nirmala','noto'])
        weight=rng.choice([300,400,400,700]) if face=='nirmala' else rng.choice([400,400,700])
        rows.append((y,size,face,weight,rng.randint(16,120),line(rng)));y+=step
    css=(f'@font-face{{font-family:NotoT;src:url("{(FONTS/"NotoSansTelugu-Regular.ttf").as_uri()}");font-weight:400}}'
         f'@font-face{{font-family:NotoT;src:url("{(FONTS/"NotoSansTelugu-Bold.ttf").as_uri()}");font-weight:700}}'
         f'body{{margin:0;background:{bg};color:{fg}}}div{{position:absolute;white-space:nowrap}}')
    body=''.join(f'<div style="top:{y}px;left:{x}px;font-size:{s}px;font-weight:{w};font-family:'
                 f'{"Segoe UI,Nirmala UI" if f=="nirmala" else "Segoe UI,NotoT"}">{html.escape(t)}</div>' for y,s,f,w,x,t in rows)
    return rows,f'<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head><body>{body}</body></html>'


def label(text):return unicodedata.normalize('NFC',text.replace('\u200c','').replace('\u200d',''))


class Detector:
    """Same boxes as lens-ocr screen mode (engine/ocr_main.cpp detect): DB probability map, 8-connected components,
    mean-probability score, unclip by area*ratio/perimeter, axis-aligned, rescaled; recognition is skipped."""
    def __init__(self,threads=2,thresh=0.3,box_thresh=0.6,unclip=1.5):
        o=ort.SessionOptions();o.intra_op_num_threads=threads;o.inter_op_num_threads=1;o.log_severity_level=3
        self.s=ort.InferenceSession(str(M/'PaddlePaddle--PP-OCRv5_mobile_det/inference.onnx'),o,providers=['CPUExecutionProvider'])
        self.thresh,self.box_thresh,self.unclip=thresh,box_thresh,unclip

    def __call__(self,img):
        h,w=img.shape[:2];r=1.0
        if min(h,w)<64:r=64/min(h,w)
        if max(h,w)*r>4000:r=4000/max(h,w)
        nh,nw=max(32,round(h*r/32)*32),max(32,round(w*r/32)*32)
        x=(cv2.resize(img,(nw,nh)).astype(np.float32)/255-np.array([0.485,0.456,0.406],np.float32))/np.array([0.229,0.224,0.225],np.float32)
        prob=self.s.run(None,{'x':x.transpose(2,0,1)[None]})[0][0,0]
        n,labels,stats,_=cv2.connectedComponentsWithStats((prob>self.thresh).astype(np.uint8),connectivity=8)
        score=np.bincount(labels.ravel(),prob.ravel(),n)/np.maximum(stats[:,cv2.CC_STAT_AREA],1);sx,sy=w/nw,h/nh;boxes=[]
        for i in range(1,n):
            x0,y0,bw,bh=stats[i,:4]
            if min(bw,bh)<3 or score[i]<self.box_thresh:continue
            d=bw*bh*self.unclip/(2*(bw+bh));b=(x0-d,y0-d,x0+bw+d,y0+bh+d)
            if min(b[2]-b[0],b[3]-b[1])<5:continue
            b=[int(min(max(b[0]*sx,0),w)),int(min(max(b[1]*sy,0),h)),int(min(max(b[2]*sx,0),w)),int(min(max(b[3]*sy,0),h))]
            if b[2]-b[0]>=2 and b[3]-b[1]>=2:boxes.append(b)
        return boxes


class Edge:
    """One headless Edge (no window, temporary profile) driven over the DevTools protocol on a loopback port; a fresh
    browser per page costs 13-27 s on a loaded machine. Same 1280-px viewport and device scale 1 as --screenshot."""
    def __init__(self,profile,height):
        self.p=subprocess.Popen([str(EDGE),'--headless=new','--disable-gpu','--hide-scrollbars','--no-first-run','--disable-extensions',
                                 f'--user-data-dir={profile}','--remote-debugging-address=127.0.0.1','--remote-debugging-port=0',
                                 f'--window-size=1280,{height}','about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        port_file=Path(profile)/'DevToolsActivePort'
        for _ in range(600):
            if port_file.exists() and port_file.read_text().strip():break
            time.sleep(0.1)
        self.port=int(port_file.read_text().split()[0]);self.height=height;self.loop=asyncio.new_event_loop();self.n=0
        self.loop.run_until_complete(self.connect())

    async def connect(self):
        self.http=aiohttp.ClientSession()
        targets=await (await self.http.get(f'http://127.0.0.1:{self.port}/json/list')).json()
        self.ws=await self.http.ws_connect(next(t for t in targets if t['type']=='page')['webSocketDebuggerUrl'],max_msg_size=0)
        await self.call('Page.enable')
        await self.call('Emulation.setDeviceMetricsOverride',width=1280,height=self.height,deviceScaleFactor=1,mobile=False)

    async def call(self,method,wait_event=None,**params):
        self.n+=1;msg_id=self.n;await self.ws.send_json({'id':msg_id,'method':method,'params':params});result=None;seen=wait_event is None
        while result is None or not seen:
            msg=await self.ws.receive_json()
            if msg.get('id')==msg_id:
                if 'error' in msg:raise RuntimeError(msg['error'])
                result=msg['result']
            elif msg.get('method')==wait_event:seen=True
        return result

    async def shot(self,url):
        await self.call('Page.navigate','Page.loadEventFired',url=url)
        await self.call('Runtime.evaluate',expression='document.fonts.ready.then(()=>1)',awaitPromise=True)
        return base64.b64decode((await self.call('Page.captureScreenshot',format='png'))['data'])

    def screenshot(self,url):return self.loop.run_until_complete(self.shot(url))

    def close(self):
        try:self.loop.run_until_complete(self.ws.send_json({'id':0,'method':'Browser.close'}))
        except Exception:pass
        self.loop.run_until_complete(self.http.close())
        try:self.p.wait(timeout=30)
        except subprocess.TimeoutExpired:self.p.kill()


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--pages',type=int,default=400);ap.add_argument('--seed',type=int,default=7)
    ap.add_argument('--height',type=int,default=2400);args=ap.parse_args()
    rng=random.Random(args.seed);dictionary=set(json.loads((TE/'ctc-dictionary.json').read_text(encoding='utf-8')))
    (OUT/'crops').mkdir(parents=True,exist_ok=True)
    detect=Detector();kept=skipped=0
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile,tempfile.TemporaryDirectory() as pages,open(OUT/'lines.jsonl','w',encoding='utf-8') as out:
        edge=Edge(profile,args.height)
        for p in range(args.pages):
            rows,doc=page(rng,args.height);src=Path(pages)/f'page{p}.html';src.write_text(doc,encoding='utf-8')
            img=cv2.imdecode(np.frombuffer(edge.screenshot(src.as_uri()),np.uint8),cv2.IMREAD_COLOR);boxes=detect(img)
            for i,(y,s,f,w,x,t) in enumerate(rows):
                # boxes whose vertical centre falls inside this row's band (row top .. next row top) belong to it
                lo=y-s*0.3;hi=rows[i+1][0]-s*0.3 if i+1<len(rows) else args.height
                mine=[b for b in boxes if lo<=(b[1]+b[3])/2<hi]
                text=label(t)
                if not mine or any(ch not in dictionary for ch in text):skipped+=1;continue
                b=[min(m[0] for m in mine),min(m[1] for m in mine),max(m[2] for m in mine),max(m[3] for m in mine)]
                m0=[max(0,b[0]-6),max(0,b[1]-6),min(img.shape[1],b[2]+6),min(img.shape[0],b[3]+6)]
                name=f'p{p:04d}-{i:02d}.png';cv2.imwrite(str(OUT/'crops'/name),img[m0[1]:m0[3],m0[0]:m0[2]])
                out.write(json.dumps({'crop':name,'box':[b[0]-m0[0],b[1]-m0[1],b[2]-m0[0],b[3]-m0[1]],'boxes':len(mine),
                                      'text':text,'font':f,'weight':w,'size':s},ensure_ascii=False)+'\n');kept+=1
            if p%20==0:print('page',p,'lines',kept,'skipped',skipped,flush=True)
        edge.close()
    fonts={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(FONTS.glob('*.ttf'))}
    nirmala=Path(r'C:\Windows\Fonts\Nirmala.ttc');fonts['Nirmala.ttc (Windows)']=hashlib.sha256(nirmala.read_bytes()).hexdigest()
    (OUT/'manifest.json').write_text(json.dumps({'generator':'scripts/make_ocr_te_train.py','seed':args.seed,'pages':args.pages,'page_height':args.height,
        'edge_version':edge_version(),'fonts':fonts,'noto_source':'github.com/notofonts/notofonts.github.io@161e72fed8324679a4167a56c0717d60dbf013f9 (OFL-1.1)',
        'detector':'PP-OCRv5_mobile_det, lens-ocr axis-aligned DB post-processing (Python mirror)','lines':kept,'skipped':skipped,
        'lines_sha256':hashlib.sha256((OUT/'lines.jsonl').read_bytes()).hexdigest()},indent=1),encoding='utf-8')
    print('lines',kept,'skipped',skipped)


if __name__=='__main__':main()
