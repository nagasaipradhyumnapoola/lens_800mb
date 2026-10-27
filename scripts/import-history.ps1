param(
  [string]$Format,
  [string]$SourcePath,
  [string]$DatabasePath,
  [string]$DateOrder,
  [string]$SourceTimeZone,
  [string]$TwoDigitYearCentury,
  [string]$OriginalTimestamp,
  [string]$SourceApplication='SelectedText',
  [string]$Language='und',
  [switch]$Preview,        # parse and summarise only; nothing is written
  [switch]$Progress,       # extra stdout lines {"progress":{...}} before the result line
  [string]$CancelPath,     # when this file appears, the import rolls back and reports "cancelled"
  [string]$EnginePath      # lens-engine.exe of an installed build; defaults to the repository build
)
$ErrorActionPreference='Stop'
$WarningPreference='Stop'
Set-StrictMode -Version Latest
$utf8=[Text.UTF8Encoding]::new($false,$true)
$lenient=[Text.UTF8Encoding]::new($false,$false)
$latin1=[Text.Encoding]::Latin1
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); $OutputEncoding=[Text.UTF8Encoding]::new($false)
$importerVersion='lens-history/1.1.0'
$script:failureCode='invalid_export'
$script:outcome='not_started'
$script:native=$null; $script:commitSent=$false; $script:exchangeFailed=$false; $script:streaming=$false; $script:totalBytes=0; $script:bytesRead=0
$script:imported=0; $script:deduplicated=0; $script:sent=0; $script:batches=0
$script:ids=[Collections.Generic.List[object]]::new()
$script:skipped=[ordered]@{}; $script:duplicates=0; $script:seen=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
$script:previewCount=0; $script:first=$null; $script:last=$null; $script:kinds=[Collections.Generic.HashSet[string]]::new(); $script:sample=[Collections.Generic.List[object]]::new()
$maxIdsReported=10000

function FailImport([string]$code) {
  $script:failureCode=$code
  throw [InvalidOperationException]::new('history_import_failed')
}
function Skip([string]$reason) { if($script:skipped.Contains($reason)) { $script:skipped[$reason]++ } else { $script:skipped[$reason]=1 } }
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
function Stamp([DateTimeOffset]$value) { return $value.ToString('yyyy-MM-ddTHH:mm:sszzz',[Globalization.CultureInfo]::InvariantCulture) }
function ZoneName([TimeSpan]$offset) {
  if($offset -eq [TimeSpan]::Zero) { return 'UTC' }
  $sign=if($offset -lt [TimeSpan]::Zero){'-'}else{'+'}; $abs=$offset.Duration()
  return 'UTC'+$sign+$abs.Hours.ToString('00')+':'+$abs.Minutes.ToString('00')
}
function Clip([string]$value,[int]$limit) { if($null -eq $value) { return '' }; if($value.Length -gt $limit) { return $value.Substring(0,$limit) }; return $value }
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

# ---------------------------------------------------------------- native engine: one process, one transaction
function Exchange([string]$line) {
  $process=$script:native
  try { $process.StandardInput.WriteLine($line); $process.StandardInput.Flush() } catch { $script:exchangeFailed=$true; FailImport 'native_outcome_unknown' }
  $pending=$process.StandardOutput.ReadLineAsync()
  if(!$pending.Wait(300000)) { $script:exchangeFailed=$true; $process.Kill($true); $process.WaitForExit(); FailImport 'native_outcome_unknown' }
  $text=$pending.GetAwaiter().GetResult()
  if($null -eq $text) { $script:exchangeFailed=$true; FailImport 'native_outcome_unknown' }
  $value=$text | ConvertFrom-Json -AsHashtable -Depth 30 -DateKind String
  if($value -isnot [Collections.IDictionary] -or !$value.Contains('ok')) { $script:exchangeFailed=$true; FailImport 'native_outcome_unknown' }
  return $value
}
function StartNative {
  $engine=if($EnginePath){[IO.Path]::GetFullPath($EnginePath)}else{Join-Path (Split-Path -Parent $PSScriptRoot) 'build/engine/Release/lens-engine.exe'}
  if(!(Test-Path -LiteralPath $engine -PathType Leaf)) { FailImport 'native_unavailable' }
  $info=[Diagnostics.ProcessStartInfo]::new($engine)
  $info.UseShellExecute=$false; $info.CreateNoWindow=$true
  $info.RedirectStandardInput=$true; $info.RedirectStandardOutput=$true; $info.RedirectStandardError=$true
  $info.StandardInputEncoding=$utf8; $info.StandardOutputEncoding=$utf8; $info.StandardErrorEncoding=$utf8
  $info.ArgumentList.Add('--db'); $info.ArgumentList.Add([IO.Path]::GetFullPath($DatabasePath))
  $process=[Diagnostics.Process]::new(); $process.StartInfo=$info
  $script:failureCode='native_unavailable'
  if(!$process.Start()) { FailImport 'native_unavailable' }
  $script:native=$process; $script:nativeErrors=$process.StandardError.ReadToEndAsync()
  $script:outcome='unknown'
  # Closing stdin without commit (or any rejected chunk, which poisons the transaction) rolls back every chunk.
  if((Exchange '{"op":"begin"}').ok -ne $true) { $script:exchangeFailed=$true; FailImport 'native_outcome_unknown' }
}
function AbortNative {
  $process=$script:native; if($null -eq $process) { return }
  try { $process.StandardInput.Close() } catch {}
  if(!$process.WaitForExit(60000)) { try { $process.Kill($true) } catch {} }
  $script:outcome='rolled_back'
}
function CheckCancel {
  if($CancelPath -and (Test-Path -LiteralPath $CancelPath)) { AbortNative; FailImport 'cancelled' }
}
function ReportProgress {
  if(!$Progress) { return }
  $done=if($Preview){$script:previewCount}else{$script:sent}
  $p=[ordered]@{records=$done;batches=$script:batches}
  if($script:totalBytes) { $p['bytes_read']=$script:bytesRead; $p['bytes_total']=$script:totalBytes }
  [Console]::Out.WriteLine(([ordered]@{progress=$p} | ConvertTo-Json -Compress)); [Console]::Out.Flush()
}
function SendChunk($records) {
  CheckCancel
  $wire=@{op='import_batch';consent=$true;records=$records} | ConvertTo-Json -Depth 30 -Compress
  if($utf8.GetByteCount($wire)+1 -gt 2*1024*1024) { FailImport 'native_request_size_limit' }
  if($null -eq $script:native) { StartNative }
  $result=Exchange $wire
  if($result.ok -ne $true) { AbortNative; FailImport 'native_rejected_batch' }
  if(!$result.Contains('imported') -or !$result.Contains('deduplicated') -or !$result.Contains('source_ids')) { $script:exchangeFailed=$true; FailImport 'native_outcome_unknown' }
  $script:imported+=$result.imported; $script:deduplicated+=$result.deduplicated; $script:sent+=$records.Count; $script:batches++
  if($script:ids.Count -le $maxIdsReported) { foreach($id in $result.source_ids) { $script:ids.Add($id) } }
  ReportProgress
}
# Records are buffered into chunks of at most 128 records and 2 MiB per native request line.
$script:batch=[Collections.Generic.List[object]]::new(); $script:batchBytes=0
function Emit($record) {
  CheckRecord $record
  if($Preview) {
    $script:previewCount++
    $script:kinds.Add($record.kind)|Out-Null
    $when=(Rfc3339 $record.timestamp).UtcDateTime
    if($null -eq $script:first -or $when -lt $script:first) { $script:first=$when }
    if($null -eq $script:last -or $when -gt $script:last) { $script:last=$when }
    if($script:sample.Count -lt 3) {
      $title=if($record.metadata.Contains('title')){[string]$record.metadata.title}else{($record.text -split "`n")[0]}
      $script:sample.Add([ordered]@{title=(Clip $title 80);timestamp=$record.timestamp;kind=$record.kind})
    }
    if($Progress -and $script:previewCount % 1000 -eq 0) { ReportProgress; CheckCancel }
    return
  }
  $single=@{op='import_batch';consent=$true;records=@($record)} | ConvertTo-Json -Depth 30 -Compress
  $recordBytes=$utf8.GetByteCount($single)
  if($recordBytes+1 -gt 2*1024*1024) { FailImport 'native_request_size_limit' }
  if($script:batch.Count -eq 128 -or ($script:batch.Count -and $script:batchBytes+$recordBytes+1 -gt 2*1024*1024)) {
    if($script:streaming) { SendChunk $script:batch.ToArray() } else { $script:chunks.Add($script:batch.ToArray()) }
    $script:batch=[Collections.Generic.List[object]]::new(); $script:batchBytes=0
  }
  $script:batch.Add($record); $script:batchBytes+=$recordBytes
}
function Unique([string]$key) {
  if(!$script:seen.Add($key)) { $script:duplicates++; return $false }
  return $true
}

# ---------------------------------------------------------------- e-mail (RFC 5322 / MIME)
$mailFormats=[string[]]@('ddd, d MMM yyyy HH:mm:ss zzz','d MMM yyyy HH:mm:ss zzz','ddd, d MMM yyyy HH:mm zzz','d MMM yyyy HH:mm zzz',
  'ddd, dd MMM yyyy HH:mm:ss zzz','dd MMM yyyy HH:mm:ss zzz')
$namedZones=@{EST='-05:00';EDT='-04:00';CST='-06:00';CDT='-05:00';MST='-07:00';MDT='-06:00';PST='-08:00';PDT='-07:00';GMT='+00:00';UT='+00:00';UTC='+00:00';Z='+00:00';IST='+05:30'}
function MailDate([string]$value) {
  if(!$value) { return $null }
  $v=[regex]::Replace($value,'\s*\([^)]*\)\s*$','').Trim()
  $m=[regex]::Match($v,'\s([A-Z]{1,3})$')
  if($m.Success -and $namedZones.ContainsKey($m.Groups[1].Value)) { $v=$v.Substring(0,$m.Index)+' '+$namedZones[$m.Groups[1].Value] }
  $v=[regex]::Replace($v,'([+-])(\d{2})(\d{2})$','$1$2:$3')
  $parsed=[DateTimeOffset]::MinValue
  if([DateTimeOffset]::TryParseExact($v,$mailFormats,[Globalization.CultureInfo]::InvariantCulture,[Globalization.DateTimeStyles]::AllowWhiteSpaces,[ref]$parsed)) { return $parsed }
  return $null
}
function EightBit([string]$value) {  # raw header bytes may be UTF-8
  if($value -notmatch '[\u0080-\u00ff]') { return $value }
  try { return $utf8.GetString($latin1.GetBytes($value)) } catch { return $value }
}
function CharsetText([byte[]]$bytes,[string]$charset) {
  $name=if($charset){$charset.Trim('"',' ').ToLowerInvariant()}else{'utf-8'}
  if($name -in @('utf-8','utf8','us-ascii','ascii','')) { return $lenient.GetString($bytes) }
  try { return [Text.Encoding]::GetEncoding($name).GetString($bytes) } catch { return $lenient.GetString($bytes) }
}
function QpBytes([string]$value) {
  $v=[regex]::Replace($value,'=\r?\n','')
  $v=[regex]::Replace($v,'=([0-9A-Fa-f]{2})',{ param($m) [string][char][Convert]::ToInt32($m.Groups[1].Value,16) })
  return $latin1.GetBytes($v)
}
function DecodeWords([string]$value) {
  if(!$value) { return '' }
  $v=EightBit $value
  $v=[regex]::Replace($v,'(\?=)\s+(=\?)','$1$2')
  return [regex]::Replace($v,'=\?([^?\s]+)\?([BbQq])\?([^?\s]*)\?=',{
    param($m)
    try {
      $bytes=if($m.Groups[2].Value -in 'B','b'){[Convert]::FromBase64String($m.Groups[3].Value)}else{QpBytes ($m.Groups[3].Value.Replace('_',' '))}
      return CharsetText $bytes $m.Groups[1].Value
    } catch { return $m.Value }
  })
}
function HeaderParam([string]$header,[string]$name) {
  $m=[regex]::Match($header,"(?i);\s*$name\s*=\s*(?:""([^""]*)""|([^;\s]+))")
  if(!$m.Success) { return '' }
  if($m.Groups[1].Success) { return $m.Groups[1].Value }; return $m.Groups[2].Value
}
function SplitMessage([string]$message) {
  $m=[regex]::Match($message,'\r?\n\r?\n')
  $head=if($m.Success){$message.Substring(0,$m.Index)}else{$message}
  $body=if($m.Success){$message.Substring($m.Index+$m.Length)}else{''}
  $headers=@{}
  foreach($line in [regex]::Split([regex]::Replace($head,'\r?\n[ \t]+',' '),'\r?\n')) {
    $h=[regex]::Match($line,'^([!-9;-~]+):[ \t]*(.*)$')
    if($h.Success) { $name=$h.Groups[1].Value.ToLowerInvariant(); if(!$headers.ContainsKey($name)) { $headers[$name]=$h.Groups[2].Value } }
  }
  return @{headers=$headers;body=$body}
}
function HtmlText([string]$html) {
  $t=[regex]::Replace($html,'(?is)<(script|style)[^>]*>.*?</\1>','')
  $t=[regex]::Replace($t,'(?i)<br\s*/?>|</(p|div|li|tr|h\d)>',"`n")
  $t=[regex]::Replace($t,'<[^>]+>','')
  $t=[Net.WebUtility]::HtmlDecode($t)
  return [regex]::Replace($t,'\n{3,}',"`n`n").Trim()
}
function MimeText($part,[int]$depth,$state) {
  $type=if($part.headers.ContainsKey('content-type')){$part.headers['content-type']}else{'text/plain'}
  $mime=$type.Split(';')[0].Trim().ToLowerInvariant()
  $disposition=if($part.headers.ContainsKey('content-disposition')){$part.headers['content-disposition'].ToLowerInvariant()}else{''}
  if($mime.StartsWith('multipart/') -and $depth -lt 6) {
    $boundary=HeaderParam $type 'boundary'
    if(!$boundary) { return }
    $pieces=[regex]::Split($part.body,'(?m)^--'+[regex]::Escape($boundary)+'(?:--)?[ \t]*\r?$')
    for($i=1;$i -lt $pieces.Length;$i++) {
      $piece=$pieces[$i] -replace '^\r?\n',''
      if(!$piece.Trim()) { continue }
      MimeText (SplitMessage $piece) ($depth+1) $state
    }
    return
  }
  if($disposition.StartsWith('attachment') -or !($mime -in @('text/plain','text/html'))) { $state.attachments++; return }
  $encoding=if($part.headers.ContainsKey('content-transfer-encoding')){$part.headers['content-transfer-encoding'].Trim().ToLowerInvariant()}else{''}
  $bytes=$null
  if($encoding -eq 'base64') { try { $bytes=[Convert]::FromBase64String(($part.body -replace '\s','')) } catch { $state.attachments++; return } }
  elseif($encoding -eq 'quoted-printable') { $bytes=QpBytes $part.body }
  else { $bytes=$latin1.GetBytes($part.body) }
  $text=CharsetText $bytes (HeaderParam $type 'charset')
  if($mime -eq 'text/plain' -and $null -eq $state.plain) { $state.plain=$text }
  elseif($mime -eq 'text/html' -and $null -eq $state.html) { $state.html=$text }
}
function DisplayName([string]$from) {
  $m=[regex]::Match($from,'^\s*"?([^"<]+?)"?\s*<[^>]*>\s*$')
  if($m.Success) { return $m.Groups[1].Value.Trim() }
  if($from -notmatch '@') { return $from.Trim() }
  return ''
}
$script:ordinal=0
function HandleMessage([string]$message) {
  $parsed=SplitMessage $message
  $h=$parsed.headers
  $date=if($h.ContainsKey('date')){MailDate $h['date']}else{$null}
  if($null -eq $date) { Skip 'missing_or_invalid_date'; return }
  $messageId=if($h.ContainsKey('message-id')){$h['message-id'].Trim().ToLowerInvariant()}else{''}
  $state=@{plain=$null;html=$null;attachments=0}
  MimeText $parsed 0 $state
  $body=if($null -ne $state.plain){$state.plain}elseif($null -ne $state.html){HtmlText $state.html}else{''}
  $body=$body -replace "`r`n","`n"
  $truncated=$false; if($body.Length -gt 900000) { $body=$body.Substring(0,900000); $truncated=$true }
  $subject=DecodeWords $(if($h.ContainsKey('subject')){$h['subject']}else{''})
  $from=DecodeWords $(if($h.ContainsKey('from')){$h['from']}else{''})
  $to=DecodeWords $(if($h.ContainsKey('to')){$h['to']}else{''})
  $cc=DecodeWords $(if($h.ContainsKey('cc')){$h['cc']}else{''})
  $key=if($messageId){"id:$messageId"}else{'hash:'+[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($utf8.GetBytes("$($date.UtcTicks)|$from|$subject|$body")))}
  $script:ordinal++
  if(!(Unique $key)) { return }
  $text="Subject: $subject`nFrom: $from`nTo: $to`n`n$body"
  if(!$text.Trim()) { Skip 'empty_message'; return }
  $metadata=[ordered]@{title=(Clip $subject 1000);sender=(Clip (DisplayName $from) 200);from=(Clip $from 2000);to=(Clip $to 2000);cc=(Clip $cc 2000);
    message_id=(Clip $messageId 512);attachments=$state.attachments;body_truncated=$truncated;timestamp_basis='email_date_header';record_number=$script:ordinal}
  $md=@{}; foreach($k in $metadata.Keys) { $md[$k]=$metadata[$k] }
  Emit (MakeRecord $script:ordinal $text (Stamp $date) (ZoneName $date.Offset) 'Email' 'imported_email' $md)
}

# ---------------------------------------------------------------- iCalendar and vCard (RFC 5545 / 6350)
function Unfold([string]$raw) { return [regex]::Split([regex]::Replace($raw,'\r?\n[ \t]',''),'\r?\n') }
function PropertyLine([string]$line) {
  $m=[regex]::Match($line,'^([A-Za-z0-9-]+)((?:;[^:]*)?):(.*)$')
  if(!$m.Success) { return $null }
  $params=@{}
  foreach($p in ($m.Groups[2].Value.TrimStart(';') -split ';')) { if($p -match '^([^=]+)=(.*)$') { $params[$Matches[1].ToUpperInvariant()]=$Matches[2].Trim('"') } }
  $value=$m.Groups[3].Value
  if($params.ContainsKey('ENCODING') -and $params['ENCODING'] -ieq 'QUOTED-PRINTABLE') { $value=$lenient.GetString((QpBytes $value)) }
  return @{name=$m.Groups[1].Value.ToUpperInvariant();params=$params;value=$value}
}
function Unescape([string]$v) { return [regex]::Replace($v,'\\([\\;,nN])',{ param($m) if($m.Groups[1].Value -in 'n','N'){"`n"}else{$m.Groups[1].Value} }) }
function CalendarTime($prop) {
  $v=$prop.value.Trim()
  if($v -match '^(\d{8})$') {
    $wall=[DateTime]::ParseExact($v,'yyyyMMdd',[Globalization.CultureInfo]::InvariantCulture)
    $zone=if($SourceTimeZone){SourceZone $SourceTimeZone}else{[TimeZoneInfo]::Utc}
    return @{time=[DateTimeOffset]::new($wall,$zone.GetUtcOffset($wall));all_day=$true}
  }
  if($v -notmatch '^\d{8}T\d{6}Z?$') { return $null }
  if($v.EndsWith('Z')) {
    $wall=[DateTime]::ParseExact($v.TrimEnd('Z'),'yyyyMMddTHHmmss',[Globalization.CultureInfo]::InvariantCulture)
    return @{time=[DateTimeOffset]::new($wall,[TimeSpan]::Zero);all_day=$false}
  }
  $wall=[DateTime]::ParseExact($v,'yyyyMMddTHHmmss',[Globalization.CultureInfo]::InvariantCulture)
  $zoneName=if($prop.params.ContainsKey('TZID')){$prop.params['TZID']}else{$SourceTimeZone}
  if(!$zoneName) { FailImport 'source_timezone_required' }  # floating local time: the user must say where
  $zone=SourceZone $zoneName
  if($zone.IsInvalidTime($wall) -or $zone.IsAmbiguousTime($wall)) { return $null }
  return @{time=[DateTimeOffset]::new($wall,$zone.GetUtcOffset($wall));all_day=$false}
}
function ImportCalendar([string]$raw) {
  if($raw -notmatch '(?m)^BEGIN:VCALENDAR') { FailImport 'unsupported_calendar_layout' }
  $vevent=$null
  foreach($line in (Unfold $raw)) {
    if($line -ceq 'BEGIN:VEVENT') { $vevent=@{}; continue }
    if($null -eq $vevent) { continue }
    if($line -ceq 'END:VEVENT') {
      $e=$vevent; $vevent=$null
      if(!$e.ContainsKey('DTSTART')) { Skip 'missing_start'; continue }
      $start=CalendarTime $e['DTSTART']
      if($null -eq $start) { Skip 'invalid_or_ambiguous_time'; continue }
      $summary=if($e.ContainsKey('SUMMARY')){Unescape $e['SUMMARY'].value}else{''}
      $location=if($e.ContainsKey('LOCATION')){Unescape $e['LOCATION'].value}else{''}
      $description=if($e.ContainsKey('DESCRIPTION')){Unescape $e['DESCRIPTION'].value}else{''}
      $organizer=if($e.ContainsKey('ORGANIZER') -and $e['ORGANIZER'].params.ContainsKey('CN')){$e['ORGANIZER'].params['CN']}else{''}
      $uid=if($e.ContainsKey('UID')){$e['UID'].value}else{''}
      $recurrence=if($e.ContainsKey('RECURRENCE-ID')){$e['RECURRENCE-ID'].value}else{''}
      $script:ordinal++
      if(!(Unique "$uid|$($e['DTSTART'].value)|$recurrence|$summary")) { continue }
      $when=if($start.all_day){$start.time.ToString('yyyy-MM-dd',[Globalization.CultureInfo]::InvariantCulture)+' (all day)'}else{Stamp $start.time}
      $text="Event: $summary`nWhen: $when"
      if($location) { $text+="`nWhere: $location" }
      if($organizer) { $text+="`nOrganizer: $organizer" }
      if($description) { $text+="`n`n$description" }
      $md=@{title=(Clip $summary 1000);location=(Clip $location 1000);organizer=(Clip $organizer 200);uid=(Clip $uid 512);all_day=$start.all_day;
        recurrence_rule=$(if($e.ContainsKey('RRULE')){Clip $e['RRULE'].value 512}else{''});timestamp_basis='calendar_event_start';record_number=$script:ordinal}
      if($e.ContainsKey('DTEND')) { $md['end']=$e['DTEND'].value }
      Emit (MakeRecord $script:ordinal $text (Stamp $start.time) (ZoneName $start.time.Offset) 'Calendar' 'imported_event' $md)
      continue
    }
    $p=PropertyLine $line
    if($null -ne $p -and !$vevent.ContainsKey($p.name)) { $vevent[$p.name]=$p }
  }
}
function ImportContacts([string]$raw) {
  if($raw -notmatch '(?m)^BEGIN:VCARD') { FailImport 'unsupported_contacts_layout' }
  $card=$null
  foreach($line in (Unfold $raw)) {
    if($line -ieq 'BEGIN:VCARD') { $card=[ordered]@{}; continue }
    if($null -eq $card) { continue }
    if($line -ieq 'END:VCARD') {
      $c=$card; $card=$null
      $value={ param($n) if($c.Contains($n)){ (($c[$n] | ForEach-Object { Unescape $_.value }) -join '; ') }else{''} }
      $name=& $value 'FN'
      if(!$name -and $c.Contains('N')) { $name=((Unescape $c['N'][0].value) -split ';' | Where-Object {$_} | Select-Object -First 2) -join ' ' }
      if(!$name) { Skip 'missing_name'; continue }
      $email=& $value 'EMAIL'; $phone=& $value 'TEL'; $org=(& $value 'ORG') -replace ';',' '
      $script:ordinal++
      $uid=& $value 'UID'
      if(!(Unique $(if($uid){"uid:$uid"}else{"$name|$email|$phone"}))) { continue }
      $stamp=$null; $basis='import_time'; $zone='UTC'
      if($c.Contains('REV') -and $c['REV'][0].value -match '^(\d{8}T\d{6}Z)$') {
        $rev=[DateTimeOffset]::new([DateTime]::ParseExact($Matches[1].TrimEnd('Z'),'yyyyMMddTHHmmss',[Globalization.CultureInfo]::InvariantCulture),[TimeSpan]::Zero)
        $stamp=Stamp $rev; $basis='vcard_revision'
      } else { $stamp=$observedAt }
      $text="Contact: $name"
      foreach($pair in @(@('Organization',$org),@('Title',(& $value 'TITLE')),@('Phone',$phone),@('Email',$email),@('Birthday',(& $value 'BDAY')),@('Note',(& $value 'NOTE')))) {
        if($pair[1]) { $text+="`n$($pair[0]): $($pair[1])" }
      }
      $md=@{title=(Clip $name 200);contact_name=(Clip $name 200);organization=(Clip $org 500);uid=(Clip $uid 512);timestamp_basis=$basis;record_number=$script:ordinal}
      $record=MakeRecord $script:ordinal $text $stamp $zone 'Contacts' 'imported_contact' $md
      if($basis -eq 'import_time') { $record.original_timestamp=$null }
      Emit $record
      continue
    }
    $p=PropertyLine $line
    if($null -ne $p) { if(!$card.Contains($p.name)) { $card[$p.name]=[Collections.Generic.List[object]]::new() }; $card[$p.name].Add($p) }
  }
}

# ---------------------------------------------------------------- browser history (Google Takeout JSON or CSV)
function SafeUrl([string]$url) {
  $uri=$null
  if(![Uri]::TryCreate($url,[UriKind]::Absolute,[ref]$uri) -or $uri.Scheme -notin @('http','https','ftp')) { return $null }
  # Query strings and fragments often carry session tokens; only scheme, host and path are kept.
  return @{url=$uri.GetLeftPart([UriPartial]::Path) -replace '^([a-z]+://)[^/@]*@','$1';removed=[bool]($uri.Query -or $uri.Fragment -or $uri.UserInfo)}
}
function VisitTime([string]$value) {
  $v=$value.Trim()
  if($v -match '^\d{10,17}$') {
    $n=[long]$v
    $ms=if($v.Length -ge 16){[long]($n/1000)}elseif($v.Length -ge 13){$n}else{$n*1000}
    return [DateTimeOffset]::FromUnixTimeMilliseconds($ms)
  }
  $parsed=[DateTimeOffset]::MinValue
  if($v -match '(Z|[+-]\d{2}:\d{2})$' -and [DateTimeOffset]::TryParse($v,[Globalization.CultureInfo]::InvariantCulture,[Globalization.DateTimeStyles]::None,[ref]$parsed)) { return $parsed }
  $wall=[DateTime]::MinValue
  if([DateTime]::TryParse($v,[Globalization.CultureInfo]::InvariantCulture,[Globalization.DateTimeStyles]::None,[ref]$wall)) {
    if(!$SourceTimeZone) { FailImport 'source_timezone_required' }
    $zone=SourceZone $SourceTimeZone; $wall=[DateTime]::SpecifyKind($wall,[DateTimeKind]::Unspecified)
    if($zone.IsInvalidTime($wall) -or $zone.IsAmbiguousTime($wall)) { return $null }
    return [DateTimeOffset]::new($wall,$zone.GetUtcOffset($wall))
  }
  return $null
}
function Visit([string]$url,[string]$title,[string]$time) {
  $safe=SafeUrl $url
  if($null -eq $safe) { Skip 'unsupported_url'; return }
  $when=VisitTime $time
  if($null -eq $when) { Skip 'invalid_time'; return }
  $script:ordinal++
  if(!(Unique "$($safe.url)|$($when.UtcTicks)")) { return }
  $title=Clip $title 1000
  $text=if($title){"$title`n$($safe.url)"}else{$safe.url}
  $when=$when.ToOffset([TimeSpan]::Zero)
  Emit (MakeRecord $script:ordinal $text (Stamp $when) 'UTC' 'Browser history' 'imported_browser_visit' @{title=$title;url=$safe.url;query_removed=$safe.removed;timestamp_basis='browser_visit_time';record_number=$script:ordinal})
}
function ImportBrowserHistory([string]$raw) {
  $trimmed=$raw.TrimStart()
  if($trimmed.StartsWith('{')) {
    $doc=$raw | ConvertFrom-Json -AsHashtable -Depth 10 -DateKind String
    if($doc -isnot [Collections.IDictionary] -or !$doc.Contains('Browser History')) { FailImport 'unsupported_browser_history_layout' }
    foreach($item in $doc['Browser History']) {
      if($item -isnot [Collections.IDictionary] -or $item['url'] -isnot [string]) { Skip 'invalid_entry'; continue }
      Visit $item['url'] ([string]$item['title']) ([string]$item['time_usec'])
    }
    return
  }
  $rows=@($raw | ConvertFrom-Csv)
  if(!$rows.Count) { FailImport 'unsupported_browser_history_layout' }
  $names=@($rows[0].PSObject.Properties.Name)
  $urlName=$names | Where-Object { $_ -ieq 'url' } | Select-Object -First 1
  $titleName=$names | Where-Object { $_ -ieq 'title' } | Select-Object -First 1
  $timeName=$names | Where-Object { $_ -in @('visit_time','time','date','last_visit_time','visited_on','timestamp') } | Select-Object -First 1
  if(!$urlName -or !$timeName) { FailImport 'unsupported_browser_history_layout' }
  foreach($row in $rows) { Visit ([string]$row.$urlName) $(if($titleName){[string]$row.$titleName}else{''}) ([string]$row.$timeName) }
}

# ---------------------------------------------------------------- PDF text (literal-string text operators only)
function PdfString([string]$s) {
  return [regex]::Replace($s,'\\(\r?\n|[nrtbf()\\]|[0-7]{1,3})',{
    param($m) $c=$m.Groups[1].Value
    switch -casesensitive ($c) { 'n' {"`n"} 'r' {"`r"} 't' {"`t"} 'b' {''} 'f' {''} '(' {'('} ')' {')'} '\' {'\'}
      default { if($c -match '^[0-7]+$'){[string][char][Convert]::ToInt32($c,8)}else{''} } }
  })
}
function PdfText([byte[]]$bytes) {
  $raw=$latin1.GetString($bytes)
  if(!$raw.StartsWith('%PDF-')) { FailImport 'unsupported_pdf' }
  if($raw -match '/Encrypt\s') { FailImport 'pdf_encrypted' }
  $out=[Text.StringBuilder]::new()
  foreach($m in [regex]::Matches($raw,'<<((?:[^<>]|<<(?:[^<>]|<<[^<>]*>>)*>>)*)>>\s*stream\r?\n')) {
    $dict=$m.Groups[1].Value
    if($dict -match '/Subtype\s*/Image|/Type\s*/XRef|/Type\s*/ObjStm|/Length1|/Subtype\s*/Type1C|/FontFile') { continue }
    $start=$m.Index+$m.Length; $end=$raw.IndexOf('endstream',$start)
    if($end -lt 0) { continue }
    $data=$raw.Substring($start,$end-$start)
    if($dict -match '/FlateDecode') {
      try {
        $compressed=[IO.MemoryStream]::new($latin1.GetBytes($data.TrimEnd("`r","`n")))
        $z=[IO.Compression.ZLibStream]::new($compressed,[IO.Compression.CompressionMode]::Decompress)
        $plain=[IO.MemoryStream]::new(); $z.CopyTo($plain); $z.Dispose()
        if($plain.Length -gt 64MB) { continue }
        $data=$latin1.GetString($plain.ToArray())
      } catch { continue }
    } elseif($dict -match '/Filter') { continue }
    if($data -notmatch '\bBT\b') { continue }
    foreach($op in [regex]::Matches($data,'(\((?:\\.|[^\\)])*\))\s*(?:Tj|''|")|\[((?:\\.|[^\]\\])*)\]\s*TJ|<[0-9A-Fa-f\s]+>\s*Tj|(?<![A-Za-z])(T\*|Td|TD|ET)(?![A-Za-z])')) {
      if($op.Value.StartsWith('<')) { continue }
      if($op.Groups[3].Success) { [void]$out.Append("`n"); continue }
      if($op.Groups[1].Success) { $s=$op.Groups[1].Value; [void]$out.Append((PdfString $s.Substring(1,$s.Length-2))); continue }
      foreach($part in [regex]::Matches($op.Groups[2].Value,'\((?:\\.|[^\\)])*\)|-?\d+(?:\.\d+)?')) {
        if($part.Value.StartsWith('(')) { [void]$out.Append((PdfString $part.Value.Substring(1,$part.Value.Length-2))) }
        elseif([double]$part.Value -lt -200) { [void]$out.Append(' ') }
      }
    }
  }
  $text=[regex]::Replace(($out.ToString() -replace "[ \t]+`n","`n"),'\n{3,}',"`n`n").Trim()
  if(!$text) { FailImport 'pdf_text_unavailable' }  # scanned pages and CID/hex-encoded fonts need OCR, not this extractor
  $created=$null
  $d=[regex]::Match($raw,"/CreationDate\s*\(D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(Z|[+-]\d{2}'?\d{2}'?)?")
  if($d.Success) {
    $offset=[TimeSpan]::Zero
    if($d.Groups[7].Success -and $d.Groups[7].Value -ne 'Z') { $z=$d.Groups[7].Value -replace "'",''; $offset=[TimeSpan]::new([int]$z.Substring(0,3),[int]($z.Substring(0,1)+$z.Substring(3,2)),0) }
    try { $created=[DateTimeOffset]::new([int]$d.Groups[1].Value,[int]$d.Groups[2].Value,[int]$d.Groups[3].Value,[int]$d.Groups[4].Value,[int]$d.Groups[5].Value,[int]$d.Groups[6].Value,$offset) } catch {}
  }
  return @{text=$text;created=$created}
}

# ---------------------------------------------------------------- main
try {
  if(!(Get-Command ConvertFrom-Json).Parameters.ContainsKey('DateKind')) { FailImport 'powershell_version_unsupported' }
  if($Format -cnotin @('WhatsApp','LensJsonl','Text','Mbox','Eml','Ics','Vcf','BrowserHistory','Pdf') -or !$SourcePath -or (!$DatabasePath -and !$Preview)) { FailImport 'invalid_import_parameters' }
  if($Language.Length -gt 32 -or !$Language -or $Language.IndexOf([char]0) -ge 0) { FailImport 'invalid_import_parameters' }
  $observedAt=[DateTimeOffset]::UtcNow.ToString('o',[Globalization.CultureInfo]::InvariantCulture)
  $script:chunks=[Collections.Generic.List[object]]::new()
  # Hold the one selected file open (no writers) for the whole import; reject growth.
  $stream=[IO.File]::Open([IO.Path]::GetFullPath($SourcePath),[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
  try {
    $limit=if($Format -ceq 'Mbox'){8GB}elseif($Format -in @('Pdf','BrowserHistory','Ics','Vcf')){64MB}else{16MB}
    if($stream.Length -lt 1 -or $stream.Length -gt $limit) { FailImport 'file_size_limit' }
    $script:totalBytes=$stream.Length; $script:bytesRead=0
    $exportHash=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($stream)).ToLowerInvariant()
    if($stream.Position -ne $stream.Length) { FailImport 'source_changed' }
    $null=$stream.Seek(0,[IO.SeekOrigin]::Begin)
    if($Format -ceq 'Mbox') {
      # Streamed: one message in memory at a time, chunks sent as they fill, all inside one engine transaction.
      $script:streaming=-not $Preview
      $reader=[IO.StreamReader]::new($stream,$latin1,$false,1MB)
      $message=[Text.StringBuilder]::new(); $started=$false; $previousBlank=$true
      while($null -ne ($line=$reader.ReadLine())) {
        $script:bytesRead+=$line.Length+1
        if($line.StartsWith('From ') -and $previousBlank) {
          if($started) { HandleMessage $message.ToString() }
          [void]$message.Clear(); $started=$true; $previousBlank=$false; continue
        }
        if(!$started) { if($line.Trim()) { FailImport 'unsupported_mbox_layout' }; continue }
        if($line.StartsWith('>') -and $line -match '^>+From ') { $line=$line.Substring(1) }  # mboxrd unescaping
        [void]$message.Append($line).Append("`n"); $previousBlank=$line.Length -eq 0
      }
      if(!$started) { FailImport 'unsupported_mbox_layout' }
      HandleMessage $message.ToString()
    } else {
      $bytes=[byte[]]::new([int]$stream.Length); $offset=0
      while($offset -lt $bytes.Length) {
        $read=$stream.Read($bytes,$offset,$bytes.Length-$offset)
        if(!$read) { FailImport 'source_changed' }; $offset+=$read
      }
      if($stream.ReadByte() -ne -1) { FailImport 'source_changed' }
      $script:bytesRead=$bytes.Length
    }
  } finally { $stream.Dispose() }
  if($Format -cnotin @('Mbox','Eml','Pdf')) {
    $raw=$utf8.GetString($bytes)
    if($raw.Length -gt 0 -and $raw[0] -eq [char]0xfeff) { $raw=$raw.Substring(1) }
    if($raw.IndexOf([char]0) -ge 0) { FailImport 'invalid_utf8_export' }
  }
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
      Emit (MakeRecord ($i+1) $message $stamp $SourceTimeZone 'WhatsApp' 'imported_message' $metadata)
    }
  } elseif($Format -ceq 'Text') {
    if(!$OriginalTimestamp) { FailImport 'original_timestamp_required' }
    $parsed=Rfc3339 $OriginalTimestamp
    if(!$SourceTimeZone) {
      $SourceTimeZone=if($parsed.Offset -eq [TimeSpan]::Zero){'UTC'}else{'UTC'+$parsed.ToString('zzz',[Globalization.CultureInfo]::InvariantCulture)}
    }
    CheckZone $parsed $SourceTimeZone
    Emit (MakeRecord 1 $raw $OriginalTimestamp $SourceTimeZone $SourceApplication 'imported_note' @{timestamp_basis='user_supplied_original_time'})
  } elseif($Format -ceq 'Eml') {
    HandleMessage $latin1.GetString($bytes)
    if(!$script:ordinal) { FailImport 'invalid_message' }
  } elseif($Format -ceq 'Ics') { ImportCalendar $raw
  } elseif($Format -ceq 'Vcf') { ImportContacts $raw
  } elseif($Format -ceq 'BrowserHistory') { ImportBrowserHistory $raw
  } elseif($Format -ceq 'Pdf') {
    $pdf=PdfText $bytes
    $stampValue=$null
    if($OriginalTimestamp) { $stampValue=Rfc3339 $OriginalTimestamp } elseif($null -ne $pdf.created) { $stampValue=$pdf.created } else { FailImport 'original_timestamp_required' }
    $text=$pdf.text; $parts=[Math]::Ceiling($text.Length/200000)
    for($i=0;$i -lt $parts;$i++) {  # long documents become consecutive parts of at most 200,000 characters
      $piece=$text.Substring($i*200000,[Math]::Min(200000,$text.Length-$i*200000))
      $app=if($PSBoundParameters.ContainsKey('SourceApplication')){$SourceApplication}else{'PDF'}
      Emit (MakeRecord ($i+1) $piece (Stamp $stampValue) (ZoneName $stampValue.Offset) $app 'imported_document' @{part=$i+1;parts=$parts;
        timestamp_basis=$(if($OriginalTimestamp){'user_supplied_original_time'}else{'pdf_creation_date'});record_number=$i+1})
    }
  } elseif($Format -ceq 'LensJsonl') {
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
      Emit $record
    }
  }
  if($Preview) {
    CheckCancel
    [ordered]@{ok=$true;preview=$true;format=$Format;records=$script:previewCount;duplicates_in_file=$script:duplicates;skipped=$script:skipped;
      first_timestamp=$(if($script:first){$script:first.ToString('o')}else{$null});last_timestamp=$(if($script:last){$script:last.ToString('o')}else{$null});
      kinds=@($script:kinds);sample=$script:sample.ToArray();export_sha256=$exportHash;importer_version=$importerVersion} | ConvertTo-Json -Depth 10 -Compress |
      ForEach-Object { [Console]::Out.WriteLine($_) }
    exit 0
  }
  if($script:batch.Count) { if($script:streaming) { SendChunk $script:batch.ToArray() } else { $script:chunks.Add($script:batch.ToArray()) } }
  $total=$script:sent+($script:chunks | ForEach-Object { $_.Count } | Measure-Object -Sum).Sum
  if(!$total) { FailImport 'batch_size_limit' }
  # Non-streamed formats validated every record above, before the database process started.
  foreach($chunk in $script:chunks) { SendChunk $chunk }
  CheckCancel
  if($script:imported+$script:deduplicated -ne $script:sent) { $script:exchangeFailed=$true; FailImport 'native_outcome_unknown' }
  $script:commitSent=$true
  $commit=Exchange '{"op":"commit"}'
  if($commit.ok -ne $true -or $commit.transaction -ne 'committed') { FailImport 'native_outcome_unknown' }
  $script:native.StandardInput.Close()
  if(!$script:native.WaitForExit(60000)) { $script:native.Kill($true); FailImport 'native_outcome_unknown' }
  $null=$script:nativeErrors.GetAwaiter().GetResult()
  $script:outcome='committed'
  $result=[ordered]@{ok=$true;atomic=$true;partial=$false;outcome='committed';records=$script:sent;batches=$script:batches;
    imported=$script:imported;deduplicated=$script:deduplicated;duplicates_in_file=$script:duplicates;skipped=$script:skipped;
    export_sha256=$exportHash;importer_version=$importerVersion}
  if($script:sent -le $maxIdsReported) { $result['source_ids']=$script:ids.ToArray() } else { $result['source_ids_omitted']=$true }
  [Console]::Out.WriteLine(($result | ConvertTo-Json -Depth 30 -Compress))
} catch {
  # A failure before commit closes the engine's input without committing: the whole import rolls back.
  if($null -ne $script:native -and !$script:commitSent -and !$script:exchangeFailed -and $script:outcome -ne 'rolled_back') { AbortNative }
  $unknown=$script:outcome -eq 'unknown'
  @{ok=$false;error=$(if($unknown){'native_outcome_unknown'}else{$script:failureCode});atomic=$true;partial=$false;
    outcome=$script:outcome;imported=$(if($unknown){$null}else{0});importer_version=$importerVersion} | ConvertTo-Json -Compress |
    ForEach-Object { [Console]::Out.WriteLine($_) }
  [Console]::Error.WriteLine('history_import_failed')
  exit 1
} finally {
  if($null -ne $script:native) { if(!$script:native.HasExited) { try { $script:native.Kill($true) } catch {} }; $script:native.Dispose() }
}
