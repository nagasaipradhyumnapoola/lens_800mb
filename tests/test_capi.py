"""The C API of the iPhone app (adapters/capi/lens.h), exercised through lens-capi.dll on Windows: the memory core in the
app's process, and the device side of the Lens link against the real lens-mesh (pairing with laptop approval, pinned
laptop certificate, recall of laptop memory, phone notes). Loopback only; synthetic data only."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
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


def load():
    for d in (REL,ROOT/'third_party/vcpkg/installed/x64-windows/bin'):
        if d.is_dir():os.add_dll_directory(str(d))
    lib=ctypes.CDLL(str(REL/'lens-capi.dll'))
    P,S,I=ctypes.c_void_p,ctypes.c_char_p,ctypes.c_int
    for name,res,args in [('lens_store_open',P,[S,S,ctypes.POINTER(P)]),('lens_store_request',P,[P,S]),('lens_store_close',None,[P]),
                          ('lens_link_identity',I,[ctypes.POINTER(P)]*3),('lens_link_fingerprint',P,[S]),
                          ('lens_link_connect',P,[S,I,S,S,S,I,ctypes.POINTER(P)]),('lens_link_ask',P,[P,S]),('lens_link_close',None,[P]),
                          ('lens_free',None,[P])]:
        f=getattr(lib,name);f.restype=res;f.argtypes=args
    return lib


class Api:
    def __init__(self):self.lib=load()

    def text(self,p):
        if not p:return None
        try:return ctypes.string_at(p).decode('utf-8')
        finally:self.lib.lens_free(p)

    def open(self,db,models='{}'):
        err=ctypes.c_void_p();h=self.lib.lens_store_open(str(db).encode(),models.encode(),ctypes.byref(err));return h,self.text(err.value)

    def request(self,h,req):return json.loads(self.text(self.lib.lens_store_request(h,json.dumps(req).encode())))

    def identity(self):
        k,c,f=ctypes.c_void_p(),ctypes.c_void_p(),ctypes.c_void_p()
        assert self.lib.lens_link_identity(ctypes.byref(k),ctypes.byref(c),ctypes.byref(f))==0
        return self.text(k.value),self.text(c.value),self.text(f.value)

    def connect(self,hosts,port,fp,key,cert,timeout=5000):
        err=ctypes.c_void_p()
        h=self.lib.lens_link_connect(json.dumps(hosts).encode(),port,fp.encode(),key.encode(),cert.encode(),timeout,ctypes.byref(err))
        return h,self.text(err.value)

    def ask(self,h,req):return json.loads(self.text(self.lib.lens_link_ask(h,json.dumps(req).encode())))


NOTE={'op':'add','consent':True,'id':'phone-1','text':'Synthetic note: the Orsolya lantern workshop moved to Thursday at 6 pm.',
      'language':'en','timestamp':'2026-11-02T09:00:00Z','kind':'note','device':'phone','provenance':'lens-companion',
      'source_application':'Lens','consent_context':{'mode':'explicit_user_note'}}


@unittest.skipUnless((REL/'lens-capi.dll').exists(),'lens-capi.dll not built')
class Store(unittest.TestCase):
    def test_memory_in_the_app_process(self):
        api=Api()
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'memory.db'
            h,err=api.open(db);self.assertTrue(h,err)
            self.assertTrue(api.request(h,NOTE)['ok'])
            hit=api.request(h,{'op':'recall','query':'lantern workshop','mode':'keyword','limit':5})
            self.assertFalse(hit.get('not_found'),hit);self.assertEqual(hit['results'][0]['source']['id'],'phone-1')
            self.assertEqual(api.request(h,{'op':'no_such_op'})['ok'],False)
            self.assertEqual(json.loads(api.text(api.lib.lens_store_request(h,b'{not json')))['error'],'invalid_request')
            api.lib.lens_store_close(h)
            h,err=api.open(db);self.assertTrue(h,err)  # reopens with the same wrapped key; the note survived
            self.assertEqual(api.request(h,{'op':'find_source','id':'phone-1'})['source']['id'],'phone-1')
            self.assertTrue(b'Orsolya' not in db.read_bytes())  # encrypted at rest
            api.lib.lens_store_close(h)
            h,err=api.open(db,json.dumps({'embedding_model':'x.onnx'}));self.assertFalse(h);self.assertEqual(err,'invalid_model_configuration')
            self.assertEqual(json.loads(api.text(api.lib.lens_store_request(None,b'{}')))['error'],'store_closed')

    def test_device_identity(self):
        api=Api();key,cert,fp=api.identity()
        self.assertIn('PRIVATE KEY',key);self.assertEqual(fp,hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert)).hexdigest())
        self.assertEqual(api.text(api.lib.lens_link_fingerprint(cert.encode())),fp)
        self.assertIsNone(api.text(api.lib.lens_link_fingerprint(b'not a certificate')))
        self.assertNotEqual(api.identity()[2],fp)  # a new identity each time


@unittest.skipUnless((REL/'lens-capi.dll').exists() and (REL/'lens-mesh.exe').exists(),'lens-capi.dll or lens-mesh.exe not built')
class Link(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.data=Path(self.tmp.name);self.name=f'lens-capi-test-{uuid.uuid4().hex[:8]}'
        (self.data/'config.json').write_text(json.dumps({'mesh_port':0,'mesh_bind':'127.0.0.1'}),encoding='utf-8')
        self.agent=subprocess.Popen([str(REL/'lens-agent.exe'),'--data-dir',str(self.data),'--root',str(ROOT),'--pipe-name',self.name],
                                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.pipe=Pipe(self.name)
        self.pipe.ask({'op':'add','consent':True,'id':'laptop-1','text':'Synthetic memo: the Halvorsen contract renewal is due on 14 November.',
                       'language':'en','timestamp':'2026-10-27T09:00:00Z','device':'laptop','kind':'screen_observation','provenance':'synthetic-test'})
        self.assertTrue(self.pipe.ask({'op':'set_consent','phone_link':True})['phone_link'])

    def tearDown(self):
        self.pipe.ask({'op':'shutdown'});self.pipe.close();self.agent.wait(timeout=30);self.tmp.cleanup()

    def test_pair_with_approval_then_recall_and_note(self):
        api=Api();key,cert,phone_fp=api.identity()
        qr=self.pipe.ask({'op':'mesh_pair_begin'})['qr']
        h,err=api.connect(['127.0.0.1'],qr['port'],'0'*64,key,cert);self.assertFalse(h);self.assertEqual(err,'laptop_mismatch')
        with socket.socket() as s:s.bind(('127.0.0.1',0));closed=s.getsockname()[1]
        h,err=api.connect(['127.0.0.1'],closed,qr['fp'],key,cert,1000);self.assertFalse(h);self.assertEqual(err,'laptop_unreachable')
        h,err=api.connect(['127.0.0.1'],qr['port'],qr['fp'],'junk','junk');self.assertFalse(h);self.assertEqual(err,'identity_unreadable')
        h,err=api.connect(['192.0.2.1','127.0.0.1'],qr['port'],qr['fp'].upper(),key,cert,1000);self.assertTrue(h,err)  # first address unreachable
        self.assertEqual(api.ask(h,{'op':'recall','query':'Halvorsen'})['error'],'not_paired')
        r=api.ask(h,{'op':'pair','token':qr['token'],'name':'iPhone'});self.assertTrue(r['awaiting_approval'],r)
        v=int.from_bytes(hashlib.sha256(f"{qr['fp']}:{phone_fp}".encode()).digest()[:4],'big')%100000000
        self.assertEqual(r['verification_code'],f'{v//10000:04d} {v%10000:04d}')  # the phone shows the laptop's code
        self.assertEqual([p['fingerprint'] for p in self.pipe.ask({'op':'mesh_pending'})['pending']],[phone_fp])
        self.assertTrue(self.pipe.ask({'op':'mesh_approve','fingerprint':phone_fp})['paired'])
        st=api.ask(h,{'op':'pair_status'});self.assertTrue(st['paired']);self.assertRegex(st['account_id'],'^[0-9a-f]{32}$')
        hit=api.ask(h,{'op':'search','query':'Halvorsen'});self.assertEqual(hit['sources'][0]['id'],'laptop-1')
        self.assertTrue(api.ask(h,{**NOTE,'id':'iphone-1'})['ok'])
        self.assertEqual(self.pipe.ask({'op':'find_source','id':'iphone-1'})['source']['device'],'iPhone')
        self.assertEqual(json.loads(api.text(api.lib.lens_link_ask(h,b'{"op":"ping"}\n{"op":"delete"}')))['error'],'invalid_request')
        api.lib.lens_link_close(h)
        h,err=api.connect(['127.0.0.1'],qr['port'],qr['fp'],key,cert);self.assertTrue(h,err)  # paired across connections
        self.assertTrue(api.ask(h,{'op':'ping'})['ok'])
        self.assertTrue(self.pipe.ask({'op':'mesh_unpair','fingerprint':phone_fp})['removed'])
        self.assertEqual(api.ask(h,{'op':'ping'})['error'],'not_paired')
        api.lib.lens_link_close(h)


if __name__=='__main__':unittest.main()
