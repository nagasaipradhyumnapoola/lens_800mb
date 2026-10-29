"""Train the Lens English grapheme-to-phoneme model for words outside the misaki lexicon (spoken replies, lens-tts).

Data: misaki us_gold + us_silver (Apache-2.0; models/hexgrad--misaki), lower-case words of letters and apostrophes
(DEFAULT pronunciation for heteronyms), phonemes in Kokoro's symbol set. 2% of words, chosen by hash, are held out.
Model: a small Transformer encoder-decoder (characters -> phonemes), trained with cross-entropy and label smoothing on
the GPU when present. Exported as two ONNX graphs for greedy decoding in engine/g2p_en.cpp: encoder (chars ->
memory) and decoder (memory, phonemes so far -> next-phoneme logits).
Output: models/Lens--g2p-en/{encoder.onnx,decoder.onnx,vocab.json,training.json}
Usage: .tools\\venv-train-cuda\\Scripts\\python.exe lens_model/train/train_g2p.py [--epochs 30]
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import re
import time
import torch
import torch.nn as nn
import torch.nn.functional as F
ROOT=Path(__file__).resolve().parents[2]
LEX=ROOT/'models/hexgrad--misaki'
OUT=ROOT/'models/Lens--g2p-en'
PAD,BOS,EOS=0,1,2
MAX_IN,MAX_OUT=24,32


def load():
    pairs={}
    for name in ('us_silver.json','us_gold.json'):  # gold last: it wins
        for w,v in json.loads((LEX/name).read_text(encoding='utf-8')).items():
            if isinstance(v,dict):v=v.get('DEFAULT') if isinstance(v.get('DEFAULT'),str) else next((x for x in v.values() if isinstance(x,str)),None)
            if isinstance(v,str) and re.fullmatch(r"[a-z][a-z']{0,%d}"%(MAX_IN-1),w) and 0<len(v)<MAX_OUT-1:pairs[w]=v
    return sorted(pairs.items())


class G2P(nn.Module):
    def __init__(self,n_in,n_out,d=256,heads=4,layers=3,ff=1024,drop=0.1):
        super().__init__()
        self.src=nn.Embedding(n_in,d,padding_idx=PAD);self.tgt=nn.Embedding(n_out,d,padding_idx=PAD)
        self.pos_in=nn.Parameter(torch.randn(MAX_IN+2,d)*0.02);self.pos_out=nn.Parameter(torch.randn(MAX_OUT+2,d)*0.02)
        self.tf=nn.Transformer(d,heads,layers,layers,ff,drop,batch_first=True,norm_first=True);self.out=nn.Linear(d,n_out)

    def encode(self,src):
        return self.tf.encoder(self.src(src)+self.pos_in[:src.shape[1]],src_key_padding_mask=src==PAD)

    def decode(self,memory,src,tgt):
        t=tgt.shape[1];mask=torch.triu(torch.full((t,t),float('-inf'),device=tgt.device),1)
        h=self.tf.decoder(self.tgt(tgt)+self.pos_out[:t],memory,tgt_mask=mask,memory_key_padding_mask=src==PAD)
        return self.out(h)


IN_LEN,OUT_LEN=MAX_IN+2,MAX_OUT+2  # ONNX graphs use fixed, PAD-padded shapes (masks make the padding inert)


class Encoder(nn.Module):  # ONNX: chars [1,IN_LEN] -> memory [1,IN_LEN,d]
    def __init__(self,m):super().__init__();self.m=m
    def forward(self,src):return self.m.encode(src)


class Decoder(nn.Module):  # ONNX: memory, chars (memory mask), phonemes [1,OUT_LEN] -> logits [1,OUT_LEN,V]; read row t
    def __init__(self,m):super().__init__();self.m=m
    def forward(self,memory,src,tgt):return self.m.decode(memory,src,tgt)


def pad(ids,n):return ids+[PAD]*(n-len(ids))


def greedy(model,src,n):
    memory=model.encode(src);tgt=torch.full((src.shape[0],1),BOS,device=src.device);done=torch.zeros(src.shape[0],dtype=torch.bool,device=src.device)
    for _ in range(n):
        nxt=model.decode(memory,src,tgt)[:,-1].argmax(-1);nxt[done]=PAD;tgt=torch.cat([tgt,nxt[:,None]],1);done|=nxt==EOS
        if done.all():break
    return tgt[:,1:]


def edit(a,b):
    d=list(range(len(b)+1))
    for i,ca in enumerate(a,1):
        p,d[0]=d[0],i
        for j,cb in enumerate(b,1):p,d[j]=d[j],min(d[j]+1,d[j-1]+1,p+(ca!=cb))
    return d[-1]


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--epochs',type=int,default=30);ap.add_argument('--batch',type=int,default=256)
    ap.add_argument('--lr',type=float,default=7e-4);ap.add_argument('--seed',type=int,default=20261030)
    ap.add_argument('--export-only',action='store_true',help='re-export the saved checkpoint (artifacts/lens-model/checkpoints/g2p-en)');args=ap.parse_args()
    torch.manual_seed(args.seed);rng=random.Random(args.seed);dev='cuda' if torch.cuda.is_available() else 'cpu'
    pairs=load();held=lambda w:int(hashlib.sha256(w.encode()).hexdigest(),16)%50==0
    train=[p for p in pairs if not held(p[0])];val=[p for p in pairs if held(p[0])]
    chars=['<pad>','<s>','</s>']+sorted({c for w,_ in pairs for c in w});phones=['<pad>','<s>','</s>']+sorted({c for _,v in pairs for c in v})
    ci={c:i for i,c in enumerate(chars)};pi={c:i for i,c in enumerate(phones)}
    enc=lambda w:[ci[c] for c in w];dec=lambda v:[BOS]+[pi[c] for c in v]+[EOS]
    def tensor(seqs,n):
        t=torch.zeros(len(seqs),n,dtype=torch.long)
        for i,s in enumerate(seqs):t[i,:len(s)]=torch.tensor(s)
        return t.to(dev)
    model=G2P(len(chars),len(phones)).to(dev);opt=torch.optim.AdamW(model.parameters(),lr=args.lr,weight_decay=0.01)
    steps=args.epochs*math.ceil(len(train)/args.batch);warm=1000
    sched=torch.optim.lr_scheduler.LambdaLR(opt,lambda s:min(1,(s+1)/warm)*0.5*(1+math.cos(math.pi*min(1,s/steps))))

    def evaluate(items):
        model.eval();errs=n=words=0
        with torch.no_grad():
            for k in range(0,len(items),512):
                part=items[k:k+512];src=tensor([enc(w) for w,_ in part],max(len(w) for w,_ in part))
                for (w,v),row in zip(part,greedy(model,src,MAX_OUT).tolist()):
                    p=''.join(phones[x] for x in row if x>EOS) if EOS not in row else ''.join(phones[x] for x in row[:row.index(EOS)] if x>EOS)
                    e=edit(v,p);errs+=e;n+=len(v);words+=e==0
        model.train();return errs/n,words/len(items)
    t0=time.perf_counter();log=[];ckpt=ROOT/'artifacts/lens-model/checkpoints/g2p-en/model.pt'
    if args.export_only:model.load_state_dict(torch.load(ckpt,map_location=dev));args.epochs=0
    for epoch in range(args.epochs):
        rng.shuffle(train)
        for k in range(0,len(train),args.batch):
            part=train[k:k+args.batch];src=tensor([enc(w) for w,_ in part],max(len(w) for w,_ in part))
            tgt=tensor([dec(v) for _,v in part],max(len(v) for _,v in part)+2)
            logits=model.decode(model.encode(src),src,tgt[:,:-1])
            loss=F.cross_entropy(logits.reshape(-1,logits.shape[-1]),tgt[:,1:].reshape(-1),ignore_index=PAD,label_smoothing=0.1)
            opt.zero_grad(set_to_none=True);loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1.0);opt.step();sched.step()
        per,wa=evaluate(val[:2000]);log.append({'epoch':epoch+1,'loss':float(loss.detach()),'val_phoneme_error':per,'val_word_accuracy':wa,'seconds':time.perf_counter()-t0})
        print(json.dumps(log[-1]),flush=True)
    if not args.export_only:ckpt.parent.mkdir(parents=True,exist_ok=True);torch.save(model.state_dict(),ckpt)
    per,wa=evaluate(val);print('held-out words',len(val),'phoneme error',round(per,4),'word accuracy',round(wa,4))
    OUT.mkdir(parents=True,exist_ok=True);model=model.eval().cpu()
    # Fixed shapes: the TorchScript exporter bakes attention's sequence length into Reshape constants.
    torch.backends.mha.set_fastpath_enabled(False)
    # Wrappers in eval mode: the exporter restores the wrapper's mode afterwards, which would put the model back in training.
    src=torch.tensor([pad(enc('zephyrus'),IN_LEN)]);memory=Encoder(model).eval()(src)
    torch.onnx.export(Encoder(model).eval(),(src,),str(OUT/'encoder.onnx'),input_names=['chars'],output_names=['memory'],opset_version=17,dynamo=False)
    torch.onnx.export(Decoder(model).eval(),(memory,src,torch.tensor([pad([BOS],OUT_LEN)])),str(OUT/'decoder.onnx'),
                      input_names=['memory','chars','phonemes'],output_names=['logits'],opset_version=17,dynamo=False)
    model.eval()
    (OUT/'vocab.json').write_text(json.dumps({'chars':chars,'phonemes':phones,'pad':PAD,'bos':BOS,'eos':EOS,'max_out':MAX_OUT,
                                              'input_length':IN_LEN,'output_length':OUT_LEN},ensure_ascii=False),encoding='utf-8')
    import numpy as np,onnxruntime as ort  # parity: ONNX greedy decoding equals PyTorch on words of several lengths
    e=ort.InferenceSession(str(OUT/'encoder.onnx'),providers=['CPUExecutionProvider']);d=ort.InferenceSession(str(OUT/'decoder.onnx'),providers=['CPUExecutionProvider'])
    for w,_ in val[:200]:
        chars=np.array([pad(enc(w),IN_LEN)],dtype=np.int64);mem=e.run(None,{'chars':chars})[0];out=[BOS]
        for _ in range(MAX_OUT):
            b=int(d.run(None,{'memory':mem,'chars':chars,'phonemes':np.array([pad(out,OUT_LEN)],dtype=np.int64)})[0][0,len(out)-1].argmax())
            if b==EOS:break
            out.append(b)
        with torch.no_grad():ref=[x for x in greedy(model,torch.tensor([enc(w)]),MAX_OUT)[0].tolist()]
        ref=ref[:ref.index(EOS)] if EOS in ref else ref
        if out[1:]!=ref:raise SystemExit(f'ONNX export differs from PyTorch on {w!r}: {out[1:]} vs {ref}')
    print('export parity: 200 held-out words identical')
    sha=lambda p:hashlib.sha256((OUT/p).read_bytes()).hexdigest()
    (OUT/'training.json').write_text(json.dumps({'data':'misaki us_gold + us_silver (Apache-2.0)','pairs':len(pairs),'train':len(train),'held_out':len(val),
        'held_out_rule':'sha256(word) % 50 == 0','held_out_phoneme_error':per,'held_out_word_accuracy':wa,'args':vars(args),'device':dev,
        'parameters':sum(p.numel() for p in model.parameters()),'log':log,'files':{f:sha(f) for f in ('encoder.onnx','decoder.onnx','vocab.json')}},indent=1),encoding='utf-8')
    print('wrote',OUT)


if __name__=='__main__':main()
