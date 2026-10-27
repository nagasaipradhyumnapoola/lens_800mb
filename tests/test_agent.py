"""lens-agent: the always-on background process. Talks to it over its named pipe exactly as the app will. The observer
is pointed at an invisible synthetic window (never the user's screen). Only synthetic test data."""
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import uuid
ROOT=Path(__file__).resolve().parents[1]
REL=ROOT/'build/engine/Release'


class Pipe:
    def __init__(self,name,timeout=30):
        end=time.time()+timeout
        while True:
            try:self.f=open(rf'\\.\pipe\{name}','r+b',buffering=0);break
            except OSError:
                if time.time()>end:raise
                time.sleep(0.2)
        self.buf=b''

    def ask(self,req):
        self.f.write((json.dumps(req,ensure_ascii=False)+'\n').encode());
        while b'\n' not in self.buf:
            chunk=self.f.read(65536)
            if not chunk:raise ConnectionError('agent closed the pipe')  # never spin on a dead peer
            self.buf+=chunk
        line,self.buf=self.buf.split(b'\n',1);return json.loads(line)

    def close(self):self.f.close()


class Agent(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.data=Path(self.tmp.name);self.name=f'lens-test-{uuid.uuid4().hex[:10]}'
        self.app=subprocess.Popen([str(REL/'lens-observer-testapp.exe'),'--invisible','Agent test window','Synthetic label',
                                   'Synthetic agent note: the Halvorsen review is on Friday.'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
        assert self.app.stdout.readline().strip()=='ready'
        (self.data/'config.json').write_text(json.dumps({'observer':{'min_interval_ms':300,'max_interval_ms':1000}}),encoding='utf-8')
        self.agent=subprocess.Popen([str(REL/'lens-agent.exe'),'--data-dir',str(self.data),'--root',str(ROOT),'--pipe-name',self.name,
                                     '--observer-follow',f'pid:{self.app.pid}'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
        self.pipe=Pipe(self.name)

    def tearDown(self):
        try:self.pipe.ask({'op':'shutdown'});self.pipe.close()
        except OSError:pass
        try:self.agent.wait(timeout=30)
        except subprocess.TimeoutExpired:self.agent.kill();self.agent.wait()
        self.agent.stderr.close()
        self.app.stdin.write('quit\n');self.app.stdin.flush();self.app.wait(timeout=10);self.app.stdout.close();self.app.stdin.close()
        self.tmp.cleanup()

    def test_status_passthrough_and_rejection(self):
        s=self.pipe.ask({'op':'status'})
        self.assertTrue(s['ok']);self.assertEqual(s['semantic'],'verified');self.assertFalse(s['observe_screen']);self.assertFalse(s['observer_running'])
        add={'op':'add','consent':True,'id':'m1','text':'Synthetic memo: Brightwater invoice 5521 approved.','language':'en',
             'timestamp':'2026-10-27T10:00:00Z','device':'test','kind':'note','provenance':'synthetic-test'}
        self.assertTrue(self.pipe.ask(add)['ok'])
        self.assertEqual(self.pipe.ask({'op':'search','query':'Brightwater'})['sources'][0]['id'],'m1')
        self.assertEqual(self.pipe.ask({'op':'train_text_dictionary'})['error'],'unsupported_operation')
        self.assertEqual(self.pipe.ask({'op':'set_consent'})['error'],'invalid_request')

    def test_observation_requires_consent_and_follows_it(self):
        time.sleep(2);self.assertEqual(self.pipe.ask({'op':'status'})['observed'],0)  # no consent: nothing observed
        self.assertTrue(self.pipe.ask({'op':'set_consent','observe_screen':True})['observe_screen'])
        end=time.time()+20
        while time.time()<end and self.pipe.ask({'op':'status'})['stored']<1:time.sleep(0.5)
        s=self.pipe.ask({'op':'status'});self.assertTrue(s['observer_running']);self.assertGreaterEqual(s['stored'],1)
        hit=self.pipe.ask({'op':'search','query':'Halvorsen review'})['sources'][0]
        self.assertEqual(hit['kind'],'screen_observation');self.assertIn('Halvorsen',hit['text'])
        self.assertTrue(self.pipe.ask({'op':'pause'})['paused'])
        self.assertFalse(self.pipe.ask({'op':'set_consent','observe_screen':False})['observe_screen'])
        self.assertFalse(self.pipe.ask({'op':'status'})['observer_running'])
        self.assertFalse(json.loads((self.data/'config.json').read_text(encoding='utf-8'))['observe_screen'])
        self.assertNotIn(b'Halvorsen',(self.data/'memory.db').read_bytes())

    def test_single_instance(self):
        second=subprocess.run([str(REL/'lens-agent.exe'),'--data-dir',str(self.data),'--root',str(ROOT),'--pipe-name',self.name],
                              capture_output=True,text=True,timeout=30)
        self.assertEqual(second.returncode,3);self.assertIn('already_running',second.stderr)


if __name__=='__main__':unittest.main()
