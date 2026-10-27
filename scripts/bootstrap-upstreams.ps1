$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$lock=Get-Content -LiteralPath third_party/upstream-lock.json -Raw | ConvertFrom-Json
$build=Get-Content -LiteralPath third_party/build-lock.json -Raw | ConvertFrom-Json
$sources=@()
foreach($name in @('ggml-org/whisper.cpp','cactus-compute/needle')) {
  $item=$lock.dependencies | Where-Object repository -eq $name
  $sources+=@{url=$item.url+'.git';commit=$item.commit;path='third_party/'+($name.Split('/')[-1])}
}
$sources+=@{url=$build.vcpkg_repository;commit=$build.vcpkg_commit;path='third_party/vcpkg'}
foreach($source in $sources) {
  if(Test-Path -LiteralPath $source.path) {
    $actual=& git -C $source.path rev-parse HEAD
    if($LASTEXITCODE -ne 0 -or $actual -ne $source.commit){throw "Existing upstream differs from lock: $($source.path). Preserving it."}
  } else {
    & git clone --filter=blob:none --no-checkout $source.url $source.path
    if($LASTEXITCODE -ne 0){throw 'Upstream clone failed'}
    & git -C $source.path fetch --depth 1 origin $source.commit
    if($LASTEXITCODE -ne 0){throw 'Pinned commit fetch failed'}
    & git -C $source.path checkout --detach $source.commit
    if($LASTEXITCODE -ne 0){throw 'Pinned checkout failed'}
  }
}
if(!(Test-Path -LiteralPath third_party/vcpkg/vcpkg.exe)) {
  & third_party/vcpkg/bootstrap-vcpkg.bat -disableMetrics
  if($LASTEXITCODE -ne 0){throw 'Project-local vcpkg bootstrap failed'}
}
