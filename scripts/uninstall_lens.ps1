<#
.SYNOPSIS
  Removes Lens for the current user. Memories are kept unless -RemoveData is given.
.DESCRIPTION
  Stops Lens processes running from this installation (asking the agent to shut down cleanly first), removes the
  sign-in entry and the Start menu shortcut recorded by the installer, then the install folder. Your encrypted
  memories, key and settings stay in the data folder unless you ask for them to be deleted.
.PARAMETER InstallDir   Folder Lens was installed to (default: %LOCALAPPDATA%\Programs\Lens).
.PARAMETER RemoveData   Also delete the encrypted memory database, its key and settings (%LOCALAPPDATA%\Lens or -DataDir).
.PARAMETER DataDir      Data folder to remove with -RemoveData (default: %LOCALAPPDATA%\Lens).
.PARAMETER Force        Do not ask before deleting data.
.PARAMETER RunKey       Registry key holding the sign-in entry (default: the one recorded at install, else HKCU Run).
.PARAMETER ProgramsDir  Folder holding the Start menu shortcut (default: the one recorded at install, else Start menu Programs).
.PARAMETER PipeName     The agent's pipe, used to ask it to shut down (default: lens-agent-<user name>).
#>
[CmdletBinding()]
param(
  [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Programs\Lens'),
  [switch]$RemoveData,
  [string]$DataDir = (Join-Path $env:LOCALAPPDATA 'Lens'),
  [switch]$Force,
  [string]$RunKey,
  [string]$ProgramsDir,
  [string]$PipeName = ('lens-agent-' + $env:USERNAME)
)
$ErrorActionPreference = 'Stop'
$recordPath = Join-Path $InstallDir 'install.json'
if (-not (Test-Path -LiteralPath $recordPath)) { throw "No Lens installation found in $InstallDir" }
$record = Get-Content -LiteralPath $recordPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $RunKey) { $RunKey = if ($record.run_key) { $record.run_key } else { 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' } }
if (-not $RunKey.StartsWith('HKCU:', [StringComparison]::OrdinalIgnoreCase)) { throw 'RunKey must be under HKCU: (per-user only).' }
$links = @()
if ($ProgramsDir) { $links += (Join-Path $ProgramsDir 'Lens.lnk') }
elseif ($record.shortcut -is [string]) { $links += $record.shortcut }
else { $links += (Join-Path ([Environment]::GetFolderPath('Programs')) 'Lens.lnk') }

# Process.Path is re-read on every access; a process that exits in between reads as null, so read it once.
$fromHere = { param($p) $path = $p.Path; $path -and $path.StartsWith($InstallDir, [StringComparison]::OrdinalIgnoreCase) }
# Ask a running agent from this installation to shut down cleanly (it stops its observer, voice and engine children).
if (Get-Process -Name lens-agent -ErrorAction SilentlyContinue | Where-Object { & $fromHere $_ }) {
  try {
    $pipe = New-Object System.IO.Pipes.NamedPipeClientStream('.', $PipeName, [System.IO.Pipes.PipeDirection]::InOut)
    $pipe.Connect(3000)
    $bytes = [Text.Encoding]::UTF8.GetBytes("{`"op`":`"shutdown`"}`n"); $pipe.Write($bytes, 0, $bytes.Length); $pipe.Flush()
    $buffer = New-Object byte[] 256; [void]$pipe.Read($buffer, 0, $buffer.Length); $pipe.Dispose()
  } catch { Write-Verbose "Agent did not answer on $PipeName; stopping it instead." }
}
# Stop whatever still runs from this installation.
Get-Process -Name lens-app, lens-agent, lens-engine, lens-observer, lens-ocr, lens-voice, lens-mesh, lens-sherpa, lens-tts -ErrorAction SilentlyContinue |
  Where-Object { & $fromHere $_ } |
  ForEach-Object { if (-not $_.WaitForExit(10000)) { Stop-Process -Id $_.Id -Force; $_.WaitForExit(5000) | Out-Null } }

# Sign-in entry (written by the installer or by the app's "Start with Windows"): only if it points into this installation.
if (Test-Path -LiteralPath $RunKey) {
  $value = (Get-ItemProperty -LiteralPath $RunKey -Name 'LensAgent' -ErrorAction SilentlyContinue).LensAgent
  if ($value -and $value.TrimStart('"').StartsWith($InstallDir, [StringComparison]::OrdinalIgnoreCase)) {
    Remove-ItemProperty -LiteralPath $RunKey -Name 'LensAgent'
  }
}
foreach ($link in $links) {
  if (Test-Path -LiteralPath $link) { $target = (New-Object -ComObject WScript.Shell).CreateShortcut($link).TargetPath
    if ($target -and $target.StartsWith($InstallDir, [StringComparison]::OrdinalIgnoreCase)) { Remove-Item -LiteralPath $link -Force } }
}
Remove-Item -LiteralPath $InstallDir -Recurse -Force
Write-Host 'Lens removed.'

if ($RemoveData -and (Test-Path -LiteralPath $DataDir)) {
  if (-not $Force) {
    $answer = Read-Host "Permanently delete all Lens memories in $DataDir? Type DELETE to confirm"
    if ($answer -ne 'DELETE') { Write-Host 'Memories kept.'; return }
  }
  Remove-Item -LiteralPath $DataDir -Recurse -Force
  Write-Host 'Lens memories deleted.'
} elseif (Test-Path -LiteralPath $DataDir) { Write-Host "Your encrypted memories remain in $DataDir." }
