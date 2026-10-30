#!/usr/bin/env bash
# stb_image.h at the commit pinned in third_party/upstream-lock.json (sha256-checked), for lens-ocr's image decoding
# outside Windows. Output: third_party/stb/{stb_image.h,LICENSE}
set -euo pipefail
[ -f third_party/stb/stb_image.h ] && { echo "stb present"; exit 0; }
mkdir -p third_party/stb
python3 - <<'EOF'
import hashlib,json,urllib.request
d=next(x for x in json.load(open('third_party/upstream-lock.json'))['dependencies'] if x['repository']=='nothings/stb')
for name,want in [(f['path'],f['sha256']) for f in d['files']]+[(d['license_path'],d['license_sha256'])]:
    data=urllib.request.urlopen(f"https://raw.githubusercontent.com/nothings/stb/{d['commit']}/{name}",timeout=60).read()
    if hashlib.sha256(data).hexdigest()!=want:raise SystemExit('stb hash mismatch: '+name)
    open('third_party/stb/'+name,'wb').write(data)
print('stb',d['commit'])
EOF
