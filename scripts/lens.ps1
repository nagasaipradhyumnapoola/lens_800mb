param(
  [Parameter(Mandatory=$true)][ValidateSet('ImportText','ImportAudio','ImportImage','Search','Stats','Delete','Extract','Timeline','Source','Context','Recall','Index')][string]$Action,
  [string]$Text,[string]$SourcePath,[string]$Query,[string]$Id,[string]$Language='auto',
  [string]$DatabasePath,[string]$OriginalTimestamp,[string]$SourceTimeZone,[string]$SourceApplication,
  [string]$SourceLocator,[string]$FromTimestamp,[string]$UntilTimestamp,
  [ValidateSet('hybrid','semantic','keyword')][string]$Mode='hybrid',[ValidateRange(1,20)][int]$Limit=10
)
$ErrorActionPreference='Stop'
# Output must be UTF-8 regardless of the system ANSI code page; otherwise CJK/Indic text becomes '?'.
$utf8=[Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=$utf8;[Console]::InputEncoding=$utf8;$OutputEncoding=$utf8
try {
# Private text and queries may come from stdin so they never appear in process arguments or shell history.
function ReadStdin([int]$limit) {
  if(![Console]::IsInputRedirected){throw 'stdin_not_redirected'}
  $value=[IO.StreamReader]::new([Console]::OpenStandardInput(),[Text.UTF8Encoding]::new($false,$true)).ReadToEnd()
  if($value.EndsWith("`r`n")){$value=$value.Substring(0,$value.Length-2)}elseif($value.EndsWith("`n")){$value=$value.Substring(0,$value.Length-1)}
  if(!$value){throw 'stdin_empty'}
  if([Text.Encoding]::UTF8.GetByteCount($value) -gt $limit){throw 'stdin_too_large'}
  return $value
}
if($Action -eq 'ImportText' -and !$PSBoundParameters.ContainsKey('Text')){$Text=ReadStdin (1024*1024)}
if($Action -in @('Search','Context','Recall') -and !$PSBoundParameters.ContainsKey('Query')){$Query=ReadStdin 1024}
$root=Split-Path -Parent $PSScriptRoot
if(!$DatabasePath){$DatabasePath=Join-Path $root 'data/private/lens.db'}
$DatabasePath=[IO.Path]::GetFullPath($DatabasePath)
$parent=Split-Path -Parent $DatabasePath
if(!(Test-Path -LiteralPath $parent)){New-Item -ItemType Directory -Path $parent | Out-Null}
function Native([string]$exe,$request,[string[]]$arguments=@()) {
  $info=[Diagnostics.ProcessStartInfo]::new($exe)
  $info.UseShellExecute=$false;$info.CreateNoWindow=$true
  $info.RedirectStandardInput=$true;$info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
  $info.StandardInputEncoding=$utf8;$info.StandardOutputEncoding=$utf8;$info.StandardErrorEncoding=$utf8
  foreach($arg in $arguments){$info.ArgumentList.Add($arg)}
  $process=[Diagnostics.Process]::new();$process.StartInfo=$info
  try {
    if(!$process.Start()){throw 'native_start_failed'}
    $output=$process.StandardOutput.ReadToEndAsync();$errors=$process.StandardError.ReadToEndAsync()
    # An array sends several requests to one process (e.g. import then index without reloading).
    $many=$request -is [array]
    foreach($item in @($request)){$process.StandardInput.WriteLine(($item | ConvertTo-Json -Depth 30 -Compress))}
    $process.StandardInput.Close()
    if(!$process.WaitForExit(180000)){$process.Kill($true);throw 'native_timeout'}
    $result=$output.GetAwaiter().GetResult();$null=$errors.GetAwaiter().GetResult()
    if($process.ExitCode -ne 0){throw "native_request_failed: exit $($process.ExitCode)"}
    $parsed=@($result -split "`n" | Where-Object {$_.Trim()} | ForEach-Object {$_ | ConvertFrom-Json -Depth 30})
    if($many){return ,$parsed}
    return $parsed[0]
  } finally {$process.Dispose()}
}
function VerifyArtifact([string]$path,[string]$expected) {
  if((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected){throw 'model_digest_mismatch'}
}
# Embedding model arguments; every artifact is hash-checked against its committed lock before use.
function EmbeddingArguments {
  $lock=Get-Content -LiteralPath (Join-Path $root 'third_party/embedding-lock.json') -Raw | ConvertFrom-Json
  $model=$lock.files | Where-Object filename -eq 'onnx/model_qint8_avx512_vnni.onnx'
  $tokenizer=$lock.files | Where-Object filename -eq 'onnx/tokenizer.json'
  $ort=(Get-Content -LiteralPath (Join-Path $root 'third_party/ocr-runtime-lock.json') -Raw | ConvertFrom-Json).runtime_artifacts | Where-Object { $_.path.EndsWith('/onnxruntime.dll') }
  foreach($artifact in @($model,$tokenizer,$ort)){VerifyArtifact (Join-Path $root $artifact.path) $artifact.sha256}
  $id='intfloat/multilingual-e5-small@'+$lock.revision.Substring(0,12)+'/onnx/model_qint8_avx512_vnni.onnx#sha256:'+$model.sha256.Substring(0,16)
  $arguments=@('--ort',(Join-Path $root $ort.path),'--embedding-model',(Join-Path $root $model.path),'--embedding-tokenizer',(Join-Path $root $tokenizer.path),'--embedding-id',$id)
  # The multilingual cross-encoder reranks recall results; it is loaded only when a recall needs it.
  $rerankLock=Get-Content -LiteralPath (Join-Path $root 'third_party/reranker-lock.json') -Raw | ConvertFrom-Json
  $reranker=$rerankLock.files | Where-Object filename -eq 'onnx/model_qint8_avx512_vnni.onnx'
  $rerankTokenizer=$rerankLock.files | Where-Object filename -eq 'tokenizer.json'
  foreach($artifact in @($reranker,$rerankTokenizer)){VerifyArtifact (Join-Path $root $artifact.path) $artifact.sha256}
  return $arguments+@('--reranker-model',(Join-Path $root $reranker.path),'--reranker-tokenizer',(Join-Path $root $rerankTokenizer.path))
}
function Memory($request,[switch]$Semantic){
  $arguments=@('--db',$DatabasePath);if($Semantic){$arguments+=EmbeddingArguments}
  Native (Join-Path $root 'build/engine/Release/lens-engine.exe') $request $arguments
}
# Store one source and index it for semantic recall in the same engine process.
function StoreAndIndex($record){
  $replies=Memory @($record,@{op='index'}) -Semantic
  $stored=$replies[0];$stored | Add-Member -NotePropertyName semantic_index -NotePropertyValue $replies[1] -Force
  return $stored
}
$modelLock=Get-Content -LiteralPath (Join-Path $root 'third_party/model-lock.json') -Raw | ConvertFrom-Json
$filters=@{}
if($SourceApplication){$filters.application=$SourceApplication}
if($FromTimestamp){$filters.from=$FromTimestamp}
if($UntilTimestamp){$filters.to=$UntilTimestamp}
if($Action -eq 'Search') {$result=Memory @{op='search';query=$Query;filters=$filters}}
elseif($Action -eq 'Timeline') {$result=Memory @{op='timeline';filters=$filters}}
elseif($Action -eq 'Context') {$result=Memory @{op='retrieve_context';query=$Query;filters=$filters}}
elseif($Action -eq 'Source') {$result=Memory @{op='find_source';id=$Id;filters=$filters}}
elseif($Action -eq 'Stats') {$result=Memory @{op='stats'}}
elseif($Action -eq 'Recall') {
  # Time words in the question ("last week") are interpreted in this machine's current UTC offset.
  $offset=[int][TimeZoneInfo]::Local.GetUtcOffset([DateTime]::UtcNow).TotalMinutes
  $result=Memory @{op='recall';query=$Query;mode=$Mode;limit=$Limit;filters=$filters;utc_offset_minutes=$offset} -Semantic:($Mode -ne 'keyword')
}
elseif($Action -eq 'Index') {$result=Memory @{op='index';limit=4096} -Semantic}
elseif($Action -eq 'Delete') {$result=Memory @{op='delete';id=$Id;consent=$true}}
elseif($Action -eq 'Extract') {
  $base=Join-Path $root 'models/Cactus-Compute--needle3'
  foreach($name in @('needle3.cact','windows-x86_64/libneedle3.dll')) {
    $artifact=$modelLock | Where-Object { $_.repo -eq 'Cactus-Compute/needle3' -and $_.filename -eq $name }
    VerifyArtifact (Join-Path $root $artifact.path) $artifact.sha256
  }
  $result=Native (Join-Path $root 'build/engine/Release/lens-needle.exe') @{
    library=(Join-Path $base 'windows-x86_64/libneedle3.dll');weights=(Join-Path $base 'needle3.cact');text=$Text
    tools=(Get-Content -LiteralPath (Join-Path $root 'data/fixtures/extraction-tools.json') -Raw | ConvertFrom-Json)
  }
  $result | Add-Member -NotePropertyName lens_status -NotePropertyValue 'untrusted proposal; no actions executed' -Force
} else {
  if(!$Id){$Id=[Guid]::NewGuid().ToString()}
  $observed=[DateTime]::UtcNow.ToString('o')
  $record=@{op='add';consent=$true;id=$Id;text=$Text;language=$(if($Language -eq 'auto'){'und'}else{$Language});
    timestamp=$(if($OriginalTimestamp){$OriginalTimestamp}else{$observed});device=[Environment]::MachineName;kind='manual_import';
    original_timestamp=$(if($OriginalTimestamp){$OriginalTimestamp}else{$null});observed_at=$observed;
    timezone=$SourceTimeZone;source_application=$SourceApplication;source_locator=$SourceLocator;
    consent_context=@{mode='explicit_local_import';action=$Action};metadata=@{};
    provenance='explicit local text import';confidence=1.0}
  # PowerShell optional string parameters are null; the native contract uses empty strings.
  foreach($field in @('timezone','source_application','source_locator')){if($null -eq $record[$field]){$record[$field]=''}}
  if($Action -eq 'ImportAudio') {
    $SourcePath=[IO.Path]::GetFullPath($SourcePath)
    if($Language -in @('zh','hi')) {
      $sherpaLock=Get-Content -LiteralPath (Join-Path $root 'third_party/sherpa-reference-lock.json') -Raw | ConvertFrom-Json
      $selectedLock=if($Language -eq 'hi'){Get-Content -LiteralPath (Join-Path $root 'third_party/indic-hindi-lock.json') -Raw | ConvertFrom-Json}else{$sherpaLock}
      $weight=$selectedLock.models | Where-Object { $_.filename -in @('model.int8.onnx','hi/model.int8.onnx') }
      $tokens=$selectedLock.models | Where-Object filename -eq 'tokens.txt'
      $library=$sherpaLock.runtime_artifacts | Where-Object path -Like '*/lib/sherpa-onnx-c-api.dll'
      VerifyArtifact (Join-Path $root $weight.path) $weight.sha256
      VerifyArtifact (Join-Path $root $tokens.path) $tokens.sha256
      VerifyArtifact (Join-Path $root $library.path) $library.sha256
      $recognition=Native (Join-Path $root 'build/engine/Release/lens-sherpa.exe') @{
        consent=$true;audio=$SourcePath;model=(Join-Path $root $weight.path);tokens=(Join-Path $root $tokens.path);
        library=(Join-Path $root $library.path);language=$Language;model_type=$(if($Language -eq 'hi'){'nemo_ctc'}else{'dolphin'})
      }
      $record.text=$recognition.text;$record.confidence=0.0;$record.kind='audio_import'
      $record.model_version=$(if($Language -eq 'hi'){'indicconformer-hi-120m-int8@'}else{'dolphin-small-int8@'})+$weight.sha256
      $record.provenance=(@{provider=$recognition.provider;audio_sha256=(Get-FileHash -LiteralPath $SourcePath).Hash;
        model_sha256=$weight.sha256;model_confidence=$null;confidence_policy='numeric zero means unavailable, not measured accuracy'} | ConvertTo-Json -Compress)
      $result=StoreAndIndex $record
      $result | Add-Member -NotePropertyName transcript -NotePropertyValue $recognition
    } else {
      $filename=if($Language -in @('es','hi')){'ggml-small-q5_1.bin'}else{'ggml-base-q5_1.bin'}
      $weight=$modelLock | Where-Object filename -eq $filename
      $model=Join-Path $root $weight.path;VerifyArtifact $model $weight.sha256
      $record.model_version='whisper.cpp/'+$filename+'@'+$weight.sha256
      $record.op='ingest_audio';$record.audio=$SourcePath;$record.model=$model;$record.language=$Language;$record.kind='audio_import'
      $record.provenance=(@{provider='whisper.cpp';audio_sha256=(Get-FileHash -LiteralPath $SourcePath).Hash;model_sha256=$weight.sha256} | ConvertTo-Json -Compress)
      $result=StoreAndIndex $record
    }
  } elseif($Action -eq 'ImportImage') {
    if($Language -notin @('en','es','zh','fr','de','pt','hi')){throw 'script-specific OCR pack is not configured for this language'}
    $modelName=if($Language -eq 'hi'){'devanagari_PP-OCRv5_mobile_rec'}else{'PP-OCRv6_small_rec'}
    $folder=Join-Path $root "models/PaddlePaddle--$modelName"
    $ocrLock=Get-Content -LiteralPath (Join-Path $root 'third_party/ocr-runtime-lock.json') -Raw | ConvertFrom-Json
    $export=$ocrLock.exports | Where-Object { $_.model -eq $modelName -and $_.path.EndsWith('.onnx') }
    VerifyArtifact (Join-Path $folder 'inference.onnx') $export.sha256
    $dictionary=$ocrLock.exports | Where-Object { $_.model -eq $modelName -and $_.path.EndsWith('ctc-dictionary.json') }
    $runtime=$ocrLock.runtime_artifacts | Where-Object { $_.path.EndsWith('/onnxruntime.dll') }
    VerifyArtifact (Join-Path $root $dictionary.path) $dictionary.sha256
    VerifyArtifact (Join-Path $root $runtime.path) $runtime.sha256
    $recognition=Native (Join-Path $root 'build/engine/Release/lens-ocr.exe') @{
      consent=$true;runtime=(Join-Path $root '.tools/ocr-runtime/onnxruntime.dll');model=(Join-Path $folder 'inference.onnx');
      dictionary=(Join-Path $folder 'ctc-dictionary.json');image=[IO.Path]::GetFullPath($SourcePath)
    }
    $record.text=$recognition.text;$record.confidence=$recognition.confidence;$record.kind='ocr_crop_import'
    $record.model_version='PaddleOCR/'+$modelName+'@'+$export.sha256
    $record.provenance=(@{image_sha256=(Get-FileHash -LiteralPath $SourcePath).Hash;model_sha256=$export.sha256;scope='user-supplied text crop'} | ConvertTo-Json -Compress)
    $result=StoreAndIndex $record;$result | Add-Member -NotePropertyName recognition -NotePropertyValue $recognition
  } else {$result=StoreAndIndex $record}
}
$result | ConvertTo-Json -Depth 30
} catch {
  [Console]::Error.WriteLine('lens_request_failed')
  exit 1
}
