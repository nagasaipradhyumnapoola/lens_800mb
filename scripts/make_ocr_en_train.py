"""Synthetic English screen text lines for fine-tuning the general (Latin + Chinese) screen recogniser (development only).

Text is programmatic or from licensed public corpora, never from the OCR dev/held-out generators:
- code in Python, JavaScript, SQL, Go, C#, YAML, JSON and Bash built from templates with identifiers drawn from the
  corpus vocabulary (snake_case, camelCase, PascalCase), strings, numbers, operators, comments, brackets;
- terminals: `ls -l` listings, bash/PowerShell/cmd prompts with flags (including `-l` next to `-1`), git/npm/pip/docker
  output, Windows and POSIX paths, progress markers;
- UI text: settings labels with values (On, Off, 35%, Automatic), menus, buttons, status bars, tab titles, mixed case;
- identifiers, e-mail-like and URL-like strings, version numbers, hashes, dates, times, money, percentages;
- English prose from SQuAD 2.0 train contexts (CC BY-SA 4.0) and, for 15% of lines, Spanish/German XQuAD contexts
  (CC BY-SA 4.0) so the other Latin-script languages are not forgotten.
Rendering: headless Microsoft Edge (no window, temporary profile) on 2400-px-tall pages at device scales 1, 1.25, 1.5
and 2, sizes 9-26 CSS px, light/dark/low-contrast/coloured themes, syntax colours on code. Fonts are Windows fonts that
the English held-out set does NOT use: Segoe UI, Consolas, Arial, Arial Narrow, Times New Roman, Calibri, Bahnschrift,
Corbel, Constantia, Franklin Gothic, Microsoft Sans Serif, Palatino Linotype, Sitka, Ebrima, Gadugi, MS Gothic
(held-out: Tahoma, Verdana, Cascadia Mono, Lucida Console, Courier New, Georgia, Trebuchet MS, Cambria, Candara).
Boxes come from the shipped detector (scripts/make_ocr_te_train.py Detector, identical to lens-ocr); each row's crop
is stored with a 6-px margin and its exact box. Labels collapse whitespace (the metric does too).
Output: artifacts/ocr-train/en-screen-v1/crops/, lines.jsonl, manifest.json
Usage: .venv-train\\Scripts\\python.exe scripts/make_ocr_en_train.py --prepare-corpus   (pyarrow; writes corpus.json once)
       .venv\\Scripts\\python.exe scripts/make_ocr_en_train.py [--pages 1100] [--seed 11]
"""
import argparse
import hashlib
import html
import json
from pathlib import Path
import random
import re
import tempfile
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/ocr-train/en-screen-v1'
CORPUS=OUT/'corpus.json'
DICT=ROOT/'models/PaddlePaddle--PP-OCRv6_tiny_rec/ctc-dictionary.json'
EXT=ROOT/'data/external'
UI=['Segoe UI','Arial','Calibri','Bahnschrift','Corbel','Franklin Gothic Medium','Microsoft Sans Serif','Ebrima','Gadugi','Arial Narrow','Segoe UI Semilight']
SERIF=['Times New Roman','Constantia','Palatino Linotype','Sitka Text']
MONO=['Consolas','Consolas','Consolas','MS Gothic']
THEMES=[('#ffffff','#1f2328','#6e7781'),('#1e1e1e','#d4d4d4','#858585'),('#0c0c0c','#cccccc','#767676'),('#012456','#eeedf0','#9aa6c3'),
        ('#f3f3f3','#3b3b3b','#9a9a9a'),('#2b2d31','#dbdee1','#949ba4'),('#fffbe6','#5c4b00','#a08c3c'),('#ffffff','#6b7280','#a1a1aa')]
SYNTAX=[['#c586c0','#ce9178','#6a9955','#b5cea8','#4fc1ff'],['#af00db','#a31515','#008000','#098658','#0070c1']]
KEYWORDS=set('def return import from class if else elif for while in not and or with as try except raise lambda yield async await const let var '
             'function new this null true false True False None SELECT FROM WHERE GROUP BY ORDER JOIN ON AS AND OR LIMIT INSERT INTO VALUES '
             'UPDATE SET func package type struct interface go defer public private static void string int bool namespace using'.split())


def prepare_corpus():
    import pyarrow.parquet as pq
    split=lambda texts,hi:[s.strip() for t in texts for s in re.split(r'(?<=[.!?])\s+',t) if 20<=len(s.strip())<=hi]
    ctx=list(dict.fromkeys(pq.read_table(EXT/'squad_v2/train.parquet',columns=['context']).column('context').to_pylist()))
    random.Random(5).shuffle(ctx)
    other=[c for lang in ('es','de') for c in dict.fromkeys(pq.read_table(EXT/f'xquad/xquad.{lang}.parquet',columns=['context']).column('context').to_pylist())]
    OUT.mkdir(parents=True,exist_ok=True)
    CORPUS.write_text(json.dumps({'english':split(ctx[:6000],400),'latin':split(other,300)},ensure_ascii=False),encoding='utf-8')
    print('corpus',CORPUS)


class Corpus:
    def __init__(self,rng):
        corpus=json.loads(CORPUS.read_text(encoding='utf-8'));self.sentences=corpus['english'];self.other=corpus['latin']
        words=[w for s in self.sentences[:40000] for w in re.findall(r"[A-Za-z][a-z]{2,11}",s)]
        self.words=list(dict.fromkeys(w.lower() for w in words));self.names=list(dict.fromkeys(w for w in words if w[0].isupper()))[:4000]
        self.rng=rng

    def w(self):return self.rng.choice(self.words)
    def ident(self):
        parts=[self.w() for _ in range(self.rng.choice([1,1,2,2,3]))];style=self.rng.random()
        if style<0.45:return '_'.join(parts)
        if style<0.8:return parts[0]+''.join(p.capitalize() for p in parts[1:])
        return ''.join(p.capitalize() for p in parts)
    def num(self):
        r=self.rng;k=r.random()
        if k<0.3:return str(r.randint(0,99))
        if k<0.5:return str(r.randint(100,99999))
        if k<0.7:return f'{r.randint(0,999)}.{r.randint(0,99):02d}'
        if k<0.85:return f'{r.randint(1,999):,}'.replace(',',r.choice([',',',','']))+(f',{r.randint(0,999):03d}' if r.random()<0.4 else '')
        return f'0x{r.randint(0,65535):04x}'
    def phrase(self,lo=3,hi=12):
        s=self.rng.choice(self.sentences).split();n=self.rng.randint(lo,hi);i=self.rng.randint(0,max(0,len(s)-n));return ' '.join(s[i:i+n])


def code(c):
    r=c.rng;i,j,s=c.ident(),c.ident(),c.w();q=r.choice(['"',"'"]);ind=' '*r.choice([0,0,2,4,4,8,12])
    t=r.choice([
        f'def {i}({j}: {r.choice(["str","int","Path","list[dict]","dict[str, int]"])}) -> {r.choice(["None","bool","list[str]","int"])}:',
        f'{i} = {j}.get({q}{s}{q}, {c.num()})',f'for {i} in sorted({j}.items(), key=lambda kv: -kv[1]):',
        f'if {i} is not None and len({j}) >= {r.randint(1,9)}:',f'return {{{q}{s}{q}: {i}, {q}{c.w()}{q}: [{c.num()}, {c.num()}]}}',
        f'{i}[{q}{s}{q}] = float({j}[{q}{s}{q}])',f'with open({q}{s}.{r.choice(["csv","json","txt","log"])}{q}, encoding={q}utf-8{q}) as f:',
        f'"""{c.phrase(3,9)}."""',f'# {c.phrase(3,10)}',f'print(f"{{{i}}}: {{{j}:.2f}}")',f'self.{i} = {j} or []',
        f'const {i} = await fetch(`/api/v{r.randint(1,3)}/{s}?limit=${{{j}}}`);',f'export function {i}({j}, {c.ident()} = {c.num()}) {{',
        f'{i}.map(({j}) => {j}.{c.ident()}).filter(Boolean);',f'// {c.phrase(3,10)}',f'if ({i} !== null && {j}.length > {r.randint(0,9)}) {{',
        f'let {i} = {{ {s}: {q}{c.w()}{q}, {c.w()}: {c.num()} }};',f'}} else {{',f'}});',
        f'SELECT {i}, COUNT(*) AS {j} FROM {s} WHERE {c.w()} > {c.num()} GROUP BY {i};',f'-- {c.phrase(3,10)}',
        f"date_trunc('{r.choice(['month','week','day'])}', o.{i}) AS {j},",f'LEFT JOIN {s} s ON s.{i} = o.{j}',
        f'func ({i[:1]} *{j.capitalize()}) {c.ident().capitalize()}(ctx context.Context) error {{',f'if err != nil {{ return fmt.Errorf("{s}: %w", err) }}',
        f'public async Task<{r.choice(["int","bool","string"])}> {c.ident().capitalize()}Async({c.ident().capitalize()} {j})',
        f'{s}:',f'  {c.w()}: {r.choice([c.num(),c.w(),"true","false"])}',f'  - name: {c.ident()}',
        f'{{"{s}": {c.num()}, "{c.w()}": "{c.w()}", "{c.w()}": [{c.num()}, null]}}',
        f'export {i.upper()}="{c.w()}"; echo "${i.upper()}" | grep -i {s}'])
    return ind+t


def terminal(c):
    r=c.rng;u=c.w()[:8];perm=r.choice(['-rw-r--r--','-rwxr-xr-x','drwxr-xr-x','-rw-------','lrwxrwxrwx'])
    month=r.choice(['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'])
    f=f'{c.ident()}-{r.randint(1,99)}.{r.choice(["py","md","pdf","json","log","txt","csv","yml","rs"])}'
    return r.choice([
        f'{perm} {r.randint(1,9)} {u} {r.choice(["staff","users","root"])} {r.randint(10,999999):>6} {month} {r.randint(1,28):>2} {r.randint(0,23):02d}:{r.randint(0,59):02d} {f}',
        f'{u}@{c.w()}-{r.randint(1,9)}:~/{c.w()}/{c.w()}$ {r.choice(["ls -l","ls -la","ls -1","git status","git log --oneline -5","python -m pytest -q","make -j4"])} {c.w() if r.random()<0.4 else ""}'.rstrip(),
        f'PS C:\\Users\\{u}\\{c.w()}> {r.choice(["git status","ls","Get-ChildItem -Recurse","npm run build","python .\\"+c.w()+".py"])}',
        f'C:\\{c.w().capitalize()}\\{c.w()}>{r.choice(["dir","cd ..","ipconfig /all","type "+f])}',
        f'        modified:   {r.choice(["src","tests","lib","app"])}/{f}',f'{r.randint(1,99)} passed, {r.randint(0,3)} failed in {r.randint(0,59)}.{r.randint(10,99)}s',
        f'{"."*r.randint(8,40)}{r.choice(["F",".","E","s"])}{"."*r.randint(0,12)} [{r.randint(10,100):>3}%]',
        f'   Compiling {c.w()} v{r.randint(0,3)}.{r.randint(0,30)}.{r.randint(0,9)}',f'Successfully installed {c.w()}-{r.randint(0,9)}.{r.randint(0,20)}.{r.randint(0,9)}',
        f'{c.w()}-{r.randint(1,9)}   Up {r.randint(2,59)} minutes   0.0.0.0:{r.randint(1024,65535)}->{r.randint(80,9000)}/tcp',
        f'  {r.randint(1,400)}:{r.randint(1,120)}  {r.choice(["warning","error"])}  {c.phrase(3,6)}  {c.w()}-{c.w()}',
        f'commit {"".join(r.choice("0123456789abcdef") for _ in range(40))}',f'Author: {r.choice(c.names)} <{c.w()}@{c.w()}.org>'])


def ui(c):
    r=c.rng;label_=' '.join(w.capitalize() if k==0 else w for k,w in enumerate(c.phrase(1,4).split()))
    return r.choice([
        f'{label_} {r.choice(["On","Off","Automatic","Never","Always",f"{r.randint(1,100)}%","Default","Enabled","Disabled"])}',
        label_,f'{label_}...',f'Ln {r.randint(1,999)}, Col {r.randint(1,120)}  Spaces: {r.choice([2,4,8])}  UTF-8  {r.choice(["CRLF","LF"])}',
        f'{c.ident()}.{r.choice(["py","ts","tsx","js","md","json","cs","go","sql","yaml"])}',
        f'{r.choice(c.names)} {r.randint(1,12)}:{r.randint(0,59):02d} {r.choice(["AM","PM"])}',f'{r.randint(1,28)} {r.choice(["Jan","March","Sep","November"])} {r.randint(2019,2030)}',
        f'${r.randint(1,99999):,}.{r.randint(0,99):02d}',f'{r.randint(0,100)}% complete',f'https://{c.w()}.{r.choice(["com","org","io","dev"])}/{c.w()}/{r.randint(1,999)}?ref={c.w()}',
        f'{c.w()}.{c.w()}@{c.w()}.com',f'v{r.randint(0,9)}.{r.randint(0,40)}.{r.randint(0,99)}',f'{c.ident()} ({r.randint(1,999)})',
        f'{label_.upper()}',f'Home > {c.w().capitalize()} > {c.w().capitalize()}',f'Saved {r.randint(1,59)} {r.choice(["seconds","minutes"])} ago'])


def line(c):
    k=c.rng.random()
    if k<0.25:return 'code',code(c)
    if k<0.42:return 'terminal',terminal(c)
    if k<0.62:return 'ui',ui(c)
    if k<0.85:return 'prose',c.phrase(4,16)
    phrase=c.rng.choice(c.other).split();n=c.rng.randint(4,14);return 'latin',' '.join(phrase[:n])


def colour(text,palette,rng):
    out=[]
    for tok in re.findall(r'"[^"]*"|\'[^\']*\'|`[^`]*`|\w+|\s+|[^\w\s]',text):
        e=html.escape(tok,quote=False)
        if tok[:1] in '"\'`':out.append(f'<span style="color:{palette[1]}">{e}</span>')
        elif tok in KEYWORDS:out.append(f'<span style="color:{palette[0]}">{e}</span>')
        elif tok.isdigit():out.append(f'<span style="color:{palette[3]}">{e}</span>')
        elif rng.random()<0.15 and tok.strip():out.append(f'<span style="color:{palette[4]}">{e}</span>')
        else:out.append(e)
    return ''.join(out)


def page(c,height,scale):
    r=c.rng;bg,fg,mu=r.choice(THEMES);dark=int(bg[1:3],16)<128;rows=[];y=16;css_h=height/scale
    while True:
        kind,text=line(c)
        if kind in('code','terminal'):font=r.choice(MONO);weight=r.choice([400,400,400,700])
        elif kind=='prose' and r.random()<0.35:font=r.choice(SERIF);weight=r.choice([400,400,700])
        else:font=r.choice(UI);weight=r.choice([300,400,400,400,600,700])
        size=r.choice([9,10,10,11,11,12,12,13,13,14,14,15,16,18,20,22,26]);step=int(size*r.uniform(2.2,2.8))
        if y+step>css_h-16:break
        colour_=r.choice([fg,fg,fg,mu]);markup=colour(text,SYNTAX[0 if dark else 1],r) if kind=='code' and r.random()<0.7 else html.escape(text,quote=False)
        rows.append((y,size,font,weight,r.randint(8,160),text,kind,markup,colour_));y+=step
    body=''.join(f'<div style="top:{y}px;left:{x}px;font:{w} {s}px \'{f}\';color:{col}">{m}</div>' for y,s,f,w,x,t,k,m,col in rows)
    doc=(f'<!doctype html><html><head><meta charset="utf-8"><style>body{{margin:0;background:{bg}}}div{{position:absolute;white-space:pre}}</style></head>'
         f'<body>{body}</body></html>')
    return rows,doc


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--pages',type=int,default=1100);ap.add_argument('--seed',type=int,default=11)
    ap.add_argument('--height',type=int,default=2400);ap.add_argument('--prepare-corpus',action='store_true');args=ap.parse_args()
    if args.prepare_corpus:return prepare_corpus()
    import cv2
    import numpy as np
    from make_ocr_screens import edge_version
    from make_ocr_te_train import Detector,Edge,label  # cv2/onnxruntime/aiohttp: the runtime venv, not .venv-train
    rng=random.Random(args.seed);c=Corpus(rng);dictionary=set(json.loads(DICT.read_text(encoding='utf-8')))
    (OUT/'crops').mkdir(parents=True,exist_ok=True);detect=Detector();kept=skipped=0;kinds={}
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile,tempfile.TemporaryDirectory() as pages,open(OUT/'lines.jsonl','w',encoding='utf-8') as out:
        edge=Edge(profile,args.height)
        for p in range(args.pages):
            scale=rng.choice([1,1,1,1.25,1.5,2]);rows,doc=page(c,args.height,scale);src=Path(pages)/f'page{p}.html';src.write_text(doc,encoding='utf-8')
            png=edge.screenshot(src.as_uri(),size=(round(1280/scale),round(args.height/scale)),scale=scale)
            img=cv2.imdecode(np.frombuffer(png,np.uint8),cv2.IMREAD_COLOR);boxes=detect(img)
            for i,(y,s,f,w,x,t,k,m,col) in enumerate(rows):
                lo=(y-s*0.3)*scale;hi=(rows[i+1][0]-s*0.3)*scale if i+1<len(rows) else img.shape[0]
                mine=[b for b in boxes if lo<=(b[1]+b[3])/2<hi];text=' '.join(label(t).split())
                if not mine or not text or any(ch not in dictionary for ch in text):skipped+=1;continue
                b=[min(q[0] for q in mine),min(q[1] for q in mine),max(q[2] for q in mine),max(q[3] for q in mine)]
                m0=[max(0,b[0]-6),max(0,b[1]-6),min(img.shape[1],b[2]+6),min(img.shape[0],b[3]+6)]
                name=f'p{p:04d}-{i:02d}.png';cv2.imwrite(str(OUT/'crops'/name),img[m0[1]:m0[3],m0[0]:m0[2]])
                out.write(json.dumps({'crop':name,'box':[b[0]-m0[0],b[1]-m0[1],b[2]-m0[0],b[3]-m0[1]],'boxes':len(mine),'text':text,
                                      'kind':k,'font':f,'weight':w,'size':s,'scale':scale},ensure_ascii=False)+'\n');kept+=1;kinds[k]=kinds.get(k,0)+1
            if p%50==0:print('page',p,'lines',kept,'skipped',skipped,flush=True)
        edge.close()
    (OUT/'manifest.json').write_text(json.dumps({'generator':'scripts/make_ocr_en_train.py','seed':args.seed,'pages':args.pages,'page_height':args.height,
        'edge_version':edge_version(),'fonts':{'ui':UI,'serif':SERIF,'mono':sorted(set(MONO))},'sources':{'prose':'SQuAD 2.0 train contexts (CC BY-SA 4.0)',
        'latin':'XQuAD es/de contexts (CC BY-SA 4.0)'},'detector':'PP-OCRv5_mobile_det, lens-ocr axis-aligned DB post-processing (Python mirror)',
        'lines':kept,'skipped':skipped,'by_kind':kinds,'lines_sha256':hashlib.sha256((OUT/'lines.jsonl').read_bytes()).hexdigest()},indent=1),encoding='utf-8')
    print('lines',kept,'skipped',skipped,kinds)


if __name__=='__main__':main()
