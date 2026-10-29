#!/usr/bin/env bash
# sherpa-onnx's C API header at the commit pinned in third_party/upstream-lock.json (sha256-checked; identical to the
# v2.0.0 SDK header the Windows build uses). lens-sherpa loads the sherpa-onnx library at run time, so the header is all
# the build needs. Output: build/sherpa-onnx-include/sherpa-onnx/c-api/c-api.h
set -euo pipefail
out=build/sherpa-onnx-include/sherpa-onnx/c-api
[ -f "$out/c-api.h" ] && { echo "sherpa-onnx header present"; exit 0; }
COMMIT=$(python3 -c "import json;print(next(x for x in json.load(open('third_party/upstream-lock.json'))['dependencies'] if x['repository']=='k2-fsa/sherpa-onnx')['commit'])")
mkdir -p "$out"
curl -fsSL -o "$out/c-api.h" "https://raw.githubusercontent.com/k2-fsa/sherpa-onnx/$COMMIT/sherpa-onnx/c-api/c-api.h"
want=9764470f09d219d6e7a80c6950059502c900ef82691ed6bea260d8ce9518f78a
got=$( (sha256sum "$out/c-api.h" 2>/dev/null || shasum -a 256 "$out/c-api.h") | cut -d' ' -f1)
[ "$got" = "$want" ] || { rm -f "$out/c-api.h"; echo "sherpa-onnx header hash mismatch: $got"; exit 1; }
echo "sherpa-onnx header $COMMIT"
