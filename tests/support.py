"""Shared test helpers: resolve the pinned project-local PowerShell, never an arbitrary host copy first."""
import json
from pathlib import Path
import shutil
ROOT=Path(__file__).resolve().parents[1]


def pwsh():
    lock=json.loads((ROOT/'third_party/pwsh-lock.json').read_text(encoding='utf-8'))
    local=ROOT/lock['install_path']/'pwsh.exe'
    if local.is_file():return str(local)
    found=shutil.which('pwsh')
    if found:return found
    raise RuntimeError('PowerShell 7 unavailable: run .venv\\Scripts\\python.exe scripts/bootstrap_pwsh.py')
