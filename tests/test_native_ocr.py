import json
from pathlib import Path
import subprocess
import unittest
import tempfile
ROOT=Path(__file__).resolve().parents[1]
EXE=ROOT/'build/engine/Release/lens-ocr.exe'


class NativeOCR(unittest.TestCase):
    def test_native_recognition_preserves_primary_language_text(self):
        self.assertTrue(EXE.exists(),'Native OCR adapter is not built')
        for lang,model,anchor in [('en','PP-OCRv6_tiny_rec','Arun'),('es','PP-OCRv6_tiny_rec','Ana'),
                                  ('zh','PP-OCRv6_tiny_rec','北京'),('hi','devanagari_PP-OCRv5_mobile_rec','15:00')]:
            with self.subTest(language=lang):
                folder=ROOT/'models'/('PaddlePaddle--'+model)
                req={'consent':True,'runtime':str(ROOT/'.tools/ocr-runtime/onnxruntime.dll'),
                     'model':str(folder/'inference.onnx'),'dictionary':str(folder/'ctc-dictionary.json'),
                     'image':str(ROOT/'artifacts/ocr-smoke'/(lang+'.png'))}
                p=subprocess.run([str(EXE)],input=json.dumps(req)+'\n',encoding='utf-8',capture_output=True,timeout=30)
                self.assertEqual(p.returncode,0,p.stderr)
                result=json.loads(p.stdout)
                self.assertIn(anchor,result['text'])
                if lang=='hi':self.assertTrue(any('\u0900'<=c<='\u097f' for c in result['text']))

    def test_image_processing_requires_consent(self):
        self.assertTrue(EXE.exists())
        p=subprocess.run([str(EXE)],input='{"consent":false}\n',encoding='utf-8',capture_output=True,timeout=10)
        self.assertNotEqual(p.returncode,0)
        self.assertIn('consent_required',p.stderr)

    def test_non_float_output_is_rejected_before_pointer_read(self):
        import onnx
        from onnx import helper,TensorProto
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);model=folder/'uint8-output.onnx';dictionary=folder/'dict.json'
            dictionary.write_text('["blank","X"]',encoding='utf-8')
            node=helper.make_node('Constant',[],['prediction'],value=helper.make_tensor('c',TensorProto.UINT8,[1,2,2],[0,1,0,1]))
            graph=helper.make_graph([node],'typed-output-guard',
                [helper.make_tensor_value_info('x',TensorProto.FLOAT,[1,3,48,None])],
                [helper.make_tensor_value_info('prediction',TensorProto.UINT8,[1,2,2])])
            onnx.save(helper.make_model(graph,opset_imports=[helper.make_opsetid('',17)]),model)
            req={'consent':True,'runtime':str(ROOT/'.tools/ocr-runtime/onnxruntime.dll'),
                 'model':str(model),'dictionary':str(dictionary),'image':str(ROOT/'artifacts/ocr-smoke/en.png')}
            p=subprocess.run([str(EXE)],input=json.dumps(req)+'\n',encoding='utf-8',capture_output=True,timeout=30)
            self.assertNotEqual(p.returncode,0)
            self.assertIn('ocr_output_type_mismatch',p.stderr)


def screen_image(lines,size=(900,260)):
    """Render a synthetic two-language screen in memory (PNG bytes): Segoe UI and Microsoft YaHei."""
    import io
    from PIL import Image,ImageDraw,ImageFont
    img=Image.new('RGB',size,(255,255,255));d=ImageDraw.Draw(img)
    for i,(text,font) in enumerate(lines):d.text((30,30+i*50),text,fill=(20,20,20),font=ImageFont.truetype(font,24))
    buf=io.BytesIO();img.save(buf,format='PNG');return buf.getvalue()


class NativeScreenOCR(unittest.TestCase):
    LINES=[('Synthetic invoice 4821 is due on Friday',r'C:\Windows\Fonts\segoeui.ttf'),
           ('供应商合同续签截止日期是十一月十四日',r'C:\Windows\Fonts\msyh.ttc'),
           ('Meeting moved to room B12 at 4:30 pm',r'C:\Windows\Fonts\segoeui.ttf')]

    def ask(self,**extra):
        import base64
        m=ROOT/'models'
        req={'consent':True,'runtime':str(ROOT/'.tools/ocr-runtime/onnxruntime.dll'),'mode':'screen',
             'detector':str(m/'PaddlePaddle--PP-OCRv5_mobile_det/inference.onnx'),'route':'auto',
             'recognizers':{'general':{'model':str(m/'PaddlePaddle--PP-OCRv6_tiny_rec/inference.onnx'),'dictionary':str(m/'PaddlePaddle--PP-OCRv6_tiny_rec/ctc-dictionary.json')},
                            'hi':{'model':str(m/'PaddlePaddle--devanagari_PP-OCRv5_mobile_rec/inference.onnx'),'dictionary':str(m/'PaddlePaddle--devanagari_PP-OCRv5_mobile_rec/ctc-dictionary.json')}},
             'image_base64':base64.b64encode(screen_image(self.LINES)).decode('ascii'),**extra}
        return subprocess.run([str(EXE)],input=json.dumps(req,ensure_ascii=False)+'\n',encoding='utf-8',capture_output=True,timeout=120)

    def test_screen_detects_and_reads_lines_in_order(self):
        p=self.ask();self.assertEqual(p.returncode,0,p.stderr);r=json.loads(p.stdout)
        texts=[l['text'] for l in r['lines']];self.assertEqual(len(texts),3,texts)
        self.assertIn('invoice 4821',texts[0]);self.assertIn('十一月十四日',texts[1]);self.assertIn('B12',texts[2])
        ys=[l['box'][1] for l in r['lines']];self.assertEqual(ys,sorted(ys))
        self.assertTrue(all(l['recognizer']=='general' for l in r['lines']))
        self.assertGreater(r['peak_working_set_bytes'],0)

    def test_region_reads_only_that_region(self):
        p=self.ask(region=[0,70,900,60]);self.assertEqual(p.returncode,0,p.stderr)
        texts=[l['text'] for l in json.loads(p.stdout)['lines']]
        self.assertEqual(len(texts),1,texts);self.assertIn('十一月',texts[0])

    def test_invalid_region_is_rejected(self):
        p=self.ask(region=[800,200,500,500]);self.assertNotEqual(p.returncode,0);self.assertIn('invalid_region',p.stderr)

    def test_serve_mode_keeps_models_loaded_and_survives_bad_requests(self):
        import base64
        good=json.loads(self.request_json());bad={**good,'consent':False};broken={**good,'image_base64':'@@@'}
        p=subprocess.Popen([str(EXE),'--serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',bufsize=1)
        def ask(req):p.stdin.write(json.dumps(req,ensure_ascii=False)+'\n');p.stdin.flush();return json.loads(p.stdout.readline())
        first=ask(good);second=ask(good);refused=ask(bad);failed=ask(broken);third=ask(good)
        p.stdin.close();self.assertEqual(p.wait(timeout=30),0)
        for r in (first,second,third):self.assertTrue(r['ok']);self.assertEqual(len(r['lines']),3)
        self.assertGreater(first['timing_ms']['detector_load'],0);self.assertEqual(second['timing_ms']['detector_load'],0)
        self.assertEqual(second['timing_ms']['recognizer_load'],0)
        self.assertEqual(refused,{'ok':False,'error':'consent_required'});self.assertFalse(failed['ok'])

    def request_json(self):
        import base64
        m=ROOT/'models'
        return json.dumps({'consent':True,'runtime':str(ROOT/'.tools/ocr-runtime/onnxruntime.dll'),'mode':'screen',
             'detector':str(m/'PaddlePaddle--PP-OCRv5_mobile_det/inference.onnx'),'route':'auto',
             'recognizers':{'general':{'model':str(m/'PaddlePaddle--PP-OCRv6_tiny_rec/inference.onnx'),'dictionary':str(m/'PaddlePaddle--PP-OCRv6_tiny_rec/ctc-dictionary.json')}},
             'image_base64':base64.b64encode(screen_image(self.LINES)).decode('ascii')})

    def test_screen_requires_consent(self):
        p=self.ask(consent=False);self.assertNotEqual(p.returncode,0);self.assertIn('consent_required',p.stderr)


if __name__=='__main__':unittest.main()
