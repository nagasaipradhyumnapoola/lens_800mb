"""Hybrid semantic + keyword recall through the real engine: cross-language evidence, abstention, encryption,
incremental indexing, deletion, filters, chunked long sources and the PowerShell client."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from support import pwsh
ROOT=Path(__file__).resolve().parents[1]
ENGINE=ROOT/'build/engine/Release/lens-engine.exe'
LOCK=json.loads((ROOT/'third_party/embedding-lock.json').read_text(encoding='utf-8'))
MODEL=next(ROOT/f['path'] for f in LOCK['files'] if f['filename']=='onnx/model_qint8_avx512_vnni.onnx')
TOKENIZER=next(ROOT/f['path'] for f in LOCK['files'] if f['filename']=='onnx/tokenizer.json')
RLOCK=json.loads((ROOT/'third_party/reranker-lock.json').read_text(encoding='utf-8'))
RERANKER=[str(ROOT/next(f['path'] for f in RLOCK['files'] if f['filename']==n)) for n in ('onnx/model_qint8_avx512_vnni.onnx','tokenizer.json')]
SAMPLES=[('zh-budget','zh','王芳说下周二上午十点在上海办公室开预算评审会。'),
         ('hi-yoga','hi','लोधी गार्डन वाली योगा क्लास अब सुबह साढ़े छह बजे होगी।'),
         ('es-flight','es','El vuelo IB 3170 a Madrid sale de la terminal 4 a las 18:40.'),
         ('en-allergy','en','Lena prefers vegetarian food and is allergic to peanuts, so avoid satay at the team lunch.'),
         ('ta-train','ta','சென்னையிலிருந்து மதுரைக்கு வைகை எக்ஸ்பிரஸ் மதியம் ஒரு மணிக்கு புறப்படும்.'),
         ('te-rent','te','గుంటూరు ఇంటి అద్దె వచ్చే నెల నుండి పన్నెండు వేలు అవుతుంది.')]


def add(i,text,lang,stamp='2026-03-01T10:00:00Z'):
    return {'op':'add','consent':True,'id':i,'text':text,'language':lang,'timestamp':stamp,'device':'test','kind':'manual_import','provenance':'test'}


class HybridRetrieval(unittest.TestCase):
    def engine(self,db,*requests,model_id='test-e5@1'):
        args=[str(ENGINE),'--db',str(db),'--ort',str(ROOT/'.tools/ocr-runtime/onnxruntime.dll'),'--embedding-model',str(MODEL),
              '--embedding-tokenizer',str(TOKENIZER),'--embedding-id',model_id,'--reranker-model',RERANKER[0],'--reranker-tokenizer',RERANKER[1]]
        p=subprocess.run(args,input=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in requests),capture_output=True,encoding='utf-8',timeout=300)
        self.assertEqual(p.returncode,0,p.stderr)
        return [json.loads(x) for x in p.stdout.splitlines()]

    def seeded(self,tmp):
        db=Path(tmp)/'memory.db'
        out=self.engine(db,*[add(i,t,l) for i,l,t in SAMPLES],{'op':'index'})
        self.assertEqual((out[-1]['indexed_sources'],out[-1]['pending_sources']),(len(SAMPLES),0))
        return db

    def recall(self,db,query,**extra):
        return self.engine(db,{'op':'recall','query':query,**extra})[0]

    def test_cross_language_questions_return_original_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=self.seeded(tmp)
            for query,expected in [('When is the budget review with Wang Fang?','zh-budget'),
                                   ('What time is the yoga class at Lodhi Garden now?','hi-yoga'),
                                   ('¿Qué no puede comer Lena?','en-allergy'),('मदुरै की ट्रेन कितने बजे निकलती है?','ta-train')]:
                r=self.recall(db,query)
                self.assertFalse(r['not_found'],query);top=r['results'][0]
                self.assertEqual(top['source']['id'],expected,query)
                text=top['source']['text'].encode('utf-8');ev=top['evidence']
                self.assertEqual(text[ev['byte_offset']:ev['byte_end']].decode('utf-8'),ev['quote'])
                self.assertFalse(r['generated_claims'])
                self.assertIsNotNone(top['scores']['semantic'])

    def test_unsupported_question_abstains_with_default_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=self.seeded(tmp)
            for query in ['When is my Canada visa interview?','我们在东京订了哪家酒店？']:
                r=self.recall(db,query)
                self.assertTrue(r['not_found'],(query,r.get('best_semantic')));self.assertEqual(r['results'],[])

    def test_exact_keyword_match_is_kept_even_for_rare_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=self.seeded(tmp)
            r=self.recall(db,'IB 3170')
            self.assertTrue(r['full_keyword_match']);self.assertEqual(r['results'][0]['source']['id'],'es-flight')
            k=self.recall(db,'IB 3170',mode='keyword')
            self.assertIsNone(k['model']);self.assertEqual(k['results'][0]['source']['id'],'es-flight')

    def test_vectors_stay_inside_the_encrypted_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=self.seeded(tmp)
            stats=self.engine(db,{'op':'stats'})[0]
            self.assertEqual((stats['schema_version'],stats['vector_chunks'],stats['embedded_sources']),(8,len(SAMPLES),len(SAMPLES)))
            for f in Path(tmp).iterdir():
                data=f.read_bytes()
                for marker in (b'embedding_chunks',b'SQLite format 3','王芳'.encode(),b'passage: '):self.assertNotIn(marker,data,f.name)

    def test_incremental_index_delete_and_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=self.seeded(tmp)
            out=self.engine(db,add('en-new','The Orion launch review moved to Thursday at 3 pm.','en'),{'op':'index'},{'op':'index'})
            self.assertEqual((out[1]['indexed_sources'],out[2]['indexed_sources'],out[2]['pending_sources']),(1,0,0))
            r=self.recall(db,'When is the Orion release review?',filters={'language':'en'})
            self.assertTrue(all(x['source']['language']=='en' for x in r['results']));self.assertEqual(r['results'][0]['source']['id'],'en-new')
            out=self.engine(db,{'op':'delete','id':'en-new','consent':True},{'op':'stats'},{'op':'recall','query':'When is the Orion release review?','abstain':False})
            self.assertEqual(out[1]['vector_chunks'],len(SAMPLES))
            self.assertNotIn('en-new',[x['source']['id'] for x in out[2]['results']])

    def test_vectors_from_another_model_are_ignored_and_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=self.seeded(tmp)
            r=self.engine(db,{'op':'recall','query':'When is the budget review with Wang Fang?','mode':'semantic','abstain':False},model_id='other-model@2')[0]
            self.assertEqual((r['unindexed_sources'],r['results']),(len(SAMPLES),[]))

    def test_reranker_is_default_when_configured_and_optional_otherwise(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=self.seeded(tmp)
            r=self.recall(db,'When is the budget review with Wang Fang?')
            self.assertTrue(r['reranked']);self.assertIsNotNone(r['results'][0]['scores']['rerank'])
            plain=subprocess.run([str(ENGINE),'--db',str(db),'--ort',str(ROOT/'.tools/ocr-runtime/onnxruntime.dll'),'--embedding-model',str(MODEL),
                                  '--embedding-tokenizer',str(TOKENIZER),'--embedding-id','test-e5@1'],
                                 input=json.dumps({'op':'recall','query':'When is the budget review with Wang Fang?','abstain':False})+'\n',
                                 capture_output=True,encoding='utf-8',timeout=120)
            out=json.loads(plain.stdout)
            self.assertFalse(out['reranked']);self.assertEqual(out['results'][0]['source']['id'],'zh-budget')
            forced=subprocess.run([str(ENGINE),'--db',str(db),'--ort',str(ROOT/'.tools/ocr-runtime/onnxruntime.dll'),'--embedding-model',str(MODEL),
                                   '--embedding-tokenizer',str(TOKENIZER),'--embedding-id','test-e5@1'],
                                  input=json.dumps({'op':'recall','query':'budget','rerank':True})+'\n',capture_output=True,encoding='utf-8',timeout=120)
            self.assertEqual(json.loads(forced.stdout)['error'],'reranker_not_configured')

    def test_language_centering_stops_other_script_hubs_outranking_the_answer(self):
        # Diagnosed failure: e5's language-identity component let an unrelated Telugu note outrank the right
        # English memory. Centering applies once a script group has >= 50 stored vectors.
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'memory.db'
            records=[add(f'te-{i}',f'రవి లాగిన్ సమస్యను పరిష్కరించాడు, కారణం పాత కాష్ సంఖ్య {i}.','te') for i in range(60)]
            records+=[add(f'en-{i}',f'Read an article about urban gardening trends, item {i}.','en') for i in range(60)]
            records.append(add('answer','The plumber said the bathroom leak comes from a cracked pipe behind the wall.','en'))
            self.engine(db,*records,{'op':'index'})
            q='What is causing the water problem in the washroom?'
            centered=self.recall(db,q,abstain=False)
            self.assertTrue(centered['centered']);self.assertEqual(centered['results'][0]['source']['id'],'answer')
            raw=self.recall(db,q,abstain=False,center=False,rerank=False)
            self.assertFalse(raw['centered'])

    def test_long_source_is_chunked_and_quotes_the_matching_chunk(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'memory.db'
            filler=' '.join(f'Routine status line {i} about weather and traffic in the city.' for i in range(120))
            text=filler+' The vendor contract renewal for Acme Analytics is due on 30 November and costs 4.2 lakh rupees. '+filler
            out=self.engine(db,add('long','x'*0+text,'en'),{'op':'index'},
                            {'op':'recall','query':'When does the Acme vendor agreement need renewing?','limit':1})
            self.assertGreater(out[1]['chunks'],3)
            ev=out[2]['results'][0]['evidence']
            self.assertIn('Acme Analytics',ev['quote']);self.assertTrue(ev['truncated'])
            self.assertEqual(text.encode()[ev['byte_offset']:ev['byte_end']].decode(),ev['quote'])

    def test_powershell_client_imports_indexes_and_recalls_via_stdin(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'memory.db'
            def cli(*args,stdin):
                p=subprocess.run([pwsh(),'-NoProfile','-File',str(ROOT/'scripts/lens.ps1'),'-DatabasePath',str(db),*args],
                                 input=stdin,capture_output=True,encoding='utf-8',timeout=180)
                self.assertEqual(p.returncode,0,p.stderr);return json.loads(p.stdout)
            stored=cli('-Action','ImportText','-Language','te','-Id','te-rent',stdin=SAMPLES[5][2])
            self.assertTrue(stored['ok']);self.assertEqual(stored['semantic_index']['pending_sources'],0)
            r=cli('-Action','Recall',stdin='What will the rent be for the Guntur house from next month?')
            self.assertEqual(r['results'][0]['source']['text'],SAMPLES[5][2])
            self.assertIn('multilingual-e5-small',r['model'])


if __name__=='__main__':unittest.main()
