"""Hardware compatibility tooling: static ISA audit rules and the privacy-safe hardware profile."""
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
import getpass
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import check_hardware_compat as compat
import hardware_profile


def tree(files):
    tmp=tempfile.TemporaryDirectory();root=Path(tmp.name)
    for rel,text in files.items():(root/rel).parent.mkdir(parents=True,exist_ok=True);(root/rel).write_text(text,encoding='utf-8')
    return tmp,root


ENGINE_CMAKE='''add_executable(lens-engine main.cpp)
target_link_libraries(lens-engine PRIVATE lens-store "${W}/ggml/src/Release/ggml-cpu.lib")
add_executable(lens-embed embed_main.cpp)
target_link_libraries(lens-embed PRIVATE lens-embedding)
'''


class StaticAudit(unittest.TestCase):
    def test_unconditional_avx2_fails_and_flags_the_engine(self):
        tmp,root=tree({'build/whisper/CMakeCache.txt':'GGML_AVX:BOOL=ON\nGGML_AVX2:BOOL=ON\nGGML_NATIVE:BOOL=OFF\nGGML_BACKEND_DL:BOOL=OFF\n',
                       'engine/CMakeLists.txt':ENGINE_CMAKE})
        with tmp:
            r=compat.audit(root);checks={c['check']:c for c in r['checks']}
            self.assertEqual(r['result'],'FAIL')
            self.assertIn('GGML_AVX2',checks['ggml CPU backend ISA']['detail'])
            link=checks['binaries linking the ggml CPU backend']
            self.assertEqual(link['status'],'FAIL');self.assertIn('lens-engine',link['detail']);self.assertNotIn('lens-embed',link['detail'])

    def test_runtime_dispatch_passes(self):
        tmp,root=tree({'build/whisper-dl/CMakeCache.txt':'GGML_AVX2:BOOL=ON\nGGML_BACKEND_DL:BOOL=ON\nGGML_CPU_ALL_VARIANTS:BOOL=ON\n',
                       'engine/CMakeLists.txt':'set(WHISPER_BUILD "${LENS_ROOT}/build/whisper-dl")\n'+ENGINE_CMAKE,
                       'build/engine/Release/ggml-cpu-x64.dll':'x'})
        with tmp:
            r=compat.audit(root);statuses={c['check']:c['status'] for c in r['checks']}
            self.assertEqual(r['result'],'PASS_STATIC')
            self.assertEqual(statuses['ggml CPU backend ISA'],'PASS')
            self.assertEqual(statuses['baseline ggml CPU variant shipped beside the engine'],'PASS')

    def test_runtime_dispatch_without_baseline_variant_fails(self):
        tmp,root=tree({'build/whisper-dl/CMakeCache.txt':'GGML_BACKEND_DL:BOOL=ON\nGGML_CPU_ALL_VARIANTS:BOOL=ON\n',
                       'engine/CMakeLists.txt':'set(WHISPER_BUILD "${LENS_ROOT}/build/whisper-dl")\n'})
        with tmp:self.assertEqual(compat.audit(root)['result'],'FAIL')

    def test_native_build_fails(self):
        tmp,root=tree({'build/whisper/CMakeCache.txt':'GGML_NATIVE:BOOL=ON\n'})
        with tmp:self.assertEqual(compat.audit(root)['result'],'FAIL')

    def test_arch_flags_fail_but_baseline_flags_pass(self):
        tmp,root=tree({'engine/CMakeLists.txt':'target_compile_options(x PRIVATE /arch:AVX2)\n'})
        with tmp:self.assertEqual(compat.audit_flags([root/'engine/CMakeLists.txt'])['status'],'FAIL')
        tmp,root=tree({'engine/CMakeLists.txt':'target_compile_options(x PRIVATE /utf-8 /W4 /sdl -march=x86-64-v2)\n'})
        with tmp:self.assertEqual(compat.audit_flags([root/'engine/CMakeLists.txt'])['status'],'PASS')

    def test_prebuilt_runtimes_are_never_passed_statically(self):
        tmp,root=tree({'.tools/ocr-runtime/onnxruntime.dll':'x'})
        with tmp:
            statuses={c['check']:c['status'] for c in compat.audit(root)['checks']}
            self.assertEqual(statuses['prebuilt runtime: ONNX Runtime 1.24.4 (retrieval, OCR)'],'NOT_VERIFIED')
            self.assertNotIn('PASS',[v for k,v in statuses.items() if k.startswith('prebuilt')])

    def test_missing_build_is_not_verified(self):
        tmp,root=tree({})
        with tmp:self.assertEqual(compat.audit_ggml(root/'build/whisper/CMakeCache.txt')['status'],'NOT_VERIFIED')


class HardwareProfile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.p=hardware_profile.profile()

    def test_reports_required_fields(self):
        p=self.p
        self.assertGreater(p['memory']['total_bytes'],1<<30);self.assertGreater(p['cpu']['logical_processors'],0)
        for f in ('sse4_2','avx','avx2'):self.assertIn(f,p['cpu']['features'])
        self.assertIsInstance(p['cpu']['meets_lens_baseline'],bool)
        self.assertIn('build',p['windows']);self.assertIn('ac_online',p['power'])

    def test_contains_no_host_or_user_identity(self):
        text=json.dumps(self.p,ensure_ascii=False).lower()
        for ident in {socket.gethostname(),getpass.getuser()}:
            if len(ident)>=3:self.assertNotIn(ident.lower(),text)


if __name__=='__main__':unittest.main()
