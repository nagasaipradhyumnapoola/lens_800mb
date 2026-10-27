"""Static CPU-instruction compatibility audit (docs/acceptance-gates.md, "Instruction compatibility (static)").

Rule (docs/LENS_V1_SPEC.md §15): the baseline is x86-64 with SSE4.2 + POPCNT; AVX, AVX2, AVX-512, FMA, F16C,
BMI2 and VNNI may only be used behind runtime CPU dispatch. This audit checks the build configurations Lens
controls and lists the prebuilt runtimes whose behaviour on a CPU without AVX/AVX2 still needs a dynamic test
(an H3 machine or an instruction-set emulator). It never marks an unverified prebuilt binary as passing.
Usage: .venv\\Scripts\\python.exe scripts/check_hardware_compat.py [--out reports/hardware/compat-audit.json]
Exit code: 0 when no check FAILs (NOT_VERIFIED items remain listed), 1 otherwise.
"""
import argparse
import json
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]
# ggml options that compile ISA extensions into ggml-cpu unconditionally unless the CPU backend is built as
# runtime-selected variants (GGML_BACKEND_DL + GGML_CPU_ALL_VARIANTS).
GGML_ISA=['GGML_AVX','GGML_AVX2','GGML_AVX512','GGML_AVX512_VBMI','GGML_AVX512_VNNI','GGML_AVX512_BF16','GGML_AVX_VNNI',
          'GGML_FMA','GGML_F16C','GGML_BMI2','GGML_AMX_TILE','GGML_AMX_INT8','GGML_AMX_BF16']
ARCH=re.compile(r'/arch:(AVX\S*)|-m(avx\S*|fma|f16c|bmi2)|-march=(?!x86-64(?:-v2)?\b)\S+',re.I)
# Prebuilt third-party runtimes: dynamic verification required before any compatibility claim.
PREBUILT=[('ONNX Runtime 1.24.4 (retrieval, OCR)','.tools/ocr-runtime/onnxruntime.dll'),
          ('sherpa-onnx 2.0.0 bundled ONNX Runtime','.tools/sherpa-runtime/sherpa-onnx-v2.0.0-win-x64-shared-MD-Release-no-tts/bin/onnxruntime.dll'),
          ('SQLCipher / OpenSSL (vcpkg x64-windows)','build/engine/Release/libcrypto-3-x64.dll'),
          ('Needle3 published native engine','third_party/needle')]


def cmake_cache(path):
    out={}
    for line in Path(path).read_text(encoding='utf-8',errors='replace').splitlines():
        m=re.match(r'^([A-Za-z0-9_]+):[A-Z]+=(.*)$',line)
        if m:out[m.group(1)]=m.group(2)
    return out


def on(cache,key):return cache.get(key,'').upper() in ('ON','TRUE','1','YES')


def audit_ggml(cache_path):
    if not Path(cache_path).exists():return {'check':'ggml CPU backend ISA','status':'NOT_VERIFIED','detail':f'missing {cache_path}'}
    c=cmake_cache(cache_path);isa=[k for k in GGML_ISA if on(c,k)]
    dispatch=on(c,'GGML_BACKEND_DL') and on(c,'GGML_CPU_ALL_VARIANTS')
    if on(c,'GGML_NATIVE'):return {'check':'ggml CPU backend ISA','status':'FAIL','detail':'GGML_NATIVE=ON targets the build machine CPU'}
    if isa and not dispatch:
        return {'check':'ggml CPU backend ISA','status':'FAIL','detail':f'compiled unconditionally: {", ".join(isa)}; '
                'no runtime dispatch (needs GGML_BACKEND_DL=ON and GGML_CPU_ALL_VARIANTS=ON)'}
    return {'check':'ggml CPU backend ISA','status':'PASS','detail':'runtime-selected CPU variants' if dispatch else 'baseline ISA only'}


def audit_flags(paths):
    hits=[]
    for p in paths:
        p=Path(p)
        if not p.exists():continue
        text=p.read_text(encoding='utf-8',errors='replace')
        if p.name=='CMakeCache.txt':text='\n'.join(f'{k}={v}' for k,v in cmake_cache(p).items() if 'FLAGS' in k)
        hits+=[f'{p.name}: {m.group(0)}' for m in ARCH.finditer(text)]
    return {'check':'Lens native compile flags','status':'FAIL' if hits else 'PASS','detail':'; '.join(hits) or 'no ISA-raising flags (MSVC x64 default: SSE2)'}


def audit_links(cmakelists,ggml_result):
    text=Path(cmakelists).read_text(encoding='utf-8') if Path(cmakelists).exists() else ''
    linked=sorted({m.group(1) for m in re.finditer(r'target_link_libraries\(([\w-]+)([^)]*)\)',text) if 'ggml-cpu.lib' in m.group(2)})
    status='FAIL' if 'lens-engine' in linked and ggml_result['status']=='FAIL' else 'INFO'
    return {'check':'binaries linking the ggml CPU backend','status':status,
            'detail':('lens-engine.exe links ggml-cpu in-process, so the engine itself inherits the unconditional ISA'
                      if status=='FAIL' else 'see ggml check')+f'; executables: {", ".join(linked) or "none"}'}


def audit_models(root):
    names=sorted(p.relative_to(root).as_posix() for p in Path(root,'models').rglob('*avx512*.onnx')) if Path(root,'models').exists() else []
    return {'check':'ISA-named ONNX model variants','status':'INFO',
            'detail':'ONNX graphs run on any CPU through ONNX Runtime kernels; speed on CPUs without that ISA must be '
                     f'measured per tier: {", ".join(names) or "none"}'}


def whisper_build(root):
    """The whisper.cpp build directory engine/CMakeLists.txt links against (default build/whisper)."""
    text=Path(root,'engine/CMakeLists.txt').read_text(encoding='utf-8') if Path(root,'engine/CMakeLists.txt').exists() else ''
    m=re.search(r'set\(WHISPER_BUILD\s+"\$\{LENS_ROOT\}/([^"]+)"\)',text)
    return Path(root,m.group(1) if m else 'build/whisper')


def audit_baseline_variant(root,ggml_result):
    release=Path(root,'build/engine/Release')
    if 'runtime-selected' not in ggml_result.get('detail',''):return None
    ok=(release/'ggml-cpu-x64.dll').exists()
    return {'check':'baseline ggml CPU variant shipped beside the engine','status':'PASS' if ok else 'FAIL',
            'detail':'ggml-cpu-x64.dll (SSE2) present' if ok else 'ggml-cpu-x64.dll missing: CPUs without SSE4.2/AVX would lose ASR'}


def audit(root=ROOT):
    ggml=audit_ggml(whisper_build(root)/'CMakeCache.txt')
    checks=[ggml,audit_flags([Path(root,'engine/CMakeLists.txt'),Path(root,'build/engine/CMakeCache.txt')]),
            audit_links(Path(root,'engine/CMakeLists.txt'),ggml),audit_models(root)]
    checks+=[c for c in [audit_baseline_variant(root,ggml)] if c]
    checks+=[{'check':f'prebuilt runtime: {name}','status':'NOT_VERIFIED' if Path(root,path).exists() else 'ABSENT',
              'detail':'requires a dynamic run on a CPU without AVX/AVX2 (H3 machine or emulator)'} for name,path in PREBUILT]
    return {'baseline':'x86-64 SSE4.2 + POPCNT','checks':checks,'result':'FAIL' if any(c['status']=='FAIL' for c in checks) else 'PASS_STATIC'}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path);args=ap.parse_args()
    r=audit();text=json.dumps(r,indent=1)
    if args.out:args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(text+'\n',encoding='utf-8')
    print(text);raise SystemExit(1 if r['result']=='FAIL' else 0)


if __name__=='__main__':main()
