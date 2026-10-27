param([switch]$Dependencies)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$vswhere='C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe'
$cmake=& $vswhere -latest -products '*' -find '**\cmake.exe' | Select-Object -First 1
if(!$cmake){throw 'Existing Visual Studio CMake not found. No system install is performed.'}
if($Dependencies) {
  $env:VCPKG_DISABLE_METRICS='1';$env:VCPKG_MAX_CONCURRENCY='2'
  & third_party\vcpkg\vcpkg.exe install 'sqlcipher[fts5,tool]:x64-windows' nlohmann-json:x64-windows --overlay-ports=third_party/overlays --disable-metrics
  if($LASTEXITCODE -ne 0){throw 'SQLCipher dependencies failed'}
}
& $cmake -S third_party/whisper.cpp -B build/whisper -G 'Visual Studio 18 2026' -A x64 -DBUILD_SHARED_LIBS=OFF -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_SERVER=OFF -DGGML_OPENMP=OFF -DGGML_NATIVE=OFF
if($LASTEXITCODE -ne 0){throw 'whisper configuration failed'}
& $cmake --build build/whisper --config Release --target whisper-cli -j 2
if($LASTEXITCODE -ne 0){throw 'whisper build failed'}
& $cmake -S engine -B build/engine -G 'Visual Studio 18 2026' -A x64 -DCMAKE_PREFIX_PATH="$root/third_party/vcpkg/installed/x64-windows"
if($LASTEXITCODE -ne 0){throw 'Lens configuration failed'}
& $cmake --build build/engine --config Release -j 2
if($LASTEXITCODE -ne 0){throw 'Lens native build failed'}
$bin=Join-Path $root 'build/engine/Release'
foreach($file in @('sqlcipher.dll','libcrypto-3-x64.dll','libssl-3-x64.dll')) {
  $from=Join-Path $root "third_party/vcpkg/installed/x64-windows/bin/$file"
  if(Test-Path -LiteralPath $from){Copy-Item -LiteralPath $from -Destination $bin -Force}
}
if(!(Test-Path -LiteralPath (Join-Path $bin 'lens-engine.exe'))){throw 'SQLCipher-backed engine was not built'}
