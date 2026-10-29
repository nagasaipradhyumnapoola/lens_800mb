# Android (arm64-v8a) build of the portable Lens core on a Windows host: NDK r27.1 toolchain chained through vcpkg
# (OpenSSL, zstd, utf8proc, nlohmann-json for arm64-android), the pinned SQLCipher 4.19.0 amalgamation, and ONNX Runtime's
# C API headers (the engine loads libonnxruntime.so at run time; the app ships it from the official AAR).
# Prerequisites: vcpkg install openssl zstd utf8proc nlohmann-json --triplet arm64-android; build/sqlcipher-4.19.0
# (ci/sqlcipher/amalgamation.sh, e.g. in the Linux container). Usage (repository root): powershell ci/android/build.ps1
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
$ndk = "$env:LOCALAPPDATA\Android\Sdk\ndk\27.1.12297006"
$vs = 'C:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\CMake'
$cmake = "$vs\CMake\bin\cmake.exe"; $ninja = "$vs\Ninja\ninja.exe"
$headers = "$root\build\onnxruntime-1.24.4-headers"
if (-not (Test-Path "$headers\include\onnxruntime_cxx_api.h")) {
  $tgz = "$env:TEMP\ort-linux-x64-1.24.4.tgz"
  Invoke-WebRequest -UseBasicParsing 'https://github.com/microsoft/onnxruntime/releases/download/v1.24.4/onnxruntime-linux-x64-1.24.4.tgz' -OutFile $tgz
  $want = (Get-Content "$root\ci\linux\onnxruntime.sha256").Split(' ')[0]
  if ((Get-FileHash $tgz -Algorithm SHA256).Hash.ToLower() -ne $want) { throw 'ONNX Runtime archive hash mismatch' }
  New-Item -ItemType Directory -Force $headers | Out-Null
  tar -xzf $tgz -C $headers --strip-components=1 'onnxruntime-linux-x64-1.24.4/include'; Remove-Item $tgz
}
& $cmake -S "$root\engine" -B "$root\build\android-arm64" -G Ninja "-DCMAKE_MAKE_PROGRAM=$ninja" -DCMAKE_BUILD_TYPE=Release `
  "-DCMAKE_TOOLCHAIN_FILE=$root\third_party\vcpkg\scripts\buildsystems\vcpkg.cmake" "-DVCPKG_CHAINLOAD_TOOLCHAIN_FILE=$ndk\build\cmake\android.toolchain.cmake" `
  -DVCPKG_TARGET_TRIPLET=arm64-android -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-29 `
  "-DLENS_SQLCIPHER_AMALGAMATION=$root\build\sqlcipher-4.19.0" "-DLENS_ORT_DIR=$headers"
if ($LASTEXITCODE) { throw "configure failed ($LASTEXITCODE)" }
& $cmake --build "$root\build\android-arm64" --parallel
if ($LASTEXITCODE) { throw "build failed ($LASTEXITCODE)" }
Get-ChildItem "$root\build\android-arm64\bin" | Select-Object Name, Length
