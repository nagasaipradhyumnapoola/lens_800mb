"""Security tests (docs/LENS_V1_SPEC.md §17, Milestone 14): hostile input to the engine, the agent pipe and the device
link must never crash a process or corrupt memory, and the repository must hold no keys or personal databases."""
import json
from pathlib import Path
import random
import socket
import ssl
import subprocess
import sys
import tempfile
import unittest
import uuid
ROOT=Path(__file__).resolve().parents[1]
REL=ROOT/'build/engine/Release'
sys.path.insert(0,str(ROOT/'tests'))
from test_agent import Pipe
from test_mesh import Link,make_cert


def hostile_lines(rng,n):
    ops=['add','search','recall','delete','find_source','timeline','episodes','episode_context','consolidate','import_batch','index','stats','begin','commit',
         'rollback','train_text_dictionary','ingest_audio','unload_models','nope']
    values=[None,True,-1,0,2**63,1e308,'','x'*5000,'\u0000','\ud7ff\ue000','../../etc/passwd','C:\\Windows\\System32\\config\\SAM',[],{},[[[[[[]]]]]],
            '"; DROP TABLE observations; --',"' OR 1=1 --",'*','NEAR(','"unterminated','2026-13-45T99:99:99Z','\u202eevil']
    keys=['op','id','text','query','consent','timestamp','language','device','kind','provenance','limit','mode','records','audio','model','start','end',
          'metadata','source_id','samples','gap_seconds']
    for _ in range(n):
        r=rng.random()
        if r<0.15:yield ''.join(chr(rng.randrange(1,0x2fff)) for _ in range(rng.randrange(1,200)))
        elif r<0.2:yield '{'*rng.randrange(1,500)
        else:
            req={k:rng.choice(values) for k in rng.sample(keys,rng.randrange(1,8))}
            req['op']=rng.choice(ops) if rng.random()<0.9 else rng.choice(values)
            yield json.dumps(req)


class EngineHostileInput(unittest.TestCase):
    def test_engine_answers_every_hostile_line_and_keeps_its_data(self):
        rng=random.Random(20261027)
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'m.db';exe=str(REL/'lens-engine.exe')
            seed={'op':'add','consent':True,'id':'keep','text':'Synthetic canary memory: the Orchard key is green.','language':'en',
                  'timestamp':'2026-10-27T09:00:00Z','device':'t','kind':'note','provenance':'synthetic-test'}
            lines=[json.dumps(seed)]+list(hostile_lines(rng,600))+[json.dumps({'op':'search','query':'Orchard'})]
            p=subprocess.run([exe,'--db',str(db)],input='\n'.join(l.replace('\n',' ') for l in lines)+'\n',capture_output=True,text=True,encoding='utf-8',timeout=600)
            self.assertEqual(p.returncode,0,p.stderr[-500:])
            out=p.stdout.splitlines();self.assertEqual(len(out),len(lines))  # exactly one answer per line, no crash
            for l in out:json.loads(l)
            self.assertEqual(json.loads(out[-1])['sources'][0]['id'],'keep')
            again=subprocess.run([exe,'--db',str(db)],input=json.dumps({'op':'stats'})+'\n',capture_output=True,text=True,timeout=60)
            self.assertTrue(json.loads(again.stdout)['ok'])

    def test_oversized_request_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=subprocess.run([str(REL/'lens-engine.exe'),'--db',str(Path(tmp)/'m.db')],input='{"op":"stats","x":"'+'a'*(3*1024*1024)+'"}\n',
                             capture_output=True,text=True,timeout=120)
            self.assertIn('request_too_large',p.stdout)


class AgentAndLinkHostileInput(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.data=Path(self.tmp.name);self.name=f'lens-sec-{uuid.uuid4().hex[:8]}'
        (self.data/'config.json').write_text(json.dumps({'phone_link':True,'mesh_port':0,'mesh_bind':'127.0.0.1'}),encoding='utf-8')
        self.agent=subprocess.Popen([str(REL/'lens-agent.exe'),'--data-dir',str(self.data),'--root',str(ROOT),'--pipe-name',self.name],
                                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.pipe=Pipe(self.name)

    def tearDown(self):
        self.pipe.ask({'op':'shutdown'});self.pipe.close();self.agent.wait(timeout=60);self.tmp.cleanup()

    def test_agent_pipe_survives_garbage(self):
        rng=random.Random(7)
        for line in hostile_lines(rng,150):
            self.pipe.f.write((line.replace('\n',' ')+'\n').encode('utf-8','surrogatepass'))
            buf=self.pipe.buf
            while b'\n' not in buf:
                chunk=self.pipe.f.read(65536)
                if not chunk:self.fail(f'agent closed the pipe after: {line[:200]!r}')
                buf+=chunk
            resp,self.pipe.buf=buf.split(b'\n',1);json.loads(resp)
        self.assertTrue(self.pipe.ask({'op':'status'})['ok'])
        self.assertEqual(self.pipe.ask({'op':'set_consent','observe_screen':'yes'})['error'],'invalid_request')

    def test_link_survives_plaintext_probes_and_oversized_lines(self):
        qr=self.pipe.ask({'op':'mesh_pair_begin'})['qr']
        for probe in [b'GET / HTTP/1.1\r\nHost: x\r\n\r\n',b'\x16\x03\x01\x00\x05garbage',bytes(range(256))*20]:
            s=socket.create_connection(('127.0.0.1',qr['port']),timeout=10)
            try:
                s.sendall(probe);s.recv(4096)
            except OSError:pass
            s.close()
        with tempfile.TemporaryDirectory() as certs:
            stranger=Link(qr['port'],qr['fp'],make_cert(Path(certs),'stranger'))  # an unpaired peer sends hostile requests
            for line in hostile_lines(random.Random(11),120):
                stranger.s.sendall((line.replace('\n',' ')+'\n').encode('utf-8','surrogatepass'))
                while b'\n' not in stranger.buf:
                    chunk=stranger.s.recv(65536)
                    if not chunk:self.fail(f'link closed after: {line[:200]!r}')
                    stranger.buf+=chunk
                resp,stranger.buf=stranger.buf.split(b'\n',1);json.loads(resp)
            stranger.close()
            link=Link(qr['port'],qr['fp'],make_cert(Path(certs),'phone'));link.ask({'op':'pair','token':qr['token'],'name':'Fuzz'})
            buf=b''
            try:  # the service refuses the oversized line and closes; a reset while still sending is the same refusal
                link.s.sendall(b'{"op":"ping","x":"'+b'a'*(2*1024*1024)+b'"}\n')
                while b'\n' not in buf:
                    chunk=link.s.recv(65536)
                    if not chunk:break
                    buf+=chunk
            except (ConnectionResetError,ssl.SSLError):pass
            self.assertTrue(buf==b'' or b'request_too_large' in buf,buf[:200]);link.close()
            ok=Link(qr['port'],qr['fp'],make_cert(Path(certs),'phone'))  # different key: unpaired, but the service is still up
            self.assertEqual(ok.ask({'op':'ping'})['error'],'not_paired');ok.close()
        self.assertTrue(self.pipe.ask({'op':'status'})['mesh_running'])


class Repository(unittest.TestCase):
    def test_no_keys_or_databases_are_tracked(self):
        files=subprocess.run(['git','ls-files'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.splitlines()
        banned=[f for f in files if f.endswith(('.db','.db-wal','.key','.dpapi','.pem','.pfx','.p12','.jks','.keystore'))]
        self.assertEqual(banned,[])
        leaks=[]
        for f in files:
            p=ROOT/f
            if p.suffix.lower() in ('.png','.jar','.onnx','.bin','.pdiparams','.dll','.exe','.zip','.parquet') or not p.is_file() or p.stat().st_size>5_000_000:continue
            t=p.read_bytes()
            if b'-----BEGIN' in t and b'PRIVATE KEY-----' in t and 'test' not in f:leaks.append(f)
        self.assertEqual(leaks,[])


if __name__=='__main__':unittest.main()
