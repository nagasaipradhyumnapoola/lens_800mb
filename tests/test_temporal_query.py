"""Natural-language time expressions in recall: interpreted windows, multilingual phrases, offsets, relaxation."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
ENGINE=ROOT/'build/engine/Release/lens-engine.exe'
LOCK=json.loads((ROOT/'third_party/embedding-lock.json').read_text(encoding='utf-8'))
MODEL=next(ROOT/f['path'] for f in LOCK['files'] if f['filename']=='onnx/model_qint8_avx512_vnni.onnx')
TOKENIZER=next(ROOT/f['path'] for f in LOCK['files'] if f['filename']=='onnx/tokenizer.json')
RLOCK=json.loads((ROOT/'third_party/reranker-lock.json').read_text(encoding='utf-8'))
RERANKER=[str(ROOT/next(f['path'] for f in RLOCK['files'] if f['filename']==n)) for n in ('onnx/model_qint8_avx512_vnni.onnx','tokenizer.json')]
NOW='2026-10-26T12:00:00Z'  # a Monday
RECORDS=[('agent-new','en','Read an article about agent memory architectures on the Lens research blog.','2026-10-21T09:00:00Z'),
         ('agent-old','en','Read an article about agent memory architectures on a different research blog.','2026-09-10T09:00:00Z'),
         ('zh-new','zh','读了一篇关于智能体记忆的文章。','2026-10-25T03:00:00Z'),
         ('bill','en','The electricity bill for October was 2,870 rupees.','2025-11-02T09:00:00Z'),
         ('late','en','Booked the dentist appointment for next month.','2026-10-25T20:00:00Z')]


class TemporalQuery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.db=Path(cls.tmp.name)/'memory.db'
        cls.ask(*[{'op':'add','consent':True,'id':i,'text':t,'language':l,'timestamp':ts,'device':'test','kind':'k','provenance':'test'} for i,l,t,ts in RECORDS],{'op':'index'})

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    @classmethod
    def ask(cls,*requests):
        args=[str(ENGINE),'--db',str(cls.db),'--ort',str(ROOT/'.tools/ocr-runtime/onnxruntime.dll'),'--embedding-model',str(MODEL),
              '--embedding-tokenizer',str(TOKENIZER),'--embedding-id','test-e5@1','--reranker-model',RERANKER[0],'--reranker-tokenizer',RERANKER[1]]
        p=subprocess.run(args,input=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in requests),capture_output=True,encoding='utf-8',timeout=300)
        assert p.returncode==0,p.stderr
        return [json.loads(x) for x in p.stdout.splitlines()]

    def recall(self,query,**extra):
        return self.ask({'op':'recall','query':query,'now':NOW,**extra})[0]

    def test_last_week_filters_to_the_previous_iso_week(self):
        r=self.recall('Where did I read about agent memory last week?')
        self.assertEqual(r['time_filter'],'applied')
        self.assertEqual((r['time_window']['from'],r['time_window']['to']),('2026-10-19T00:00:00Z','2026-10-26T00:00:00Z'))
        ids=[x['source']['id'] for x in r['results']]
        self.assertEqual(ids[0],'agent-new')
        self.assertNotIn('agent-old',ids)  # September evidence is outside the window
        self.assertTrue(all('2026-10-19'<=x['source']['timestamp']<'2026-10-26' for x in r['results']))

    def test_chinese_yesterday_and_spanish_last_month(self):
        r=self.recall('昨天我读了什么关于智能体记忆的文章？')
        self.assertEqual((r['time_window']['from'],r['time_filter']),('2026-10-25T00:00:00Z','applied'))
        self.assertEqual(r['results'][0]['source']['id'],'zh-new')
        r=self.recall('¿Qué artículo sobre memoria de agentes leí el mes pasado?')
        self.assertEqual((r['time_window']['from'],r['time_window']['to']),('2026-09-01T00:00:00Z','2026-10-01T00:00:00Z'))
        self.assertEqual(r['results'][0]['source']['id'],'agent-old')

    def test_utc_offset_moves_day_boundaries(self):
        utc=self.recall('What did I book today?',limit=5)
        self.assertNotIn('late',[x['source']['id'] for x in utc['results']])
        ist=self.recall('What did I book today?',utc_offset_minutes=330,abstain=False)
        self.assertEqual(ist['time_window']['from'],'2026-10-25T18:30:00Z')
        self.assertEqual(ist['results'][0]['source']['id'],'late')

    def test_content_month_falls_back_when_no_evidence_in_window(self):
        r=self.recall('How much was the electricity bill in October?')
        self.assertEqual(r['time_filter'],'relaxed_no_evidence_in_window')
        self.assertEqual(r['results'][0]['source']['id'],'bill')

    def test_ambiguous_or_absent_time_words_are_not_interpreted(self):
        for q in ['कल एजेंट मेमोरी के बारे में क्या पढ़ा?','Where did I read about agent memory?','May I see the agent memory article?']:
            self.assertNotIn('time_window',self.recall(q),q)

    def test_explicit_filters_win_and_interpretation_can_be_disabled(self):
        r=self.recall('Where did I read about agent memory last week?',filters={'from':'2026-09-01T00:00:00Z','to':'2026-10-01T00:00:00Z'},abstain=False)
        self.assertNotIn('time_window',r);self.assertEqual(r['results'][0]['source']['id'],'agent-old')
        self.assertNotIn('time_window',self.recall('agent memory last week',interpret_time=False))


if __name__=='__main__':unittest.main()
