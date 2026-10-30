"""README charts (docs/images/*.svg, light and dark variants) drawn from the recorded reports — no number is typed in by
hand except where noted. Re-run after a new benchmark: .venv\\Scripts\\python.exe -B scripts/make_readme_charts.py
Sources:
  OCR   reports/ocr-screens/ocr-native-en-hard-heldout-*.json (25 English hard screens, held-out, run once per config)
  ASR   reports/voice/asr-english-engine-*.json (product path) and reports/asr-holdout-en-results.json (whisper base)
  RAM   reports/perf/sustained-*.json (30-minute whole-tree runs on H0, synthetic invisible windows)
"""
import glob
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/images'
THEMES={  # dataviz reference palette: slot-1 blue for Lens, neutral ink for comparisons
    'light':{'surface':'#fcfcfb','ink':'#0b0b0b','ink2':'#52514e','muted':'#b8b6ae','grid':'#e4e2dc','lens':'#2a78d6','line':'#52514e'},
    'dark':{'surface':'#1a1a19','ink':'#f0efec','ink2':'#c3c2b7','muted':'#5f5e58','grid':'#2e2d2a','lens':'#3987e5','line':'#c3c2b7'},
}


def latest(pattern):return json.loads(Path(sorted(glob.glob(str(ROOT/pattern)))[-1]).read_text(encoding='utf-8'))


def hbar(name,title,subtitle,rows,unit,theme,limit=None,limit_label=None,lower_is_better=True):
    """Horizontal bars. rows: (label, value, note, is_lens)."""
    t=THEMES[theme];W,left,right,top,bar,gap=760,250,250,74,26,14
    H=top+len(rows)*(bar+gap)+40;vmax=max([v for _,v,_,_ in rows]+([limit] if limit else []))*1.08
    x=lambda v:left+(W-left-right)*v/vmax
    s=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="system-ui,-apple-system,Segoe UI,Roboto,sans-serif">',
       f'<rect width="{W}" height="{H}" rx="10" fill="{t["surface"]}"/>',
       f'<text x="24" y="32" font-size="17" font-weight="600" fill="{t["ink"]}">{title}</text>',
       f'<text x="24" y="54" font-size="12.5" fill="{t["ink2"]}">{subtitle}</text>']
    if limit:  # drawn first, behind the bars and their labels
        lx=x(limit);s.append(f'<line x1="{lx}" y1="{top-8}" x2="{lx}" y2="{H-30}" stroke="{t["line"]}" stroke-width="2" stroke-dasharray="5 4"/>')
        s.append(f'<text x="{lx}" y="{H-12}" font-size="12" text-anchor="middle" fill="{t["ink2"]}">{limit_label}</text>')
    for i,(label,v,note,lens) in enumerate(rows):
        y=top+i*(bar+gap);w=max(4,x(v)-left)
        s.append(f'<text x="{left-12}" y="{y+bar/2+4.5}" font-size="13" text-anchor="end" fill="{t["ink"]}" font-weight="{600 if lens else 400}">{label}</text>')
        s.append(f'<path d="M{left},{y} h{w-4} a4,4 0 0 1 4,4 v{bar-8} a4,4 0 0 1 -4,4 h-{w-4} z" fill="{t["lens"] if lens else t["muted"]}"/>')
        s.append(f'<text x="{left+w+8}" y="{y+bar/2+4.5}" font-size="13" fill="{t["ink"]}" font-weight="600" paint-order="stroke" stroke="{t["surface"]}" stroke-width="5">{v:g}{unit}</text>')
        if note:s.append(f'<text x="{W-24}" y="{y+bar/2+4.5}" font-size="12" text-anchor="end" fill="{t["ink2"]}">{note}</text>')  # fixed column
    s.append(f'<text x="{W-24}" y="{H-12}" font-size="11.5" text-anchor="end" fill="{t["ink2"]}">{"lower is better" if lower_is_better else "higher is better"}</text>')
    s.append('</svg>')
    (OUT/f'{name}-{theme}.svg').write_text('\n'.join(s),encoding='utf-8')


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    ocr={}
    for tag in ('lens-shipped-small','lens-shipped','baidu-server-medium','baidu-server-medium-raw'):
        r=latest(f'reports/ocr-screens/ocr-native-en-hard-heldout-*-oracle-{tag}-2*.json')
        ocr[tag]=(round(100*r['summary']['en']['page_cer'],2),r['summary']['latency_ms']['full_compute_p50']/1000,r['summary']['peak_working_set_mb_max'])
    note=lambda k:f'{ocr[k][1]:.1f} s · {ocr[k][2]:.0f} MB'
    ocr_rows=[('Lens (shipped)',ocr['lens-shipped-small'][0],note('lens-shipped-small'),True),
              ('Baidu largest + Lens rows',ocr['baidu-server-medium'][0],note('baidu-server-medium'),False),
              ('Lens, previous recogniser',ocr['lens-shipped'][0],note('lens-shipped'),False),
              ('Baidu largest, raw output',ocr['baidu-server-medium-raw'][0],note('baidu-server-medium-raw'),False)]
    eng=latest('reports/voice/asr-english-engine-*.json')['sets'];whisper=json.loads((ROOT/'reports/asr-holdout-en-results.json').read_text())['summary'][0]['wer']
    asr_rows=[('Lens — FLEURS English',round(100*eng['fleurs']['wer'],2),'100 held-out clips',True),
              ('whisper base — FLEURS English',round(100*whisper,2),'same clips',False),
              ('Lens — LibriSpeech clean',round(100*eng['librispeech']['wer'],2),f'{eng["librispeech"]["utterances"]} utterances',True)]
    ram=[]
    for f,label in (('sustained-20261027T215134Z','27 Oct, before governor'),('sustained-20261028T061621Z','28 Oct, before governor'),
                    ('sustained-20261030T043959Z','30 Oct, governor v2')):
        r=json.loads((ROOT/'reports/perf'/f'{f}.json').read_text());ram.append((label,round(r['peak_working_set_bytes']/1e6),'peak working set',f.endswith('043959Z')))
    idle=json.loads((ROOT/'reports/perf/sustained-20261030T043959Z.json').read_text())['idle_after_load']['ws']
    ram.append(('30 Oct, idle after load',round(idle/1e6),'idle target 50–100 MB',True))
    for theme in THEMES:
        hbar('ocr-heldout','Screen OCR — English hard screens (held-out)','Page character error rate, 25 unseen screens: code, terminals, settings, tables, mail; CPU only',
             ocr_rows,'%',theme)
        hbar('asr-english','Speech input — English word error rate','Product path: Canary-180M-flash INT8 in ≤ 8 s pieces, whisper fallback; CPU only',asr_rows,'%',theme)
        hbar('ram-whole-system','Whole system RAM — 30-minute runs','Agent + engine + observer + OCR worker, synthetic load, one laptop (H0)',ram,' MB',theme,
             limit=500,limit_label='500 MB ceiling')
    print('wrote',sorted(p.name for p in OUT.glob('*.svg')))


if __name__=='__main__':main()
