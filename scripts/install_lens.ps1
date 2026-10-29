<#
.SYNOPSIS
  Installs Lens for the current user (no administrator rights). Runs on Windows PowerShell 5.1 and PowerShell 7.
.DESCRIPTION
  Verifies every file of the package against manifest.json (sha256) before copying it to the install folder, adds a
  Start menu shortcut, and registers the background agent to start at sign-in only when -Autostart is given (the user's
  opt-in; the app's first-run setup and Privacy page can turn it on or off later). Every capture (screen, microphone,
  phone link) stays OFF until the user turns it on in the app. Memories are stored encrypted under %LOCALAPPDATA%\Lens
  and are not touched by reinstalling. Per-user only: no administrator rights, no services, nothing outside the
  user's profile. The package is NOT code-signed yet (no certificate), so Windows may warn about an unknown publisher.
.PARAMETER InstallDir   Target folder (default: %LOCALAPPDATA%\Programs\Lens).
.PARAMETER Autostart    Start the Lens background agent (tray icon) when the user signs in.
.PARAMETER NoShortcut   Do not create the Start menu shortcut.
.PARAMETER ProgramsDir  Folder for the Start menu shortcut (default: the user's Start menu Programs folder; tests pass a temp folder).
.PARAMETER RunKey       Registry key for the sign-in entry (default: HKCU Run; tests pass a scratch key under HKCU).
.PARAMETER Launch       Open Lens after installing (first-run setup).
#>
[CmdletBinding()]
param(
  [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Programs\Lens'),
  [switch]$Autostart,
  [switch]$NoShortcut,
  [string]$ProgramsDir = [Environment]::GetFolderPath('Programs'),
  [string]$RunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run',
  [switch]$Launch
)
$ErrorActionPreference = 'Stop'
$source = Split-Path -Parent $MyInvocation.MyCommand.Path
$manifestPath = Join-Path $source 'manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath)) { throw 'manifest.json not found next to the installer.' }
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json

# Refuse unsupported machines early: 64-bit Windows 10 or later with SSE4.2 + POPCNT (docs/LENS_V1_SPEC.md section 15).
if (-not [Environment]::Is64BitOperatingSystem) { throw 'Lens needs 64-bit Windows.' }
if ([Environment]::OSVersion.Version.Major -lt 10) { throw 'Lens needs Windows 10 or later.' }

Write-Host "Verifying $($manifest.files.Count) files..."
foreach ($f in $manifest.files) {
  $path = Join-Path $source ($f.path -replace '/', '\')
  if (-not (Test-Path -LiteralPath $path)) { throw "Missing file: $($f.path)" }
  $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($hash -ne $f.sha256) { throw "File does not match the package manifest: $($f.path)" }
}

$running = Get-Process -Name lens-agent, lens-app -ErrorAction SilentlyContinue | Where-Object { $path = $_.Path; $path -and $path.StartsWith($InstallDir, [StringComparison]::OrdinalIgnoreCase) }
if ($running) { throw 'Lens is running from the install folder. Close it (and its background agent) first.' }

Write-Host "Installing to $InstallDir"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
foreach ($f in $manifest.files) {
  $from = Join-Path $source ($f.path -replace '/', '\')
  $to = Join-Path $InstallDir ($f.path -replace '/', '\')
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $to) | Out-Null
  Copy-Item -LiteralPath $from -Destination $to -Force
}
Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $InstallDir 'manifest.json') -Force

$app = Join-Path $InstallDir 'bin\lens-app.exe'
if (-not $RunKey.StartsWith('HKCU:', [StringComparison]::OrdinalIgnoreCase)) { throw 'RunKey must be under HKCU: (per-user only).' }
$shortcut = $null
if (-not $NoShortcut) {
  New-Item -ItemType Directory -Force -Path $ProgramsDir | Out-Null
  $shortcut = Join-Path $ProgramsDir 'Lens.lnk'
  $shell = New-Object -ComObject WScript.Shell
  $link = $shell.CreateShortcut($shortcut)
  $link.TargetPath = $app; $link.WorkingDirectory = (Split-Path -Parent $app); $link.Description = 'Lens - your private memory'
  $link.Save()
}
# Sign-in entry: lens-app --background is a windowless launcher that starts the agent with its tray icon and exits.
if ($Autostart) {
  if (-not (Test-Path -LiteralPath $RunKey)) { New-Item -Path $RunKey -Force | Out-Null }
  Set-ItemProperty -LiteralPath $RunKey -Name 'LensAgent' -Value ('"' + $app + '" --background')
} elseif (Test-Path -LiteralPath $RunKey) { Remove-ItemProperty -LiteralPath $RunKey -Name 'LensAgent' -ErrorAction SilentlyContinue }

$record = [ordered]@{ product = 'Lens'; version = $manifest.version; install_dir = $InstallDir; installed_utc = (Get-Date).ToUniversalTime().ToString('o');
  autostart = [bool]$Autostart; shortcut = $shortcut; run_key = $RunKey; installed_bytes = $manifest.installed_bytes; code_signed = $false }
$record | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $InstallDir 'install.json') -Encoding UTF8
Write-Host "Lens $($manifest.version) installed ($([math]::Round($manifest.installed_bytes / 1MB)) MB). Nothing is captured until you choose what to allow in the app."
if ($Launch) { Start-Process -FilePath $app }
