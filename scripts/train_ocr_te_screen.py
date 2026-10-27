"""Fine-tune the Telugu screen recogniser's sequence neck and CTC head on synthetic screen renders (development only).

Base: PaddlePaddle te_PP-OCRv5_mobile_rec (Apache-2.0), ONNX export pinned in third_party/ocr-runtime-lock.json.
The PPLCNetV3 backbone stays frozen and runs in ONNX Runtime (CPU); the EncoderWithSVTR neck (1x3 conv, 1x1 conv,
two global-attention blocks dim 120 / 8 heads, final LayerNorm, 1x1 conv, shortcut concat, 1x3 conv, 1x1 conv) and
the CTC linear head are re-implemented in Paddle dygraph, initialised from the export's own constants, verified to
reproduce the export before training (max |p - p_onnx| reported), trained with CTC on scripts/make_ocr_te_train.py
lines (box jitter at load time; BatchNorm statistics frozen), and written back into a copy of the ONNX graph, so the
shipped worker runs the same ONNX Runtime graph with new constants only. No real screens, dev or held-out data.
Output: models/Lens--te_PP-OCRv5_mobile_rec_screen/{inference.onnx,ctc-dictionary.json,training.json}
Usage: .venv\\Scripts\\python.exe scripts/train_ocr_te_screen.py [--steps 3000] [--batch 32] [--lr 3e-4]
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import random
import shutil
import time
import cv2
import numpy as np
import onnx
from onnx import numpy_helper
import onnxruntime as ort
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'models/PaddlePaddle--te_PP-OCRv5_mobile_rec'
DATA=ROOT/'artifacts/ocr-train/te-v1'
OUT=ROOT/'models/Lens--te_PP-OCRv5_mobile_rec_screen'
FEATURE='p2o.pd_op.assign.0.0'  # backbone output after the [3,2] average pool: N x 480 x 1 x T
os.environ.setdefault('OMP_NUM_THREADS','2')
import paddle  # noqa: E402  (after OMP_NUM_THREADS)
import paddle.nn as nn  # noqa: E402
import paddle.nn.functional as F  # noqa: E402


def constants(model):
    return {n.output[0]:numpy_helper.to_array(n.attribute[0].t) for n in model.graph.node if n.op_type=='Constant'}


class BN(nn.Layer):  # inference-mode BatchNorm: running statistics frozen, affine trainable
    def __init__(self,c,k):
        super().__init__()
        self.w=self.create_parameter([len(c[k+'.w_0'])],default_initializer=nn.initializer.Assign(c[k+'.w_0']))
        self.b=self.create_parameter([len(c[k+'.b_0'])],default_initializer=nn.initializer.Assign(c[k+'.b_0']))
        self.register_buffer('mean',paddle.to_tensor(c[k+'.w_1']));self.register_buffer('var',paddle.to_tensor(c[k+'.w_2']))
        self.key=k

    def forward(self,x):
        s=(self.w/paddle.sqrt(self.var+1e-5)).reshape([1,-1,1,1])
        return (x-self.mean.reshape([1,-1,1,1]))*s+self.b.reshape([1,-1,1,1])


class ConvBN(nn.Layer):
    def __init__(self,c,conv,bn,pad):
        super().__init__()
        self.w=self.create_parameter(list(c[conv+'.w_0'].shape),default_initializer=nn.initializer.Assign(c[conv+'.w_0']))
        self.bn=BN(c,bn);self.pad=pad;self.key=conv

    def forward(self,x):return F.swish(self.bn(F.conv2d(x,self.w,padding=self.pad)))


class Linear(nn.Layer):
    def __init__(self,c,k):
        super().__init__()
        self.w=self.create_parameter(list(c[k+'.w_0'].shape),default_initializer=nn.initializer.Assign(c[k+'.w_0']))
        self.b=self.create_parameter(list(c[k+'.b_0'].shape),default_initializer=nn.initializer.Assign(c[k+'.b_0']))
        self.key=k

    def forward(self,x):return paddle.matmul(x,self.w)+self.b


class LN(nn.Layer):
    def __init__(self,c,k,eps):
        super().__init__()
        self.w=self.create_parameter([120],default_initializer=nn.initializer.Assign(c[k+'.w_0']))
        self.b=self.create_parameter([120],default_initializer=nn.initializer.Assign(c[k+'.b_0']))
        self.eps=eps;self.key=k

    def forward(self,x):return F.layer_norm(x,[120],self.w,self.b,self.eps)


class Block(nn.Layer):
    def __init__(self,c,ln,lin,drop):
        super().__init__()
        self.n1=LN(c,f'layer_norm_{ln}',1e-5);self.qkv=Linear(c,f'linear_{lin}');self.proj=Linear(c,f'linear_{lin+1}')
        self.n2=LN(c,f'layer_norm_{ln+1}',1e-5);self.fc1=Linear(c,f'linear_{lin+2}');self.fc2=Linear(c,f'linear_{lin+3}');self.drop=drop

    def forward(self,x):
        qkv=self.qkv(self.n1(x)).reshape([0,-1,3,8,15]).transpose([2,0,3,1,4])
        a=F.softmax(paddle.matmul(qkv[0]*15**-0.5,qkv[1],transpose_y=True),axis=-1)
        x=x+F.dropout(self.proj(paddle.matmul(a,qkv[2]).transpose([0,2,1,3]).reshape([0,-1,120])),self.drop,training=self.training)
        return x+F.dropout(self.fc2(F.swish(self.fc1(self.n2(x)))),self.drop,training=self.training)


class Neck(nn.Layer):
    def __init__(self,c,drop=0.1):
        super().__init__()
        self.conv1=ConvBN(c,'conv2d_131','batch_norm2d_146',[0,1]);self.conv2=ConvBN(c,'conv2d_132','batch_norm2d_147',0)
        self.blocks=nn.LayerList([Block(c,0,0,drop),Block(c,2,4,drop)]);self.norm=LN(c,'layer_norm_4',1e-6)
        self.conv3=ConvBN(c,'conv2d_133','batch_norm2d_148',0);self.conv4=ConvBN(c,'conv2d_134','batch_norm2d_149',[0,1])
        self.conv5=ConvBN(c,'conv2d_135','batch_norm2d_150',0);self.head=Linear(c,'linear_8')

    def forward(self,h):  # h: N x 480 x 1 x T -> logits N x T x classes
        z=self.conv2(self.conv1(h));t=z.shape[3]
        z=z.flatten(2).transpose([0,2,1])
        for b in self.blocks:z=b(z)
        z=self.norm(z).reshape([0,1,t,120]).transpose([0,3,1,2])
        z=self.conv5(self.conv4(paddle.concat([h,self.conv3(z)],axis=1)))
        return self.head(z.squeeze(2).transpose([0,2,1]))

    def named_constants(self):
        out={}
        for layer in self.sublayers(include_self=True):
            if isinstance(layer,BN):out[layer.key+'.w_0']=layer.w;out[layer.key+'.b_0']=layer.b
            elif isinstance(layer,ConvBN):out[layer.key+'.w_0']=layer.w
            elif isinstance(layer,(Linear,LN)):out[layer.key+'.w_0']=layer.w;out[layer.key+'.b_0']=layer.b
        return out


def prepare(crop,box,rng):
    """Jittered box crop -> 48-high float CHW (PaddleX: /127.5-1), natural width (>= 1)."""
    x0,y0,x1,y1=box
    if rng is not None:
        h=y1-y0;j=max(1,round(h*0.08))
        x0+=rng.randint(-j,j);x1+=rng.randint(-j,j);y0+=rng.randint(-j,j);y1+=rng.randint(-j,j)
    x0,y0=max(0,x0),max(0,y0);x1,y1=min(crop.shape[1],max(x1,x0+2)),min(crop.shape[0],max(y1,y0+2))
    c=crop[y0:y1,x0:x1];w=min(3200,max(1,math.ceil(48*c.shape[1]/c.shape[0])))
    if rng is not None and rng.random()<0.3:  # resolution jitter: down-up sample like a lower-DPI screen
        f=rng.uniform(0.6,0.9);c=cv2.resize(cv2.resize(c,None,fx=f,fy=f,interpolation=cv2.INTER_AREA),(c.shape[1],c.shape[0]))
    return (cv2.resize(c,(w,48)).astype(np.float32)/127.5-1).transpose(2,0,1)


def batch(items,rng):
    xs=[prepare(cv2.imread(str(DATA/'crops'/it['crop'])),it['box'],rng) for it in items]
    width=max(320,max(x.shape[2] for x in xs));out=np.zeros((len(xs),3,48,width),np.float32)
    for i,x in enumerate(xs):out[i,:,:,:x.shape[2]]=x
    return out


def edit(a,b):
    prev=list(range(len(b)+1))
    for i,ca in enumerate(a,1):
        cur=[i]+[0]*len(b)
        for j,cb in enumerate(b,1):cur[j]=min(prev[j]+1,cur[j-1]+1,prev[j-1]+(ca!=cb))
        prev=cur
    return prev[-1]


def decode(logits,dictionary):
    out=[]
    for row in logits.argmax(-1):
        t='';prev=0
        for k in row:
            if k and k!=prev:t+=dictionary[k]
            prev=k
        out.append(t)
    return out


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--steps',type=int,default=3000);ap.add_argument('--batch',type=int,default=32)
    ap.add_argument('--lr',type=float,default=3e-4);ap.add_argument('--seed',type=int,default=11);ap.add_argument('--threads',type=int,default=3)
    ap.add_argument('--val',type=int,default=400);ap.add_argument('--eval-every',type=int,default=250)
    ap.add_argument('--resume',action='store_true');args=ap.parse_args()
    rng=random.Random(args.seed);paddle.seed(args.seed);paddle.set_device('cpu')
    base=onnx.load(str(BASE/'inference.onnx'));c=constants(base)
    dictionary=json.loads((BASE/'ctc-dictionary.json').read_text(encoding='utf-8'));index={ch:i for i,ch in enumerate(dictionary)}
    backbone_path=DATA/'backbone.onnx'
    onnx.utils.extract_model(str(BASE/'inference.onnx'),str(backbone_path),['x'],[FEATURE])
    o=ort.SessionOptions();o.intra_op_num_threads=args.threads;o.inter_op_num_threads=1;o.log_severity_level=3
    backbone=ort.InferenceSession(str(backbone_path),o,providers=['CPUExecutionProvider'])
    full=ort.InferenceSession(str(BASE/'inference.onnx'),o,providers=['CPUExecutionProvider'])
    lines=[json.loads(l) for l in (DATA/'lines.jsonl').read_text(encoding='utf-8').splitlines()]
    rng.shuffle(lines);val,train=lines[:args.val],lines[args.val:]
    neck=Neck(c)
    # parity: ONNX backbone + Paddle neck must reproduce the original export
    neck.eval();x=batch(val[:8],None);ref=full.run(None,{'x':x})[0]
    mine=F.softmax(neck(paddle.to_tensor(backbone.run(None,{'x':x})[0])),axis=-1).numpy()
    parity=float(np.abs(ref-mine).max());print('parity max |dp|',parity,flush=True)
    if parity>1e-3:raise SystemExit('neck re-implementation does not match the export')

    def evaluate():
        neck.eval();errs=chars=0
        for i in range(0,len(val),16):
            items=val[i:i+16];x=batch(items,None)
            pred=decode(neck(paddle.to_tensor(backbone.run(None,{'x':x})[0])).numpy(),dictionary)
            for it,p in zip(items,pred):errs+=edit(it['text'],' '.join(p.split()));chars+=len(it['text'])
        neck.train();return errs/chars

    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

    def export(step,completed):
        """Write the current constants into a copy of the export (every evaluation, so an interrupted run keeps them)."""
        model=onnx.load(str(BASE/'inference.onnx'));trained={k:v.numpy() for k,v in neck.named_constants().items()};changed=0
        for n in model.graph.node:
            if n.op_type=='Constant' and n.output[0] in trained:
                n.attribute[0].t.CopyFrom(numpy_helper.from_array(trained[n.output[0]].astype(np.float32),n.output[0]));changed+=1
        OUT.mkdir(parents=True,exist_ok=True);onnx.save(model,str(OUT/'inference.onnx'));shutil.copy(BASE/'ctc-dictionary.json',OUT/'ctc-dictionary.json')
        exported=ort.InferenceSession(str(OUT/'inference.onnx'),o,providers=['CPUExecutionProvider'])
        neck.eval();x=batch(val[:8],None)
        check=float(np.abs(exported.run(None,{'x':x})[0]-F.softmax(neck(paddle.to_tensor(backbone.run(None,{'x':x})[0])),axis=-1).numpy()).max())
        neck.train()
        record={'base':'PaddlePaddle/te_PP-OCRv5_mobile_rec (Apache-2.0)','base_onnx_sha256':sha(BASE/'inference.onnx'),
                'trained':'EncoderWithSVTR neck + CTC head; backbone and BatchNorm statistics frozen','constants_replaced':changed,
                'data':json.loads((DATA/'manifest.json').read_text(encoding='utf-8')),'train_lines':len(train),'val_lines':len(val),
                'args':vars(args),'step':step,'completed':completed,'resumed_from':resumed,'parity_before':parity,'export_parity':check,
                'history':history,'onnx_sha256':sha(OUT/'inference.onnx'),'dictionary_sha256':sha(OUT/'ctc-dictionary.json'),'seconds':time.time()-t0}
        (OUT/'training.json').write_text(json.dumps(record,indent=1,ensure_ascii=False),encoding='utf-8')
        return record,check,changed

    start=1;resumed=None;history=[]
    if args.resume and (OUT/'training.json').exists():  # constants and history from the last export; AdamW moments restart
        prev=json.loads((OUT/'training.json').read_text(encoding='utf-8'))
        if prev['completed'] or prev['args']['steps']!=args.steps or prev['data']['lines_sha256']!=json.loads((DATA/'manifest.json').read_text(encoding='utf-8'))['lines_sha256']:
            raise SystemExit('nothing to resume: last run completed or used other steps/data')
        own=constants(onnx.load(str(OUT/'inference.onnx')))
        for k,v in neck.named_constants().items():v.set_value(own[k])
        start=prev['step']+1;resumed=prev['step'];history=prev['history'];rng.seed(args.seed*1000003+prev['step'])
    if not history:history=[{'step':0,'val_cer':evaluate()}];print(history[-1],flush=True)
    train.sort(key=lambda it:(it['box'][2]-it['box'][0])/max(1,it['box'][3]-it['box'][1]))  # width buckets
    groups=[train[i:i+args.batch] for i in range(0,len(train),args.batch)]
    params=[p for p in neck.parameters() if not p.stop_gradient]
    sched=paddle.optimizer.lr.CosineAnnealingDecay(args.lr,args.steps)
    for _ in range(start-1):sched.step()
    opt=paddle.optimizer.AdamW(sched,parameters=params,weight_decay=1e-4,grad_clip=nn.ClipGradByGlobalNorm(5.0))
    neck.train();t0=time.time();running=[]
    for step in range(start,args.steps+1):
        items=rng.choice(groups);x=batch(items,rng);feat=paddle.to_tensor(backbone.run(None,{'x':x})[0])
        logp=F.log_softmax(neck(feat),axis=-1).transpose([1,0,2])  # T x N x C
        labels=[[index[ch] for ch in it['text']] for it in items];L=max(len(l) for l in labels)
        loss=F.ctc_loss(logp,paddle.to_tensor([l+[0]*(L-len(l)) for l in labels],dtype='int32'),
                        paddle.full([len(items)],logp.shape[0],dtype='int64'),paddle.to_tensor([len(l) for l in labels],dtype='int64'),
                        blank=0,reduction='mean')
        loss.backward();opt.step();opt.clear_grad();sched.step();running.append(float(loss))
        if step%50==0:print(f'step {step} loss {np.mean(running[-50:]):.4f} {time.time()-t0:.0f}s',flush=True)
        if step%args.eval_every==0 or step==args.steps:
            history.append({'step':step,'loss':float(np.mean(running[-50:])),'val_cer':evaluate()});print(history[-1],flush=True)
            record,check,changed=export(step,step==args.steps)
    lock_path=ROOT/'third_party/ocr-runtime-lock.json';lock=json.loads(lock_path.read_text(encoding='utf-8'))
    pins=[{'model':OUT.name,'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p),'license':'Apache-2.0 (derived)',
           'base':record['base'],'base_onnx_sha256':record['base_onnx_sha256'],'recipe':'scripts/train_ocr_te_screen.py',
           'data_lines_sha256':record['data']['lines_sha256'],'training_record_sha256':sha(OUT/'training.json')}
          for p in (OUT/'inference.onnx',OUT/'ctc-dictionary.json')]
    lock['derived']=[d for d in lock.get('derived',[]) if d['model']!=OUT.name]+pins
    lock_path.write_text(json.dumps(lock,indent=2),encoding='utf-8')
    print('export parity',check,'constants',changed,OUT)


if __name__=='__main__':main()
