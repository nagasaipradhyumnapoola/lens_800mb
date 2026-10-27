"""Generate the HELD-OUT OCR screen set: never used for tuning, training or rule design; evaluate only.

Differs from the dev set (scripts/make_ocr_screens.py) in every axis it can: newly authored text (other topics, no
sentence shared with the dev set or with any training generator), other fonts (Georgia, Verdana, Calibri, Tahoma,
Trebuchet MS for Latin; SimSun and Microsoft YaHei Light for Chinese; Nirmala Text — not Nirmala UI — for
Devanagari, Tamil and Telugu), other layouts (mail list, dark notes, cards, heading + body, compact 13 px) and a new
seed for line order. Global languages (2026-10-27, docs/LENS_V1_SPEC.md §1a): fr, pt, de, id, ru in the same Latin
fonts; ja in MS PGothic / Yu Gothic (dev: Yu Gothic UI); ar, ur in Tahoma / Times New Roman / Arial, right-to-left
(dev: Segoe UI); bn, mr, gu in Nirmala Text; their line order uses seed+1 so the original 32 screens are unchanged.
Rendering is the same headless Microsoft Edge path (no window, isolated temporary profile,
1280x800, device scale 1). Content is authored synthetic text, no personal data.
Output: artifacts/ocr-screens/heldout-v1/<scenario>.png and manifest.json (Edge version, sha256 per image, lines).
Usage: .venv\\Scripts\\python.exe scripts/make_ocr_screens_heldout.py
"""
import hashlib
import html
import json
from pathlib import Path
import random
import subprocess
import tempfile
from make_ocr_screens import EDGE,edge_version
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/ocr-screens/heldout-v1'
SEED=20261027

TEXT={
 'en':['The school annual day is on 5 December.','Train ticket fare was fixed at 1,240 rupees.',
       'Doctor appointment: Wednesday 10:15 am, clinic 3.','Srinivas must submit the project report.',
       'The cricket match was cancelled due to rain.','The library stays closed on Sundays.',
       'Students can check exam results online.','Total bill: 3,675 rupees, payment complete.'],
 'zh':['学校年度庆典将于12月5日举行。','火车票价格定为1240元。','医生预约在周三上午10:15。','项目报告需要由李明提交。',
       '由于下雨，板球比赛被取消了。','图书馆周日不开放。','学生可以在网上查看考试成绩。','总账单：3675元，已完成付款。'],
 'es':['La fiesta anual del colegio es el 5 de diciembre.','El billete de tren cuesta 1.240 pesos.',
       'Cita médica: miércoles a las 10:15, consultorio 3.','Lucía debe entregar el informe del proyecto.',
       'El partido se canceló por la lluvia.','La biblioteca cierra los domingos.',
       'Los estudiantes pueden ver sus notas en línea.','Factura total: 3.675 pesos, pago completado.'],
 'hi':['विद्यालय का वार्षिक उत्सव 5 दिसंबर को होगा।','रेल टिकट का किराया 1,240 रुपये तय हुआ।',
       'डॉक्टर से मुलाकात बुधवार सुबह 10:15 बजे है।','परियोजना रिपोर्ट श्रीनिवास को जमा करनी है।',
       'बारिश के कारण क्रिकेट मैच रद्द हो गया।','पुस्तकालय रविवार को बंद रहता है।',
       'छात्र परीक्षा परिणाम ऑनलाइन देख सकते हैं।','कुल बिल: 3,675 रुपये, भुगतान पूरा हुआ।'],
 'ta':['பள்ளி ஆண்டு விழா டிசம்பர் 5 அன்று நடைபெறும்.','ரயில் டிக்கெட் கட்டணம் 1,240 ரூபாய் என நிர்ணயிக்கப்பட்டது.',
       'மருத்துவர் சந்திப்பு புதன்கிழமை காலை 10:15 மணிக்கு.','திட்ட அறிக்கையை சீனிவாசன் சமர்ப்பிக்க வேண்டும்.',
       'மழை காரணமாக கிரிக்கெட் போட்டி ரத்து செய்யப்பட்டது.','நூலகம் ஞாயிற்றுக்கிழமை மூடப்பட்டிருக்கும்.',
       'மாணவர்கள் தேர்வு முடிவுகளை இணையத்தில் பார்க்கலாம்.','மொத்த கட்டணம்: 3,675 ரூபாய், செலுத்தப்பட்டது.'],
 'te':['పాఠశాల వార్షికోత్సవం డిసెంబర్ 5న జరుగుతుంది.','రైలు టికెట్ ధర 1,240 రూపాయలుగా నిర్ణయించారు.',
       'డాక్టర్ అపాయింట్‌మెంట్ బుధవారం ఉదయం 10:15 కి.','ప్రాజెక్ట్ నివేదిక శ్రీనివాస్ సమర్పించాలి.',
       'క్రికెట్ మ్యాచ్ వర్షం కారణంగా రద్దయింది.','గ్రంథాలయం ఆదివారం మూసి ఉంటుంది.',
       'విద్యార్థులు పరీక్ష ఫలితాలు ఆన్‌లైన్‌లో చూడవచ్చు.','మొత్తం బిల్లు: 3,675 రూపాయలు, చెల్లింపు పూర్తయింది.'],
 'fr':["La fête annuelle de l'école aura lieu le 5 décembre.",'Le prix du billet de train est fixé à 1 240 euros.',
       'Rendez-vous chez le médecin : mercredi à 10 h 15, cabinet 3.','Srinivas doit remettre le rapport du projet.',
       'Le match de cricket a été annulé à cause de la pluie.','La bibliothèque est fermée le dimanche.',
       'Les élèves peuvent consulter leurs résultats en ligne.','Facture totale : 3 675 euros, paiement effectué.'],
 'pt':['A festa anual da escola será no dia 5 de dezembro.','O preço da passagem de trem foi fixado em R$ 1.240.',
       'Consulta médica: quarta-feira às 10h15, consultório 3.','Srinivas precisa entregar o relatório do projeto.',
       'A partida de críquete foi cancelada por causa da chuva.','A biblioteca fica fechada aos domingos.',
       'Os alunos podem ver os resultados das provas on-line.','Conta total: R$ 3.675, pagamento concluído.'],
 'de':['Das Schulfest findet am 5. Dezember statt.','Der Fahrpreis für das Zugticket beträgt 1.240 Euro.',
       'Arzttermin: Mittwoch, 10:15 Uhr, Praxis 3.','Srinivas muss den Projektbericht einreichen.',
       'Das Cricketspiel wurde wegen Regen abgesagt.','Die Bibliothek ist sonntags geschlossen.',
       'Schüler können ihre Prüfungsergebnisse online ansehen.','Gesamtrechnung: 3.675 Euro, Zahlung abgeschlossen.'],
 'id':['Perayaan tahunan sekolah diadakan pada 5 Desember.','Harga tiket kereta ditetapkan Rp1.240.000.',
       'Janji dokter: Rabu pukul 10.15, ruang praktik 3.','Srinivas harus menyerahkan laporan proyek.',
       'Pertandingan kriket dibatalkan karena hujan.','Perpustakaan tutup setiap hari Minggu.',
       'Siswa dapat melihat hasil ujian secara daring.','Total tagihan: Rp3.675.000, pembayaran selesai.'],
 'ru':['Школьный праздник пройдёт 5 декабря.','Стоимость билета на поезд: 1 240 рублей.','Приём у врача: среда, 10:15, кабинет 3.',
       'Шринивас должен сдать отчёт по проекту.','Матч по крикету отменили из-за дождя.','Библиотека закрыта по воскресеньям.',
       'Студенты могут посмотреть результаты экзаменов онлайн.','Итого к оплате: 3 675 рублей, оплата завершена.'],
 'ja':['学校の年次行事は12月5日に行われます。','電車の切符の料金は1,240円に決まりました。','病院の予約：水曜日の午前10時15分、診察室3。',
       'スリニヴァスさんはプロジェクト報告書を提出する必要があります。','雨のため、クリケットの試合は中止になりました。','図書館は日曜日休館です。',
       '学生はオンラインで試験結果を確認できます。','合計金額：3,675円、支払いが完了しました。'],
 'ar':['يقام الحفل السنوي للمدرسة في 5 ديسمبر.','تم تحديد سعر تذكرة القطار بمبلغ 1,240 ريالا.','موعد الطبيب: الأربعاء الساعة 10:15، العيادة 3.',
       'يجب على سرينيفاس تسليم تقرير المشروع.','ألغيت مباراة الكريكيت بسبب المطر.','تغلق المكتبة أيام الأحد.',
       'يمكن للطلاب الاطلاع على نتائج الامتحانات عبر الإنترنت.','إجمالي الفاتورة: 3,675 ريالا، تم الدفع.'],
 'ur':['اسکول کا سالانہ جشن 5 دسمبر کو ہوگا۔','ٹرین ٹکٹ کا کرایہ 1,240 روپے مقرر کیا گیا۔','ڈاکٹر سے ملاقات: بدھ صبح 10:15 بجے، کلینک 3۔',
       'سری نواس کو منصوبے کی رپورٹ جمع کرانی ہے۔','بارش کی وجہ سے کرکٹ میچ منسوخ ہو گیا۔','لائبریری اتوار کو بند رہتی ہے۔',
       'طلبہ امتحان کے نتائج آن لائن دیکھ سکتے ہیں۔','کل بل: 3,675 روپے، ادائیگی مکمل ہو گئی۔'],
 'bn':['স্কুলের বার্ষিক অনুষ্ঠান 5 ডিসেম্বর অনুষ্ঠিত হবে।','ট্রেনের টিকিটের ভাড়া 1,240 টাকা ঠিক করা হয়েছে।',
       'ডাক্তারের অ্যাপয়েন্টমেন্ট: বুধবার সকাল 10:15, ক্লিনিক 3।','শ্রীনিবাসকে প্রকল্পের প্রতিবেদন জমা দিতে হবে।',
       'বৃষ্টির কারণে ক্রিকেট ম্যাচ বাতিল হয়েছে।','গ্রন্থাগার রবিবার বন্ধ থাকে।','ছাত্রছাত্রীরা অনলাইনে পরীক্ষার ফলাফল দেখতে পারবে।',
       'মোট বিল: 3,675 টাকা, পেমেন্ট সম্পূর্ণ হয়েছে।'],
 'mr':['शाळेचा वार्षिक समारंभ 5 डिसेंबर रोजी होईल.','रेल्वे तिकिटाचे भाडे 1,240 रुपये ठरले आहे.','डॉक्टरांची भेट: बुधवार सकाळी 10:15, दवाखाना 3.',
       'श्रीनिवासला प्रकल्पाचा अहवाल सादर करायचा आहे.','पावसामुळे क्रिकेट सामना रद्द झाला.','ग्रंथालय रविवारी बंद असते.',
       'विद्यार्थी परीक्षेचे निकाल ऑनलाइन पाहू शकतात.','एकूण बिल: 3,675 रुपये, पेमेंट पूर्ण झाले.'],
 'gu':['શાળાનો વાર્ષિક ઉત્સવ 5 ડિસેમ્બરે યોજાશે.','ટ્રેન ટિકિટનું ભાડું 1,240 રૂપિયા નક્કી કરવામાં આવ્યું છે.',
       'ડૉક્ટરની મુલાકાત: બુધવાર સવારે 10:15, ક્લિનિક 3.','શ્રીનિવાસે પ્રોજેક્ટનો અહેવાલ જમા કરાવવાનો છે.',
       'વરસાદને કારણે ક્રિકેટ મેચ રદ થઈ.','પુસ્તકાલય રવિવારે બંધ રહે છે.','વિદ્યાર્થીઓ પરીક્ષાનાં પરિણામો ઓનલાઇન જોઈ શકે છે.',
       'કુલ બિલ: 3,675 રૂપિયા, ચુકવણી પૂર્ણ થઈ.'],
}
ORIGINAL=('en','zh','es','hi','ta','te')
RTL=('ar','ur')
JAPANESE={'mail':'"MS PGothic"','notes':'"Yu Gothic Light"','cards':'"Yu Gothic Medium"','heading':'"MS Gothic"','compact':'"Yu Gothic"'}
ARABIC={'mail':'Tahoma','notes':'"Times New Roman"','cards':'Arial','heading':'Tahoma','compact':'Arial'}
# Latin/Chinese font per layout; Indic lines always fall back to Nirmala Text (weights vary by layout).
LATIN={'mail':'Georgia','notes':'Verdana','cards':'Calibri','heading':'Tahoma','compact':'"Trebuchet MS"'}
CHINESE={'mail':'SimSun','notes':'"Microsoft YaHei Light"','cards':'SimSun','heading':'"Microsoft YaHei Light"','compact':'SimSun'}


def css(layout,lang):
    face={'zh':CHINESE,'ja':JAPANESE,'ar':ARABIC,'ur':ARABIC}.get(lang,LATIN)[layout]+',"Nirmala Text"'
    return {
     'mail':f'body{{margin:0;background:#fff;color:#202124;font-family:{face};font-size:15px}}'
            'header{background:#f1f3f4;padding:14px 24px;font-size:13px;color:#5f6368}div{padding:11px 24px;border-bottom:1px solid #e0e0e0}'
            'div:nth-of-type(odd){background:#f8fbff}',
     'notes':f'body{{margin:36px;background:#0d1117;color:#c9d1d9;font-family:{face};font-size:16px;line-height:2.1;font-weight:300}}',
     'cards':f'body{{margin:28px;background:#eef2f7;color:#1b2733;font-family:{face};font-size:17px}}'
             'div{background:#fff;border-left:4px solid #3b82f6;border-radius:6px;padding:9px 16px;margin:9px 0;width:fit-content;max-width:1100px}'
             'div:nth-of-type(3n){background:#fff7e6;border-color:#f59e0b}',
     'heading':f'body{{margin:34px 48px;background:#fdfdfb;color:#222;font-family:{face};font-size:17px;line-height:1.95}}'
               'div:first-of-type{font-size:26px;font-weight:700;margin-bottom:10px}',
     'compact':f'body{{margin:22px;background:#ffffff;color:#3c4043;font-family:{face};font-size:13px;line-height:1.6}}',
    }[layout]


def page(lines,layout,lang):
    head='<header>Inbox</header>' if layout=='mail' else ''
    body=head+''.join(f'<div>{html.escape(l)}</div>' for l in lines)
    if lang in ORIGINAL or lang=='mixed':
        return f'<!doctype html><html><head><meta charset="utf-8"><style>{css(layout,lang)}</style></head><body>{body}</body></html>'
    rtl=' dir="rtl"' if lang in RTL else ''
    return f'<!doctype html><html lang="{lang}"{rtl}><head><meta charset="utf-8"><style>{css(layout,lang)}</style></head><body>{body}</body></html>'


def scenarios():
    rng=random.Random(SEED);out=[]
    for lang in ORIGINAL:
        lines=TEXT[lang]
        for layout in LATIN:
            order=lines[:];rng.shuffle(order)
            gt=(['Inbox'] if layout=='mail' else [])+order
            out.append((f'{lang}-{layout}',lang,gt,page(order,layout,lang)))
    for layout in ('notes','cards'):
        mixed=[TEXT[l][rng.randrange(8)] for l in ('te','en','hi','zh','ta','es','te')]
        out.append((f'mixed-{layout}','mixed',mixed,page(mixed,layout,'mixed')))
    rng=random.Random(SEED+1)
    for lang in [l for l in TEXT if l not in ORIGINAL]:
        for layout in LATIN:
            order=TEXT[lang][:];rng.shuffle(order)
            out.append((f'{lang}-{layout}',lang,(['Inbox'] if layout=='mail' else [])+order,page(order,layout,lang)))
    for layout in ('mail','compact'):
        mixed=[TEXT[l][rng.randrange(8)] for l in ('ru','ja','fr','bn','de','gu','pt','mr','id')]
        out.append((f'mixed-global-{layout}','mixed',(['Inbox'] if layout=='mail' else [])+mixed,page(mixed,layout,'mixed')))
    return out


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    manifest={'set':'heldout-v1','purpose':'held-out evaluation only; never used for tuning','seed':SEED,'renderer':'Microsoft Edge headless',
              'edge_version':edge_version(),'viewport':[1280,800],'scale':1,'scenarios':[]}
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
