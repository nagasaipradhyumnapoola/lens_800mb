$ErrorActionPreference='Continue'
$audit=[ordered]@{
  observed_at_utc=[DateTime]::UtcNow.ToString('o')
  operating_system=(Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber,TotalVisibleMemorySize,FreePhysicalMemory)
  cpu=(Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors)
  gpu_visible_to_wmi=(Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion)
  disk=(Get-Volume -DriveLetter D | Select-Object DriveLetter,FileSystem,Size,SizeRemaining)
  powershell=$PSVersionTable.PSVersion.ToString()
  tools=@()
}
foreach($name in @('git','gh','python','py','uv','cmake','ninja','cl','rustc','cargo','node','npm','java','javac','adb','sdkmanager','emulator')) {
  $cmd=Get-Command $name -ErrorAction SilentlyContinue
  $audit.tools+=@{name=$name;path=if($cmd){$cmd.Source}else{$null}}
}
$audit | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath reports/environment.json -Encoding utf8
