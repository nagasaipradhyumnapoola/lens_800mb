param(
  [string]$Format,
  [string]$SourcePath,
  [string]$DatabasePath,
  [string]$DateOrder,
  [string]$SourceTimeZone,
  [string]$TwoDigitYearCentury,
  [string]$OriginalTimestamp,
  [string]$SourceApplication='SelectedText',
  [string]$Language='und'
)
$ErrorActionPreference='Stop'
$WarningPreference='Stop'
Set-StrictMode -Version Latest
$utf8=[Text.UTF8Encoding]::new($false,$true)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); $OutputEncoding=[Text.UTF8Encoding]::new($false)
$importerVersion='lens-history/1.0.0'
$script:failureCode='invalid_export'
$script:outcome='not_started'

function FailImport([string]$code) {
  $script:failureCode=$code
  throw [InvalidOperationException]::new('history_import_failed')
}
function RequiredString($value,[string]$name,[int]$limit=1024) {
  if($value -isnot [Collections.IDictionary] -or !$value.Contains($name)) { FailImport 'invalid_record' }
  $item=$value[$name]
  if($item -isnot [string] -or !$item.Length -or $item.IndexOf([char]0) -ge 0 -or $utf8.GetByteCount($item) -gt $limit) {
    FailImport 'invalid_record'
  }
  return $item
}
function CheckJsonElement([System.Text.Json.JsonElement]$element) {
  if($element.ValueKind -eq [System.Text.Json.JsonValueKind]::Object) {
    $names=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach($property in $element.EnumerateObject()) {
      if(!$names.Add($property.Name)) { FailImport 'duplicate_json_field' }
      CheckJsonElement $property.Value
    }
  } elseif($element.ValueKind -eq [System.Text.Json.JsonValueKind]::Array) {
    foreach($item in $element.EnumerateArray()) { CheckJsonElement $item }
  }
}
function ReadJson([string]$line) {
  $options=[System.Text.Json.JsonDocumentOptions]::new(); $options.MaxDepth=30
  $document=[System.Text.Json.JsonDocument]::Parse($line,$options)
  try { CheckJsonElement $document.RootElement }
  finally { $document.Dispose() }
  return ($line | ConvertFrom-Json -AsHashtable -Depth 30 -DateKind String)
}
function Rfc3339([string]$value) {
  if($value -cnotmatch '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,7})?(?:Z|[+-]\d{2}:\d{2})$') {
    FailImport 'invalid_timestamp'
  }
  $parsed=[DateTimeOffset]::MinValue
  if(![DateTimeOffset]::TryParse($value,[Globalization.CultureInfo]::InvariantCulture,[Globalization.DateTimeStyles]::None,[ref]$parsed)) {
    FailImport 'invalid_timestamp'
  }
  return $parsed
}
function SourceZone([string]$value) {
  if(!$value -or $value.Length -gt 128) { FailImport 'source_timezone_required' }
  if($value -ceq 'UTC') { return [TimeZoneInfo]::Utc }
  if($value -cmatch '^UTC(?<sign>[+-])(?<hour>\d{2}):(?<minute>\d{2})$') {
    $hours=[int]$Matches.hour; $minutes=[int]$Matches.minute
    if($hours -gt 14 -or $minutes -gt 59 -or ($hours -eq 14 -and $minutes -ne 0)) { FailImport 'invalid_timezone' }
    $offset=[TimeSpan]::FromMinutes(($hours*60+$minutes)*$(if($Matches.sign -eq '-'){-1}else{1}))
    return [TimeZoneInfo]::CreateCustomTimeZone($value,$offset,$value,$value)
  }
  try { return [TimeZoneInfo]::FindSystemTimeZoneById($value) }
  catch { FailImport 'invalid_timezone' }
}
function CheckZone([DateTimeOffset]$stamp,[string]$name) {
  $zone=SourceZone $name
  $wall=[DateTime]::SpecifyKind($stamp.DateTime,[DateTimeKind]::Unspecified)
  if($zone.IsInvalidTime($wall) -or $zone.IsAmbiguousTime($wall)) { FailImport 'ambiguous_or_invalid_local_time' }
  if($zone.GetUtcOffset($wall) -ne $stamp.Offset) { FailImport 'conflicting_timezone' }
}
function WhatsAppTime([string]$date,[string]$clock,$zone) {
  $parts=[regex]::Split($date,'[/.]')
  $year=[int]$parts[2]
  if($parts[2].Length -eq 2) {
    if(!$TwoDigitYearCentury -or $TwoDigitYearCentury -notmatch '^\d{3,4}$' -or [int]$TwoDigitYearCentury % 100 -ne 0 -or [int]$TwoDigitYearCentury -gt 9900) {
      FailImport 'two_digit_year_century_required'
    }
    $year += [int]$TwoDigitYearCentury
  }
  $month=[int]$parts[$(if($DateOrder -eq 'DMY'){1}else{0})]
  $day=[int]$parts[$(if($DateOrder -eq 'DMY'){0}else{1})]
  $clock=$clock.Replace([char]0x00a0,[char]0x20).Replace([char]0x202f,[char]0x20)
  $time=[DateTime]::MinValue
  $styles=[Globalization.DateTimeStyles]::NoCurrentDateDefault
  $patterns=[string[]]@('H:mm','HH:mm','H:mm:ss','HH:mm:ss','h:mm tt','hh:mm tt','h:mm:ss tt','hh:mm:ss tt')
  if(![DateTime]::TryParseExact($clock,$patterns,[Globalization.CultureInfo]::InvariantCulture,$styles,[ref]$time)) {
    FailImport 'invalid_timestamp'
  }
  try { $wall=[DateTime]::new($year,$month,$day,$time.Hour,$time.Minute,$time.Second,[DateTimeKind]::Unspecified) }
  catch { FailImport 'invalid_timestamp' }
  if($zone.IsInvalidTime($wall) -or $zone.IsAmbiguousTime($wall)) { FailImport 'ambiguous_or_invalid_local_time' }
  return [DateTimeOffset]::new($wall,$zone.GetUtcOffset($wall)).ToString('yyyy-MM-ddTHH:mm:sszzz',[Globalization.CultureInfo]::InvariantCulture)
}
function MakeRecord([int]$ordinal,[string]$text,[string]$stamp,[string]$zone,[string]$app,[string]$kind,$metadata) {
  $idBytes=$utf8.GetBytes("$Format|$exportHash|$ordinal")
  $id='history-'+[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($idBytes)).ToLowerInvariant()
  $metadata['importer_version']=$importerVersion
  $metadata['export_sha256']=$exportHash
  return @{
    id=$id;text=$text;language=$Language;timestamp=$stamp;original_timestamp=$stamp;observed_at=$observedAt;
    timezone=$zone;source_application=$app;source_locator="sha256:$exportHash#record=$ordinal";
    device='user-selected-export';kind=$kind;confidence=1.0;
    provenance=([ordered]@{export_sha256=$exportHash;format=$Format;importer_version=$importerVersion} | ConvertTo-Json -Compress);
    consent_context=@{mode='user_selected_export';format=$Format;export_sha256=$exportHash};metadata=$metadata
  }
}
function CheckRecord($record) {
  foreach($field in @('id','device','source_application')) { $null=RequiredString $record $field 1024 }
  foreach($field in @('timestamp','observed_at')) { $null=Rfc3339 (RequiredString $record $field 64) }
  $null=RequiredString $record 'text' (1024*1024)
  $null=RequiredString $record 'language' 32
  $null=RequiredString $record 'kind' 64
  $null=RequiredString $record 'timezone' 128
  foreach($field in @('provenance','source_locator')) { $null=RequiredString $record $field 8192 }
  if($record['metadata'] -isnot [Collections.IDictionary] -or $record['consent_context'] -isnot [Collections.IDictionary]) { FailImport 'invalid_record' }
  $null=RequiredString $record['consent_context'] 'mode' 128
  if($utf8.GetByteCount(($record['metadata'] | ConvertTo-Json -Depth 30 -Compress)) -gt 65536 -or
     $utf8.GetByteCount(($record['consent_context'] | ConvertTo-Json -Depth 30 -Compress)) -gt 8192) { FailImport 'invalid_record' }
}
function NativeImport($chunks,[int]$count) {
  $root=Split-Path -Parent $PSScriptRoot
  $info=[Diagnostics.ProcessStartInfo]::new((Join-Path $root 'build/engine/Release/lens-engine.exe'))
  $info.UseShellExecute=$false; $info.CreateNoWindow=$true
  $info.RedirectStandardInput=$true; $info.RedirectStandardOutput=$true; $info.RedirectStandardError=$true
  $info.StandardInputEncoding=$utf8; $info.StandardOutputEncoding=$utf8; $info.StandardErrorEncoding=$utf8
  $info.ArgumentList.Add('--db'); $info.ArgumentList.Add([IO.Path]::GetFullPath($DatabasePath))
  $process=[Diagnostics.Process]::new(); $process.StartInfo=$info
  # One engine process, one explicit transaction: begin, every chunk, commit. Closing stdin without
  # commit (or any rejected chunk, which poisons the transaction) rolls back every chunk.
  function Exchange([string]$line) {
    $process.StandardInput.WriteLine($line); $process.StandardInput.Flush()
    $pending=$process.StandardOutput.ReadLineAsync()
    if(!$pending.Wait(120000)) { $process.Kill($true); $process.WaitForExit(); FailImport 'native_outcome_unknown' }
    $text=$pending.GetAwaiter().GetResult()
    if($null -eq $text) { FailImport 'native_outcome_unknown' }
    $value=$text | ConvertFrom-Json -AsHashtable -Depth 30 -DateKind String
    if($value -isnot [Collections.IDictionary] -or !$value.Contains('ok')) { FailImport 'native_outcome_unknown' }
    return $value
  }
  try {
    if(!$process.Start()) { FailImport 'native_unavailable' }
    $errors=$process.StandardError.ReadToEndAsync()
    $script:outcome='unknown'
    if((Exchange '{"op":"begin"}').ok -ne $true) { FailImport 'native_outcome_unknown' }
    $imported=0; $deduplicated=0; $ids=[Collections.Generic.List[object]]::new()
    foreach($wire in $chunks) {
      $result=Exchange $wire
      if($result.ok -ne $true) { $process.StandardInput.Close(); $process.WaitForExit(30000)|Out-Null; $script:outcome='rolled_back'; FailImport 'native_rejected_batch' }
      if(!$result.Contains('imported') -or !$result.Contains('deduplicated') -or !$result.Contains('source_ids')) { FailImport 'native_outcome_unknown' }
      $imported+=$result.imported; $deduplicated+=$result.deduplicated; foreach($id in $result.source_ids) { $ids.Add($id) }
    }
    if($imported+$deduplicated -ne $count) { FailImport 'native_outcome_unknown' }
    $commit=Exchange '{"op":"commit"}'
    if($commit.ok -ne $true -or $commit.transaction -ne 'committed') { FailImport 'native_outcome_unknown' }
    $process.StandardInput.Close()
    if(!$process.WaitForExit(30000)) { $process.Kill($true); FailImport 'native_outcome_unknown' }
    $null=$errors.GetAwaiter().GetResult()
    $script:outcome='committed'
    return @{ok=$true;atomic=$true;partial=$false;outcome='committed';records=$count;batches=$chunks.Count;
      imported=$imported;deduplicated=$deduplicated;source_ids=$ids.ToArray();importer_version=$importerVersion}
  } finally { if(!$process.HasExited) { try { $process.Kill($true) } catch {} }; $process.Dispose() }
}

try {
  if(!(Get-Command ConvertFrom-Json).Parameters.ContainsKey('DateKind')) { FailImport 'powershell_version_unsupported' }
  if($Format -cnotin @('WhatsApp','LensJsonl','Text') -or !$SourcePath -or !$DatabasePath) { FailImport 'invalid_import_parameters' }
  if($Language.Length -gt 32 -or !$Language -or $Language.IndexOf([char]0) -ge 0) { FailImport 'invalid_import_parameters' }
  # Hold one selected file open; reject growth and invalid UTF-8 before starting the database process.
  $stream=[IO.File]::Open([IO.Path]::GetFullPath($SourcePath),[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
  try {
    if($stream.Length -lt 1 -or $stream.Length -gt 16*1024*1024) { FailImport 'file_size_limit' }
    $bytes=[byte[]]::new([int]$stream.Length); $offset=0
    while($offset -lt $bytes.Length) {
      $read=$stream.Read($bytes,$offset,$bytes.Length-$offset)
      if(!$read) { FailImport 'source_changed' }; $offset+=$read
    }
    if($stream.ReadByte() -ne -1) { FailImport 'source_changed' }
  } finally { $stream.Dispose() }
  $exportHash=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
  $raw=$utf8.GetString($bytes)
  if($raw.Length -gt 0 -and $raw[0] -eq [char]0xfeff) { $raw=$raw.Substring(1) }
  if($raw.IndexOf([char]0) -ge 0) { FailImport 'invalid_utf8_export' }
  $observedAt=[DateTimeOffset]::UtcNow.ToString('o',[Globalization.CultureInfo]::InvariantCulture)
  $records=[Collections.Generic.List[object]]::new()
  if($Format -ceq 'WhatsApp') {
    if($DateOrder -cnotin @('DMY','MDY')) { FailImport 'date_order_required' }
    $zone=SourceZone $SourceTimeZone
    $date='\d{1,2}[/.]\d{1,2}[/.](?:\d{4}|\d{2})'
    $clock='\d{1,2}:\d{2}(?::\d{2})?(?:[ \u00a0\u202f]+(?:AM|PM))?'
    $pattern="(?m)^[\u200e\u200f]*(?:\[(?<iosdate>$date),[ \u00a0\u202f]*(?<iostime>$clock)\][ \u00a0\u202f]+|(?<androiddate>$date),[ \u00a0\u202f]*(?<androidtime>$clock)[ \u00a0\u202f]+-[ \u00a0\u202f]+)"
    $headers=[regex]::Matches($raw,$pattern,[Text.RegularExpressions.RegexOptions]::CultureInvariant)
    if(!$headers.Count -or $headers[0].Index -ne 0) { FailImport 'unsupported_whatsapp_layout' }
    for($i=0;$i -lt $headers.Count;$i++) {
      $header=$headers[$i]; $begin=$header.Index+$header.Length
      $end=if($i+1 -lt $headers.Count){$headers[$i+1].Index}else{$raw.Length}
      $body=$raw.Substring($begin,$end-$begin)
      # Exactly one export record separator is removed; internal message line endings survive.
      if($body.EndsWith("`r`n")) { $body=$body.Substring(0,$body.Length-2) }
      elseif($body.EndsWith("`n") -or $body.EndsWith("`r")) { $body=$body.Substring(0,$body.Length-1) }
      $sender=''; $message=$body
      $senderMatch=[regex]::Match($body,'^(?<sender>[^\r\n]+?): (?<text>[\s\S]*)$')
      if($senderMatch.Success) { $sender=$senderMatch.Groups['sender'].Value; $message=$senderMatch.Groups['text'].Value }
      $ios=$header.Groups['iosdate'].Success
      $stamp=WhatsAppTime $header.Groups[$(if($ios){'iosdate'}else{'androiddate'})].Value $header.Groups[$(if($ios){'iostime'}else{'androidtime'})].Value $zone
      $metadata=@{sender=$sender;date_order=$DateOrder;source_timestamp_text=$header.Value;
        export_layout=$(if($ios){'ios'}else{'android'});record_number=$i+1;timestamp_basis='export_message_time'}
      if($TwoDigitYearCentury) { $metadata['two_digit_year_century']=$TwoDigitYearCentury }
      $records.Add((MakeRecord ($i+1) $message $stamp $SourceTimeZone 'WhatsApp' 'imported_message' $metadata))
    }
  } elseif($Format -ceq 'Text') {
    if(!$OriginalTimestamp) { FailImport 'original_timestamp_required' }
    $parsed=Rfc3339 $OriginalTimestamp
    if(!$SourceTimeZone) {
      $SourceTimeZone=if($parsed.Offset -eq [TimeSpan]::Zero){'UTC'}else{'UTC'+$parsed.ToString('zzz',[Globalization.CultureInfo]::InvariantCulture)}
    }
    CheckZone $parsed $SourceTimeZone
    $records.Add((MakeRecord 1 $raw $OriginalTimestamp $SourceTimeZone $SourceApplication 'imported_note' @{timestamp_basis='user_supplied_original_time'}))
  } else {
    $lines=[regex]::Split($raw,'\r\n|\n|\r')
    $lineCount=$lines.Length; if($lines[-1] -eq '') { $lineCount-- }
    if($lineCount -lt 2) { FailImport 'invalid_jsonl' }
    $header=ReadJson $lines[0]
    if($header -isnot [Collections.IDictionary] -or $header.Count -ne 2 -or !$header.Contains('format') -or !$header.Contains('version') -or
       $header.format -cne 'lens-history' -or ($header.version -isnot [long] -and $header.version -isnot [int]) -or $header.version -ne 1) {
      FailImport 'unsupported_jsonl_version'
    }
    $allowed=@('id','text','language','timestamp','original_timestamp','observed_at','timezone','device','kind','source_application','source_locator','provenance','consent_context','metadata','confidence','model_version')
    for($i=1;$i -lt $lineCount;$i++) {
      $row=ReadJson $lines[$i]
      if($row -isnot [Collections.IDictionary]) { FailImport 'invalid_record' }
      foreach($key in $row.Keys) { if($key -cnotin $allowed) { FailImport 'unsupported_record_field' } }
      foreach($field in @('id','text','language','timestamp','observed_at','timezone','device','kind','source_application','source_locator','provenance')) {
        $null=RequiredString $row $field $(if($field -eq 'text'){1024*1024}elseif($field -in @('provenance','source_locator')){8192}else{1024})
      }
      if(!$row.Contains('original_timestamp') -or $row.metadata -isnot [Collections.IDictionary] -or $row.consent_context -isnot [Collections.IDictionary]) { FailImport 'invalid_record' }
      $parsed=Rfc3339 $row.timestamp; $null=Rfc3339 $row.observed_at
      CheckZone $parsed $row.timezone
      if($null -ne $row.original_timestamp) {
        $original=Rfc3339 (RequiredString $row 'original_timestamp' 64)
        if($original.UtcTicks -ne $parsed.UtcTicks) { FailImport 'conflicting_source_timestamp' }
      }
      $null=RequiredString $row.consent_context 'mode' 128
      $metadata=@{}; foreach($key in $row.metadata.Keys) { $metadata[$key]=$row.metadata[$key] }
      $metadata['export_metadata']=$row.metadata; $metadata['source_record_id']=$row.id; $metadata['source_observed_at']=$row.observed_at
      $record=MakeRecord $i $row.text $row.timestamp $row.timezone $row.source_application $row.kind $metadata
      $record.language=$row.language; $record.device=$row.device; $record.original_timestamp=$row.original_timestamp
      $record.metadata['source_locator']=$row.source_locator
      $record.consent_context['source_context']=$row.consent_context
      $record.provenance=([ordered]@{export_sha256=$exportHash;format=$Format;importer_version=$importerVersion;source_provenance=$row.provenance} | ConvertTo-Json -Depth 30 -Compress)
      if($row.Contains('confidence')) {
        $value=$row.confidence
        if(($value -isnot [long] -and $value -isnot [int] -and $value -isnot [double] -and $value -isnot [decimal]) -or
           ![double]::IsFinite([double]$value) -or $value -lt 0 -or $value -gt 1) { FailImport 'invalid_confidence' }
        $record.confidence=$value
      }
      if($row.Contains('model_version')) { $record['model_version']=RequiredString $row 'model_version' 1024 }
      $records.Add($record)
    }
  }
  if(!$records.Count) { FailImport 'batch_size_limit' }
  foreach($record in $records) { CheckRecord $record }
  # Native requests are bounded (128 records, 2 MiB per line); split into chunks under one transaction.
  $chunks=[Collections.Generic.List[string]]::new(); $batch=[Collections.Generic.List[object]]::new(); $batchBytes=0
  foreach($record in $records) {
    $single=@{op='import_batch';consent=$true;records=@($record)} | ConvertTo-Json -Depth 30 -Compress
    $recordBytes=$utf8.GetByteCount($single)
    if($recordBytes+1 -gt 2*1024*1024) { FailImport 'native_request_size_limit' }
    if($batch.Count -eq 128 -or ($batch.Count -and $batchBytes+$recordBytes+1 -gt 2*1024*1024)) {
      $chunks.Add((@{op='import_batch';consent=$true;records=$batch.ToArray()} | ConvertTo-Json -Depth 30 -Compress))
      $batch=[Collections.Generic.List[object]]::new(); $batchBytes=0
    }
    $batch.Add($record); $batchBytes+=$recordBytes
  }
  if($batch.Count) { $chunks.Add((@{op='import_batch';consent=$true;records=$batch.ToArray()} | ConvertTo-Json -Depth 30 -Compress)) }
  foreach($wire in $chunks) { if($utf8.GetByteCount($wire)+1 -gt 2*1024*1024) { FailImport 'native_request_size_limit' } }
  # No content is written to an intermediate file; the engine owns the single transaction.
  $script:failureCode='native_unavailable'
  $result=NativeImport $chunks $records.Count
  $result | ConvertTo-Json -Depth 30 -Compress
} catch {
  $unknown=$script:outcome -eq 'unknown'
  @{ok=$false;error=$(if($unknown){'native_outcome_unknown'}else{$script:failureCode});atomic=$true;partial=$false;
    outcome=$script:outcome;imported=$(if($unknown){$null}else{0});importer_version=$importerVersion} | ConvertTo-Json -Compress
  [Console]::Error.WriteLine('history_import_failed')
  exit 1
}
