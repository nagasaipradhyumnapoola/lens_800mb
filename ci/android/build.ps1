# Android build of the portable Lens core on a Windows host: NDK r27.1 toolchain chained through vcpkg
# (OpenSSL, zstd, utf8proc, nlohmann-json for the ABI's triplet), the pinned SQLCipher 4.19.0 amalgamation, and ONNX Runtime's
# C API headers (the engine loads libonnxruntime.so at run time; the app ships it from the official AAR).
# Prerequisites: vcpkg install openssl zstd utf8proc nlohmann-json --triplet arm64-android (x64-android for x86_64);
# build/sqlcipher-4.19.0 (ci/sqlcipher/amalgamation.sh, e.g. in the Linux container).
# Usage (repository root): powershell ci/android/build.ps1 [-Abi arm64-v8a|x86_64] [-CoreOnly]
# -Abi x86_64 is for the emulator; -CoreOnly builds only liblens-core.so (the app's in-process memory core). Either way
# liblens-core.so is staged in android/native-libs/<abi>/ for Gradle.
param([ValidateSet('arm64-v8a', 'x86_64')][string]$Abi = 'arm64-v8a', [switch]$CoreOnly)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
$ndk = "$env:LOCALAPPDATA\Android\Sdk\ndk\27.1.12297006"
$vs = 'C:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\CMake'
$cmake = "$vs\CMake\bin\cmake.exe"; $ninja = "$vs\Ninja\ninja.exe"
$triplet = @{ 'arm64-v8a' = 'arm64-android'; 'x86_64' = 'x64-android' }[$Abi]
$out = "$root\build\" + @{ 'arm64-v8a' = 'android-arm64'; 'x86_64' = 'android-x86_64' }[$Abi]
$headers = "$root\build\onnxruntime-1.24.4-headers"
if (-not (Test-Path "$headers\include\onnxruntime_cxx_api.h")) {
  $tgz = "$env:TEMP\ort-linux-x64-1.24.4.tgz"
  Invoke-WebRequest -UseBasicParsing 'https://github.com/microsoft/onnxruntime/releases/download/v1.24.4/onnxruntime-linux-x64-1.24.4.tgz' -OutFile $tgz
  $want = (Get-Content "$root\ci\linux\onnxruntime.sha256").Split(' ')[0]
  if ((Get-FileHash $tgz -Algorithm SHA256).Hash.ToLower() -ne $want) { throw 'ONNX Runtime archive hash mismatch' }
  New-Item -ItemType Directory -Force $headers | Out-Null
  tar -xzf $tgz -C $headers --strip-components=1 'onnxruntime-linux-x64-1.24.4/include'; Remove-Item $tgz
}
# sherpa-onnx's C API header for lens-sherpa: the v2.0.0 SDK copy (same text as the pinned source, ci/fetch_sherpa_header.sh).
$sherpa = "$root\.tools\sherpa-runtime\sherpa-onnx-v2.0.0-win-x64-shared-MD-Release-no-tts\include"
if (-not (Test-Path "$sherpa\sherpa-onnx\c-api\c-api.h")) { $sherpa = '' }
& $cmake -S "$root\engine" -B $out -G Ninja "-DCMAKE_MAKE_PROGRAM=$ninja" -DCMAKE_BUILD_TYPE=Release `
  "-DCMAKE_TOOLCHAIN_FILE=$root\third_party\vcpkg\scripts\buildsystems\vcpkg.cmake" "-DVCPKG_CHAINLOAD_TOOLCHAIN_FILE=$ndk\build\cmake\android.toolchain.cmake" `
  "-DVCPKG_TARGET_TRIPLET=$triplet" "-DANDROID_ABI=$Abi" -DANDROID_PLATFORM=android-29 `
  "-DLENS_SQLCIPHER_AMALGAMATION=$root\build\sqlcipher-4.19.0" "-DLENS_ORT_DIR=$headers" "-DLENS_SHERPA_INCLUDE=$sherpa"
if ($LASTEXITCODE) { throw "configure failed ($LASTEXITCODE)" }
if ($CoreOnly) { & $cmake --build $out --parallel --target lens-core } else { & $cmake --build $out --parallel }
if ($LASTEXITCODE) { throw "build failed ($LASTEXITCODE)" }
New-Item -ItemType Directory -Force "$root\android\native-libs\$Abi" | Out-Null
Copy-Item "$out\bin\liblens-core.so" "$root\android\native-libs\$Abi\" -Force
Get-ChildItem "$out\bin" | Select-Object Name, Length
