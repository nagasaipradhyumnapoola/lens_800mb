#!/usr/bin/env bash
# Builds the portable Lens core inside ci/linux/Dockerfile and runs the smoke test (ci/linux/smoke.py). SQLCipher is the
# pinned 4.19.0 amalgamation (ci/sqlcipher/amalgamation.sh) with the Windows build's options, on every platform.
# Usage (repository root): docker build -t lens-linux ci/linux && docker run --rm -v "$PWD:/src" lens-linux bash ci/linux/build.sh
set -euo pipefail
[ -f build/sqlcipher-4.19.0/sqlite3.c ] || bash ci/sqlcipher/amalgamation.sh
[ -f build/sherpa-onnx-include/sherpa-onnx/c-api/c-api.h ] || bash ci/fetch_sherpa_header.sh
bash ci/fetch_stb.sh
cmake -S engine -B build/linux -G Ninja -DCMAKE_BUILD_TYPE=Release -DLENS_ORT_DIR=/opt/onnxruntime \
      -DLENS_SQLCIPHER_AMALGAMATION="$PWD/build/sqlcipher-4.19.0" -DLENS_SHERPA_INCLUDE="$PWD/build/sherpa-onnx-include"
cmake --build build/linux --parallel
cp -f /opt/onnxruntime/lib/libonnxruntime.so* build/linux/bin/
# The Secret Service needs a session bus and an unlocked keyring; a throwaway one per run (test data only).
dbus-run-session -- bash -c 'eval "$(echo -n lens-ci | gnome-keyring-daemon --unlock --components=secrets)" && python3 ci/linux/smoke.py build/linux/bin'
