"""Exercise the staged native client against public/synthetic fixtures outside its folder."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    report = json.loads((ROOT / 'reports/staged-bundle.json').read_text(encoding='utf-8'))
    bundle = Path(report['directory'])
    assert hashlib.sha256((bundle / 'bundle-manifest.json').read_bytes()).hexdigest() == report['manifest_sha256']
    actual_files = [p for p in bundle.rglob('*') if p.is_file()]
    assert len(actual_files) == report['file_count']
    assert sum(p.stat().st_size for p in actual_files) == report['total_bytes']
    for record in report['files']:
        if hashlib.sha256((bundle / record['path']).read_bytes()).hexdigest() != record['sha256']:
            raise RuntimeError('Bundle digest mismatch')
    checks = []
    with tempfile.TemporaryDirectory(prefix='lens-bundle-check-') as temp:
        db = Path(temp) / 'public-fixtures.db'

        def run(name, *args):
            start = time.perf_counter()
            result = subprocess.run(['pwsh', '-NoProfile', '-File', str(bundle / 'scripts/lens.ps1'),
                                     '-DatabasePath', str(db), *args], cwd=temp,
                                    capture_output=True, encoding='utf-8', timeout=180)
            if result.returncode:
                raise RuntimeError('Staged check failed: ' + name)
            value = json.loads(result.stdout)
            if value.get('ok') is False:
                raise RuntimeError('Staged native request rejected: ' + name)
            checks.append({'name': name, 'elapsed_ms': (time.perf_counter() - start) * 1000,
                           'stderr_empty': not bool(result.stderr)})
            return value

        run('stats', '-Action', 'Stats')
        run('text_import', '-Action', 'ImportText', '-Text', 'BundleSentinel 北京记忆', '-Language', 'zh', '-Id', 'bundle-text')
        samples = json.loads((ROOT / 'data/fixtures/fleurs-smoke.json').read_text(encoding='utf-8'))['samples']
        for lang in ['en', 'es', 'zh', 'hi']:
            sample = next(s for s in samples if s['language'] == lang)
            value = run('audio_' + lang, '-Action', 'ImportAudio', '-Language', lang,
                        '-SourcePath', str(ROOT / sample['path']), '-Id', 'bundle-audio-' + lang)
            assert value['transcript']['text'].strip()
            assert run('source_reopen_' + lang, '-Action', 'Search', '-Query', value['transcript']['text'])['sources']
        for lang in ['en', 'es', 'zh', 'hi']:
            value = run('ocr_' + lang, '-Action', 'ImportImage', '-Language', lang,
                        '-SourcePath', str(ROOT / 'artifacts/ocr-smoke' / (lang + '.png')), '-Id', 'bundle-ocr-' + lang)
            assert value['recognition']['text'].strip()
        value = run('extraction_proposal', '-Action', 'Extract', '-Text', 'Schedule a meeting with Ana tomorrow at 3 PM in Madrid.')
        assert 'no actions executed' in value['lens_status']
        assert run('literal_retrieval', '-Action', 'Search', '-Query', '北京记忆')['sources'][0]['id'] == 'bundle-text'
        assert run('not_found', '-Action', 'Search', '-Query', 'NonexistentBundleAnswer59421')['not_found']
        assert b'BundleSentinel' not in db.read_bytes()
        assert not db.read_bytes().startswith(b'SQLite format 3')
        assert Path(str(db) + '.key').exists()
        checks.append({'name': 'encrypted_database_and_dpapi_key', 'passed': True})
    result = {'success': True, 'bundle': str(bundle), 'checks': checks,
              'fixtures': 'public FLEURS speech and Lens-authored synthetic text crops; not private capture',
              'controller': 'Python development harness; all product operations use staged PowerShell/native workers',
              'network_restriction': 'not imposed; offline gate remains pending',
              'clean_machine_validation': False}
    (ROOT / 'reports/staged-bundle-check.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'success': True, 'check_count': len(checks), 'bundle': str(bundle)}, indent=2))


if __name__ == '__main__':
    main()
