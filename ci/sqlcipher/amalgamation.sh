#!/usr/bin/env bash
# SQLCipher 4.19.0 (the version the Windows build pins: third_party/overlays/sqlcipher) as a single-file amalgamation for platforms without a SQLCipher
# package (Android, iOS): sqlite3.c + include/sqlcipher/sqlite3.h, compiled into the engine by engine/portable.cmake
# (LENS_SQLCIPHER_AMALGAMATION) against the platform's OpenSSL. The source tarball is checked against the overlay's SHA-512.
# Usage (repository root, Linux or macOS with tclsh): bash ci/sqlcipher/amalgamation.sh  -> build/sqlcipher-4.19.0/
set -euo pipefail
VERSION=4.19.0
SHA512=17083306b4e5f4236810b318cbca4c101fa02184f57d90261fd9b2e71c6dbce7d6e6f7586f3f7410a38c49453967a0068938200b434ca3972e19648f810761ef
OUT="$PWD/build/sqlcipher-$VERSION"
WORK=$(mktemp -d)
curl -fsSL -o "$WORK/src.tgz" "https://github.com/sqlcipher/sqlcipher/archive/refs/tags/v$VERSION.tar.gz"
echo "$SHA512  $WORK/src.tgz" | sha512sum -c - 2>/dev/null || echo "$SHA512  $WORK/src.tgz" | shasum -a 512 -c -
tar -xzf "$WORK/src.tgz" -C "$WORK"
cd "$WORK/sqlcipher-$VERSION"
./configure --with-tempstore=yes --disable-tcl CFLAGS="-DSQLITE_HAS_CODEC" >/dev/null
make sqlite3.c >/dev/null
mkdir -p "$OUT/include/sqlcipher"
cp sqlite3.c "$OUT/"; cp sqlite3.h sqlite3ext.h "$OUT/include/sqlcipher/"
rm -rf "$WORK"
echo "amalgamation: $OUT"
