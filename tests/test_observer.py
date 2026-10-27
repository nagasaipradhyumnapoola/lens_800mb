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
        cfg=Path(tmp.name)/'observer.json'
        cfg.write_text(json.dumps({'min_interval_ms':300,'max_interval_ms':1200,'settle_ms':600,'max_settle_ms':3000,'device':'test-device',**(config or {})}),encoding='utf-8')
        args=[OBSERVER]+(['--consent'] if consent else [])+['--follow',f'pid:{app.p.pid}','--config',cfg]
        o=Proc(args);self.addCleanup(o.stop);return o

    def records(self,o,seconds):return [json.loads(x) for x in o.lines(o.out,seconds)]

    def wait(self,o,n=1,timeout=25,quiet=1.5):
        # Waits for n records (the observer can start slowly on a loaded machine), then collects for `quiet` seconds.
        out=[];end=time.time()+timeout
        while len(out)<n and time.time()<end:
            try:out.append(json.loads(o.out.get(timeout=max(0.01,end-time.time()))))
            except queue.Empty:break
        return out+self.records(o,quiet)

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
        a=self.app();o=self.observer(a);recs=self.wait(o,timeout=25)
        self.assertGreaterEqual(len(recs),1)
        r=recs[0];self.assertEqual(r['op'],'add');self.assertTrue(r['consent'])
        self.assertIn('quarterly review moved to Thursday',r['text']);self.assertIn('Synthetic label',r['text'])
        self.assertEqual(r['kind'],'screen_observation');self.assertEqual(r['source_application'],'lens-observer-testapp.exe')
        self.assertEqual(r['metadata']['capture'],'uia');self.assertGreaterEqual(r['metadata']['password_elements_skipped'],1)
        for x in recs:self.assertNotIn(SECRET,json.dumps(x,ensure_ascii=False))
        self.assertNotIn(SECRET,'\n'.join(o.lines(o.err,0.5)))

    def test_unchanged_window_is_recorded_once_and_changes_are_recorded(self):
        a=self.app();o=self.observer(a)
        first=self.wait(o,timeout=25);self.assertEqual(len(first),1,first)
        a.send('set Synthetic update: the launch is now on Friday.');changed=self.wait(o,timeout=25)
        self.assertEqual(len(changed),1,changed);self.assertIn('launch is now on Friday',changed[0]['text'])
        self.assertNotEqual(first[0]['id'],changed[0]['id'])

    def test_script_language_label(self):
        a=self.app(body='सिंथेटिक नोट: तिमाही समीक्षा गुरुवार को है। यह परीक्षण पाठ है।',label='परीक्षण')
        recs=self.wait(self.observer(a),timeout=25);self.assertEqual(recs[0]['language'],'hi')

    def test_latin_text_gets_a_language_not_und(self):
        a=self.app(title='Notas sintéticas',label='Nota de prueba',body='La reunión trimestral se pasó al jueves y todos los equipos están de acuerdo.')
        r=self.wait(self.observer(a),timeout=25)[0];self.assertEqual(r['language'],'es',r['metadata']['language_detail'])
        self.assertEqual(r['metadata']['language_detail']['method'],'lens-lid-rules-v1')
        r=self.wait(self.observer(self.app()),timeout=25)[0];self.assertEqual(r['language'],'en',r['metadata']['language_detail'])

    LID_CASES=[  # synthetic sentences written for this test (no personal or copied content)
        ('en','The quarterly review moved to Thursday and the team will send the notes after the meeting.'),
        ('es','La reunión trimestral se pasó al jueves y el equipo enviará las notas después.'),
        ('fr','La réunion trimestrielle est déplacée à jeudi et nous enverrons les notes avec le compte rendu.'),
        ('pt','A reunião trimestral foi para quinta e a equipe vai enviar as notas depois, não hoje.'),
        ('de','Die Besprechung wurde auf Donnerstag verschoben und wir schicken die Notizen danach.'),
        ('id','Rapat kuartalan dipindahkan ke hari Kamis dan kami akan mengirim catatan setelah itu.'),
        ('hi-Latn','kal ki meeting nahi hogi, aap mujhe bata dena kya plan hai aur kab milna hai'),
        ('ta-Latn','naan inniki romba busy, naalaikku paakalam, enna sollunga, seri thaan'),
        ('te-Latn','nenu ippudu office lo unnanu, repu kaluddam, meeru ela unnaru, chala pani undi'),
        ('hi','सिंथेटिक नोट: तिमाही समीक्षा गुरुवार को है और यह परीक्षण पाठ है।'),
        ('mr','उद्या गुरुवारी बैठक आहे आणि मी नोंदी पाठवणार आहे, काळजी करू नका.'),
        ('bn','ত্রৈমাসিক পর্যালোচনা বৃহস্পতিবারে সরানো হয়েছে।'),
        ('te','త్రైమాసిక సమీక్ష గురువారానికి మార్చబడింది.'),
        ('ta','காலாண்டு மதிப்பாய்வு வியாழக்கிழமைக்கு மாற்றப்பட்டது.'),
        ('gu','ત્રિમાસિક સમીક્ષા ગુરુવારે ખસેડવામાં આવી છે.'),
        ('ur','سہ ماہی جائزہ جمعرات کو منتقل کر دیا گیا ہے اور ٹیم نوٹس بھیجے گی۔'),
        ('ar','تم نقل المراجعة الفصلية إلى يوم الخميس وسيرسل الفريق الملاحظات.'),
        ('ru','Квартальный обзор перенесли на четверг, команда пришлёт заметки.'),
        ('zh','季度评审改到星期四，团队会在会后发送笔记。'),
        ('ja','四半期レビューは木曜日に移動しました。チームはメモを送ります。'),
    ]

    def identify(self,texts):
        p=subprocess.run([str(OBSERVER),'--identify-language'],input=''.join(json.dumps({'text':t},ensure_ascii=False)+'\n' for t in texts),
                         capture_output=True,encoding='utf-8',timeout=30)
        self.assertEqual(p.returncode,0,p.stderr);return [json.loads(x) for x in p.stdout.splitlines()]

    def test_language_identification_covers_scripts_and_romanized_text(self):
        got=self.identify([t for _,t in self.LID_CASES])
        wrong=[(want,g) for (want,_),g in zip(self.LID_CASES,got) if g['language']!=want]
        self.assertEqual(wrong,[])

    def test_language_identification_marks_code_switching_as_mixed(self):
        got=self.identify(['yaar the meeting is tomorrow, kya tum notes bhej doge? main abhi busy hoon but will reply after the call',
                           'आज की meeting cancel हो गई है, please send the updated notes to the whole team before Friday'])
        for g in got:self.assertEqual(g['language'],'mixed',g);self.assertEqual(len(g['languages']),2,g)
        self.assertEqual(set(got[0]['languages']),{'en','hi-Latn'});self.assertEqual(set(got[1]['languages']),{'hi','en'})
        self.assertEqual([g['language'] for g in self.identify(['12345 -- ##',''])],['und','und'])

    # Visible text only (real-screen fix 1): no scroll-back, no off-screen elements, capped with a truncation flag.
    def test_scrollback_of_a_long_edit_box_is_not_captured(self):
        a=self.app();a.send('fill 400 Synthetic history line');self.assertEqual(a.out.get(timeout=10),'ok')
        r=self.wait(self.observer(a),timeout=25)[0]
        self.assertIn('Synthetic history line 400',r['text'])
        self.assertNotIn('Synthetic history line 1\n',r['text']+'\n');self.assertNotIn('Synthetic history line 200\n',r['text'])
        self.assertLess(r['text'].count('Synthetic history line'),40,r['text'])

    def test_offscreen_and_clipped_elements_are_not_captured(self):
        a=self.app();a.send('offscreen Synthetic offscreen marker');self.assertEqual(a.out.get(timeout=10),'ok')
        a.send('panel 60 Synthetic chat message');self.assertEqual(a.out.get(timeout=10),'ok')
        r=self.wait(self.observer(a),timeout=25)[0];t=r['text']+'\n'
        self.assertIn('Synthetic chat message 60\n',t);self.assertIn('quarterly review',t)
        self.assertNotIn('offscreen marker',t);self.assertNotIn('Synthetic chat message 1\n',t);self.assertNotIn('Synthetic chat message 30\n',t)
        self.assertLessEqual(t.count('Synthetic chat message'),4,t);self.assertGreater(r['metadata']['offscreen_elements'],50)

    def test_capture_is_capped_and_truncation_recorded(self):
        long_line=' '.join(['Synthetic visible words']*30)
        a=self.app(body='\\n'.join([long_line]*6))
        r=self.wait(self.observer(a,{'max_capture_chars':300}),timeout=25)[0]
        self.assertLessEqual(len(r['text'].encode('utf-8')),300);self.assertTrue(r['metadata']['truncated'])
        r=self.wait(self.observer(self.app()),timeout=25)[0];self.assertFalse(r['metadata']['truncated'])

    # Settle / debounce (real-screen fix 2).
    def test_streaming_text_is_captured_once_after_it_settles(self):
        a=self.app();o=self.observer(a,{'settle_ms':1500,'max_settle_ms':20000})
        self.assertEqual(len(self.wait(o,timeout=25)),1)
        for i in range(12):
            a.send(f'append Synthetic streamed sentence number {i} about the launch plan');a.out.get(timeout=10);time.sleep(0.35)
        during=self.records(o,0.2);self.assertEqual(during,[],'captured while text was still streaming')
        after=self.wait(o,timeout=25);self.assertEqual(len(after),1,after)
        self.assertIn('streamed sentence number 11',after[0]['text']);self.assertEqual(after[0]['metadata']['capture_mode'],'delta')
        self.assertNotIn('streamed sentence number 0 ',after[0]['text'])  # scrolled out of the visible area by the time it settled

    def test_text_that_never_settles_is_captured_within_the_bound_and_backs_off(self):
        a=self.app();o=self.observer(a,{'settle_ms':1500,'max_settle_ms':2500})
        self.assertEqual(len(self.wait(o,timeout=25)),1)
        got=[];end=time.time()+12;i=0
        while time.time()<end:
            a.send(f'append Synthetic ticker update {i} for the streaming window');a.out.get(timeout=10);i+=1
            got+=self.records(o,0.3)
        self.assertGreaterEqual(len(got),1,'bounded delay never captured');self.assertLessEqual(len(got),4,got)  # back-off: not every poll
        o.send('status');st=[json.loads(x) for x in o.lines(o.err,2) if '"status"' in x][-1]
        self.assertGreaterEqual(st['counts'].get('forced_captures',0),1,st)

    # Delta storage and near-duplicate suppression (real-screen fix 3).
    def test_delta_stores_only_new_lines_linked_to_the_previous_capture(self):
        a=self.app(body='Synthetic agenda item one about budgets\\nSynthetic agenda item two about hiring')
        o=self.observer(a);first=self.wait(o,timeout=25);self.assertEqual(len(first),1,first);first=first[0]
        self.assertEqual(first['metadata']['capture_mode'],'snapshot');self.assertEqual(first['metadata']['snapshot_reason'],'first')
        a.send('append Synthetic agenda item three about the vendor contract');a.out.get(timeout=10)
        d=self.wait(o,timeout=25);self.assertEqual(len(d),1,d);d=d[0];m=d['metadata']
        self.assertEqual(m['capture_mode'],'delta');self.assertEqual(m['previous_capture'],first['id']);self.assertEqual(m['base_snapshot'],first['id'])
        self.assertEqual(m['window_key'],first['metadata']['window_key'])
        self.assertIn('item three about the vendor contract',d['text']);self.assertNotIn('item one',d['text']);self.assertNotIn('Synthetic label',d['text'])
        self.assertEqual(m['lines_new'],1)

    def test_near_duplicate_rerender_and_tiny_delta_are_not_stored(self):
        lines=[f'Synthetic dashboard row {i} with a stable value' for i in range(9)]  # all visible: the edit shows ~10 lines
        a=self.app(body='\\n'.join(lines+['Status 1']));o=self.observer(a);self.assertEqual(len(self.wait(o,timeout=25)),1)
        a.send('set '+'\\n'.join(lines+['Status 2']));a.out.get(timeout=10)  # a re-render: one short line changed
        self.assertEqual(self.records(o,4),[])
        a.send('set '+'\\n'.join(lines[:8]+['Status 2','Synthetic new row: the supplier confirmed delivery for next Tuesday morning at nine']));a.out.get(timeout=10)
        d=self.wait(o,timeout=25);self.assertEqual(len(d),1,d);self.assertIn('supplier confirmed delivery',d[0]['text'])
        o.send('status');st=[json.loads(x) for x in o.lines(o.err,2) if '"status"' in x][-1]
        self.assertGreaterEqual(st['counts'].get('near_duplicates',0),1,st)

    def test_document_change_takes_a_full_snapshot(self):
        a=self.app();o=self.observer(a);first=self.wait(o,timeout=25)[0]
        a.send('title Synthetic second document');a.out.get(timeout=10)
        s=self.wait(o,timeout=25);self.assertEqual(len(s),1,s);m=s[0]['metadata']
        self.assertEqual(m['capture_mode'],'snapshot');self.assertEqual(m['snapshot_reason'],'document_changed')
        self.assertIn('quarterly review',s[0]['text']);self.assertEqual(m['previous_capture'],first['id'])

    # CPU budget (real-screen fix 5): the observer itself stays well under 10% of one core on a streaming window.
    def test_observer_cpu_stays_low_on_a_streaming_window(self):
        import psutil
        a=self.app();a.send('fill 400 Synthetic history line');a.out.get(timeout=10)
        o=self.observer(a,{'min_interval_ms':1000,'max_interval_ms':8000,'settle_ms':2000,'max_settle_ms':12000})
        proc=psutil.Process(o.p.pid);time.sleep(3);c0=sum(proc.cpu_times()[:2]);t0=time.time()
        end=t0+20;i=0
        while time.time()<end:
            a.send(f'append Synthetic streamed token {i}');a.out.get(timeout=10);i+=1;time.sleep(0.25)
        cpu=100*(sum(proc.cpu_times()[:2])-c0)/(time.time()-t0)
        print(f'observer CPU {cpu:.2f}% of one core over {time.time()-t0:.1f} s of streaming')
        self.assertLess(cpu,10.0)

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
        a=self.app();o=self.observer(a);self.assertEqual(len(self.wait(o,timeout=25)),1)
        o.send('pause');time.sleep(0.5);a.send('set Synthetic paused text that must not be recorded.')
        self.assertEqual(self.records(o,3),[])
        o.send('resume');resumed=self.wait(o,timeout=25)
        self.assertEqual(len(resumed),1);self.assertIn('must not be recorded',resumed[0]['text'])

    OCR={'runtime':str(ROOT/'.tools/ocr-runtime/onnxruntime.dll'),'detector':str(ROOT/'models/PaddlePaddle--PP-OCRv5_mobile_det/inference.onnx'),
         'route':'auto','threads':2,'recognizers':{'general':{'model':str(ROOT/'models/PaddlePaddle--PP-OCRv6_tiny_rec/inference.onnx'),
                                                              'dictionary':str(ROOT/'models/PaddlePaddle--PP-OCRv6_tiny_rec/ctc-dictionary.json')}}}

    def painted_app(self,text):
        a=Proc([APP,'--invisible','--paint',text,'Painted window']);self.addCleanup(a.stop)
        self.assertEqual(a.out.get(timeout=20),'ready');time.sleep(0.5);return a

    def test_ocr_fallback_reads_text_ui_automation_cannot_see(self):
        a=self.painted_app('Synthetic canvas note: invoice 7310 due Monday')
        recs=self.wait(self.observer(a,{'ocr':self.OCR,'min_interval_ms':500,'max_interval_ms':2000}),timeout=40)
        self.assertTrue(recs,'no OCR record');r=recs[0]
        self.assertEqual(r['metadata']['capture'],'ocr');self.assertEqual(r['provenance'],'lens-observer ocr')
        self.assertIn('invoice 7310',r['text']);self.assertIsNone(r['metadata']['region'])

    def test_ocr_fallback_reads_only_the_changed_region_after_a_change(self):
        a=self.painted_app('Synthetic canvas note: invoice 7310 due Monday')
        o=self.observer(a,{'ocr':self.OCR,'min_interval_ms':500,'max_interval_ms':1000})
        first=self.wait(o,timeout=40);self.assertEqual(len(first),1,first)
        a.send('set Synthetic canvas note: invoice 7310 due Friday');changed=self.wait(o,timeout=40)
        self.assertEqual(len(changed),1,changed);self.assertIn('Friday',changed[0]['text'])
        self.assertIsNotNone(changed[0]['metadata']['region'])

    def test_ocr_worker_is_reused_then_released_when_idle(self):
        import psutil
        a=self.painted_app('Synthetic canvas note: invoice 7310 due Monday')
        o=self.observer(a,{'ocr':self.OCR,'min_interval_ms':500,'max_interval_ms':1000,'ocr_idle_ms':5000})
        self.assertIn('invoice',json.loads(o.out.get(timeout=20))['text'])
        workers=[c for c in psutil.Process(o.p.pid).children() if c.name().lower()=='lens-ocr.exe']
        self.assertEqual(len(workers),1,workers)
        a.send('set Synthetic canvas note: invoice 7310 due Friday');self.assertIn('Friday',json.loads(o.out.get(timeout=30))['text'])
        self.assertEqual([c.pid for c in psutil.Process(o.p.pid).children() if c.name().lower()=='lens-ocr.exe'],[workers[0].pid])
        a.stop();time.sleep(9)  # window gone: no OCR requests, so the worker must be released
        self.assertEqual([c for c in psutil.Process(o.p.pid).children() if c.name().lower()=='lens-ocr.exe'],[])

    def test_without_ocr_config_text_invisible_to_uia_is_not_captured(self):
        a=self.painted_app('Synthetic canvas note: invoice 7310 due Monday')
        for r in self.records(self.observer(a),4):self.assertNotIn('invoice',r['text'])

    def test_observations_are_stored_and_searchable_in_encrypted_memory(self):
        a=self.app(body='Synthetic memo: the vendor contract renewal is due on 14 November.')
        recs=self.wait(self.observer(a),timeout=25);self.assertTrue(recs)
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'memory.db'
            proc=subprocess.run([str(ENGINE),'--db',str(db)],input=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in recs)+
                                json.dumps({'op':'search','query':'vendor contract renewal'})+'\n',encoding='utf-8',capture_output=True,timeout=60)
            rows=[json.loads(x) for x in proc.stdout.splitlines()]
            self.assertTrue(rows[0]['ok'],rows[0]);hit=rows[-1]['sources'][0]
            self.assertEqual(hit['id'],recs[0]['id']);self.assertIn('vendor contract renewal',hit['text'])
            self.assertNotIn(b'vendor contract renewal',db.read_bytes())


if __name__=='__main__':unittest.main()
