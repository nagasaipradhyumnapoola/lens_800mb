"""Structured query interpretation: application hints (6 languages), action trace, strict explicit filters, relaxation."""
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
RECORDS=[('chrome','en','Read an article about agent memory consolidation on the Latent Notes blog.','Google Chrome'),
         ('notes','en','Note to self: write up thoughts about agent memory consolidation.','Notepad'),
         ('mail','en','Grace: the investor presentation rehearsal moved to Tuesday 11 am.','Microsoft Outlook'),
         ('slack','en','Reminder in channel: investor presentation slides are due Monday.','Slack'),
         ('wechat','zh','王芳说预算评审会改到下周二上午十点。','WeChat'),
         ('dl','en','Q3 vendor contract PDF saved to the Finance folder.','Microsoft Edge')]


class QueryInterpretation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.db=Path(cls.tmp.name)/'memory.db'
        cls.ask(*[{'op':'add','consent':True,'id':i,'text':t,'language':l,'timestamp':'2026-10-20T09:00:00Z','device':'test','kind':'k',
                   'provenance':'test','source_application':app} for i,l,t,app in RECORDS],{'op':'index'})

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
        r=self.ask({'op':'recall','query':query,'abstain':False,**extra})[0]
        self.assertTrue(r['ok'],r);return r

    def test_browser_hint_prefers_the_chrome_record(self):
        r=self.recall('What did I read in Chrome about agent memory?')
        self.assertEqual(r['interpretation']['constraints'],'applied')
        self.assertIn('chrome',r['interpretation']['application_filter'])
        self.assertEqual([x['source']['id'] for x in r['results']],['chrome'])
        self.assertEqual(r['interpretation']['action'],'read')

    def test_email_class_maps_to_mail_clients(self):
        r=self.recall('Which email mentioned the investor presentation?')
        self.assertEqual(r['results'][0]['source']['id'],'mail')
        self.assertTrue(all(x['source']['source_application']=='Microsoft Outlook' for x in r['results']))

    def test_native_script_application_hint(self):
        r=self.recall('微信里王芳说预算会议是什么时候？')
        self.assertIn('wechat',r['interpretation']['application_filter'])
        self.assertEqual(r['results'][0]['source']['id'],'wechat')

    def test_hint_without_matching_evidence_relaxes_and_says_so(self):
        r=self.recall('What did I see on WhatsApp about the investor presentation?')
        self.assertEqual(r['interpretation']['constraints'],'relaxed_no_evidence_with_interpreted_constraints')
        self.assertIn(r['results'][0]['source']['id'],('mail','slack'))

    def test_explicit_application_filter_is_strict_and_suppresses_interpretation(self):
        r=self.recall('Which email mentioned the investor presentation?',filters={'application_contains':['slack']})
        self.assertEqual([x['source']['id'] for x in r['results']],['slack'])
        self.assertEqual(r['interpretation']['application_filter'],[])
        bad=self.ask({'op':'recall','query':'x','filters':{'application_contains':'slack'}})[0]
        self.assertEqual(bad['error'],'invalid_filter')

    def test_like_wildcards_in_filter_values_are_literal(self):
        r=self.ask({'op':'recall','query':'investor presentation','filters':{'application_contains':['%']}})[0]
        self.assertTrue(r['not_found'])

    def test_download_action_is_traced_and_interpretation_can_be_disabled(self):
        r=self.recall('Where did I save the vendor contract I downloaded in Edge?')
        self.assertEqual((r['interpretation']['action'],r['results'][0]['source']['id']),('downloaded','dl'))
        off=self.recall('What did I read in Chrome about agent memory?',interpret_query=False)
        self.assertEqual(off['interpretation']['application_filter'],[])


if __name__=='__main__':unittest.main()
