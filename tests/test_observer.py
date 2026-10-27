"""Milestone 3 observer: consent-gated UI Automation capture of a SYNTHETIC test window (never a user window: the
observer follows only the test app's process id). Test windows are fully transparent, click-through and never activated,
so nothing appears on, or takes input from, the user's screen. Checks capture, privacy exclusions, change detection, pause/resume and encrypted storage."""
import json
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time
import unittest
ROOT=Path(__file__).resolve().parents[1]
REL=ROOT/'build/engine/Release'
OBSERVER=REL/'lens-observer.exe';APP=REL/'lens-observer-testapp.exe';ENGINE=REL/'lens-engine.exe'
SECRET='synthetic-password-do-not-capture'


class Proc:
    def __init__(self,args,**kw):
        self.p=subprocess.Popen([str(a) for a in args],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                text=True,encoding='utf-8',bufsize=1,**kw)
        self.out=queue.Queue();self.err=queue.Queue()
        threading.Thread(target=self.pump,args=(self.p.stdout,self.out),daemon=True).start()
        threading.Thread(target=self.pump,args=(self.p.stderr,self.err),daemon=True).start()

    @staticmethod
    def pump(stream,q):
        for line in stream:q.put(line.rstrip('\n'))

    def send(self,line):self.p.stdin.write(line+'\n');self.p.stdin.flush()

    def lines(self,q,seconds):
        end=time.time()+seconds;out=[]
        while time.time()<end:
            try:out.append(q.get(timeout=max(0.01,end-time.time())))
            except queue.Empty:break
        return out

    def stop(self):
        if self.p.poll() is None:
            try:self.p.stdin.close()
            except OSError:pass
            try:self.p.wait(timeout=10)
            except subprocess.TimeoutExpired:self.p.kill();self.p.wait(timeout=10)
        for s in (self.p.stdin,self.p.stdout,self.p.stderr):
            try:s.close()
            except (OSError,ValueError):pass


class Observer(unittest.TestCase):
    def app(self,title='Lens observer test window',label='Synthetic label for the Lens observer test',
            body='Synthetic note: the quarterly review moved to Thursday.'):
        a=Proc([APP,'--invisible',title,label,body,SECRET]);self.addCleanup(a.stop)
        self.assertEqual(a.out.get(timeout=20),'ready');time.sleep(0.5);return a

    def observer(self,app,config=None,consent=True):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        cfg=Path(tmp.name)/'observer.json';cfg.write_text(json.dumps({'min_interval_ms':300,'max_interval_ms':1200,'device':'test-device',**(config or {})}),encoding='utf-8')
        args=[OBSERVER]+(['--consent'] if consent else [])+['--follow',f'pid:{app.p.pid}','--config',cfg]
        o=Proc(args);self.addCleanup(o.stop);return o

    def records(self,o,seconds):return [json.loads(x) for x in o.lines(o.out,seconds)]

    def test_test_window_is_invisible_and_never_takes_focus(self):
        import ctypes
        from ctypes import wintypes
        a=self.app();found=[]
        @ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        def visit(hwnd,_):
            pid=wintypes.DWORD();ctypes.windll.user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            if pid.value==a.p.pid and ctypes.windll.user32.IsWindowVisible(hwnd):found.append(hwnd)
            return True
        ctypes.windll.user32.EnumWindows(visit,0);self.assertEqual(len(found),1)
        alpha=ctypes.c_ubyte(255);flags=wintypes.DWORD(0)
        self.assertTrue(ctypes.windll.user32.GetLayeredWindowAttributes(found[0],None,ctypes.byref(alpha),ctypes.byref(flags)))
        self.assertEqual(alpha.value,0);self.assertNotEqual(ctypes.windll.user32.GetForegroundWindow(),found[0])

    def test_captures_window_text_but_never_password(self):
        a=self.app();o=self.observer(a);recs=self.records(o,4)
        self.assertGreaterEqual(len(recs),1)
        r=recs[0];self.assertEqual(r['op'],'add');self.assertTrue(r['consent'])
        self.assertIn('quarterly review moved to Thursday',r['text']);self.assertIn('Synthetic label',r['text'])
        self.assertEqual(r['kind'],'screen_observation');self.assertEqual(r['source_application'],'lens-observer-testapp.exe')
        self.assertEqual(r['metadata']['capture'],'uia');self.assertGreaterEqual(r['metadata']['password_elements_skipped'],1)
        for x in recs:self.assertNotIn(SECRET,json.dumps(x,ensure_ascii=False))
        self.assertNotIn(SECRET,'\n'.join(o.lines(o.err,0.5)))

    def test_unchanged_window_is_recorded_once_and_changes_are_recorded(self):
        a=self.app();o=self.observer(a)
        first=self.records(o,4);self.assertEqual(len(first),1,first)
        a.send('set Synthetic update: the launch is now on Friday.');changed=self.records(o,4)
        self.assertEqual(len(changed),1,changed);self.assertIn('launch is now on Friday',changed[0]['text'])
        self.assertNotEqual(first[0]['id'],changed[0]['id'])

    def test_script_language_label(self):
        a=self.app(body='सिंथेटिक नोट: तिमाही समीक्षा गुरुवार को है। यह परीक्षण पाठ है।',label='परीक्षण')
        recs=self.records(self.observer(a),4);self.assertEqual(recs[0]['language'],'hi')

    def test_excluded_process_is_never_read(self):
        a=self.app();o=self.observer(a,{'excluded_processes':['lens-observer-testapp.exe']})
        self.assertEqual(self.records(o,3),[]);o.send('status')
        status=[json.loads(x) for x in o.lines(o.err,2) if '"status"' in x]
        self.assertTrue(status and status[-1]['skipped'].get('excluded_process',0)>=1,status)

    def test_private_browsing_title_is_never_read(self):
        a=self.app(title='New tab - InPrivate - Microsoft Edge');self.assertEqual(self.records(self.observer(a),3),[])

    def test_capture_protected_window_is_never_read(self):
        a=self.app();a.send('protect');self.assertEqual(a.out.get(timeout=10),'ok')
        self.assertEqual(self.records(self.observer(a),3),[])

    def test_requires_consent(self):
        a=self.app();o=self.observer(a,consent=False)
        self.assertEqual(o.p.wait(timeout=10),2);self.assertEqual(self.records(o,0.5),[])

    def test_pause_and_resume(self):
        a=self.app();o=self.observer(a);self.assertEqual(len(self.records(o,3)),1)
        o.send('pause');time.sleep(0.5);a.send('set Synthetic paused text that must not be recorded.')
        self.assertEqual(self.records(o,3),[])
        o.send('resume');resumed=self.records(o,3)
        self.assertEqual(len(resumed),1);self.assertIn('must not be recorded',resumed[0]['text'])

    OCR={'runtime':str(ROOT/'.tools/ocr-runtime/onnxruntime.dll'),'detector':str(ROOT/'models/PaddlePaddle--PP-OCRv5_mobile_det/inference.onnx'),
         'route':'auto','threads':2,'recognizers':{'general':{'model':str(ROOT/'models/PaddlePaddle--PP-OCRv6_tiny_rec/inference.onnx'),
                                                              'dictionary':str(ROOT/'models/PaddlePaddle--PP-OCRv6_tiny_rec/ctc-dictionary.json')}}}

    def painted_app(self,text):
        a=Proc([APP,'--invisible','--paint',text,'Painted window']);self.addCleanup(a.stop)
        self.assertEqual(a.out.get(timeout=20),'ready');time.sleep(0.5);return a

    def test_ocr_fallback_reads_text_ui_automation_cannot_see(self):
        a=self.painted_app('Synthetic canvas note: invoice 7310 due Monday')
        recs=self.records(self.observer(a,{'ocr':self.OCR,'min_interval_ms':500,'max_interval_ms':2000}),15)
        self.assertTrue(recs,'no OCR record');r=recs[0]
        self.assertEqual(r['metadata']['capture'],'ocr');self.assertEqual(r['provenance'],'lens-observer ocr')
        self.assertIn('invoice 7310',r['text']);self.assertIsNone(r['metadata']['region'])

    def test_ocr_fallback_reads_only_the_changed_region_after_a_change(self):
        a=self.painted_app('Synthetic canvas note: invoice 7310 due Monday')
        o=self.observer(a,{'ocr':self.OCR,'min_interval_ms':500,'max_interval_ms':1000})
        first=self.records(o,15);self.assertEqual(len(first),1,first)
        a.send('set Synthetic canvas note: invoice 7310 due Friday');changed=self.records(o,15)
        self.assertEqual(len(changed),1,changed);self.assertIn('Friday',changed[0]['text'])
        self.assertIsNotNone(changed[0]['metadata']['region'])

    def test_ocr_worker_is_reused_then_released_when_idle(self):
        import psutil
        a=self.painted_app('Synthetic canvas note: invoice 7310 due Monday')
        o=self.observer(a,{'ocr':self.OCR,'min_interval_ms':500,'max_interval_ms':1000,'ocr_idle_ms':5000})
        self.assertIn('invoice',json.loads(o.out.get(timeout=20))['text'])
        workers=[c for c in psutil.Process(o.p.pid).children() if c.name().lower()=='lens-ocr.exe']
        self.assertEqual(len(workers),1,workers)
        a.send('set Synthetic canvas note: invoice 7310 due Friday');self.assertIn('Friday',json.loads(o.out.get(timeout=10))['text'])
        self.assertEqual([c.pid for c in psutil.Process(o.p.pid).children() if c.name().lower()=='lens-ocr.exe'],[workers[0].pid])
        a.stop();time.sleep(9)  # window gone: no OCR requests, so the worker must be released
        self.assertEqual([c for c in psutil.Process(o.p.pid).children() if c.name().lower()=='lens-ocr.exe'],[])

    def test_without_ocr_config_text_invisible_to_uia_is_not_captured(self):
        a=self.painted_app('Synthetic canvas note: invoice 7310 due Monday')
        for r in self.records(self.observer(a),4):self.assertNotIn('invoice',r['text'])

    def test_observations_are_stored_and_searchable_in_encrypted_memory(self):
        a=self.app(body='Synthetic memo: the vendor contract renewal is due on 14 November.')
        recs=self.records(self.observer(a),4);self.assertTrue(recs)
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'memory.db'
            proc=subprocess.run([str(ENGINE),'--db',str(db)],input=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in recs)+
                                json.dumps({'op':'search','query':'vendor contract renewal'})+'\n',encoding='utf-8',capture_output=True,timeout=60)
            rows=[json.loads(x) for x in proc.stdout.splitlines()]
            self.assertTrue(rows[0]['ok'],rows[0]);hit=rows[-1]['sources'][0]
            self.assertEqual(hit['id'],recs[0]['id']);self.assertIn('vendor contract renewal',hit['text'])
            self.assertNotIn(b'vendor contract renewal',db.read_bytes())


if __name__=='__main__':unittest.main()
