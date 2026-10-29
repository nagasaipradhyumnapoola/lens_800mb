#!/usr/bin/env bash
# whisper.cpp at the commit pinned in third_party/upstream-lock.json, with the Lens RAM patches applied (sha256-checked):
# the same source the Windows build uses. Skipped when third_party/whisper.cpp already exists.
set -euo pipefail
[ -d third_party/whisper.cpp/.git ] && { echo "whisper.cpp present"; exit 0; }
read -r URL COMMIT < <(python3 -c "import json;d=next(x for x in json.load(open('third_party/upstream-lock.json'))['dependencies'] if x['repository']=='ggml-org/whisper.cpp');print(d['url'],d['commit'])")
git clone --filter=blob:none "$URL" third_party/whisper.cpp
git -C third_party/whisper.cpp checkout --detach "$COMMIT"
python3 - <<'EOF'
import hashlib,json
d=next(x for x in json.load(open('third_party/upstream-lock.json'))['dependencies'] if x['repository']=='ggml-org/whisper.cpp')
for p in d['patches']:
    if hashlib.sha256(open(p['path'],'rb').read()).hexdigest()!=p['sha256']:raise SystemExit('patch hash mismatch: '+p['path'])
EOF
git -C third_party/whisper.cpp apply "$PWD"/third_party/overlays/whisper.cpp/*.patch
echo "whisper.cpp $COMMIT + patches"
