"""Schema v6 lossless text compression: compressed rows read back exactly everywhere (search, find_source, literal
scans, highlight), FTS deletes stay correct, dictionaries train from stored text, plaintext never hits the file."""
import json
from pathlib import Path
import random
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
EXE=ROOT/'build/engine/Release/lens-engine.exe'
WORDS='vendor contract renewal finance budget review meeting roadmap hiring quarterly schedule invoice partner launch'.split()


def long_text(rng,marker):
    lines=[' '.join(rng.choice(WORDS) for _ in range(12)) for _ in range(8)]
    lines.insert(3,marker);return '\n'.join(lines)


def record(i,text):
    return {'op':'add','consent':True,'id':f'c-{i:04d}','text':text,'language':'en','timestamp':f'2026-10-27T09:{i%60:02d}:00.000Z',
            'device':'test','kind':'screen_observation','provenance':'synthetic-test','source_application':'test.exe','source_locator':'window:test'}


def run(db,requests):
    p=subprocess.run([str(EXE),'--db',str(db)],input=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in requests),
                     encoding='utf-8',capture_output=True,timeout=300)
    assert p.returncode==0,p.stderr
    return [json.loads(l) for l in p.stdout.splitlines()]


class TextCompression(unittest.TestCase):
    def test_long_text_is_compressed_and_reads_back_exactly(self):
        rng=random.Random(1);marker='Synthetic marker: the Zephyrine settlement closes on 9 December.'
        text=long_text(rng,marker);short='Short note about Zephyrine.'
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'m.db'
            rows=run(db,[record(1,text),record(2,short),{'op':'stats'},{'op':'find_source','id':'c-0001'},
                         {'op':'search','query':'Zephyrine settlement'},{'op':'search','query':'9 December'}])
            stats=rows[2];self.assertEqual(stats['schema_version'],8);self.assertEqual(stats['compressed_sources'],1)
            self.assertLess(stats['compressed_text_bytes'],len(text.encode())*0.85)
            self.assertEqual(json.dumps(rows[3]).count('Zephyrine settlement'),1)
            src=rows[3].get('source') or rows[3].get('sources',[None])[0];self.assertEqual(src['text'],text)
            self.assertEqual(rows[4]['sources'][0]['id'],'c-0001');self.assertEqual(rows[4]['sources'][0]['text'],text)
            self.assertTrue(rows[5]['sources']);raw=db.read_bytes()
            self.assertNotIn(b'Zephyrine',raw)

    def test_delete_removes_compressed_text_from_search(self):
        rng=random.Random(2);text=long_text(rng,'Synthetic marker: Quillfeather audit on Tuesday.')
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'m.db'
            rows=run(db,[record(1,text),{'op':'search','query':'Quillfeather'},{'op':'delete','consent':True,'id':'c-0001'},
                         {'op':'search','query':'Quillfeather'},{'op':'stats'}])
            self.assertEqual(rows[1]['sources'][0]['id'],'c-0001');self.assertTrue(rows[3]['not_found']);self.assertEqual(rows[4]['source_count'],0)

    def test_trained_dictionary_is_used_for_new_records_and_decodes(self):
        rng=random.Random(3)
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'m.db'
            few=run(db,[record(i,long_text(rng,f'Synthetic marker {i}.')) for i in range(20)]+[{'op':'train_text_dictionary','samples':200}])
            self.assertEqual(few[-1]['error'],'insufficient_samples')
            base=[record(i,long_text(rng,f'Synthetic marker {i}.')) for i in range(20,170)]
            rows=run(db,base+[{'op':'train_text_dictionary','samples':500,'dictionary_bytes':16384},{'op':'stats'}])
            self.assertEqual(rows[-2]['dictionary_id'],1);self.assertEqual(rows[-1]['text_dictionaries'],1)
            later=long_text(rng,'Synthetic marker: Brightwater invoice 5521 approved.')
            after=run(db,[record(500,later),{'op':'search','query':'Brightwater invoice'},{'op':'find_source','id':'c-0042'}])
            self.assertEqual(after[1]['sources'][0]['text'],later)
            self.assertIn('Synthetic marker 42.',json.dumps(after[2],ensure_ascii=False))

    def test_unspaced_script_literal_scan_reads_compressed_text(self):
        text='\n'.join(['供应商合同续签截止日期是十一月十四日，财务部门需要提前准备预算审核材料。']*6+['会议改到周四下午在B12会议室举行。'])
        with tempfile.TemporaryDirectory() as tmp:
            rows=run(Path(tmp)/'m.db',[record(1,text),{'op':'stats'},{'op':'search','query':'合同续签'}])
            self.assertEqual(rows[1]['compressed_sources'],1);self.assertEqual(rows[2]['sources'][0]['id'],'c-0001')


if __name__=='__main__':unittest.main()
