"""Episodic memory (L3): consolidation groups observations by device, application and window with a time gap,
episodes are listed and filtered, neighbours answer "what was I doing before", recall carries episode context, and
rebuilding is deterministic. Only synthetic test data."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
EXE=ROOT/'build/engine/Release/lens-engine.exe'
OBS=[('a1','laptop','chrome.exe','window:Vendor contract - Chrome','09:00','Vendor contract renewal draft, section one'),
     ('a2','laptop','chrome.exe','window:Vendor contract - Chrome','09:02','Vendor contract renewal draft, section two'),
     ('a3','laptop','chrome.exe','window:Vendor contract - Chrome','09:04','Vendor contract renewal draft, signatures'),
     ('b1','laptop','winword.exe','window:Budget memo - Word','09:05','Budget memo for the Zephyrine project'),
     ('b2','laptop','winword.exe','window:Budget memo - Word','09:06','Budget memo for the Zephyrine project, revised'),
     ('c1','laptop','chrome.exe','window:Vendor contract - Chrome','09:30','Vendor contract renewal final review'),
     ('p1','phone','whatsapp','window:Chat','09:03','Reminder: call the vendor about renewal')]


def add(i,device,app,locator,hhmm,text):
    return {'op':'add','consent':True,'id':i,'text':text,'language':'en','timestamp':f'2026-10-27T{hhmm}:00.000Z','device':device,
            'kind':'screen_observation','provenance':'synthetic-test','source_application':app,'source_locator':locator}


def run(db,requests):
    p=subprocess.run([str(EXE),'--db',str(db)],input=''.join(json.dumps(r)+'\n' for r in requests),encoding='utf-8',capture_output=True,timeout=120)
    assert p.returncode==0,p.stderr
    return [json.loads(l) for l in p.stdout.splitlines()]


class Episodes(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'m.db'
        run(self.db,[add(*o) for o in OBS])

    def tearDown(self):self.tmp.cleanup()

    def test_consolidation_groups_by_window_device_and_gap(self):
        r=run(self.db,[{'op':'consolidate'},{'op':'episodes','limit':10}])
        self.assertEqual(r[0]['episodes'],4);self.assertEqual(r[0]['members'],7)
        eps=r[1]['episodes'];counts=sorted((e['device'],e['application'],e['observation_count']) for e in eps)
        self.assertEqual(counts,[('laptop','chrome.exe',1),('laptop','chrome.exe',3),('laptop','winword.exe',2),('phone','whatsapp',1)])
        first=next(e for e in eps if e['observation_count']==3)
        self.assertEqual(first['title'],'Vendor contract - Chrome');self.assertEqual(first['duration_seconds'],240)
        self.assertEqual((first['first_source_id'],first['last_source_id']),('a1','a3'))

    def test_filters_by_time_and_application(self):
        r=run(self.db,[{'op':'consolidate'},{'op':'episodes','application':'winword.exe'},
                       {'op':'episodes','start':'2026-10-27T09:20:00Z','end':'2026-10-27T10:00:00Z'},
                       {'op':'episodes','start':'2026-10-28T00:00:00Z'}])
        self.assertEqual([e['id'] for e in r[1]['episodes']].__len__(),1);self.assertEqual(r[1]['episodes'][0]['application'],'winword.exe')
        self.assertEqual([e['first_source_id'] for e in r[2]['episodes']],['c1']);self.assertTrue(r[3]['not_found'])

    def test_previous_and_next_episode_on_the_same_device(self):
        r=run(self.db,[{'op':'consolidate'},{'op':'episode_context','source_id':'b2'},{'op':'episode_context','source_id':'missing'}])
        ctx=r[1];self.assertEqual(ctx['episode']['application'],'winword.exe')
        self.assertEqual(ctx['previous']['first_source_id'],'a1');self.assertEqual(ctx['next']['first_source_id'],'c1')
        self.assertTrue(r[2]['not_found'])

    def test_recall_results_carry_episode_context(self):
        r=run(self.db,[{'op':'consolidate'},{'op':'recall','query':'Zephyrine budget memo','mode':'keyword','limit':3}])
        top=r[1]['results'][0];self.assertIn(top['source']['id'],('b1','b2'))
        self.assertEqual(top['episode']['application'],'winword.exe');self.assertEqual(top['episode']['observation_count'],2)

    def test_rebuild_is_deterministic_and_follows_deletions(self):
        first=run(self.db,[{'op':'consolidate'},{'op':'episodes','limit':10}])[1]['episodes']
        again=run(self.db,[{'op':'consolidate'},{'op':'episodes','limit':10}])[1]['episodes']
        self.assertEqual(first,again)
        r=run(self.db,[{'op':'delete','consent':True,'id':'a2'},{'op':'consolidate'},{'op':'episode_context','source_id':'a1'}])
        self.assertEqual(r[2]['episode']['observation_count'],2)


if __name__=='__main__':unittest.main()
