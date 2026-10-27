"""Milestone 12 paired-device link (lens-mesh via lens-agent): TLS 1.3 mutual authentication with pinned certificates,
one-time pairing tokens, allow-listed operations, phone contributions with forced provenance, revocation, and the
consent gate. Loopback only (no firewall prompt, nothing leaves the machine). Only synthetic data."""
import hashlib
import json
from pathlib import Path
import shutil
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
OPENSSL=shutil.which('openssl') or r'C:\Program Files\Git\mingw64\bin\openssl.exe'


def make_cert(folder,name):
    key,cert=folder/f'{name}.key',folder/f'{name}.pem'
    subprocess.run([OPENSSL,'req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256','-nodes','-keyout',str(key),'-out',str(cert),
                    '-days','1','-subj',f'/CN={name}'],check=True,capture_output=True)
    return cert,key


class Link:
    """A phone-side client: TLS 1.3, own certificate, laptop pinned by SHA-256 fingerprint."""
    def __init__(self,port,fingerprint,cert):
        ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT);ctx.minimum_version=ssl.TLSVersion.TLSv1_3
        ctx.check_hostname=False;ctx.verify_mode=ssl.CERT_NONE  # self-signed: authenticated by the pin below
        if cert:ctx.load_cert_chain(*cert)
        self.s=ctx.wrap_socket(socket.create_connection(('127.0.0.1',port),timeout=30))
        got=hashlib.sha256(self.s.getpeercert(binary_form=True)).hexdigest()
        if got!=fingerprint:raise ssl.SSLError('laptop certificate does not match the pairing code')
        self.buf=b''

    def ask(self,req):
        self.s.sendall((json.dumps(req)+'\n').encode())
        while b'\n' not in self.buf:
            chunk=self.s.recv(65536)
            if not chunk:raise ConnectionError('closed')
            self.buf+=chunk
        line,self.buf=self.buf.split(b'\n',1);return json.loads(line)

    def close(self):self.s.close()


class Mesh(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.data=Path(self.tmp.name);self.name=f'lens-mesh-test-{uuid.uuid4().hex[:8]}'
        (self.data/'config.json').write_text(json.dumps({'mesh_port':0,'mesh_bind':'127.0.0.1'}),encoding='utf-8')
        self.agent=subprocess.Popen([str(REL/'lens-agent.exe'),'--data-dir',str(self.data),'--root',str(ROOT),'--pipe-name',self.name],
                                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.pipe=Pipe(self.name)
        self.pipe.ask({'op':'add','consent':True,'id':'laptop-1','text':'Synthetic memo: the Halvorsen contract renewal is due on 14 November.',
                       'language':'en','timestamp':'2026-10-27T09:00:00Z','device':'laptop','kind':'screen_observation','provenance':'synthetic-test'})
        self.certs=Path(self.tmp.name)/'certs';self.certs.mkdir()

    def tearDown(self):
        self.pipe.ask({'op':'shutdown'});self.pipe.close();self.agent.wait(timeout=30);self.tmp.cleanup()

    def pair_code(self):
        r=self.pipe.ask({'op':'mesh_pair_begin'});self.assertTrue(r['ok'],r);return r['qr']

    def test_link_is_off_without_consent(self):
        self.assertEqual(self.pipe.ask({'op':'mesh_pair_begin'})['error'],'phone_link_off')
        self.assertFalse(self.pipe.ask({'op':'status'})['mesh_running'])

    def test_pairing_recall_contribution_and_revocation(self):
        self.assertTrue(self.pipe.ask({'op':'set_consent','phone_link':True})['phone_link'])
        qr=self.pair_code();phone=make_cert(self.certs,'phone')
        link=Link(qr['port'],qr['fp'],phone)
        self.assertEqual(link.ask({'op':'recall','query':'Halvorsen'})['error'],'not_paired')
        self.assertEqual(link.ask({'op':'pair','token':'0'*32,'name':'Pixel'})['error'],'pairing_refused')
        r=link.ask({'op':'pair','token':qr['token'],'name':'Pixel'});self.assertTrue(r['paired']);self.assertEqual(r['laptop_fingerprint'],qr['fp'])
        hit=link.ask({'op':'search','query':'Halvorsen'})['sources'][0];self.assertEqual(hit['id'],'laptop-1')
        self.assertEqual(link.ask({'op':'delete','consent':True,'id':'laptop-1'})['error'],'unsupported_operation')
        self.assertEqual(link.ask({'op':'set_consent','observe_screen':True})['error'],'unsupported_operation')
        add={'op':'add','consent':True,'id':'phone-1','text':'Synthetic phone note: call Ana about the venue.','language':'en',
             'timestamp':'2026-10-27T10:00:00Z','device':'laptop','kind':'note','provenance':'forged','source_application':'forged'}
        self.assertTrue(link.ask(add)['ok'])
        self.assertEqual(link.ask({**add,'id':'phone-2','kind':'screen_observation'})['error'],'not_allowed')
        src=self.pipe.ask({'op':'find_source','id':'phone-1'})['source']
        self.assertEqual(src['device'],'Pixel');self.assertTrue(src['provenance'].startswith('lens-mesh paired device'))
        self.assertEqual(src['source_application'],'lens-companion');self.assertEqual(src['consent_context']['mode'],'paired_device')
        link.close()
        again=Link(qr['port'],qr['fp'],phone);self.assertTrue(again.ask({'op':'ping'})['ok'])  # paired across connections
        self.assertEqual(again.ask({'op':'pair','token':qr['token'],'name':'Other'})['error'],'pairing_refused')  # token single-use
        again.close()
        stranger=Link(qr['port'],qr['fp'],make_cert(self.certs,'stranger'));self.assertEqual(stranger.ask({'op':'ping'})['error'],'not_paired');stranger.close()
        devices=self.pipe.ask({'op':'mesh_devices'})['devices'];self.assertEqual([d['name'] for d in devices],['Pixel'])
        self.assertTrue(self.pipe.ask({'op':'mesh_unpair','fingerprint':devices[0]['fingerprint']})['removed'])
        revoked=Link(qr['port'],qr['fp'],phone);self.assertEqual(revoked.ask({'op':'ping'})['error'],'not_paired');revoked.close()

    def test_client_without_certificate_and_wrong_pin_are_refused(self):
        self.pipe.ask({'op':'set_consent','phone_link':True});qr=self.pair_code()
        with self.assertRaises((ssl.SSLError,ConnectionError,OSError)):
            link=Link(qr['port'],qr['fp'],None);link.ask({'op':'ping'})
        with self.assertRaises(ssl.SSLError):Link(qr['port'],'0'*64,make_cert(self.certs,'phone'))
        key=self.data/'mesh'/'identity.dpapi';self.assertTrue(key.exists());self.assertNotIn(b'PRIVATE KEY',key.read_bytes())


if __name__=='__main__':unittest.main()
