"""Fine-tune the general screen recogniser's sequence head on synthetic English screen lines (development only).

Base: PaddlePaddle PP-OCRv6_tiny_rec (Apache-2.0), ONNX export pinned in third_party/ocr-runtime-lock.json. The backbone
(input -> `p2o.pd_op.pool2d.0.0`, N x 160 x 1 x T) stays frozen and runs in ONNX Runtime on the CPU; the head
(depthwise conv1d k=5 -> BatchNorm1d -> hardswish -> pointwise conv1d -> BatchNorm1d -> hardswish -> linear 160->80 ->
linear 80->6906) is re-implemented in PyTorch from the export's own constants, checked to reproduce the export before
training, trained on the GPU when one is present (CPU otherwise) with CTC plus a KL term toward the original head's
outputs (learning without forgetting: the recogniser also reads zh/es/fr/pt/de/id), BatchNorm statistics frozen, and
written back into a copy of the ONNX graph: the shipped worker runs the same graph with new constants only.
Preprocessing mirrors engine/ocr_main.cpp (height 48, aspect kept, x/127.5-1, zero right padding, width >= 320).
Data: scripts/make_ocr_en_train.py (2% held back as synthetic validation). No real screens, dev or held-out data.
Output: models/Lens--en_PP-OCRv6_tiny_rec_screen/{inference.onnx,ctc-dictionary.json,training.json}
Usage: .tools\\venv-train-cuda\\Scripts\\python.exe scripts/train_ocr_screen_rec.py [--steps 6000] [--batch 64] [--lr 3e-4]
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import random
import shutil
import time
import cv2
import numpy as np
import onnx
from onnx import numpy_helper
import onnxruntime as ort
import torch
import torch.nn.functional as F
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'models/PaddlePaddle--PP-OCRv6_tiny_rec'
DATA=ROOT/'artifacts/ocr-train/en-screen-v1'
OUT=ROOT/'models/Lens--en_PP-OCRv6_tiny_rec_screen'
FEATURE='p2o.pd_op.pool2d.0.0'
TRAINED=['conv1d_0.w_0','conv1d_1.w_0','batch_norm1d_0.w_0','batch_norm1d_0.b_0','batch_norm1d_1.w_0','batch_norm1d_1.b_0',
         'linear_0.w_0','linear_0.b_0','linear_1.w_0','linear_1.b_0']


class Head(torch.nn.Module):
    def __init__(self,c):
        super().__init__()
        self.p=torch.nn.ParameterDict({k.replace('.','_'):torch.nn.Parameter(torch.tensor(c[k])) for k in TRAINED})
        for k in ('batch_norm1d_0','batch_norm1d_1'):  # running statistics stay frozen
            self.register_buffer(k+'_mean',torch.tensor(c[k+'.w_1']));self.register_buffer(k+'_var',torch.tensor(c[k+'.w_2']))

    def bn(self,x,k):return F.batch_norm(x,getattr(self,k+'_mean'),getattr(self,k+'_var'),self.p[k+'_w_0'],self.p[k+'_b_0'],False,0.0,1e-5)

    def forward(self,h):  # h: N x 160 x 1 x T -> logits N x T x 6906
        x=h.squeeze(2)
        x=F.hardswish(self.bn(F.conv1d(x,self.p['conv1d_0_w_0'],padding=2,groups=160),'batch_norm1d_0'))
        x=F.hardswish(self.bn(F.conv1d(x,self.p['conv1d_1_w_0']),'batch_norm1d_1')).transpose(1,2)
        return (x@self.p['linear_0_w_0']+self.p['linear_0_b_0'])@self.p['linear_1_w_0']+self.p['linear_1_b_0']


def prepare(crop,box,rng):
    """Crop the stored margin image at the detector box, jittered by up to 2 px per side when training."""
    h,w=crop.shape[:2];j=(lambda:rng.randint(-2,2)) if rng else (lambda:0)
    x0,y0,x1,y1=max(0,box[0]+j()),max(0,box[1]+j()),min(w,box[2]+j()),min(h,box[3]+j())
    img=crop[y0:y1,x0:x1]
    if rng and rng.random()<0.3:img=np.clip(img.astype(np.float32)*rng.uniform(0.8,1.2)+rng.uniform(-20,20),0,255).astype(np.uint8)
    return img


def batch(images):
    """engine/ocr_main.cpp recogniser input: height 48, width ceil(48*w/h) (capped), padded with zeros to >= 320."""
    widths=[max(1,math.ceil(48*im.shape[1]/max(1,im.shape[0]))) for im in images];W=min(max(320,max(widths)),2400)  # 300 frames: 8 GB GPU
    x=np.zeros((len(images),3,48,W),np.float32)
    for i,(im,w) in enumerate(zip(images,widths)):
        w=min(w,W);r=cv2.resize(im,(w,48),interpolation=cv2.INTER_LINEAR).astype(np.float32)/127.5-1.0;x[i,:,:,:w]=r.transpose(2,0,1)
    return x


def decode(logits,dictionary):
    out=[]
    for seq in logits.argmax(-1).tolist():
        prev=0;s=[]
        for k in seq:
            if k!=prev and k!=0:s.append(dictionary[k])
            prev=k
        out.append(' '.join(''.join(s).split()))
    return out


def edit(a,b):
    d=list(range(len(b)+1))
    for i,ca in enumerate(a,1):
        p,d[0]=d[0],i
        for j,cb in enumerate(b,1):p,d[j]=d[j],min(d[j]+1,d[j-1]+1,p+(ca!=cb))
    return d[-1]


def main():
    global DATA,OUT
    ap=argparse.ArgumentParser();ap.add_argument('--steps',type=int,default=6000);ap.add_argument('--batch',type=int,default=64)
    ap.add_argument('--lr',type=float,default=3e-4);ap.add_argument('--kl',type=float,default=0.3);ap.add_argument('--seed',type=int,default=20261029)
    ap.add_argument('--threads',type=int,default=8);ap.add_argument('--data',type=Path,default=DATA);ap.add_argument('--out',type=Path,default=OUT)
    args=ap.parse_args();DATA,OUT=args.data,args.out
    rng=random.Random(args.seed);torch.manual_seed(args.seed);dev='cuda' if torch.cuda.is_available() else 'cpu'
    model=onnx.load(str(BASE/'inference.onnx'));c={n.output[0]:numpy_helper.to_array(n.attribute[0].t) for n in model.graph.node if n.op_type=='Constant'}
    dictionary=json.loads((BASE/'ctc-dictionary.json').read_text(encoding='utf-8'));index={ch:i for i,ch in enumerate(dictionary)}
    o=ort.SessionOptions();o.intra_op_num_threads=args.threads;o.log_severity_level=3
    backbone=ort.InferenceSession(onnx.utils.Extractor(model).extract_model(['x'],[FEATURE]).SerializeToString(),o,providers=['CPUExecutionProvider'])
    full=ort.InferenceSession(str(BASE/'inference.onnx'),o,providers=['CPUExecutionProvider'])
    rows=[json.loads(l) for l in (DATA/'lines.jsonl').open(encoding='utf-8')];rng.shuffle(rows)
    val,train=rows[:max(200,len(rows)//50)],rows[max(200,len(rows)//50):]
    cache={}
    def load(r):
        if r['crop'] not in cache:cache[r['crop']]=cv2.imread(str(DATA/'crops'/r['crop']),cv2.IMREAD_COLOR)
        return cache[r['crop']]
    head=Head(c).to(dev);teacher=Head(c).to(dev).eval()
    for p in teacher.parameters():p.requires_grad=False
    x=batch([prepare(load(r),r['box'],None) for r in val[:16]])
    with torch.no_grad():mine=torch.softmax(head(torch.tensor(backbone.run(None,{'x':x})[0],device=dev)),-1).cpu().numpy()
    parity=float(np.abs(mine-full.run(None,{'x':x})[0]).max());print('parity vs export',parity,flush=True)
    if parity>1e-3:raise SystemExit('head re-implementation does not match the export')

    def evaluate(items):
        head.eval();errs=chars=0;exact=0
        for k in range(0,len(items),64):
            part=items[k:k+64];x=batch([prepare(load(r),r['box'],None) for r in part])
            with torch.no_grad():pred=decode(head(torch.tensor(backbone.run(None,{'x':x})[0],device=dev)).cpu(),dictionary)
            for r,p in zip(part,pred):e=edit(r['text'],p);errs+=e;chars+=len(r['text']);exact+=e==0
        head.train();return errs/max(1,chars),exact/len(items)
    before=evaluate(val);print('synthetic val CER before %.4f exact %.3f'%before,flush=True)
    opt=torch.optim.AdamW(head.parameters(),lr=args.lr,weight_decay=1e-4);warm=200
    sched=torch.optim.lr_scheduler.LambdaLR(opt,lambda s:min(1,(s+1)/warm)*0.5*(1+math.cos(math.pi*min(1,s/args.steps))))
    pool=ThreadPoolExecutor(1)
    def make():
        part=[train[rng.randrange(len(train))] for _ in range(args.batch)]
        part=[r for r in part if all(ch in index for ch in r['text'])]
        x=batch([prepare(load(r),r['box'],rng) for r in part]);return part,backbone.run(None,{'x':x})[0]
    nxt=pool.submit(make);t0=time.perf_counter();log=[]
    for step in range(1,args.steps+1):
        part,feat=nxt.result();nxt=pool.submit(make)
        h=torch.tensor(feat,device=dev);logits=head(h);T=logits.shape[1]
        targets=[torch.tensor([index[ch] for ch in r['text']]) for r in part];lengths=torch.tensor([len(t) for t in targets])
        keep=lengths<=T  # CTC needs at least one frame per label
        lp=F.log_softmax(logits,-1).transpose(0,1)
        loss=F.ctc_loss(lp[:,keep],torch.cat([t for t,k in zip(targets,keep) if k]).to(dev),torch.full((int(keep.sum()),),T,dtype=torch.long),
                        lengths[keep],blank=0,zero_infinity=True)
        if args.kl:
            with torch.no_grad():ref=F.softmax(teacher(h),-1)
            loss=loss+args.kl*F.kl_div(F.log_softmax(logits,-1),ref,reduction='batchmean')/T
        opt.zero_grad(set_to_none=True);loss.backward();torch.nn.utils.clip_grad_norm_(head.parameters(),5.0);opt.step();sched.step()
        if step%200==0:
            el=time.perf_counter()-t0;entry={'step':step,'loss':float(loss),'lr':sched.get_last_lr()[0],'s_per_step':el/step}
            if step%1000==0:entry['val_cer'],entry['val_exact']=evaluate(val)
            log.append(entry);print(json.dumps(entry),flush=True)
    after=evaluate(val);print('synthetic val CER after %.4f exact %.3f'%after,flush=True)
    OUT.mkdir(parents=True,exist_ok=True)
    trained={k:head.p[k.replace('.','_')].detach().cpu().numpy().astype(np.float32) for k in TRAINED}
    for n in model.graph.node:
        if n.op_type=='Constant' and n.output[0] in trained:n.attribute[0].t.CopyFrom(numpy_helper.from_array(trained[n.output[0]],n.output[0]))
    onnx.save(model,str(OUT/'inference.onnx'));shutil.copy2(BASE/'ctc-dictionary.json',OUT/'ctc-dictionary.json')
    exported=ort.InferenceSession(str(OUT/'inference.onnx'),o,providers=['CPUExecutionProvider'])
    x=batch([prepare(load(r),r['box'],None) for r in val[:16]])
    with torch.no_grad():mine=torch.softmax(head(torch.tensor(backbone.run(None,{'x':x})[0],device=dev)),-1).cpu().numpy()
    export_parity=float(np.abs(mine-exported.run(None,{'x':x})[0]).max());print('export parity',export_parity)
    sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
    (OUT/'training.json').write_text(json.dumps({'base':str(BASE.relative_to(ROOT)),'base_sha256':sha(BASE/'inference.onnx'),'data':json.loads((DATA/'manifest.json').read_text(encoding='utf-8')),
        'args':vars(args),'device':dev,'device_name':torch.cuda.get_device_name(0) if dev=='cuda' else 'cpu','train_lines':len(train),'val_lines':len(val),
        'parity_before':parity,'parity_export':export_parity,'synthetic_val':{'before':{'cer':before[0],'exact':before[1]},'after':{'cer':after[0],'exact':after[1]}},
        'trained_constants':TRAINED,'train_seconds':time.perf_counter()-t0,'log':log,'inference_sha256':sha(OUT/'inference.onnx')},indent=1,default=str),encoding='utf-8')
    print('wrote',OUT)


if __name__=='__main__':main()
