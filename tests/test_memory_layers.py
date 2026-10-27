"""Semantic memory L4 (entities, facts) and project memory L5, schema v8 (docs/LENS_V1_SPEC.md §8).

Synthetic multilingual data only (en/es/hi/ta/te/zh), temp dirs only. Covers the v7→v8 migration and its
idempotence, extraction precision/recall on a small labelled set (a development set used while writing the rules
and a held-out set written before the first run and never used to change them), provenance of every fact and
mention, deletion cascades (privacy), the new ops, recall integration and hostile input."""
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
EXE=ROOT/'build/engine/Release/lens-engine.exe'
sys.path.insert(0,str(ROOT/'tests'))
from test_memory_v2 import schema_sql_for_synthetic_db

# (id, language, text, expected mentions [(type, surface)], expected facts [(type, value)], extra add() fields)
DEV=[
    ('d-en-1','en','Arun said the Orion project review is due on 3 November.',[('person','Arun'),('project','Orion')],[('deadline','2026-11-03')],{}),
    ('d-en-2','en','Meeting with Priya Raman on Friday to finalise the Orion budget.',[('person','Priya Raman'),('project','Orion')],[('meeting','2026-10-30')],{}),
    ('d-en-3','en','The budget for Project Orion is $12,500 according to the plan.',[('project','Orion')],[('amount','12500 USD')],{'source_locator':'window:Orion plan - Word'}),
    ('d-en-14','en','Total due by 20 November.',[],[('deadline','2026-11-20')],{'source_locator':'window:Orion plan - Word'}),
    ('d-en-4','en','Dr. Meena Iyer from Acme Labs joined the call.',[('person','Meena Iyer'),('organization','Acme Labs')],[('relationship','acme labs')],{}),
    ('d-en-5','en','We decided to use Postgres for Orion.',[('project','Orion')],[('decision',None)],{}),
    ('d-en-6','en','Monday was busy. Room 204 is booked for the workshop.',[],[],{}),
    ('d-en-7','en','Did we decide on the vendor yet?',[],[],{}),
    ('d-en-8','en','Lunch was $15 at the cafe.',[],[],{}),
    ('d-en-9','en','Meena Iyer is the lead of Project Orion.',[('person','Meena Iyer'),('project','Orion')],[('role','lead')],{}),
    ('d-en-10','en','Invoice from Globex Inc: total INR 45,000 paid on 2 Oct 2026.',[('organization','Globex Inc')],[('amount','45000 INR')],{}),
    ('d-en-11','en','Ravi: I will send the draft tomorrow',[('person','Ravi')],[],{}),
    ('d-en-12','en','Please submit the expense report by Friday.',[('person','Kavya Nair')],[('deadline','2026-10-30')],{'metadata':{'sender':'Kavya Nair'}}),
    ('d-en-13','en','Flight to Lisbon on 12 Nov for the Orion demo.',[('place','Lisbon'),('project','Orion')],[('meeting','2026-11-12')],{}),
    ('d-es-1','es','Carlos dijo que la reunión del proyecto Atlas es el 5 de noviembre.',[('person','Carlos'),('project','Atlas')],[('meeting','2026-11-05')],{}),
    ('d-es-2','es','Decidimos usar Madrid como sede del proyecto Atlas.',[('place','Madrid'),('project','Atlas')],[('decision',None)],{}),
    ('d-es-3','es','El presupuesto de Atlas es de 3.500 euros.',[('project','Atlas')],[('amount','3500 EUR')],{}),
    ('d-hi-1','hi','अरुण ने कहा कि Orion प्रोजेक्ट की डेडलाइन 3 नवंबर है।',[('person','अरुण'),('project','Orion')],[('deadline','2026-11-03')],{}),
    ('d-hi-2','hi','प्रिया जी के साथ शुक्रवार को मीटिंग है।',[('person','प्रिया')],[('meeting','2026-10-30')],{}),
    ('d-hi-3','hi','हमने तय किया कि बजट ₹50,000 होगा।',[],[('decision',None),('amount','50000 INR')],{}),
    ('d-ta-1','ta','அருண் சொன்னார் Orion ப்ராஜெக்ட் கூட்டம் நவம்பர் 5 அன்று.',[('person','அருண்'),('project','Orion')],[('meeting','2026-11-05')],{}),
    ('d-ta-2','ta','சென்னை அலுவலகத்தில் பிரியா சொன்னார்.',[('place','சென்னை'),('person','பிரியா')],[],{}),
    ('d-ta-3','ta','பட்ஜெட் 20000 ரூபாய்.',[],[('amount','20000 INR')],{}),
    ('d-te-1','te','రవి గారు చెప్పారు Atlas ప్రాజెక్ట్ గడువు నవంబర్ 10.',[('person','రవి'),('project','Atlas')],[('deadline','2026-11-10')],{}),
    ('d-te-2','te','హైదరాబాద్ లో సమావేశం రేపు.',[('place','హైదరాబాద్')],[('meeting','2026-10-28')],{}),
    ('d-zh-1','zh','王伟说Orion项目的截止日期是11月3日。',[('person','王伟'),('project','Orion')],[('deadline','2026-11-03')],{}),
    ('d-zh-2','zh','我们决定在北京开会，预算5万元。',[('place','北京')],[('decision',None),('amount','50000 CNY')],{}),
    ('d-zh-3','zh','李老师明天来参加会议。',[('person','李老师')],[('meeting','2026-10-28')],{}),
]
# Written before the first run of the extractor; never used to change it (reported, not tuned).
HELDOUT=[
    ('h1','en','Sanjay told me the Helix project kickoff is on November 18.',[('person','Sanjay'),('project','Helix')],[('meeting','2026-11-18')],{}),
    ('h2','en','Ms. Laura Chen works at Initech Corp.',[('person','Laura Chen'),('organization','Initech Corp')],[('relationship','initech')],{}),
    ('h3','en','The rent of $1,800 is due by 1 December.',[],[('amount','1800 USD'),('deadline','2026-12-01')],{}),
    ('h4','en','Happy birthday! See you in Paris next week.',[('place','Paris')],[],{}),
    ('h5','en','Agreed: we will ship Helix 2 on Friday.',[('project','Helix')],[('decision',None)],{}),
    ('h6','es','María López dijo que pagamos 200 dólares por el hotel.',[('person','María López')],[('amount','200 USD')],{}),
    ('h7','es','La fecha límite del proyecto Fénix es el 15 de diciembre.',[('project','Fénix')],[('deadline','2026-12-15')],{}),
    ('h8','hi','सुनीता ने बताया कि मीटिंग सोमवार को है।',[('person','सुनीता')],[('meeting','2026-11-02')],{}),
    ('h9','hi','Helix प्रोजेक्ट का बजट 2 लाख रुपये है।',[('project','Helix')],[('amount','200000 INR')],{}),
    ('h10','ta','கார்த்திக் சொன்னார் கூட்டம் வெள்ளிக்கிழமை.',[('person','கார்த்திக்')],[('meeting','2026-10-30')],{}),
    ('h11','ta','மதுரை கிளையின் வாடகை 15000 ரூபாய்.',[('place','மதுரை')],[('amount','15000 INR')],{}),
    ('h12','te','లక్ష్మి గారు అన్నారు మీటింగ్ సోమవారం.',[('person','లక్ష్మి')],[('meeting','2026-11-02')],{}),
    ('h13','te','మేము నిర్ణయించాము బడ్జెట్ 5 లక్షలు రూపాయలు.',[],[('decision',None),('amount','500000 INR')],{}),
    ('h14','zh','张丽告诉我Helix项目下周五开会。',[('person','张丽'),('project','Helix')],[('meeting','2026-11-06')],{}),
    ('h15','zh','我不确定是否同意这个方案。',[],[],{}),
    ('h16','zh','华为公司的报价是3000元。',[('organization','华为公司')],[('amount','3000 CNY')],{}),
    ('h17','en','Call Anita at 5pm about the Q3 invoice of €900.',[('person','Anita')],[('amount','900 EUR')],{}),
    ('h18','en','Seattle office meeting moved to 9 Nov.',[('place','Seattle')],[('meeting','2026-11-09')],{}),
]


def add(i,lang,text,n,extra):
    r={'op':'add','consent':True,'id':i,'text':text,'language':lang,'timestamp':f'2026-10-27T05:{n:02d}:00.000Z','device':'laptop',
       'kind':'screen_observation','provenance':'synthetic-test','source_application':'notes.exe','source_locator':f'window:{i}'}
    r.update(extra);return r


def run(db,requests):
    p=subprocess.run([str(EXE),'--db',str(db)],input=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in requests),encoding='utf-8',
                     capture_output=True,timeout=300)
    assert p.returncode==0,p.stderr
    return [json.loads(l) for l in p.stdout.splitlines()]


def load(db,items):
    return run(db,[add(i,lang,text,n,extra) for n,(i,lang,text,_,_,extra) in enumerate(items)])


def extracted(db):
    """All (source, type, surface) mentions and (source, type, value) facts, read back through the public ops."""
    ents=run(db,[{'op':'entities','limit':200}])[0]['entities']
    ctx=run(db,[{'op':'entity_context','id':e['id'],'limit':100} for e in ents])
    mentions={(m['source_id'],c['entity']['type'],m['surface']) for c in ctx for m in c['mentions']}
    facts=run(db,[{'op':'facts','limit':200}])[0]['facts']
    found={(s['source_id'],f['type'],f['value']) for f in facts for s in f['sources']}
    return mentions,found,facts


def score(items,mentions,facts):
    want_m={(i,t,s) for i,_,_,ms,_,_ in items for t,s in ms}
    want_f={(i,t,v) for i,_,_,_,fs,_ in items for t,v in fs}
    def prf(want,got):
        tp=len(want&got);p=tp/len(got) if got else 1.0;r=tp/len(want) if want else 1.0
        return {'tp':tp,'predicted':len(got),'expected':len(want),'precision':round(p,3),'recall':round(r,3),
                'false_positives':sorted(got-want),'missed':sorted(want-got)}
    return prf(want_m,mentions),prf(want_f,facts)


class MemoryLayers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.db=Path(cls.tmp.name)/'m.db'
        load(cls.db,DEV);cls.consolidated=run(cls.db,[{'op':'consolidate'}])[0]
        cls.mentions,cls.found,cls.facts=extracted(cls.db)

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_extraction_quality_on_the_labelled_sets(self):
        ent,fact=score(DEV,self.mentions,self.found)
        print('\nDEV entities',json.dumps(ent))
        print('DEV facts',json.dumps(fact))
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'h.db';load(db,HELDOUT);run(db,[{'op':'consolidate'}])
            m,f,_=extracted(db);hent,hfact=score(HELDOUT,m,f)
        print('HELDOUT entities',json.dumps(hent))
        print('HELDOUT facts',json.dumps(hfact))
        self.assertGreaterEqual(ent['precision'],0.9);self.assertGreaterEqual(ent['recall'],0.85)
        self.assertGreaterEqual(fact['precision'],0.9);self.assertGreaterEqual(fact['recall'],0.85)
        # Held-out floors were fixed before its first run; only precision is gated (unsupported memory is worse than none).
        self.assertGreaterEqual(hent['precision'],0.75);self.assertGreaterEqual(hfact['precision'],0.75)

    def test_consolidation_is_incremental(self):
        self.assertEqual(self.consolidated['memory']['sources_extracted'],len(DEV))
        self.assertEqual(self.consolidated['memory']['pending_sources'],0)
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'i.db';load(db,DEV[:6])
            r=run(db,[{'op':'consolidate','extract_limit':4},{'op':'consolidate'},{'op':'consolidate'},
                      add('late','en','Arun said the Orion launch review is due on 9 December.',50,{}),{'op':'consolidate'}])
            self.assertEqual((r[0]['memory']['sources_extracted'],r[0]['memory']['pending_sources']),(4,2))
            self.assertEqual(r[1]['memory']['sources_extracted'],2);self.assertEqual(r[2]['memory']['sources_extracted'],0)
            self.assertEqual(r[4]['memory']['sources_extracted'],1)
            facts=run(db,[{'op':'facts','entity':'Orion','type':'deadline'}])[0]['facts']
            self.assertIn('2026-12-09',[f['value'] for f in facts])

    def test_every_fact_and_mention_is_source_backed(self):
        texts={i:t.encode('utf-8') for i,_,t,_,_,_ in DEV}
        self.assertTrue(self.facts)
        for f in self.facts:
            self.assertGreaterEqual(f['source_count'],1);self.assertTrue(f['sources']);self.assertEqual(f['status'],'observed')
            for s in f['sources']:
                self.assertEqual(texts[s['source_id']][s['byte_offset']:s['byte_end']].decode('utf-8'),s['quote'])
            self.assertEqual(f['object'],f['sources'][0]['quote'])
        ents=run(self.db,[{'op':'entities','limit':200}])[0]['entities']
        for c in run(self.db,[{'op':'entity_context','id':e['id']} for e in ents]):
            for m in c['mentions']:
                if m['field']!='text':self.assertTrue(m['field'].startswith('metadata.'));continue
                self.assertEqual(texts[m['source_id']][m['byte_offset']:m['byte_end']].decode('utf-8'),m['surface'])
                ex=m['excerpt'];self.assertEqual(texts[m['source_id']][ex['byte_offset']:ex['byte_end']].decode('utf-8'),ex['text'])
        # A subject taken from elsewhere in the source is labelled as inferred, never as certain.
        for f in self.facts:
            if f['subject_basis']=='inferred':self.assertFalse(f['certain'])

    def test_names_join_across_scripts(self):
        r=run(self.db,[{'op':'entities','query':'Arun','type':'person'},{'op':'entities','query':'அருண்'},{'op':'entities','query':'Chennai'}])
        arun=r[0]['entities'][0];self.assertEqual(arun['type'],'person')
        self.assertTrue({'Arun','अरुण','அருண்'}<=set(arun['aliases']),arun['aliases'])
        self.assertEqual(r[1]['entities'][0]['id'],arun['id'])
        self.assertEqual(r[2]['entities'][0]['aliases'],['சென்னை'])  # a place known only in Tamil, found by its English name

    def test_entity_context_and_facts_ops(self):
        r=run(self.db,[{'op':'entity_context','name':'Orion','type':'project'},{'op':'facts','entity':'Orion','type':'deadline'},
                       {'op':'facts','type':'meeting','start':'2026-10-28T00:00:00Z','end':'2026-11-01T00:00:00Z'},
                       {'op':'entity_context','name':'Meena Iyer'},{'op':'entity_context','name':'Nobody Known'},{'op':'facts','entity':'Nobody Known'},
                       {'op':'entities','type':'place'}])
        orion=r[0];self.assertFalse(orion['not_found']);self.assertEqual(orion['entity']['type'],'project')
        self.assertGreaterEqual(orion['entity']['source_count'],8)
        self.assertIn('Arun',[x['name'] for x in orion['related']]+[a for x in orion['related'] for a in [x['name']]])
        self.assertTrue(any(p['role']=='project' for p in orion['projects']))
        self.assertIn('2026-11-03',[f['value'] for f in r[1]['facts']])
        self.assertEqual(sorted(f['value'] for f in r[2]['facts']),['2026-10-28','2026-10-28','2026-10-30','2026-10-30'])
        meena=r[3];self.assertEqual(meena['entity']['name'],'Meena Iyer')
        kinds={(f['type'],f['object_entity']['name'] if f['object_entity'] else None) for f in meena['facts']}
        self.assertIn(('relationship','Acme Labs'),kinds);self.assertIn(('role','Orion'),kinds)
        self.assertTrue(r[4]['not_found']);self.assertTrue(r[5]['not_found'])
        places={e['name'] for e in r[6]['entities']};self.assertTrue({'Lisbon','Madrid','北京'}<=places,places)

    def test_projects_group_entities_episodes_and_facts(self):
        r=run(self.db,[{'op':'projects'},{'op':'project_context','name':'Orion'},{'op':'project_context','name':'Atlas'},{'op':'project_context','id':'pr-missing'}])
        names={p['name'] for p in r[0]['projects']};self.assertTrue({'Orion','Atlas'}<=names,names)
        orion=r[1];self.assertFalse(orion['not_found'])
        self.assertTrue({'Arun','Meena Iyer'}<={e['name'] for e in orion['entities']})
        deadlines={f['value']:f['project_link'] for f in orion['facts'] if f['type']=='deadline'}
        self.assertEqual(deadlines.get('2026-11-03'),'subject')
        self.assertEqual(deadlines.get('2026-11-20'),'same_episode')  # same Word window as the Orion budget, project not named
        self.assertTrue(any(e['title']=='Orion plan - Word' for e in orion['episodes']))
        self.assertGreaterEqual(orion['project']['source_count'],orion['project']['mention_sources'])
        atlas=r[2];self.assertIn('3500 EUR',[f['value'] for f in atlas['facts']]);self.assertIn('Madrid',[e['name'] for e in atlas['entities']])
        self.assertTrue(r[3]['not_found'])

    def test_recall_uses_entities_and_returns_linked_facts(self):
        r=run(self.db,[add('memo','en','Budget memo for the marketing offsite.',59,{}),{'op':'consolidate'},
                       {'op':'recall','query':'Atlas budget','mode':'keyword','abstain':False,'limit':10},
                       {'op':'recall','query':'Atlas budget','mode':'keyword','abstain':False,'limit':10,'entity_boost':False},
                       {'op':'recall','query':'Orion project review','mode':'keyword','limit':5}])
        boosted=r[2];self.assertEqual([e['name'] for e in boosted['entities']],['Atlas'])
        flags=[x['scores']['entity_match'] for x in boosted['results']]
        self.assertIn(True,flags);self.assertIn(False,flags);self.assertEqual(flags,sorted(flags,reverse=True))
        self.assertEqual(sorted(x['source']['id'] for x in boosted['results']),sorted(x['source']['id'] for x in r[3]['results']))
        self.assertFalse(r[3]['entity_boosted'])
        self.assertTrue(all(f['sources'] for f in boosted['entity_facts']));self.assertIn('3500 EUR',[f['value'] for f in boosted['entity_facts']])
        top=r[4]['results'][0];self.assertEqual(top['source']['id'],'d-en-1')
        self.assertIn('Orion',[e['name'] for e in top['entities']]);self.assertIn('2026-11-03',[f['value'] for f in top['facts']])


class Lifecycle(unittest.TestCase):
    def test_deleting_a_source_removes_what_was_derived_from_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'d.db';load(db,DEV);run(db,[{'op':'consolidate'}])
            before=run(db,[{'op':'facts','type':'amount'},{'op':'entities','query':'Arun','type':'person'},{'op':'entities','query':'Globex'},{'op':'stats'}])
            self.assertIn('12500 USD',[f['value'] for f in before[0]['facts']]);self.assertIn('Arun',before[1]['entities'][0]['aliases'])
            self.assertEqual(len(before[2]['entities']),1)
            # No consolidate in between: triggers and the delete op remove derived records at once.
            r=run(db,[{'op':'delete','consent':True,'id':'d-en-3'},{'op':'delete','consent':True,'id':'d-en-1'},{'op':'delete','consent':True,'id':'d-en-10'},
                      {'op':'facts','type':'amount'},{'op':'entities','query':'Arun','type':'person'},{'op':'entities','query':'Globex'},
                      {'op':'facts','source_id':'d-en-1'},{'op':'project_context','name':'Orion'},{'op':'stats'}])
            self.assertEqual([x['deleted'] for x in r[:3]],[1,1,1])
            self.assertNotIn('12500 USD',[f['value'] for f in r[3]['facts']])
            arun=r[4]['entities'][0]  # still known from Hindi and Tamil sources, but nothing of the English source remains
            self.assertNotIn('Arun',arun['aliases']);self.assertNotEqual(arun['name'],'Arun');self.assertEqual(arun['source_count'],2)
            self.assertTrue(r[5]['not_found']);self.assertTrue(r[6]['not_found'])
            orion=r[7];self.assertNotIn('d-en-1',[s['source_id'] for s in orion['sources']])
            for f in orion['facts']:self.assertNotIn(f['sources'][0]['source_id'],('d-en-1','d-en-3'))
            self.assertLess(r[8]['fact_count'],before[3]['fact_count']);self.assertLess(r[8]['entity_count'],before[3]['entity_count'])
            again=run(db,[{'op':'consolidate'},{'op':'entities','query':'Globex'}])
            self.assertTrue(again[1]['not_found'])  # deleted evidence is never re-derived

    def test_v7_to_v8_migration_and_idempotence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'v.db';load(db,DEV[:4])
            # A genuine v7 database: drop every v8 object and set the version back.
            schema_sql_for_synthetic_db(db,'DROP TABLE IF EXISTS project_entities; DROP TABLE IF EXISTS project_episodes; DROP TABLE IF EXISTS project_sources;'
                                           'DROP TABLE IF EXISTS projects; DROP TABLE IF EXISTS fact_sources; DROP TABLE IF EXISTS facts;'
                                           'DROP TABLE IF EXISTS extraction_state; DROP TABLE IF EXISTS entity_mentions; DROP TABLE IF EXISTS entity_aliases;'
                                           'DROP TABLE IF EXISTS entities; DELETE FROM schema_migrations WHERE version=8; PRAGMA user_version=7;')
            r=run(db,[{'op':'stats'},{'op':'consolidate'},{'op':'entities'}])
            self.assertEqual(r[0]['schema_version'],8);self.assertEqual(r[0]['entity_count'],0)
            self.assertEqual(r[1]['memory']['sources_extracted'],4);self.assertFalse(r[2]['not_found'])
            # Re-running the v8 migration on a current database (version reset) keeps all derived memory.
            schema_sql_for_synthetic_db(db,'PRAGMA user_version=7;')
            again=run(db,[{'op':'stats'},{'op':'entities'},{'op':'consolidate'}])
            self.assertEqual(again[0]['schema_version'],8);self.assertEqual(again[1]['entities'],r[2]['entities'])
            self.assertEqual(again[2]['memory']['sources_extracted'],0)


class HostileInput(unittest.TestCase):
    def test_new_ops_reject_bad_input_without_crashing(self):
        rng=random.Random(20261027)
        ops=['entities','entity_context','facts','projects','project_context','consolidate','recall']
        values=[None,True,-1,0,2**63,1e308,'','x'*5000,'\u0000','퟿',[],{},[[[]]],'"; DROP TABLE facts; --',"' OR 1=1 --",'*','NEAR(',
                '2026-13-45T99:99:99Z','person','pr-x','en-x','अरुण','王伟','‮evil']
        keys=['op','id','name','type','query','entity','entity_id','project_id','source_id','start','end','limit','extract_limit','entity_boost','mode']
        lines=[]
        for _ in range(400):
            req={k:rng.choice(values) for k in rng.sample(keys,rng.randrange(1,7))};req['op']=rng.choice(ops);lines.append(json.dumps(req))
        lines+=[json.dumps(x) for x in [{'op':'entities','limit':0},{'op':'entities','type':'alien'},{'op':'facts','start':'yesterday'},
                {'op':'facts','type':'gossip'},{'op':'consolidate','extract_limit':0},{'op':'entity_context','id':7},{'op':'project_context','name':'n'*300},
                {'op':'entities','query':'x'*300},{'op':'stats'}]]
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'h.db';load(db,DEV[:8]);run(db,[{'op':'consolidate'}])
            p=subprocess.run([str(EXE),'--db',str(db)],input='\n'.join(lines)+'\n',capture_output=True,encoding='utf-8',timeout=600)
            self.assertEqual(p.returncode,0,p.stderr[-500:])
            out=[json.loads(l) for l in p.stdout.splitlines()];self.assertEqual(len(out),len(lines))
            tail=out[-9:]
            for x in tail[:8]:self.assertFalse(x['ok'],x)
            self.assertTrue(tail[8]['ok']);self.assertGreater(tail[8]['entity_count'],0)


if __name__=='__main__':unittest.main()
