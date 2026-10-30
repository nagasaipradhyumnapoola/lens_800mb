"""Lens-style answerability data (docs/LENS_MODEL.md, stage T2): short personal memories like the ones Lens stores
(calendar entries, order confirmations, reminders, chat lines, notes) with questions whose answer the memory does or
does not contain. Programmatic, no model writes text: structured events with slots are rendered from templates in
English (~60%), Hindi, Chinese and Spanish, plus cross-lingual questions (an English memory asked about in hi/zh/es).

Per item (one memory):
- lens_answerable: wh-questions about a stated slot, worded differently from the memory (y = 1);
- lens_near_miss_<subtype> (y = 0), the subtypes of data/fixtures/retrieval-nl/nearmiss-v1.json:
  entity (another object or attribute of the same kind), action (another verb on the same object, e.g. return vs order),
  specific (a detail the memory does not state), attribution (the same question about another person);
- lens_unrelated: an answerable question of another item (y = 0).
Leakage guard: an item is dropped when any of its texts shares a 5-word sequence or a capitalised name (4+ letters,
weekdays and months excepted) with any Lens retrieval fixture (v1, expansion, near-miss, acceptance, the sealed holdout);
names, places and products are chosen unlike the fixtures. Synthetic names only — never personal data.
Teacher: the Qwen3-1.7B zero-shot judge (lens_model/eval/compare_answerability.py, LENS_JUDGE_DEVICE=cuda) scores every
pair; its scores are Platt-calibrated against the gold labels and blended: y = 0.5 * y_gold + 0.5 * p_teacher.
Output: artifacts/lens-model/lens-style/{items.jsonl,train.jsonl,build-report.json} (train.jsonl in the format of
lens_model/train/train_answerability.py: q, e, y, y_gold, s_teacher, p_teacher, lang, kind, src="lens_style", group).
Usage: .tools\\venv-train-cuda\\Scripts\\python.exe lens_model/data/build_lens_style.py [--items 4000] [--no-teacher]
"""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import random
import re
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'artifacts/lens-model/lens-style'
FIXTURES=sorted((ROOT/'data/fixtures/retrieval-nl').glob('*.json'))
LANGS=['en','hi','zh','es']

DAYS={'en':['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'],
      'hi':['सोमवार','मंगलवार','बुधवार','गुरुवार','शुक्रवार','शनिवार','रविवार'],
      'zh':['周一','周二','周三','周四','周五','周六','周日'],
      'es':['lunes','martes','miércoles','jueves','viernes','sábado','domingo']}
TIMES={'en':['9:30 am','11 am','2:15 pm','4 pm','6:45 pm'],'hi':['सुबह 9:30 बजे','सुबह 11 बजे','दोपहर 2:15 बजे','शाम 4 बजे','शाम 6:45 बजे'],
       'zh':['上午9点半','上午11点','下午2点15分','下午4点','晚上6点45分'],'es':['a las 9:30','a las 11','a las 14:15','a las 16:00','a las 18:45']}
PEOPLE={'en':['Tobiah','Wren','Calla','Idris','Marisol','Teodor','Ottilie','Ansel','Zuri','Leif','Ondine','Casimir','Briar','Soren','Elodie','Hollis'],
        'hi':['अर्जुन','मीरा','रोहन','सुनीता','कबीर','नेहा','विक्रम','आयशा'],
        'zh':['王磊','李娜','张伟','陈静','刘洋','赵敏','孙浩','周婷'],
        'es':['Ximena','Leandro','Itziar','Fermín','Araceli','Ulises','Begoña','Rigoberto']}


def pick(rng,xs,n):return rng.sample(xs,n)


# Each schema returns (memory, answerable [..], near-misses {subtype: [..]}) for one language and one set of slots.
def meeting(L,rng):
    p,o=pick(rng,PEOPLE[L],2);d=rng.choice(DAYS[L]);t=rng.choice(TIMES[L])
    T={'en':['cost review','design sync','vendor call','quarterly planning','onboarding session'],'hi':['बजट समीक्षा','डिज़ाइन बैठक','विक्रेता कॉल','तिमाही योजना'],
       'zh':['预算评审会','设计同步会','供应商电话会','季度规划会'],'es':['revisión de presupuesto','reunión de diseño','llamada con el proveedor','planificación trimestral']}
    k,k2=pick(rng,T[L],2);room=rng.choice(['C4','D7','5F','A12','E3'])
    return {'en':(f"{p} moved the {k} to {d} at {t} in room {room}.",[f"What's the new slot for the {k}?",f"Which room will the {k} be in?",f"What time did {p} set for the {k}?"],
                  {'specific':[f"What is on the agenda for the {k}?",f"Who else was invited to the {k}?"],'attribution':[f"When did {o} schedule the {k}?"],
                   'entity':[f"When is the {k2} now?"],'action':[f"Why did {p} cancel the {k}?"]}),
            'hi':(f"{p} ने {k} को {d} {t} कमरा {room} में कर दिया।",[f"{k} अब कब है?",f"{k} किस कमरे में होगी?"],
                  {'specific':[f"{k} का एजेंडा क्या है?"],'attribution':[f"{o} ने {k} कब रखी?"],'entity':[f"{k2} कब है?"],'action':[f"{p} ने {k} रद्द क्यों की?"]}),
            'zh':(f"{p}把{k}改到了{d}{t}，在{room}会议室。",[f"{k}现在是什么时候？",f"{k}在哪个会议室开？"],
                  {'specific':[f"{k}的议程是什么？"],'attribution':[f"{o}把{k}安排在什么时候？"],'entity':[f"{k2}是什么时候？"],'action':[f"{p}为什么取消了{k}？"]}),
            'es':(f"{p} movió la {k} al {d} {t} en la sala {room}.",[f"¿Cuándo es ahora la {k}?",f"¿En qué sala será la {k}?"],
                  {'specific':[f"¿Qué temas hay en la agenda de la {k}?"],'attribution':[f"¿Cuándo programó {o} la {k}?"],'entity':[f"¿Cuándo es la {k2}?"],
                   'action':[f"¿Por qué canceló {p} la {k}?"]})}[L]


def order(L,rng):
    I={'en':['desk lamp','noise-cancelling headphones','water filter','bike helmet','air fryer','laptop sleeve'],'hi':['स्टैंडिंग डेस्क','हेडफ़ोन','वॉटर फ़िल्टर','साइकिल हेलमेट'],
       'zh':['升降桌','降噪耳机','净水器','自行车头盔'],'es':['escritorio elevable','auriculares','filtro de agua','casco de bicicleta']}
    S=['Quillfield Supply','Bluebell Mart','Harbor Electronics','Pinecrest Goods'];P=['₹2,499','₹12,800','$89','€45','₹6,300']
    i,i2=pick(rng,I[L],2);s=rng.choice(S);pr=rng.choice(P);d=rng.choice(DAYS[L])
    return {'en':(f"Order confirmed: {i} from {s} for {pr}, arriving {d}.",[f"How much did the {i} cost?",f"When will the {i} be delivered?",f"Which shop is the {i} from?"],
                  {'action':[f"When did I return the {i} to {s}?"],'specific':[f"What colour is the {i}?",f"Who is delivering the {i}?"],'entity':[f"How much did the {i2} cost?"]}),
            'hi':(f"ऑर्डर पक्का: {s} से {i}, {pr} में, {d} को पहुँचेगा।",[f"{i} कितने का था?",f"{i} कब पहुँचेगा?"],
                  {'action':[f"मैंने {i} कब लौटाया?"],'specific':[f"{i} किस रंग का है?"],'entity':[f"{i2} कितने का था?"]}),
            'zh':(f"订单已确认：在{s}买的{i}，{pr}，{d}送达。",[f"{i}花了多少钱？",f"{i}什么时候送到？"],
                  {'action':[f"我什么时候把{i}退回去的？"],'specific':[f"{i}是什么颜色的？"],'entity':[f"{i2}花了多少钱？"]}),
            'es':(f"Pedido confirmado: {i} de {s} por {pr}, llega el {d}.",[f"¿Cuánto costó el {i}?",f"¿Cuándo llega el {i}?"],
                  {'action':[f"¿Cuándo devolví el {i}?"],'specific':[f"¿De qué color es el {i}?"],'entity':[f"¿Cuánto costó el {i2}?"]})}[L]


def doctor(L,rng):
    D=['Dr. Kapoor','Dr. Alvarez','Dr. Okafor','Dr. Novak','Dr. Lindqvist'];C=['Lakeside Health','Green Park Dental','Riverbend Wellness']
    dr,dr2=pick(rng,D,2);c=rng.choice(C);d=rng.choice(DAYS[L]);t=rng.choice(TIMES[L])
    return {'en':(f"Reminder: follow-up with {dr} at {c} on {d} at {t}.",[f"When is my appointment with {dr}?",f"Where is the follow-up with {dr}?"],
                  {'specific':[f"Which medicine did {dr} prescribe?",f"What were my test results from {dr}?"],'attribution':[f"When is my appointment with {dr2}?"],
                   'action':[f"Why did {dr} cancel the follow-up?"]}),
            'hi':(f"याद दिलाना: {c} में {dr} के साथ {d} {t} फ़ॉलो-अप।",[f"{dr} के साथ अपॉइंटमेंट कब है?",f"{dr} का फ़ॉलो-अप कहाँ है?"],
                  {'specific':[f"{dr} ने कौन सी दवा लिखी?"],'attribution':[f"{dr2} के साथ अपॉइंटमेंट कब है?"]}),
            'zh':(f"提醒：{d}{t}在{c}找{dr}复诊。",[f"我和{dr}的预约是什么时候？",f"找{dr}复诊在哪里？"],
                  {'specific':[f"{dr}开了什么药？"],'attribution':[f"我和{dr2}的预约是什么时候？"]}),
            'es':(f"Recordatorio: revisión con {dr} en {c} el {d} {t}.",[f"¿Cuándo es mi cita con {dr}?",f"¿Dónde es la revisión con {dr}?"],
                  {'specific':[f"¿Qué medicamento me recetó {dr}?"],'attribution':[f"¿Cuándo es mi cita con {dr2}?"]})}[L]


def flight(L,rng):
    C={'en':['Tbilisi','Krakow','Hobart','Ljubljana','Asmara','Nairobi'],'hi':['त्बिलिसी','क्राकोव','होबार्ट','ल्युब्लियाना','नैरोबी'],'zh':['第比利斯','克拉科夫','霍巴特','卢布尔雅那','内罗毕'],
       'es':['Tiflis','Cracovia','Hobart','Liubliana','Nairobi']}
    c,c2=pick(rng,C[L],2);code=f"{rng.choice(['LX','AI','QR','TP','KQ'])} {rng.randint(100,989)}";d=rng.choice(DAYS[L]);t=rng.choice(TIMES[L]);g=rng.choice(['B14','C3','D22','A7'])
    return {'en':(f"Your flight {code} to {c} departs {d} at {t} from gate {g}.",[f"What time is my {c} flight?",f"Which gate is the {c} flight at?"],
                  {'entity':[f"What time is my {c2} flight?"],'specific':[f"Which seat do I have on the {c} flight?",f"When does the {c} flight land?"],
                   'action':[f"Why was my flight to {c} cancelled?"]}),
            'hi':(f"आपकी फ़्लाइट {code} {c} के लिए {d} {t} गेट {g} से जाएगी।",[f"{c} की फ़्लाइट कब है?",f"{c} की फ़्लाइट किस गेट से है?"],
                  {'entity':[f"{c2} की फ़्लाइट कब है?"],'specific':[f"{c} की फ़्लाइट में मेरी सीट कौन सी है?"]}),
            'zh':(f"您飞往{c}的{code}航班{d}{t}从{g}登机口出发。",[f"我飞{c}的航班什么时候起飞？",f"飞{c}的航班在几号登机口？"],
                  {'entity':[f"我飞{c2}的航班什么时候起飞？"],'specific':[f"我在飞{c}的航班上坐哪个座位？"]}),
            'es':(f"Tu vuelo {code} a {c} sale el {d} {t} desde la puerta {g}.",[f"¿Cuándo sale mi vuelo a {c}?",f"¿De qué puerta sale el vuelo a {c}?"],
                  {'entity':[f"¿Cuándo sale mi vuelo a {c2}?"],'specific':[f"¿Qué asiento tengo en el vuelo a {c}?"]})}[L]


def recommendation(L,rng):
    p,o=pick(rng,PEOPLE[L],2);title=rng.choice(['The Quiet Orchard','Salt and Static','Paper Kites','Night Market Stories','Copper Sky'])
    K={'en':[('book','film'),('podcast','book'),('film','podcast')],'hi':[('किताब','फ़िल्म'),('पॉडकास्ट','किताब')],'zh':[('书','电影'),('播客','书')],'es':[('libro','película'),('pódcast','libro')]}
    k,k2=rng.choice(K[L])
    return {'en':(f"{p} recommended the {k} '{title}' for the long weekend.",[f"Which {k} did {p} recommend?",f"What did {p} suggest I read or watch?" if k!='podcast' else f"Which podcast did {p} suggest?"],
                  {'attribution':[f"Which {k} did {o} recommend?"],'entity':[f"Which {k2} did {p} recommend?"],'specific':[f"Who wrote the {k} {p} recommended?"]}),
            'hi':(f"{p} ने लंबे वीकेंड के लिए {k} '{title}' सुझाई।",[f"{p} ने कौन सी {k} सुझाई?"],{'attribution':[f"{o} ने कौन सी {k} सुझाई?"],'entity':[f"{p} ने कौन सी {k2} सुझाई?"]}),
            'zh':(f"{p}推荐了{k}《{title}》，适合长周末。",[f"{p}推荐了哪本{k}？" if k=='书' else f"{p}推荐了什么{k}？"],{'attribution':[f"{o}推荐了什么{k}？"],'entity':[f"{p}推荐了什么{k2}？"]}),
            'es':(f"{p} recomendó el {k} '{title}' para el fin de semana largo.",[f"¿Qué {k} recomendó {p}?"],{'attribution':[f"¿Qué {k} recomendó {o}?"],'entity':[f"¿Qué {k2} recomendó {p}?"]})}[L]


def bill(L,rng):
    B={'en':['gas bill','internet bill','credit card bill','water bill'],'hi':['बिजली का बिल','इंटरनेट बिल','क्रेडिट कार्ड बिल'],'zh':['电费账单','网费账单','信用卡账单'],
       'es':['factura de la luz','factura de internet','factura de la tarjeta']}
    b,b2=pick(rng,B[L],2);amt=rng.choice(['₹1,840','₹3,215','$64','€72','₹9,050']);d=rng.choice(DAYS[L])
    return {'en':(f"Your {b} of {amt} is due on {d}.",[f"How much is the {b}?",f"When do I have to pay the {b}?"],
                  {'entity':[f"How much is the {b2}?"],'action':[f"When did I pay the {b}?"],'specific':[f"Which account is the {b} charged to?"]}),
            'hi':(f"आपका {b} {amt} का है, {d} तक भरना है।",[f"{b} कितना है?",f"{b} कब तक भरना है?"],{'entity':[f"{b2} कितना है?"],'action':[f"मैंने {b} कब भरा?"]}),
            'zh':(f"您的{b}金额{amt}，{d}到期。",[f"{b}是多少钱？",f"{b}什么时候到期？"],{'entity':[f"{b2}是多少钱？"],'action':[f"我什么时候交的{b}？"]}),
            'es':(f"Tu {b} de {amt} vence el {d}.",[f"¿Cuánto es la {b}?",f"¿Cuándo vence la {b}?"],{'entity':[f"¿Cuánto es la {b2}?"],'action':[f"¿Cuándo pagué la {b}?"]})}[L]


def tech(L,rng):
    p=rng.choice(PEOPLE[L]);tc=rng.choice(['MariaDB','Redis','Kafka','SQLite','DuckDB'])
    S={'en':['billing service','search page','audit log','mobile sync'],'hi':['बिलिंग सर्विस','सर्च पेज','ऑडिट लॉग'],'zh':['计费服务','搜索页面','审计日志'],'es':['servicio de facturación','página de búsqueda','registro de auditoría']}
    s,s2=pick(rng,S[L],2)
    return {'en':(f"We chose {tc} for the {s} after the review with {p}.",[f"Which tool did the team settle on for the {s}?",f"Who was in the review about the {s}?"],
                  {'entity':[f"Which tool did the team settle on for the {s2}?"],'specific':[f"Why did we reject the other options for the {s}?",f"When does the {s} migration start?"]}),
            'hi':(f"{p} के साथ समीक्षा के बाद हमने {s} के लिए {tc} चुना।",[f"{s} के लिए हमने क्या चुना?"],{'entity':[f"{s2} के लिए हमने क्या चुना?"],'specific':[f"{s} का माइग्रेशन कब शुरू होगा?"]}),
            'zh':(f"和{p}评审之后，我们为{s}选了{tc}。",[f"我们给{s}选了什么？"],{'entity':[f"我们给{s2}选了什么？"],'specific':[f"{s}的迁移什么时候开始？"]}),
            'es':(f"Elegimos {tc} para el {s} tras la revisión con {p}.",[f"¿Qué elegimos para el {s}?"],{'entity':[f"¿Qué elegimos para el {s2}?"],'specific':[f"¿Cuándo empieza la migración del {s}?"]})}[L]


def child_event(L,rng):
    p,o=pick(rng,PEOPLE[L],2);d=rng.choice(DAYS[L]);v=rng.choice(['Elm Street Hall','Riverside Pool','Hillcrest School','Thornbury Commons'])
    E={'en':['swimming gala','violin recital','science fair','football final'],'hi':['तैराकी प्रतियोगिता','पियानो कार्यक्रम','विज्ञान मेला'],'zh':['游泳比赛','钢琴演奏会','科学展'],'es':['competición de natación','recital de piano','feria de ciencias']}
    e,e2=pick(rng,E[L],2)
    return {'en':(f"{p}'s {e} is on {d} at {v}.",[f"When is {p}'s {e}?",f"Where is {p}'s {e}?"],
                  {'attribution':[f"When is {o}'s {e}?"],'entity':[f"When is {p}'s {e2}?"],'specific':[f"What time does {p}'s {e} start?"]}),
            'hi':(f"{p} की {e} {d} को {v} में है।",[f"{p} की {e} कब है?",f"{p} की {e} कहाँ है?"],{'attribution':[f"{o} की {e} कब है?"],'entity':[f"{p} का {e2} कब है?"]}),
            'zh':(f"{p}的{e}在{d}，地点是{v}。",[f"{p}的{e}是什么时候？",f"{p}的{e}在哪里？"],{'attribution':[f"{o}的{e}是什么时候？"],'entity':[f"{p}的{e2}是什么时候？"]}),
            'es':(f"La {e} de {p} es el {d} en {v}.",[f"¿Cuándo es la {e} de {p}?",f"¿Dónde es la {e} de {p}?"],{'attribution':[f"¿Cuándo es la {e} de {o}?"],'entity':[f"¿Cuándo es la {e2} de {p}?"]})}[L]


def deadline(L,rng):
    p,o=pick(rng,PEOPLE[L],2);d=rng.choice(DAYS[L])
    K={'en':['the grant report','the slide deck','the expense receipts','the hiring rubric'],'hi':['ग्रांट रिपोर्ट','स्लाइड डेक','टैक्स दस्तावेज़'],'zh':['项目报告','演示文稿','报税材料'],
       'es':['el informe de la beca','la presentación','los documentos fiscales']}
    k,k2=pick(rng,K[L],2)
    return {'en':(f"{p} has to send {k} by {d}.",[f"When is {k} due?",f"Who is sending {k}?"],
                  {'attribution':[f"When does {o} have to send {k}?"],'entity':[f"When is {k2} due?"],'action':[f"When did {p} approve {k}?"]}),
            'hi':(f"{p} को {k} {d} तक भेजनी है।",[f"{k} कब तक भेजनी है?",f"{k} कौन भेज रहा है?"],{'attribution':[f"{o} को {k} कब तक भेजनी है?"],'entity':[f"{k2} कब तक भेजनी है?"]}),
            'zh':(f"{p}要在{d}之前把{k}发出去。",[f"{k}什么时候要交？",f"谁负责发{k}？"],{'attribution':[f"{o}什么时候要交{k}？"],'entity':[f"{k2}什么时候要交？"]}),
            'es':(f"{p} tiene que enviar {k} antes del {d}.",[f"¿Para cuándo hay que enviar {k}?",f"¿Quién envía {k}?"],{'attribution':[f"¿Para cuándo tiene que enviar {o} {k}?"],'entity':[f"¿Para cuándo hay que enviar {k2}?"]})}[L]


SCHEMAS=[meeting,order,doctor,flight,recommendation,bill,tech,child_event,deadline]
# Cross-lingual: English memories asked about in another language (English names and items kept, as people type them).
CROSS={'zh':{'flight':lambda c:[f"我去{c}的航班几点？"],'doctor':lambda d:[f"我和{d}的预约是什么时候？"]},
       'hi':{'flight':lambda c:[f"{c} की फ़्लाइट कब है?"],'doctor':lambda d:[f"{d} के साथ अपॉइंटमेंट कब है?"]},
       'es':{'flight':lambda c:[f"¿Cuándo sale mi vuelo a {c}?"],'doctor':lambda d:[f"¿Cuándo es mi cita con {d}?"]}}


def fixture_guard():
    texts=[]
    def walk(x):
        if isinstance(x,str):texts.append(x)
        elif isinstance(x,list):[walk(v) for v in x]
        elif isinstance(x,dict):[walk(v) for v in x.values()]
    for f in FIXTURES:walk(json.loads(f.read_text(encoding='utf-8')))
    grams=set();names=set();lower=set()
    for t in texts:
        w=t.lower().split();grams.update(' '.join(w[i:i+5]) for i in range(len(w)-4));lower.update(re.findall(r'\b[a-z]{4,}\b',t))
        names.update(re.findall(r'(?<=[a-z0-9,] )[A-Z][a-z]{3,}\b',t))  # capitalised inside a sentence: a name, not "When"
    months={'January','February','March','April','June','July','August','September','October','November','December'}
    return grams,{n for n in names if n.lower() not in lower}-set(DAYS['en'])-months


def leaks(texts,grams,names):
    for t in texts:
        w=t.lower().split()
        if any(' '.join(w[i:i+5]) in grams for i in range(len(w)-4)):return True
        if set(re.findall(r'\b[A-Z][a-z]{3,}\b',t))&names:return True
    return False


def platt(s,y,iters=200):  # 1-D logistic fit of gold on teacher scores (standardised, Newton steps)
    mu,sd=s.mean(),s.std()+1e-9;z=(s-mu)/sd;a,b=1.0,0.0
    for _ in range(iters):
        p=1/(1+np.exp(-(a*z+b)));g=np.array([((p-y)*z).sum(),(p-y).sum()]);w=p*(1-p)+1e-9
        H=np.array([[(w*z*z).sum(),(w*z).sum()],[(w*z).sum(),w.sum()]])+1e-6*np.eye(2);step=np.linalg.solve(H,g);a,b=a-step[0],b-step[1]
        if np.abs(step).max()<1e-8:break
    return a/sd,b-a*mu/sd


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--items',type=int,default=4000);ap.add_argument('--seed',type=int,default=20261031)
    ap.add_argument('--batch',type=int,default=8);ap.add_argument('--no-teacher',action='store_true');a=ap.parse_args()
    rng=random.Random(a.seed);OUT.mkdir(parents=True,exist_ok=True);grams,names=fixture_guard()
    items=[];seen=set();dropped=collections.Counter()
    while len(items)<a.items and dropped['duplicate']<20*a.items:
        L=rng.choices(LANGS,[0.6,0.14,0.13,0.13])[0];schema=rng.choice(SCHEMAS)
        memory,answerable,near=schema(L,rng)
        if memory in seen:dropped['duplicate']+=1;continue
        if L=='en' and schema.__name__ in ('flight','doctor') and rng.random()<0.4:  # cross-lingual questions about an English memory
            x=rng.choice(list(CROSS));m=re.search(r'to (\w+) departs',memory) if schema.__name__=='flight' else re.search(r'with (Dr\. \w+)',memory)
            if m:answerable=answerable+CROSS[x][schema.__name__](m.group(1))
        texts=[memory]+answerable+[q for v in near.values() for q in v]
        if leaks(texts,grams,names):dropped['leak']+=1;continue
        seen.add(memory);items.append({'id':hashlib.sha256(memory.encode()).hexdigest()[:16],'lang':L,'schema':schema.__name__,'memory':memory,
                                        'answerable':answerable,'near_miss':near})
    pairs=[]
    for i,x in enumerate(items):
        for q in rng.sample(x['answerable'],min(2,len(x['answerable']))):pairs.append({'q':q,'e':x['memory'],'y':1,'kind':'lens_answerable'})
        subs=list(x['near_miss']);rng.shuffle(subs)
        for sub in subs[:3]:pairs.append({'q':rng.choice(x['near_miss'][sub]),'e':x['memory'],'y':0,'kind':f'lens_near_miss_{sub}'})
        other=items[(i+1+rng.randrange(len(items)-1))%len(items)]
        pairs.append({'q':rng.choice(other['answerable']),'e':x['memory'],'y':0,'kind':'lens_unrelated'})
        for p in pairs[-6:]:p.setdefault('lang',x['lang']);p.setdefault('group','lens:'+x['id']);p.setdefault('src','lens_style')
    with (OUT/'items.jsonl').open('w',encoding='utf-8') as f:
        for x in items:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    report={'items':len(items),'pairs':len(pairs),'dropped':dict(dropped),'seed':a.seed,'by_lang':dict(collections.Counter(x['lang'] for x in items)),
            'by_schema':dict(collections.Counter(x['schema'] for x in items)),'by_kind':dict(collections.Counter(p['kind'] for p in pairs)),
            'fixtures_guarded':[f.name for f in FIXTURES]}
    if not a.no_teacher:
        sys.path.insert(0,str(ROOT/'lens_model/eval'));import compare_answerability as ca
        os.environ.setdefault('LENS_JUDGE_DEVICE','cuda');judge=ca.make('qwen3-1.7b');s=[]
        for k in range(0,len(pairs),a.batch):
            s.extend(judge.batch(pairs[k:k+a.batch]))
            if k//a.batch%250==0:print(f'teacher {k}/{len(pairs)}',flush=True)
        s=np.array(s,dtype=float);y=np.array([p['y'] for p in pairs],dtype=float);A,B=platt(s,y);pt=1/(1+np.exp(-(A*s+B)))
        for p,st,q in zip(pairs,s,pt):p['y_gold']=p['y'];p['s_teacher']=float(st);p['p_teacher']=float(q);p['y']=0.5*p['y_gold']+0.5*float(q)
        report['teacher']={'model':'qwen3-1.7b','platt':{'a':float(A),'b':float(B)},'auc_vs_gold':ca.auc(y,s),
                           'disagree_over_0.5':int(sum(abs(p['y_gold']-p['p_teacher'])>0.5 for p in pairs)),
                           'disagree_by_kind':dict(collections.Counter(p['kind'] for p in pairs if abs(p['y_gold']-p['p_teacher'])>0.5))}
    with (OUT/'train.jsonl').open('w',encoding='utf-8') as f:
        for p in pairs:f.write(json.dumps(p,ensure_ascii=False)+'\n')
    (OUT/'build-report.json').write_text(json.dumps(report,indent=1,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(report,indent=1,ensure_ascii=False))


if __name__=='__main__':main()
