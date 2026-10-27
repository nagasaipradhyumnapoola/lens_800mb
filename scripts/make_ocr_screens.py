"""Generate the OCR screen benchmark (docs/LENS_V1_SPEC.md §5): real browser-rendered screens with exact ground truth.

Each scenario is an HTML page rendered by headless Microsoft Edge (no window is shown; isolated temporary profile) at
1280x800, device scale 1, into a PNG. Ground truth is the list of text lines in reading order. Content is authored
synthetic text (no personal data) in en, zh, es, hi, ta, te and mixed scripts; styles cover light, dark, code editor,
small fonts, chat bubbles and tables. Fonts are the Windows defaults (Segoe UI, Microsoft YaHei, Nirmala UI, Consolas).
Output: artifacts/ocr-screens/v1/<scenario>.png and manifest.json (Edge version, sha256 per image, lines).
Usage: .venv\\Scripts\\python.exe scripts/make_ocr_screens.py
"""
import hashlib
import html
import json
from pathlib import Path
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/ocr-screens/v1'
EDGE=Path(r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')

TEXT={
 'en':['Quarterly planning notes','The vendor contract renewal is due on 14 November.','Priya will share the revised budget by Friday.',
       'Meeting moved to Thursday at 4:30 pm in room B12.','Action items: update the roadmap, review hiring plan.','Total spend so far: $48,250'],
 'zh':['季度计划笔记','供应商合同续签截止日期是十一月十四日。','王芳会在周五前分享修订后的预算。','会议改到周四下午四点半，在B12会议室。',
       '待办事项：更新路线图，审核招聘计划。','目前总支出：48250元'],
 'es':['Notas de planificación trimestral','La renovación del contrato vence el 14 de noviembre.','Ana compartirá el presupuesto revisado el viernes.',
       'La reunión se movió al jueves a las 16:30 en la sala B12.','Tareas: actualizar la hoja de ruta y revisar contrataciones.','Gasto total hasta ahora: 48.250 €'],
 'hi':['तिमाही योजना नोट्स','विक्रेता अनुबंध का नवीनीकरण 14 नवंबर तक करना है।','प्रिया शुक्रवार तक संशोधित बजट साझा करेगी।',
       'बैठक गुरुवार शाम 4:30 बजे कमरा B12 में होगी।','कार्य सूची: रोडमैप अपडेट करें, भर्ती योजना देखें।','अब तक कुल खर्च: 48,250 रुपये'],
 'ta':['காலாண்டு திட்டக் குறிப்புகள்','விற்பனையாளர் ஒப்பந்த புதுப்பித்தல் நவம்பர் 14 அன்று.','பிரியா வெள்ளிக்கிழமைக்குள் திருத்திய பட்ஜெட்டை பகிர்வார்.',
       'கூட்டம் வியாழன் மாலை 4:30 மணிக்கு அறை B12 இல்.','செயல்கள்: வழிகாட்டியைப் புதுப்பி, பணியமர்த்தல் திட்டத்தை பார்.','இதுவரை மொத்த செலவு: 48,250 ரூபாய்'],
 'te':['త్రైమాసిక ప్రణాళిక గమనికలు','విక్రేత ఒప్పందం పునరుద్ధరణ నవంబర్ 14 లోపు.','ప్రియ శుక్రవారం లోపు సవరించిన బడ్జెట్ పంచుకుంటుంది.',
       'సమావేశం గురువారం సాయంత్రం 4:30 కి గది B12 లో.','చర్యలు: రోడ్‌మ్యాప్ నవీకరించండి, నియామక ప్రణాళిక చూడండి.','ఇప్పటివరకు మొత్తం ఖర్చు: 48,250 రూపాయలు'],
}
CODE=['def renew_contract(vendor_id: int) -> bool:','    deadline = date(2026, 11, 14)','    if today() > deadline:',
      '        raise ContractExpired(vendor_id)','    return notify("finance@example.com")']
FONT='font-family:"Segoe UI","Microsoft YaHei","Nirmala UI",sans-serif;'
STYLES={
 'light':'body{margin:40px;background:#ffffff;color:#1f2328;'+FONT+'font-size:18px;line-height:1.9}',
 'dark':'body{margin:40px;background:#1e1f22;color:#e6e6e6;'+FONT+'font-size:18px;line-height:1.9}',
 'small':'body{margin:30px;background:#fafafa;color:#333;'+FONT+'font-size:12px;line-height:1.8}',
 'chat':'body{margin:30px;background:#efeae2;'+FONT+'font-size:16px}div{background:#fff;border-radius:10px;padding:8px 14px;margin:10px 0;width:fit-content;max-width:900px}div:nth-child(even){background:#d9fdd3;margin-left:200px}',
 'table':'body{margin:30px;background:#fff;'+FONT+'font-size:16px}table{border-collapse:collapse}td{border:1px solid #bbb;padding:8px 14px}',
}


def page(lines,style):
    if style=='table':
        rows=''.join(f'<tr><td>{html.escape(l)}</td></tr>' for l in lines)
        body=f'<table>{rows}</table>'
    else:body=''.join(f'<div>{html.escape(l)}</div>' for l in lines)
    return f'<!doctype html><html><head><meta charset="utf-8"><style>{STYLES[style]}</style></head><body>{body}</body></html>'


def code_page():
    css='body{margin:30px;background:#1e1e1e;color:#d4d4d4;font-family:Consolas,monospace;font-size:15px;line-height:1.7;white-space:pre}'
    return '<!doctype html><html><head><meta charset="utf-8"><style>'+css+'</style></head><body>'+''.join(f'<div>{html.escape(l)}</div>' for l in CODE)+'</body></html>'


def scenarios():
    out=[]
    for lang,lines in TEXT.items():
        for style in ('light','dark','small','chat','table'):out.append((f'{lang}-{style}',lang,lines,page(lines,style)))
    mixed=[TEXT['en'][1],TEXT['hi'][2],TEXT['ta'][3],TEXT['zh'][1],TEXT['te'][2],TEXT['es'][3]]
    out.append(('mixed-light','mixed',mixed,page(mixed,'light')));out.append(('code-dark','en',CODE,code_page()))
    return out


def edge_version():
    try:return subprocess.run(['powershell','-NoProfile','-Command',f"(Get-Item '{EDGE}').VersionInfo.ProductVersion"],capture_output=True,text=True,timeout=30).stdout.strip()
    except OSError:return None


def main():
    OUT.mkdir(parents=True,exist_ok=True);manifest={'renderer':'Microsoft Edge headless','edge_version':edge_version(),'viewport':[1280,800],'scale':1,'scenarios':[]}
    with tempfile.TemporaryDirectory() as profile:
        for name,lang,lines,doc in scenarios():
            src=Path(profile)/f'{name}.html';src.write_text(doc,encoding='utf-8');png=OUT/f'{name}.png'
            subprocess.run([str(EDGE),'--headless=new','--disable-gpu','--hide-scrollbars','--no-first-run','--disable-extensions',
                            f'--user-data-dir={profile}','--force-device-scale-factor=1','--window-size=1280,800',f'--screenshot={png}',src.as_uri()],
                           capture_output=True,timeout=120,check=True)
            manifest['scenarios'].append({'name':name,'language':lang,'image':png.relative_to(ROOT).as_posix(),
                                          'sha256':hashlib.sha256(png.read_bytes()).hexdigest(),'lines':lines})
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=1),encoding='utf-8')
    print(len(manifest['scenarios']),'scenarios, Edge',manifest['edge_version'])


if __name__=='__main__':main()
