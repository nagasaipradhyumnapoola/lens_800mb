# Environment audit — 2026-10-26 (Asia/Calcutta)

D:\Lens was empty before initialization. D: is NTFS, 323,370,590,208 bytes total;
initial free space was 255,669,768,192 bytes. A new local Git repository was initialized;
no remote repository, push, publication or visibility change was made.

| Component | Observed |
|---|---|
| OS | Windows 11 Home Single Language, 10.0.26300, build 26300 |
| CPU | AMD Ryzen 9 270 w/ Radeon 780M Graphics, 8 cores / 16 logical |
| RAM | 16,037,108 KiB visible; initial free snapshot 679,168 KiB (host was busy) |
| GPU exposed to WMI | AMD Radeon 780M, driver 32.0.32015.7029; NVIDIA hardware not verified |
| PowerShell | 7.6.5 |
| Git | 2.53.0.windows.1 |
| GitHub CLI | Not on PATH; not needed for local proof |
| Python | System 3.14.4; existing uv-managed 3.12.13 used in project .venv |
| uv | 0.12.3 |
| CMake | Existing Visual Studio CMake 4.3.1-msvc1, off PATH |
| MSVC | Existing Visual Studio Community 2026 / Build Tools; compiler 19.51.36256 |
| Rust | 1.97.0; not used by this engine proof |
| Node | 24.14.1; development skill discovery only |
| Java | JDK 25.0.2; Android Studio bundled JBR also present |
| Android Studio | Installed at C:\Program Files\Android\Android Studio |
| Android SDK | Existing platforms 34, 36, 36.1; adb and command-line tools present |
| NDK | 27.1.12297006 |
| SDK CMake | 3.22.1 |
| Emulator | SDK emulator folder and Android 36 system-images present; not launched/tested |
| Attached devices | `adb devices -l` returned no devices |

No privileged or system-wide dependencies were installed. vcpkg downloads portable build tools
inside its ignored project checkout; Python packages live in the ignored .venv. These are not
distributable app files. No microphone/screen/app-data capture was enabled.

Reproduce inventory: `pwsh -File scripts/audit-environment.ps1`; see environment.json.
Inference timing is a development screening measurement on a busy host, not an isolated latency
certification. Some model trials overlapped dependency compilation; compare accuracy independently
of that timing caveat. Final device endurance, battery and energy measurements remain pending.
