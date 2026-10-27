"""Reference screen-OCR pipeline and benchmark (development; the shipped path is native C++).

Detection: PP-OCRv5_mobile_det or PP-OCRv6_tiny_det (ONNX, CPU). Pre-processing follows PaddleOCR 3.x for screens:
keep native scale (min side >= 64, max side <= 4000, dims rounded to multiples of 32), BGR, ImageNet mean/std.
Post-processing is PaddleOCR's DBPostProcess (threshold, contour, min-area rectangle, box score, unclip with pyclipper,
quad boxes) followed by its reading-order sort and rotated crops. Recognition follows PaddleX text_recognition (height
48, width max(320, 48*w/h), /127.5-1) with CTC greedy decoding, one crop per inference.
Script routing: `oracle` uses the language's recogniser; `auto` runs the multilingual recogniser (PP-OCRv6 tiny) and
retries the Indic recognisers when its confidence is below --auto-threshold, keeping the most confident result.
Metrics per screen: page CER (lines joined in reading order), mean best-match line CER, line accuracy (CER <= 0.05),
detection/recognition latency, and the process peak working set.
Usage: .venv\\Scripts\\python.exe scripts/ocr_reference.py [--det v5|v6] [--route oracle|auto] [--threads 4]
"""
import argparse
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import time
import cv2
import numpy as np
import onnxruntime as ort
import psutil
import pyclipper
ROOT=Path(__file__).resolve().parents[1]
M=ROOT/'models'
DET={'v5':(M/'PaddlePaddle--PP-OCRv5_mobile_det/inference.onnx',0.3,0.6,1.5),'v6':(M/'PaddlePaddle--PP-OCRv6_tiny_det/inference.onnx',0.2,0.4,1.4)}
REC={'general':M/'PaddlePaddle--PP-OCRv6_tiny_rec','hi':M/'PaddlePaddle--devanagari_PP-OCRv5_mobile_rec',
     'ta':M/'PaddlePaddle--ta_PP-OCRv5_mobile_rec','te':M/'PaddlePaddle--te_PP-OCRv5_mobile_rec'}
ORACLE={'en':'general','es':'general','zh':'general','hi':'hi','ta':'ta','te':'te'}


def session(path,threads):
    o=ort.SessionOptions();o.intra_op_num_threads=threads;o.inter_op_num_threads=1
    return ort.InferenceSession(str(path),o,providers=['CPUExecutionProvider'])


class Detector:
    def __init__(self,kind,threads):
        path,self.thresh,self.box_thresh,self.unclip=DET[kind];self.s=session(path,threads)

    def __call__(self,img):
        h,w=img.shape[:2];r=1.0
        if min(h,w)<64:r=64/min(h,w)
        if max(h,w)*r>4000:r=4000/max(h,w)
        nh,nw=max(32,int(round(h*r/32))*32),max(32,int(round(w*r/32))*32)
        x=cv2.resize(img,(nw,nh)).astype(np.float32)/255.0
        x=(x-np.array([0.485,0.456,0.406],np.float32))/np.array([0.229,0.224,0.225],np.float32)
        prob=self.s.run(None,{'x':x.transpose(2,0,1)[None]})[0][0,0]
        return self.boxes(prob,w/nw,h/nh)

    def boxes(self,prob,sx,sy):
        bitmap=(prob>self.thresh).astype(np.uint8)
        contours,_=cv2.findContours(bitmap,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE);out=[]
        for c in contours[:1000]:
            pts,side=self.mini_box(c)
            if side<3:continue
            if self.score(prob,c.reshape(-1,2))<self.box_thresh:continue
            box=self.expand(pts)
            if box is None:continue
            box,side=self.mini_box(box.reshape(-1,1,2))
            if side<5:continue
            box=np.array(box);box[:,0]=np.clip(box[:,0]*sx,0,None);box[:,1]=np.clip(box[:,1]*sy,0,None)
            out.append(box.astype(np.float32))
        return out

    @staticmethod
    def mini_box(contour):
        rect=cv2.minAreaRect(contour);pts=sorted(cv2.boxPoints(rect).tolist(),key=lambda p:p[0])
        i1,i4=(0,1) if pts[1][1]>pts[0][1] else (1,0);i2,i3=(2,3) if pts[3][1]>pts[2][1] else (3,2)
        return [pts[i1],pts[i2],pts[i3],pts[i4]],min(rect[1])

    @staticmethod
    def score(prob,contour):
        h,w=prob.shape;xmin,xmax=np.clip([contour[:,0].min(),contour[:,0].max()],0,w-1).astype(int)
        ymin,ymax=np.clip([contour[:,1].min(),contour[:,1].max()],0,h-1).astype(int)
        mask=np.zeros((ymax-ymin+1,xmax-xmin+1),np.uint8);c=contour.copy();c[:,0]-=xmin;c[:,1]-=ymin
        cv2.fillPoly(mask,[c.astype(np.int32)],1);return cv2.mean(prob[ymin:ymax+1,xmin:xmax+1],mask)[0]

    def expand(self,box):
        poly=np.array(box);area=cv2.contourArea(poly.astype(np.float32));length=cv2.arcLength(poly.astype(np.float32),True)
        if length==0:return None
        off=pyclipper.PyclipperOffset();off.AddPath([tuple(p) for p in poly],pyclipper.JT_ROUND,pyclipper.ET_CLOSEDPOLYGON)
        res=off.Execute(area*self.unclip/length)
        return np.array(res[0]) if len(res)==1 else None


def reading_order(boxes):
    boxes=sorted(boxes,key=lambda b:(b[0][1],b[0][0]))
    for i in range(len(boxes)-1):
        for j in range(i,-1,-1):
            if abs(boxes[j+1][0][1]-boxes[j][0][1])<10 and boxes[j+1][0][0]<boxes[j][0][0]:boxes[j],boxes[j+1]=boxes[j+1],boxes[j]
            else:break
    return boxes


def crop(img,box):
    w=int(max(np.linalg.norm(box[0]-box[1]),np.linalg.norm(box[2]-box[3])));h=int(max(np.linalg.norm(box[0]-box[3]),np.linalg.norm(box[1]-box[2])))
    m=cv2.getPerspectiveTransform(box,np.float32([[0,0],[w,0],[w,h],[0,h]]))
    c=cv2.warpPerspective(img,m,(max(w,1),max(h,1)),borderMode=cv2.BORDER_REPLICATE,flags=cv2.INTER_CUBIC)
    return np.rot90(c) if c.shape[0]/max(c.shape[1],1)>=1.5 else c


class Recognizer:
    def __init__(self,folder,threads):
        self.s=session(folder/'inference.onnx',threads);self.d=json.loads((folder/'ctc-dictionary.json').read_text(encoding='utf-8'))

    def __call__(self,c):
        h,w=c.shape[:2];W=int(min(3200,max(320,48*w/h)));rw=min(W,int(math.ceil(48*w/h)))
        x=np.zeros((3,48,W),np.float32);x[:,:,:rw]=(cv2.resize(c,(rw,48)).astype(np.float32)/127.5-1).transpose(2,0,1)
        p=self.s.run(None,{self.s.get_inputs()[0].name:x[None]})[0][0];idx=p.argmax(1);text='';conf=[];prev=0
        for t,k in enumerate(idx):
            if k and k!=prev:text+=self.d[k];conf.append(p[t,k])
            prev=k
        return text,float(np.mean(conf)) if conf else 0.0


def edit(a,b):
    prev=list(range(len(b)+1))
    for i,ca in enumerate(a,1):
        cur=[i]+[0]*len(b)
        for j,cb in enumerate(b,1):cur[j]=min(prev[j]+1,cur[j-1]+1,prev[j-1]+(ca!=cb))
        prev=cur
    return prev[-1]


def norm(s):return ' '.join(s.split())


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--det',choices=['v5','v6'],default='v5');ap.add_argument('--route',choices=['oracle','auto'],default='auto')
    ap.add_argument('--auto-threshold',type=float,default=0.90);ap.add_argument('--threads',type=int,default=4);args=ap.parse_args()
    manifest=json.loads((ROOT/'artifacts/ocr-screens/v1/manifest.json').read_text(encoding='utf-8'))
    det=Detector(args.det,args.threads);rec={k:Recognizer(v,args.threads) for k,v in REC.items()};proc=psutil.Process();rows=[]
    for sc in manifest['scenarios']:
        img=cv2.imdecode(np.fromfile(str(ROOT/sc['image']),np.uint8),cv2.IMREAD_COLOR)
        t0=time.perf_counter();boxes=reading_order(det(img));t1=time.perf_counter();lines=[]
        for b in boxes:
            c=crop(img,b)
            if args.route=='oracle' and sc['language']!='mixed':text,conf=rec[ORACLE[sc['language']]](c)
            else:
                text,conf=rec['general'](c)
                if conf<args.auto_threshold:
                    for k in ('hi','ta','te'):
                        t2,c2=rec[k](c)
                        if c2>conf:text,conf=t2,c2
            if text.strip():lines.append(norm(text))
        t2=time.perf_counter();gt=[norm(l) for l in sc['lines']]
        line_cer=[min((edit(g,p)/max(1,len(g)) for p in lines),default=1.0) for g in gt]
        page=edit('\n'.join(gt),'\n'.join(lines))/max(1,len('\n'.join(gt)))
        rows.append({'name':sc['name'],'language':sc['language'],'boxes':len(boxes),'page_cer':page,'line_cer':float(np.mean(line_cer)),
                     'line_accuracy':float(np.mean([c<=0.05 for c in line_cer])),'det_ms':(t1-t0)*1000,'rec_ms':(t2-t1)*1000,'pred':lines})
        print(f"{sc['name']:14s} boxes {len(boxes):2d} pageCER {page:.3f} lineCER {np.mean(line_cer):.3f} lineAcc {rows[-1]['line_accuracy']:.2f} det {rows[-1]['det_ms']:.0f} ms rec {rows[-1]['rec_ms']:.0f} ms",flush=True)
    by={}
    for r in rows:by.setdefault(r['language'],[]).append(r)
    summary={k:{'page_cer':float(np.mean([r['page_cer'] for r in v])),'line_accuracy':float(np.mean([r['line_accuracy'] for r in v])),
                'det_ms_p50':float(np.median([r['det_ms'] for r in v])),'total_ms_p50':float(np.median([r['det_ms']+r['rec_ms'] for r in v]))} for k,v in by.items()}
    report={'created_utc':datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),'det':args.det,'route':args.route,'auto_threshold':args.auto_threshold,
            'threads':args.threads,'peak_working_set_bytes':proc.memory_info().peak_wset,'edge_version':manifest['edge_version'],
            'summary':summary,'rows':rows}
    out=ROOT/'reports/ocr-screens';out.mkdir(parents=True,exist_ok=True)
    path=out/f"ocr-reference-{args.det}-{args.route}-{report['created_utc']}.json";path.write_text(json.dumps(report,ensure_ascii=False,indent=1),encoding='utf-8')
    for k,v in summary.items():print(k,{a:round(b,3) for a,b in v.items()})
    print('peak working set MB',report['peak_working_set_bytes']/1e6,path)


if __name__=='__main__':main()
