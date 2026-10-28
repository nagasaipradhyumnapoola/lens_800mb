"""English screen OCR under hard real-world conditions: a DEV split (tuning) and a HELD-OUT split (evaluation only).

Conditions (docs/LENS_V1_SPEC.md §1a, English first): small UI text (9-11 px), code editors (monospace, syntax colours,
line-number gutter, dark/light), terminals (shell, PowerShell), browser pages (address bar, nav links, article, footer),
PDF-like pages (serif body, 9 px footnotes), tables/spreadsheets, chat apps (names, timestamps, bubbles), mail lists,
low-contrast themes, and device scales 1, 1.25, 1.5 and 2 (bitmaps up to 2560x1600). Rendering is headless Microsoft
Edge (no window, temporary profile) over the DevTools protocol with Chromium's default (greyscale) anti-aliasing;
ClearType sub-pixel text is NOT covered.
Ground truth comes from the rendered DOM: every row (class "r") must be a single line box fully inside the viewport,
otherwise the screen is rebuilt with fewer rows; a row's text is its cells (class "c") joined by one space, left to
right. Content is authored/programmatic English (no personal data). The two splits share no font, template, vocabulary
item, code snippet or seed: dev uses Segoe UI, Consolas, Arial, Times New Roman, Calibri; held-out uses Tahoma, Verdana,
Cascadia Mono, Lucida Console, Courier New, Georgia, Trebuchet MS, Cambria, Candara.
Output: artifacts/ocr-screens/en-hard-{dev,heldout}/<scenario>.png and manifest.json
Usage: .venv\\Scripts\\python.exe scripts/make_ocr_screens_en_hard.py [--split dev|heldout|both]
"""
import argparse
import hashlib
import html
import json
from pathlib import Path
import random
import re
import tempfile
from make_ocr_screens import edge_version
from make_ocr_te_train import Edge
ROOT=Path(__file__).resolve().parents[1]

WORDS=dict(  # each list is split by position: even items -> dev, odd items -> held-out
 names=['Priya','Arjun','Maya','Daniel','Sofia','Kenji','Amara','Lucas','Elena','Omar','Hannah','Ravi','Chloe','Mateo','Nadia','Ethan',
        'Leila','Victor','Grace','Samuel','Isabel','Noah','Zara','Felix','Ingrid','Tomas','Aisha','Martin','Yuki','Bruno','Clara','Dev'],
 nouns=['invoice','roadmap','budget','release','contract','meeting','backlog','dashboard','migration','proposal','forecast','audit',
        'sprint','vendor','template','checklist','pipeline','schedule','estimate','handbook','renewal','inventory','report','ticket',
        'deadline','workshop','survey','prototype','license','quota','summary','payroll'],
 verbs=['review','update','approve','share','merge','archive','schedule','draft','sign','export','rename','restore','assign','close',
        'verify','publish','upload','cancel','confirm','flag','reopen','attach','tag','sync'],
 places=['Room B12','Hall 4','Lab 7','Studio 2','Floor 9','Desk 31','Bay 5','Suite 210','Wing C','Annex 3','Room 1.14','Office 88'],
 orgs=['Northwind','Contoso','Fabrikam','Tailspin','Litware','Proseware','Adatum','Wingtip','Lucerne','Margie','Fourth Coffee','Woodgrove'],
 exts=['pdf','xlsx','docx','csv','json','png','md','zip','txt','pptx','log','yaml'],
 months=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'],
 settings=['Show notifications','Start on login','Automatic updates','Dark mode','Sync over metered connections','Send usage data',
           'Spell check','Default download folder','Keyboard shortcuts','Battery saver','Night light','Focus assist','Text size',
           'Language','Time zone','Proxy server','Microphone access','Location access','Backup schedule','Storage sense',
           'Screen timeout','Sound output','Pointer speed','Clipboard history'],
)
TEMPLATES={  # sentences for browser/PDF/chat/mail rows
 'dev':['{name} asked the team to {verb} the {noun} before {weekday}.','The {noun} for {org} is due on {date}.',
        'Please {verb} the attached {noun} and reply by {time}.','{org} moved the {noun} review to {place}.',
        'Total for the {noun}: ${amount} across {count} items.','We will {verb} version {version} after the {noun} call.',
        'Reminder: the {noun} closes at {time} on {weekday}.','{name} shared {file} with {count} people.'],
 'heldout':['Could you {verb} the {noun} for {org} by {date}?','{name} left {count} comments on the {noun} draft.',
            'Our {noun} budget is ${amount}, up {percent}% from last quarter.','The {weekday} {noun} sync starts at {time} in {place}.',
            '{name}: I will {verb} {file} tonight.','Version {version} fixes the {noun} export bug.',
            'Status of the {noun}: {count} open, {count2} done.','{org} signed the {noun} on {date}.'],
}
CODE={
 'dev':[('python','''import csv
from pathlib import Path

def load_invoices(folder: Path) -> list[dict]:
    """Read every CSV invoice in the folder."""
    rows = []
    for path in sorted(folder.glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                row["amount"] = float(row["amount"])
                rows.append(row)
    return rows

def total_by_vendor(rows):
    totals = {}
    for row in rows:
        totals[row["vendor"]] = totals.get(row["vendor"], 0) + row["amount"]
    return dict(sorted(totals.items(), key=lambda kv: -kv[1]))

if __name__ == "__main__":
    print(total_by_vendor(load_invoices(Path("data/2026"))))'''),
        ('javascript','''// Debounced search box for the project list
const input = document.querySelector("#search");
let timer = null;

function render(items) {
  const list = document.getElementById("results");
  list.innerHTML = items.map(i => `<li>${i.name} (${i.owner})</li>`).join("");
}

input.addEventListener("input", (event) => {
  clearTimeout(timer);
  timer = setTimeout(async () => {
    const q = encodeURIComponent(event.target.value.trim());
    const res = await fetch(`/api/projects?q=${q}&limit=25`);
    if (!res.ok) { console.error("search failed", res.status); return; }
    render(await res.json());
  }, 250);
});'''),
        ('sql','''-- Monthly revenue per region, last 6 months
SELECT r.name AS region,
       date_trunc('month', o.created_at) AS month,
       SUM(o.total_cents) / 100.0 AS revenue,
       COUNT(DISTINCT o.customer_id) AS customers
FROM orders o
JOIN regions r ON r.id = o.region_id
WHERE o.status = 'paid'
  AND o.created_at >= now() - interval '6 months'
GROUP BY 1, 2
HAVING SUM(o.total_cents) > 500000
ORDER BY month DESC, revenue DESC
LIMIT 50;''')],
 'heldout':[('go','''package billing

import (
	"errors"
	"time"
)

var ErrExpired = errors.New("contract expired")

type Contract struct {
	ID       int64
	Vendor   string
	Deadline time.Time
}

func (c Contract) Check(now time.Time) error {
	if now.After(c.Deadline) {
		return ErrExpired
	}
	return nil
}

func Remaining(c Contract, now time.Time) time.Duration {
	return c.Deadline.Sub(now).Round(time.Hour)
}'''),
            ('rust','''use std::collections::HashMap;

#[derive(Debug, Clone)]
pub struct Ticket {
    pub id: u32,
    pub title: String,
    pub points: u8,
}

pub fn points_by_label(tickets: &[Ticket]) -> HashMap<&str, u32> {
    let mut out = HashMap::new();
    for t in tickets {
        let label = if t.points > 5 { "large" } else { "small" };
        *out.entry(label).or_insert(0) += t.points as u32;
    }
    out
}

fn main() {
    let t = vec![Ticket { id: 7, title: "Fix export".into(), points: 3 }];
    println!("{:?}", points_by_label(&t));
}'''),
            ('yaml','''# CI pipeline for the reporting service
name: build-and-test
on:
  push:
    branches: [main, "release/*"]
  pull_request:
jobs:
  test:
    runs-on: windows-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - name: Install dependencies
        run: python -m pip install -r requirements.txt
      - name: Run tests
        run: python -m pytest -q --maxfail=3
      - name: Upload coverage
        if: always()
        run: echo "coverage stored in reports/cov.xml"''')],
}
KEYWORDS=set('import from def return for in with as if else not and or class lambda const let function async await fetch '
             'SELECT FROM JOIN ON WHERE AND GROUP BY HAVING ORDER LIMIT AS DESC COUNT SUM DISTINCT package var type struct func '
             'nil use pub fn let mut out vec name on jobs steps run uses if'.split())
FONTS={'dev':dict(ui='"Segoe UI"',mono='Consolas',web='Arial',serif='"Times New Roman"',chat='Calibri'),
       'heldout':dict(ui='Tahoma',ui2='Verdana',mono='"Cascadia Mono"',mono2='"Lucida Console"',mono3='"Courier New"',
                      web='Georgia',web2='"Trebuchet MS"',serif='Cambria',chat='Candara')}
THEMES={'light':('#ffffff','#1f2328','#6e7781'),'dark':('#1e1f22','#e6e6e6','#9aa0a6'),'low':('#eeeeee','#8a8a8a','#a0a0a0'),
        'lowdark':('#2b2b2b','#7a7a7a','#666666')}
SEEDS={'dev':101,'heldout':202}


class Text:
    def __init__(self,split,rng):
        self.rng=rng;k=0 if split=='dev' else 1
        self.w={key:vals[k::2] for key,vals in WORDS.items()};self.t=TEMPLATES[split]

    def pick(self,key):return self.rng.choice(self.w[key])

    def file(self):return f'{self.pick("noun")}_{self.rng.randint(1,99):02d}.{self.pick("exts")}' if False else f'{self.pick("nouns")}-{self.rng.randint(1,99):02d}.{self.pick("exts")}'

    def date(self):return f'{self.rng.randint(1,28)} {self.pick("months")} {self.rng.choice([2025,2026,2027])}'

    def sentence(self):
        r=self.rng
        return r.choice(self.t).format(name=self.pick('names'),verb=self.pick('verbs'),noun=self.pick('nouns'),org=self.pick('orgs'),
            place=self.pick('places'),date=self.date(),time=f'{r.randint(1,12)}:{r.choice(["00","15","30","45"])} {r.choice(["am","pm"])}',
            weekday=r.choice(['Monday','Tuesday','Wednesday','Thursday','Friday']),amount=f'{r.randint(1,98)},{r.randint(0,999):03d}.{r.randint(0,99):02d}',
            count=r.randint(2,48),count2=r.randint(2,48),version=f'{r.randint(1,9)}.{r.randint(0,20)}.{r.randint(0,9)}',percent=r.randint(2,40),file=self.file())


def row(cells,style=''):
    cells=[cells] if isinstance(cells,str) else cells
    inner=''.join(f'<span class="c">{c}</span>' for c in cells)
    return f'<div class="r"{f" style={chr(34)}{style}{chr(34)}" if style else ""}>{inner}</div>'


def esc(s):return html.escape(s,quote=False)


def colour_code(line,lang,theme):
    kw,st,cm,nm=('#c586c0','#ce9178','#6a9955','#b5cea8') if theme=='dark' else ('#af00db','#a31515','#008000','#098658')
    if re.match(r'\s*(#|//|--)',line):return f'<span style="color:{cm}">{esc(line)}</span>'
    out=[]
    for tok in re.findall(r'"[^"]*"|\'[^\']*\'|`[^`]*`|\w+|\s+|[^\w\s]',line):
        e=esc(tok)
        if tok[:1] in '"\'`':out.append(f'<span style="color:{st}">{e}</span>')
        elif tok in KEYWORDS:out.append(f'<span style="color:{kw}">{e}</span>')
        elif tok.isdigit():out.append(f'<span style="color:{nm}">{e}</span>')
        else:out.append(e)
    return ''.join(out)


def page(css,body,bg):
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><style>html,body{{margin:0;background:{bg}}}'
            f'.r{{white-space:pre}}{css}</style></head><body>{body}</body></html>')


def scenarios(split):
    rng=random.Random(SEEDS[split]);tx=Text(split,rng);F=FONTS[split];out=[]
    f2=lambda k:F.get(k+'2',F[k])
    # 1. small UI text: settings panes at 9, 10, 11 px
    for i,(px,theme) in enumerate([(9,'light'),(10,'dark'),(11,'low'),(10,'light')]):
        bg,fg,mu=THEMES[theme];font=F['ui'] if i%2==0 else f2('ui');items=rng.sample(tx.w['settings'],len(tx.w['settings']))
        def build(n,items=items,px=px,font=font,fg=fg,mu=mu,bg=bg):
            rows=[row('Settings',f'font-weight:600;font-size:{px+3}px')]+[row([esc(s),rng.choice(['On','Off',f'{rng.randint(5,95)}%','Automatic','Never'])]) for s in items[:n]]
            css=(f'body{{font-family:{font};font-size:{px}px;color:{fg};padding:16px 24px}}.r{{display:flex;justify-content:space-between;'
                 f'width:420px;padding:3px 0;border-bottom:1px solid {mu}33}}.c:last-child{{color:{mu}}}')
            return page(css,''.join(rows),bg)
        out.append((f'small-ui-{px}px-{theme}-{i}',build,12,(1280,800),1))
    # 2. code editors with gutter, tab bar and status bar
    for i,(lang,code) in enumerate(CODE[split]):
        for theme,scale in (('dark',1),('light',1.25 if i%2 else 1)):
            bg,fg,mu=THEMES[theme];font=[F['mono'],f2('mono'),F.get('mono3',F['mono'])][i%3];px=13+(i%2)
            lines=code.split('\n')
            def build(n,lines=lines,lang=lang,theme=theme,bg=bg,fg=fg,mu=mu,font=font,px=px):
                rows=[row([f'{lang}_module.{ {"python":"py","javascript":"js","sql":"sql","go":"go","rust":"rs","yaml":"yml"}[lang]}','x'],f'font-size:12px;color:{mu}')]
                rows+=[f'<div class="r"><span class="c g">{k+1}</span><span class="c">{colour_code(l,lang,theme)}</span></div>' for k,l in enumerate(lines[:n]) if l.strip()]
                rows.append(row([f'Ln {rng.randint(1,40)}, Col {rng.randint(1,30)}','Spaces: 4','UTF-8',lang.capitalize()],f'font-size:11px;color:{mu};gap:24px;display:flex'))
                css=(f'body{{font-family:{font};font-size:{px}px;color:{fg};padding:10px 0}}.r{{padding:1px 12px;line-height:1.55}}'
                     f'.g{{display:inline-block;width:36px;color:{mu};text-align:right;margin-right:18px}}')
                return page(css,''.join(rows),bg)
            out.append((f'code-{lang}-{theme}',build,len(lines),(1280,800),scale))
    # 3. terminals
    for i,kind in enumerate(['shell','powershell','shell']):
        bg,fg=('#0c0c0c','#cccccc') if kind=='shell' else ('#012456','#eeedf0')
        def build(n,kind=kind,bg=bg,fg=fg,i=i):
            r=random.Random(SEEDS[split]*10+i);user=tx.pick('names').lower();lines=[]
            prompt=(lambda c:f'{user}@build-{r.randint(2,9)}:~/projects/{tx.pick("nouns")}$ {c}') if kind=='shell' else (lambda c:f'PS C:\\Users\\{user}\\{tx.pick("nouns")}> {c}')
            if split=='dev':
                lines+=[prompt('git status'),'On branch main',"Your branch is up to date with 'origin/main'.",'Changes not staged for commit:',
                        f'        modified:   src/{tx.pick("nouns")}.py',f'        modified:   tests/test_{tx.pick("nouns")}.py',prompt('ls -l reports')]
                lines+=[f'-rw-r--r-- 1 {user} staff {r.randint(1000,99999):>6} {tx.pick("months")} {r.randint(1,28):>2} {r.randint(10,23)}:{r.randint(10,59)} {tx.file()}' for _ in range(5)]
                lines+=[prompt('python -m pytest -q'),f'{"."*r.randint(20,40)}{"F" if r.random()<0.5 else "."}{"."*r.randint(5,15)}  [100%]',
                        f'{r.randint(40,90)} passed, {r.randint(0,2)} failed in {r.randint(2,9)}.{r.randint(10,99)}s']
            else:
                lines+=[prompt('docker ps --format "{{.Names}} {{.Status}}"')]+[f'{tx.pick("nouns")}-{r.randint(1,9)} Up {r.randint(2,59)} minutes' for _ in range(4)]
                lines+=[prompt('cargo build --release'),f'   Compiling {tx.pick("nouns")} v0.{r.randint(1,9)}.{r.randint(0,9)}',
                        f'    Finished `release` profile [optimized] target(s) in {r.randint(10,90)}.{r.randint(10,99)}s',prompt('npm run lint')]
                lines+=[f'  {r.randint(1,200)}:{r.randint(1,80)}  warning  Unexpected console statement  no-console' for _ in range(3)]
                lines+=[f'{r.randint(2,9)} problems (0 errors, {r.randint(2,9)} warnings)']
            rows=[row(esc(l)) for l in lines[:n]]
            css=f'body{{font-family:{F["mono"] if i!=1 else f2("mono")};font-size:{13 if i!=2 else 15}px;color:{fg};padding:12px 16px}}.r{{line-height:1.4}}'
            return page(css,''.join(rows),bg)
        out.append((f'terminal-{kind}-{i}',build,20,(1280,800),1 if i!=2 else 1.5))
    # 4. browser pages: address bar, nav, article, footer
    for i,(theme,scale) in enumerate([('light',1),('dark',1.5),('light',2)]):
        bg,fg,mu=THEMES[theme];font=F['web'] if i%2==0 else f2('web')
        def build(n,bg=bg,fg=fg,mu=mu,font=font):
            org=tx.pick('orgs').replace(' ','').lower()
            rows=[row(f'https://www.{org}.com/{tx.pick("nouns")}/{rng.randint(100,999)}?ref=home',f'font-size:12px;color:{mu};background:{mu}22;padding:6px 10px;border-radius:12px;width:fit-content')]
            rows.append(row([n_.capitalize() for n_ in rng.sample(tx.w['nouns'],5)],'display:flex;gap:28px;color:#3b82f6;font-size:14px;padding:10px 0'))
            rows.append(row(esc(tx.sentence().rstrip('.?')),'font-size:26px;font-weight:700;padding:8px 0'))
            rows+=[row(esc(tx.sentence()),'font-size:16px;line-height:1.9') for _ in range(n)]
            rows.append(row(f'© 2026 {tx.pick("orgs")} · Privacy · Terms · Contact',f'font-size:11px;color:{mu};padding-top:14px'))
            return page(f'body{{font-family:{font};color:{fg};padding:18px 40px}}',''.join(rows),bg)
        out.append((f'browser-{theme}-{i}',build,9,(1280,800),scale))
    # 5. PDF-like page with footnotes
    for i in range(2):
        def build(n,i=i):
            rows=[row(esc(tx.sentence().rstrip('.?')),'font-size:20px;font-weight:700;text-align:center;padding:6px 0'),
                  row(f'{tx.pick("names")} and {tx.pick("names")} · {tx.pick("orgs")} · {tx.date()}','font-size:12px;text-align:center;color:#555;padding-bottom:12px')]
            rows+=[row(esc(tx.sentence()),'font-size:15px;line-height:1.7') for _ in range(n)]
            rows+=[row(f'{k+1} {esc(tx.sentence())}','font-size:9px;color:#333;line-height:1.5') for k in range(3)]
            rows.append(row(f'Page {rng.randint(2,40)} of {rng.randint(41,90)}','font-size:10px;text-align:center;padding-top:10px'))
            css=f'body{{font-family:{F["serif"]};color:#111;background:#fff;padding:30px 120px}}'
            return page(css,''.join(rows),'#525659' if i else '#fff')
        out.append((f'pdf-{i}',build,14,(1280,800),1 if i==0 else 1.25))
    # 6. tables / spreadsheets
    for i,(px,theme) in enumerate([(13,'light'),(12,'dark'),(11,'light')]):
        bg,fg,mu=THEMES[theme];font=F['web'] if i!=1 else F['ui']
        def build(n,px=px,bg=bg,fg=fg,mu=mu,font=font):
            head=['ID','Owner','Item','Due','Amount']
            rows=[row(head,'font-weight:700')]
            rows+=[row([f'{rng.choice("ABCDEFGH")}-{rng.randint(100,9999)}',tx.pick('names'),tx.pick('nouns').capitalize(),tx.date(),
                        f'${rng.randint(1,99)},{rng.randint(0,999):03d}.{rng.randint(0,99):02d}']) for _ in range(n)]
            css=(f'body{{font-family:{font};font-size:{px}px;color:{fg};padding:20px}}.r{{display:grid;grid-template-columns:110px 130px 150px 130px 120px;'
                 f'border-bottom:1px solid {mu}55;padding:5px 0}}')
            return page(css,''.join(rows),bg)
        out.append((f'table-{px}px-{theme}',build,18,(1280,800),1))
    # 7. chat apps
    for i,(theme,scale) in enumerate([('light',1),('dark',1.25)]):
        bg,fg,mu=THEMES[theme];bubble=('#ffffff','#d9fdd3') if theme=='light' else ('#2b2d31','#005c4b')
        def build(n,bg=bg,fg=fg,mu=mu,bubble=bubble):
            rows=[]
            for k in range(n):
                side=k%2;who=tx.pick('names');t=f'{rng.randint(8,11)}:{rng.randint(10,59)} {rng.choice(["AM","PM"])}'
                rows.append(row([who,t],f'font-size:10px;color:{mu};display:flex;gap:10px;margin-left:{380 if side else 0}px'))
                rows.append(row(esc(tx.sentence()),f'background:{bubble[side]};padding:7px 12px;border-radius:9px;width:fit-content;margin:2px 0 8px {380 if side else 0}px'))
            return page(f'body{{font-family:{F["chat"]};font-size:15px;color:{fg};padding:16px 30px}}',''.join(rows),bg)
        out.append((f'chat-{theme}',build,9,(1280,800),scale))
    # 8. mail list (bold unread rows, dates right)
    for i,theme in enumerate(['light','lowdark']):
        bg,fg,mu=THEMES[theme]
        def build(n,bg=bg,fg=fg,mu=mu):
            rows=[row([tx.pick('names'),esc(tx.sentence()),tx.date()],f'font-weight:{700 if rng.random()<0.35 else 400}') for _ in range(n)]
            css=(f'body{{font-family:{F["ui"]};font-size:13px;color:{fg};padding:10px}}.r{{display:grid;grid-template-columns:150px 760px 140px;'
                 f'padding:8px 6px;border-bottom:1px solid {mu}44}}')
            return page(css,''.join(rows),bg)
        out.append((f'mail-{theme}',build,18,(1280,800),1))
    return out


GT_JS="""(()=>{const rows=[...document.querySelectorAll('.r')];return rows.map(r=>{const b=r.getBoundingClientRect();
 const cells=[...r.querySelectorAll(':scope > .c')];const text=(cells.length?cells.map(c=>c.innerText):[r.innerText]).join(' ');
 const lines=cells.length?Math.max(...cells.map(c=>c.getClientRects().length)):r.getClientRects().length;
 const rects=cells.length?cells.map(c=>{const q=c.getBoundingClientRect();return q.height>0&&q.height<b.height*1.01?1:0}):[1];
 return {text,top:b.top,bottom:b.bottom,left:b.left,right:b.right,ok:b.bottom<=innerHeight&&b.right<=innerWidth&&b.top>=0&&lines==1}})})()"""


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--split',choices=['dev','heldout','both'],default='both');args=ap.parse_args()
    for split in (['dev','heldout'] if args.split=='both' else [args.split]):
        out=ROOT/f'artifacts/ocr-screens/en-hard-{split}';out.mkdir(parents=True,exist_ok=True)
        manifest={'set':f'en-hard-{split}','purpose':'tuning' if split=='dev' else 'held-out evaluation only; never used for tuning',
                  'seed':SEEDS[split],'renderer':'Microsoft Edge headless (DevTools), greyscale anti-aliasing','edge_version':edge_version(),
                  'fonts':FONTS[split],'scenarios':[]}
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile,tempfile.TemporaryDirectory() as pages:
            edge=Edge(profile,800)
            for name,build,n,size,scale in scenarios(split):
                for attempt in range(12):
                    src=Path(pages)/f'{name}.html';src.write_text(build(n),encoding='utf-8')
                    png,rows=edge.screenshot(src.as_uri(),size=size,scale=scale,evaluate=GT_JS)
                    if all(r['ok'] for r in rows):break
                    n-=1
                else:raise SystemExit(f'{name}: rows do not fit')
                image=out/f'{name}.png';image.write_bytes(png)
                manifest['scenarios'].append({'name':name,'language':'en','condition':name.split('-')[0],'scale':scale,'css_size':size,
                    'image':image.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(png).hexdigest(),
                    'lines':[r['text'] for r in sorted(rows,key=lambda r:(round(r['top']),r['left'])) if r['text'].strip()]})
                print(split,name,len(manifest['scenarios'][-1]['lines']),'rows',flush=True)
            edge.close()
        (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=1),encoding='utf-8')
        print(split,len(manifest['scenarios']),'screens')


if __name__=='__main__':main()
