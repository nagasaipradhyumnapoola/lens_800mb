"""Create an explicit native developer bundle; never copy a workspace recursively."""
import hashlib
import json
from pathlib import Path
import shutil
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def main():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target = ROOT / 'artifacts' / ('lens-micro-0.1.0-dev-' + stamp)
    target.mkdir(parents=True, exist_ok=False)
    sources = [
        'scripts/lens.ps1', 'engine/model-registry.json',
        'data/fixtures/extraction-tools.json', 'LICENSES.md',
        'third_party/model-lock.json', 'third_party/ocr-runtime-lock.json',
        'third_party/sherpa-reference-lock.json', 'third_party/upstream-lock.json',
        'third_party/build-lock.json',
    ]
    sources += ['build/engine/Release/' + name for name in [
        'lens-engine.exe', 'lens-needle.exe', 'lens-ocr.exe', 'lens-sherpa.exe',
        'sqlcipher.dll', 'libcrypto-3-x64.dll', 'libssl-3-x64.dll',
    ]]
    sources += [p.relative_to(ROOT).as_posix() for p in (ROOT / 'third_party/licenses').glob('*') if p.is_file()]
    lock = json.loads((ROOT / 'third_party/model-lock.json').read_text(encoding='utf-8'))
    selected = {'ggml-base-q5_1.bin', 'ggml-small-q5_1.bin', 'needle3.cact',
                'windows-x86_64/libneedle3.dll'}
    sources += [r['path'] for r in lock if r['filename'] in selected]
    ocr = json.loads((ROOT / 'third_party/ocr-runtime-lock.json').read_text(encoding='utf-8'))
    sources += [r['path'] for r in ocr['exports']]
    sources += [r['path'] for r in ocr['runtime_artifacts'] if r['path'].endswith('.dll')]
    sherpa = json.loads((ROOT / 'third_party/sherpa-reference-lock.json').read_text(encoding='utf-8'))
    sources += [r['path'] for r in sherpa['models']]
    sources += [r['path'] for r in sherpa['runtime_artifacts'] if '/lib/' in r['path'] and r['path'].endswith('.dll')]
    # Validate all pinned model/runtime entries before copying any of them.
    for r in lock + ocr['exports'] + ocr['runtime_artifacts'] + sherpa['models'] + sherpa['runtime_artifacts']:
        if r['path'] in sources:
            raw = (ROOT / r['path']).read_bytes()
            if len(raw) != r['bytes'] or hashlib.sha256(raw).hexdigest() != r['sha256']:
                raise RuntimeError('Staging refused: artifact differs from lock: ' + r['path'])
    for relative in sorted(set(sources)):
        source = (ROOT / relative).resolve()
        source.relative_to(ROOT.resolve())
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    (target / 'README.md').write_text('''# Lens Micro 0.1.0-dev native developer bundle

Requires Windows x64, PowerShell 7 and the MSVC runtime already present on the audited host.
Clean-machine runtime prerequisites and redistribution are not yet certified.
No Python interpreter, model API or development checkout is needed to run these commands.
Open PowerShell in this folder:

```powershell
pwsh -NoProfile -File scripts/lens.ps1 -Action Stats
pwsh -NoProfile -File scripts/lens.ps1 -Action ImportAudio -Language en -SourcePath 'C:\\YourFiles\\consented.wav'
pwsh -NoProfile -File scripts/lens.ps1 -Action ImportImage -Language es -SourcePath 'C:\\YourFiles\\text-crop.png'
pwsh -NoProfile -File scripts/lens.ps1 -Action Search -Query 'Ana'
```

English uses Whisper Base Q5_1; Spanish uses Small Q5_1; Mandarin/Hindi use Dolphin int8.
Hindi speech remains experimental and fails the accuracy target. OCR accepts text crops only.
Needle extraction returns untrusted proposals and executes no actions; its quality target fails.
Literal source retrieval can return not_found. No natural-language answer generation is included.
The default database is data/private/lens.db with a per-user DPAPI-protected .key file.
Preserve both files on this Windows profile; portable backup/key transfer is not implemented.
This bundle contains no personal database, datasets, sample audio or captured user information.
All selected language models and current engine features are included; the original 500 MB
target does not remove features. No Android/Wear or consumer UI release is claimed.
See LICENSES.md and third_party/licenses for upstream attribution. Lens source has no selected
distribution license. This is a local developer artifact and has not been published.
''', encoding='utf-8')
    files = [{'path': p.relative_to(target).as_posix(), 'bytes': p.stat().st_size,
              'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in sorted(target.rglob('*')) if p.is_file()]
    (target / 'bundle-manifest.json').write_text(json.dumps({
        'version': '0.1.0-dev', 'files': files,
        'manifest_excludes_itself': True,
    }, indent=2), encoding='utf-8')
    report = {'directory': str(target), 'file_count': len(files) + 1,
              'total_bytes': sum(p.stat().st_size for p in target.rglob('*') if p.is_file()),
              'manifest_sha256': hashlib.sha256((target / 'bundle-manifest.json').read_bytes()).hexdigest(),
              'scope': 'native developer bundle; not installed app/device measurement',
              'prerequisites': ['Windows x64', 'PowerShell 7', 'installed MSVC runtime'],
              'clean_machine_validated': False, 'files': files}
    (ROOT / 'reports/staged-bundle.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'files'}, indent=2))


if __name__ == '__main__':
    main()
