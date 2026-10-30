"""Milestone 13 safe actions: typed capability registry, validation, nothing runs without the user's approval in the
app, approval never over the network, audit memories. laptop.open_url is never approved here (it would open a browser);
the test-only test.echo capability exercises execution. Only synthetic data."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
ROOT=Path(__file__).resolve().parents[1]
REL=ROOT/'build/engine/Release'
sys.path.insert(0,str(ROOT/'tests'))
from test_agent import Pipe
from test_mesh import Link,make_cert,pair_approved


class Actions(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.data=Path(self.tmp.name);self.name=f'lens-actions-{uuid.uuid4().hex[:8]}'
        config={'mesh_port':0,'mesh_bind':'127.0.0.1'}
        if 'expire' in self._testMethodName:config['action_expiry_seconds']=2  # short expiry for that test
        (self.data/'config.json').write_text(json.dumps(config),encoding='utf-8')
        self.agent=subprocess.Popen([str(REL/'lens-agent.exe'),'--data-dir',str(self.data),'--root',str(ROOT),'--pipe-name',self.name,'--test-capabilities'],
                                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.pipe=Pipe(self.name)

    def tearDown(self):
        self.pipe.ask({'op':'shutdown'});self.pipe.close();self.agent.wait(timeout=60);self.tmp.cleanup()

    def test_registry_and_validation(self):
        caps={c['id']:c for c in self.pipe.ask({'op':'action_capabilities'})['capabilities']}
        self.assertEqual(set(caps),{'laptop.open_url','laptop.remember','test.echo'})
        self.assertTrue(all(c['confirmation']=='required' for c in caps.values()))
        bad=[('laptop.open_url',{'url':'http://example.com'}),('laptop.open_url',{'url':'https://user@example.com/'}),
             ('laptop.open_url',{'url':'file:///C:/Windows/System32/cmd.exe'}),('laptop.open_url',{'url':'https://ex ample.com'}),
             ('laptop.remember',{'text':''}),('laptop.remember',{}),('shell.run',{'command':'calc'})]
        for cap,params in bad:
            r=self.pipe.ask({'op':'action_request','capability':cap,'params':params,'requested_by':'test'})
            self.assertFalse(r['ok'],(cap,params));self.assertIn(r['error'],('invalid_parameters','unknown_capability'))
        self.assertEqual(self.pipe.ask({'op':'action_pending'})['actions'],[])

    def test_nothing_runs_until_approved_and_audit_is_kept(self):
        r=self.pipe.ask({'op':'action_request','capability':'test.echo','params':{'message':'hello'},'requested_by':'test'})
        a=r['action'];self.assertEqual(a['status'],'pending_confirmation');self.assertNotIn('result',a)
        self.assertEqual([x['id'] for x in self.pipe.ask({'op':'action_pending'})['actions']],[a['id']])
        done=self.pipe.ask({'op':'action_decide','id':a['id'],'approve':True})['action']
        self.assertEqual(done['status'],'executed');self.assertTrue(done['result']['verified']);self.assertEqual(done['result']['echo'],'hello')
        self.assertEqual(self.pipe.ask({'op':'action_decide','id':a['id'],'approve':True})['error'],'already_decided')
        url=self.pipe.ask({'op':'action_request','capability':'laptop.open_url','params':{'url':'https://example.com/paper'},'requested_by':'test'})['action']
        denied=self.pipe.ask({'op':'action_decide','id':url['id'],'approve':False})['action'];self.assertEqual(denied['status'],'denied');self.assertNotIn('result',denied)
        note=self.pipe.ask({'op':'action_request','capability':'laptop.remember','params':{'text':'Synthetic: call the Kestrel venue on Monday.'},'requested_by':'test'})['action']
        self.assertEqual(self.pipe.ask({'op':'action_decide','id':note['id'],'approve':True})['action']['status'],'executed')
        self.assertEqual(self.pipe.ask({'op':'search','query':'Kestrel venue'})['sources'][0]['provenance'],'lens action '+note['id'])
        audit=self.pipe.ask({'op':'search','query':'denied'})['sources']
        self.assertTrue(any(s['kind']=='action_audit' and 'denied' in s['text'] for s in audit))

    def test_devices_can_request_but_never_approve(self):
        self.pipe.ask({'op':'set_consent','phone_link':True});qr=self.pipe.ask({'op':'mesh_pair_begin'})['qr']
        with tempfile.TemporaryDirectory() as certs:
            link=Link(qr['port'],qr['fp'],make_cert(Path(certs),'phone'));pair_approved(self.pipe,link,qr)
            r=link.ask({'op':'action_request','capability':'test.echo','params':{'message':'from phone'},'requested_by':'forged'})
            a=r['action'];self.assertEqual(a['requested_by'],'paired device Pixel');self.assertEqual(a['status'],'pending_confirmation')
            self.assertEqual(link.ask({'op':'action_decide','id':a['id'],'approve':True})['error'],'unsupported_operation')
            self.assertEqual(link.ask({'op':'action_status','id':a['id']})['action']['status'],'pending_confirmation')
            link.close()
        self.assertEqual(self.pipe.ask({'op':'action_decide','id':a['id'],'approve':True})['action']['status'],'executed')

    def test_undecided_requests_expire_and_cannot_be_approved_late(self):
        import time
        a=self.pipe.ask({'op':'action_request','capability':'test.echo','params':{'message':'stale'},'requested_by':'test'})['action']
        self.assertEqual(a['expires_in_seconds'],2);time.sleep(2.5)
        self.assertEqual(self.pipe.ask({'op':'action_pending'})['actions'],[])
        r=self.pipe.ask({'op':'action_decide','id':a['id'],'approve':True})
        self.assertEqual(r['error'],'action_expired');self.assertEqual(r['action']['status'],'expired');self.assertNotIn('result',r['action'])


if __name__=='__main__':unittest.main()
