"""Memory lifecycle L9 and user memory (docs/LENS_V1_SPEC.md §8, §12, §17), schema v9. Synthetic data, temp dirs only.

Encrypted backup and verified restore (DPAPI and passphrase keys, tamper and wrong-key refusal, nothing left behind on
failure), JSONL export that round-trips through the history importer, delete-all and scoped deletion proven with a
sentinel scan of a decrypted logical copy and of the raw DB/WAL/SHM files, retention rules with pinned exemption,
crash-safe key rotation (simulated crashes at each step), corrections with superseded provenance, latest-vs-superseded
facts, pins and relevance feedback as recall signals, and hostile input on the new ops."""
import datetime
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
EXE=ROOT/'build/engine/Release/lens-engine.exe'
sys.path.insert(0,str(ROOT/'tests'))
from support import pwsh
from test_memory_v2 import schema_sql_for_synthetic_db

SENTINEL='zqxsentinel'  # appears only in the sources a test deletes


def run(db,requests,env=None,check=True):
    p=subprocess.run([str(EXE),'--db',str(db)],input=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in requests),encoding='utf-8',
                     capture_output=True,timeout=300,env=env)
    if check:assert p.returncode==0,p.stderr
    return [json.loads(l) for l in p.stdout.splitlines()],p.returncode


def ask(db,*requests):return run(db,list(requests))[0]


def add(i,text,when='2026-10-20T05:00:00Z',app='notes.exe',kind='note',**extra):
    r={'op':'add','consent':True,'id':i,'text':text,'language':'en','timestamp':when,'device':'laptop','kind':kind,'provenance':'synthetic-test',
       'timezone':'UTC','source_application':app,'source_locator':f'window:{i}'}
    r.update(extra);return r


CORPUS=[add('k1','Arun said the Orion project review is due on 3 November.'),
        add('k2','The budget for Project Orion is $12,500 according to the plan.'),
        add('k3','Meeting with Priya Raman on Friday to finalise the Orion budget.'),
        add('k4','Grocery list: rice, lentils, coffee.')]
SECRET=[add('s1',f'Dr. Meena {SENTINEL.capitalize()} from {SENTINEL.capitalize()} Labs said the {SENTINEL} budget is $9,999.',app='SecretApp'),
        add('s2',f'{SENTINEL.capitalize()} project review is due on 9 December.',app='SecretApp')]


def plaintext_copy(db,tmp):
    """A decrypted logical copy of every table (FTS shadow tables included), for scanning only; synthetic data."""
    plain=Path(tmp)/'scan-plain.db'
    plain.write_bytes(b'')  # an empty file is an empty database; the helper's connection cannot create files
    schema_sql_for_synthetic_db(db,f"ATTACH DATABASE '{plain.as_posix()}' AS plain KEY ''; SELECT sqlcipher_export('plain'); DETACH DATABASE plain;")
    data=plain.read_bytes();plain.unlink();return data


def raw_files(db):
    return {s:Path(str(db)+s).read_bytes() for s in ('','-wal','-shm') if Path(str(db)+s).exists()}


class BackupRestore(unittest.TestCase):
    def test_dpapi_backup_restores_into_a_new_verified_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db,backup,target=Path(tmp)/'m.db',Path(tmp)/'b.lensbackup',Path(tmp)/'restored.db'
            r=ask(db,*CORPUS,{'op':'consolidate'},{'op':'pin','source_id':'k2'},{'op':'backup','path':str(backup)})
            b=r[-1];self.assertTrue(b['ok'],b);self.assertEqual(b['backup']['source_count'],4);self.assertEqual(b['backup']['key_mode'],'dpapi_current_user')
            self.assertTrue(Path(str(backup)+'.key').exists())
            manifest=Path(str(backup)+'.manifest.json').read_text(encoding='utf-8')
            self.assertNotIn('Orion',manifest);self.assertNotIn(b'Orion',backup.read_bytes())  # page-encrypted, metadata only
            r=ask(db,{'op':'restore','backup_path':str(backup),'target_path':str(target)})[0]
            self.assertTrue(r['ok'],r);self.assertTrue(r['verified']);self.assertEqual(r['restored_sources'],4)
            again=ask(target,{'op':'stats'},{'op':'search','query':'Orion'},{'op':'pins'},{'op':'facts','entity':'Orion','type':'deadline'})
            self.assertEqual((again[0]['schema_version'],again[0]['source_count'],again[0]['pin_count']),(9,4,1))
            self.assertEqual({s['id'] for s in again[1]['sources']},{'k1','k2','k3'});self.assertEqual(again[2]['pins'][0]['source_id'],'k2')
            self.assertIn('2026-11-03',[f['value'] for f in again[3]['facts']])
            self.assertNotIn(b'Orion',target.read_bytes())
            # An existing target is never overwritten.
            self.assertEqual(ask(db,{'op':'restore','backup_path':str(backup),'target_path':str(target)})[0]['error'],'invalid_path')

    def test_passphrase_backup_tamper_and_wrong_key_are_refused_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            db,backup=Path(tmp)/'m.db',Path(tmp)/'p.lensbackup'
            r=ask(db,*CORPUS,{'op':'backup','path':str(Path(tmp)/'weak.lensbackup'),'passphrase':'short'},
                  {'op':'backup','path':str(backup),'passphrase':'correct horse battery staple'},{'op':'backup','path':'relative.lensbackup'})
            self.assertEqual(r[-3]['error'],'weak_passphrase');self.assertFalse((Path(tmp)/'weak.lensbackup').exists())
            self.assertTrue(r[-2]['ok']);self.assertFalse(Path(str(backup)+'.key').exists());self.assertEqual(r[-1]['error'],'invalid_path')
            t1,t2,t3=Path(tmp)/'t1.db',Path(tmp)/'t2.db',Path(tmp)/'t3.db'
            r=ask(db,{'op':'restore','backup_path':str(backup),'target_path':str(t1),'passphrase':'wrong passphrase entirely'},
                  {'op':'restore','backup_path':str(backup),'target_path':str(t2)},
                  {'op':'restore','backup_path':str(backup),'target_path':str(t3),'passphrase':'correct horse battery staple'})
            self.assertEqual(r[0]['error'],'backup_key_invalid');self.assertEqual(r[1]['error'],'invalid_request');self.assertTrue(r[2]['ok'])
            for t in (t1,t2):self.assertEqual([p for p in Path(tmp).iterdir() if p.name.startswith(t.name)],[])  # nothing left behind
            self.assertEqual(ask(t3,{'op':'stats'})[0]['source_count'],4)
            data=bytearray(backup.read_bytes());data[len(data)//2]^=0x5A;backup.write_bytes(bytes(data))
            t4=Path(tmp)/'t4.db'
            r=ask(db,{'op':'restore','backup_path':str(backup),'target_path':str(t4),'passphrase':'correct horse battery staple'})[0]
            self.assertEqual(r['error'],'backup_integrity_failed');self.assertFalse(t4.exists());self.assertFalse(Path(str(t4)+'.key').exists())


class ExportAndDeletion(unittest.TestCase):
    def test_export_round_trips_through_the_history_importer(self):
        with tempfile.TemporaryDirectory() as tmp:
            db,out,db2=Path(tmp)/'m.db',Path(tmp)/'export.jsonl',Path(tmp)/'m2.db'
            r=ask(db,*CORPUS,{'op':'export','path':str(out)},{'op':'export','consent':True,'path':str(out),'scope':{'application':'notes.exe'}})
            self.assertEqual(r[-2]['error'],'consent_required');e=r[-1];self.assertTrue(e['ok']);self.assertEqual(e['exported'],4);self.assertTrue(e['plaintext'])
            lines=out.read_text(encoding='utf-8').splitlines();self.assertEqual(json.loads(lines[0]),{'format':'lens-history','version':1})
            rows=[json.loads(l) for l in lines[1:]];self.assertEqual({x['id'] for x in rows},{'k1','k2','k3','k4'})
            self.assertTrue(all(x['provenance']=='synthetic-test' and x['source_locator'] for x in rows))
            p=subprocess.run([pwsh(),'-NoProfile','-File',str(ROOT/'scripts/import-history.ps1'),'-Format','LensJsonl','-SourcePath',str(out),'-DatabasePath',str(db2)],
                             capture_output=True,encoding='utf-8',timeout=120)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertEqual(json.loads(p.stdout)['imported'],4)
            self.assertEqual({s['text'] for s in ask(db2,{'op':'search','query':'Orion'})[0]['sources']},{c['text'] for c in CORPUS[:3]})

    def scenario(self,tmp,scope):
        db=Path(tmp)/'m.db'
        ask(db,*CORPUS,*SECRET,{'op':'consolidate'},{'op':'pin','source_id':'s1'},{'op':'feedback','query':'budget','source_id':'s1','relevant':True})
        facts=ask(db,{'op':'facts','source_id':'s2'})[0]['facts']
        ask(db,{'op':'correct_fact','fact_id':facts[0]['id'],'value':'2026-12-12','statement':f'The {SENTINEL} review moved.'})
        self.assertIn(SENTINEL.encode(),plaintext_copy(db,tmp).lower())  # positive control: the scan sees it before deletion
        before=ask(db,{'op':'entities','query':SENTINEL.capitalize()+' Labs'})[0];self.assertFalse(before['not_found'])
        r=ask(db,{'op':'delete_sources','consent':True,'scope':scope},{'op':'stats'},{'op':'entities','limit':200},{'op':'pins'},
              {'op':'facts','limit':200},{'op':'recall','query':'budget','mode':'keyword','abstain':False})
        return db,r

    def assert_no_sentinel(self,db,tmp,r):
        self.assertTrue(r[0]['ok'],r[0])
        self.assertNotIn(SENTINEL,json.dumps(r[2:]).lower())
        self.assertNotIn(SENTINEL.encode(),plaintext_copy(db,tmp).lower())
        for name,data in raw_files(db).items():
            self.assertNotIn(SENTINEL.encode(),data.lower(),name)
            self.assertNotIn(SENTINEL.encode('utf-16-le'),data.lower(),name)
        wal=Path(str(db)+'-wal');self.assertTrue(not wal.exists() or wal.stat().st_size==0)

    def test_scoped_delete_by_application_leaves_nothing_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            db,r=self.scenario(tmp,{'application':'SecretApp'})
            self.assertEqual(r[0]['deleted'],2);self.assertEqual(r[1]['source_count'],4);self.assertEqual(r[1]['pin_count'],0)
            self.assertEqual(r[1]['user_fact_count'],1)  # the user's own correction stays until the user deletes everything
            self.assertTrue(r[3]['not_found'])
            self.assertEqual(sorted(x['source']['id'] for x in r[5]['results']),['k2','k3'])
            # The correction is the user's text; it is removed explicitly below by delete-all.
            r2=ask(db,{'op':'delete_sources','consent':True,'scope':{'all':True}},{'op':'stats'},{'op':'facts'})
            self.assertEqual((r2[1]['source_count'],r2[1]['user_fact_count'],r2[1]['entity_count'],r2[1]['fact_count']),(0,0,0,0))
            self.assert_no_sentinel(db,tmp,r2)

    def test_delete_all_by_time_range_and_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'m.db'
            r=ask(db,*CORPUS,add('old',f'{SENTINEL} 2019 note',when='2019-05-01T00:00:00Z'),{'op':'consolidate'},
                  {'op':'delete_sources','consent':True,'scope':{'end':'2020-01-01T00:00:00Z'}},
                  {'op':'delete_sources','consent':True,'scope':{'source_ids':['k4','missing']}},{'op':'stats'},
                  {'op':'delete_sources','consent':True,'scope':{}},{'op':'delete_sources','scope':{'all':True}},
                  {'op':'delete_sources','consent':True,'scope':{'all':True,'kind':'note'}},{'op':'delete_sources','consent':True,'scope':{'import':'nothex'}})
            self.assertEqual([x['deleted'] for x in r[6:8]],[1,1]);self.assertEqual(r[8]['source_count'],3)
            self.assertEqual([x['error'] for x in r[9:13]],['invalid_scope','consent_required','invalid_scope','invalid_scope'])
            self.assertNotIn(SENTINEL.encode(),plaintext_copy(db,tmp).lower())
            r=ask(db,{'op':'delete_sources','consent':True,'scope':{'all':True}},{'op':'stats'},{'op':'episodes'},{'op':'projects'})
            self.assertTrue(r[0]['compacted']);self.assertEqual((r[1]['source_count'],r[1]['entity_count'],r[1]['fact_count']),(0,0,0))
            self.assertTrue(r[2]['not_found']);self.assertTrue(r[3]['not_found'])
            self.assertTrue(ask(db,add('fresh','A new note after deleting everything, long enough to compress maybe '*6),{'op':'search','query':'fresh'})[0]['ok'])


class Retention(unittest.TestCase):
    def test_rules_expire_old_sources_except_pinned_ones(self):
        now=datetime.datetime.now(datetime.timezone.utc)
        recent=(now-datetime.timedelta(days=2)).strftime('%Y-%m-%dT%H:%M:%SZ')
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'m.db'
            r=ask(db,add('o1','Old screen text one',when='2020-01-01T00:00:00Z',kind='screen_observation'),
                  add('o2','Old screen text two, pinned',when='2020-01-02T00:00:00Z',kind='screen_observation'),
                  add('o3','Old voice note',when='2020-01-03T00:00:00Z',kind='voice_note'),
                  add('n1','Recent screen text',when=recent,kind='screen_observation'),
                  {'op':'pin','source_id':'o2'},{'op':'retention_set','kind':'screen_observation','max_age_days':30},
                  {'op':'retention_set','application':'Nowhere','max_age_days':1},{'op':'retention_set','max_age_days':0},
                  {'op':'retention_list'},{'op':'consolidate'},{'op':'stats'},{'op':'search','query':'Old'})
            self.assertEqual(r[7]['error'],'invalid_retention');self.assertEqual(len(r[8]['rules']),2)
            self.assertEqual(r[9]['retention']['deleted'],1)
            self.assertEqual(r[10]['source_count'],3);self.assertEqual({s['id'] for s in r[11]['sources']},{'o2','o3'})
            r=ask(db,{'op':'unpin','source_id':'o2'},{'op':'retention_remove','id':r[8]['rules'][1]['id']},{'op':'consolidate'},{'op':'retention_list'})
            self.assertEqual(r[2]['retention']['deleted'],1);self.assertEqual(len(r[3]['rules']),1)


class KeyRotation(unittest.TestCase):
    def files(self,db):return sorted(p.name for p in db.parent.iterdir())

    def test_rotation_changes_the_key_and_keeps_every_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'m.db';ask(db,*CORPUS,{'op':'consolidate'})
            old=Path(str(db)+'.key').read_bytes()
            r=ask(db,{'op':'rotate_key'},{'op':'search','query':'Orion'},{'op':'stats'})
            self.assertTrue(r[0]['rotated']);self.assertEqual(len(r[1]['sources']),3);self.assertGreater(r[2]['entity_count'],0)
            self.assertNotEqual(Path(str(db)+'.key').read_bytes(),old)
            self.assertEqual(self.files(db),['m.db','m.db.key'])
            self.assertEqual(ask(db,{'op':'stats'})[0]['source_count'],4)

    def test_a_crash_at_any_step_recovers_on_the_next_start(self):
        for point in ('rotate_after_export','rotate_after_db_swap'):
            with self.subTest(point=point),tempfile.TemporaryDirectory() as tmp:
                db=Path(tmp)/'m.db';ask(db,*CORPUS)
                env=dict(os.environ,LENS_FAULT_INJECTION=point)
                out,code=run(db,[{'op':'rotate_key'}],env=env,check=False)
                self.assertEqual(code,3);self.assertEqual(out,[])  # the process died mid-rotation
                self.assertTrue(any(n.endswith('.next') for n in self.files(db)))
                r=ask(db,{'op':'stats'},{'op':'search','query':'Orion'})
                self.assertEqual(r[0]['source_count'],4);self.assertEqual(len(r[1]['sources']),3)
                self.assertEqual([n for n in self.files(db) if n.endswith('.next')],[])
                self.assertTrue(ask(db,{'op':'rotate_key'})[0]['rotated'])
                self.assertEqual(ask(db,{'op':'stats'})[0]['source_count'],4)


class UserMemory(unittest.TestCase):
    def test_corrections_keep_the_original_as_superseded_with_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'m.db'
            r=ask(db,*CORPUS,add('k5','Orion project review is due on 20 November, the date moved.',when='2026-10-25T05:00:00Z'),
                  {'op':'consolidate'},{'op':'facts','entity':'Orion','type':'deadline'})
            facts={f['value']:f for f in r[-1]['facts']}
            self.assertTrue(facts['2026-11-20']['current']);self.assertFalse(facts['2026-11-03']['current'])  # latest evidence wins
            self.assertEqual(facts['2026-11-03']['superseded_by_later'],facts['2026-11-20']['id'])
            target=facts['2026-11-20']['id']
            r=ask(db,{'op':'correct_fact','fact_id':target,'value':'2026-11-27','statement':'Orion review is actually on 27 November.'},
                  {'op':'correct_fact','fact_id':target,'value':'next week','statement':'x'},{'op':'correct_fact','fact_id':'fa-missing','statement':'x'},
                  {'op':'facts','entity':'Orion','type':'deadline'},{'op':'facts','entity':'Orion','type':'deadline','current_only':True})
            self.assertEqual(r[0]['status'],'superseded');self.assertEqual(r[1]['error'],'invalid_value');self.assertEqual(r[2]['error'],'fact_not_found')
            by={f['value']:f for f in r[3]['facts']}
            self.assertEqual(by['2026-11-20']['user_status'],'superseded');self.assertFalse(by['2026-11-20']['current'])
            self.assertEqual(by['2026-11-20']['sources'][0]['source_id'],'k5')  # the original evidence is kept, not overwritten
            user=by['2026-11-27'];self.assertEqual(user['status'],'user_stated');self.assertTrue(user['current'])
            self.assertEqual(user['provenance']['supersedes'],target);self.assertEqual(user['provenance']['supersedes_sources'],['k5'])
            self.assertEqual([f['value'] for f in r[4]['facts']],['2026-11-27'])
            budget=ask(db,{'op':'facts','entity':'Orion','type':'amount'})[0]['facts'][0]
            r=ask(db,{'op':'correct_fact','fact_id':budget['id'],'action':'reject'},{'op':'facts','entity':'Orion','type':'amount'},
                  {'op':'recall','query':'Orion project review','mode':'keyword'})
            self.assertEqual(r[1]['facts'][0]['user_status'],'rejected');self.assertFalse(r[1]['facts'][0]['current'])
            self.assertIn('2026-11-27',[f['value'] for f in r[2]['entity_facts'] if f['current']])

    def test_pins_and_feedback_reorder_recall(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'m.db'
            q={'op':'recall','query':'Orion budget','mode':'keyword','abstain':False,'entity_boost':False}
            base=ask(db,*CORPUS,q)[-1];order=[x['source']['id'] for x in base['results']];self.assertGreaterEqual(len(order),2)
            r=ask(db,{'op':'feedback','query':'  orion   BUDGET ','source_id':order[0],'relevant':False},{'op':'pin','source_id':order[-1],'note':'keep'},q,
                  dict(q,user_signals=False),{'op':'feedback','query':'Orion budget','source_id':'missing','relevant':True},{'op':'pins'})
            got=[x['source']['id'] for x in r[2]['results']]
            self.assertEqual(got[0],order[-1]);self.assertEqual(got[-1],order[0]);self.assertTrue(r[2]['user_signals_applied'])
            self.assertEqual(r[2]['results'][-1]['feedback'],-1);self.assertTrue(r[2]['results'][0]['pinned'])
            self.assertEqual([x['source']['id'] for x in r[3]['results']],order)
            self.assertEqual(r[4]['error'],'source_not_found');self.assertEqual(r[5]['pins'][0]['note'],'keep')
            r=ask(db,{'op':'feedback','query':'Orion budget','source_id':order[1],'relevant':True},q)
            self.assertEqual(r[1]['results'][0]['source']['id'],order[1])  # explicit positive feedback outranks a pin


class HostileInput(unittest.TestCase):
    def test_new_ops_reject_bad_input_without_crashing(self):
        rng=random.Random(20261028)
        ops=['backup','restore','export','delete_sources','rotate_key','retention_set','retention_list','retention_remove','pin','unpin','pins',
             'feedback','correct_fact','imports']
        values=[None,True,False,-1,0,2**63,1e308,'','x'*5000,'\u0000',[],{},[[[]]],'relative.db','..\\..\\Windows','C:\\Windows\\System32\\config\\SAM',
                'C:\\Windows','"; DROP TABLE observations; --','2026-13-45T99:99:99Z',{'all':False},{'source_ids':[]},{'import':'zz'},{'nope':1},'k1','fa-x']
        keys=['op','path','backup_path','target_path','passphrase','scope','consent','kind','application','max_age_days','id','source_id','query',
              'relevant','fact_id','value','statement','action','note','limit','compact']
        lines=[]
        for _ in range(300):
            req={k:rng.choice(values) for k in rng.sample(keys,rng.randrange(1,7))};req['op']=rng.choice(ops)
            if req['op']=='rotate_key' or req.get('scope')=={'all':True}:continue
            lines.append(json.dumps(req))
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'h.db';ask(db,*CORPUS,{'op':'consolidate'})
            before=sorted(p.name for p in Path(tmp).iterdir())
            p=subprocess.run([str(EXE),'--db',str(db)],input='\n'.join(lines+[json.dumps({'op':'stats'})])+'\n',capture_output=True,encoding='utf-8',
                             timeout=600,cwd=tmp)
            self.assertEqual(p.returncode,0,p.stderr[-500:])
            out=[json.loads(l) for l in p.stdout.splitlines()];self.assertEqual(len(out),len(lines)+1)
            self.assertTrue(out[-1]['ok']);self.assertGreaterEqual(out[-1]['source_count'],0)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir() if not p.name.startswith('h.db')),
                             sorted(n for n in before if not n.startswith('h.db')))  # no stray files


if __name__=='__main__':unittest.main()
