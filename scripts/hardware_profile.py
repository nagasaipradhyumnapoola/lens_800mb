"""Record the hardware profile that every tier report must carry (docs/acceptance-gates.md, hardware gates).

Collects: CPU model, instruction-set features (two sources: Windows IsProcessorFeaturePresent and numpy's CPUID
probe, disagreements listed), logical processors, physical RAM (total/available), Windows version and build,
display adapters, power source and battery presence. It records no host name, user name or serial numbers.
Development tool (Python); a native equivalent inside the engine is planned for low-end test machines.
Usage: .venv\\Scripts\\python.exe scripts/hardware_profile.py [--out reports/hardware/<tier>.json]
"""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import winreg
# winnt.h PF_* constants; Windows releases that predate a constant report it as absent.
PF={'sse2':10,'sse3':13,'ssse3':36,'sse4_1':37,'sse4_2':38,'avx':39,'avx2':40,'avx512f':41}
NUMPY={'sse2':'SSE2','sse3':'SSE3','ssse3':'SSSE3','sse4_1':'SSE41','sse4_2':'SSE42','popcnt':'POPCNT','avx':'AVX',
       'f16c':'F16C','fma3':'FMA3','avx2':'AVX2','avx512f':'AVX512F','avx512_vnni':'AVX512VNNI'}
# x86-64 baseline required by docs/LENS_V1_SPEC.md §15 (the Windows 11 24H2 floor).
BASELINE=('sse4_2','popcnt')


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_=[('dwLength',wintypes.DWORD),('dwMemoryLoad',wintypes.DWORD),('ullTotalPhys',ctypes.c_ulonglong),
              ('ullAvailPhys',ctypes.c_ulonglong),('ullTotalPageFile',ctypes.c_ulonglong),('ullAvailPageFile',ctypes.c_ulonglong),
              ('ullTotalVirtual',ctypes.c_ulonglong),('ullAvailVirtual',ctypes.c_ulonglong),('ullAvailExtendedVirtual',ctypes.c_ulonglong)]


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_=[('ACLineStatus',ctypes.c_ubyte),('BatteryFlag',ctypes.c_ubyte),('BatteryLifePercent',ctypes.c_ubyte),
              ('SystemStatusFlag',ctypes.c_ubyte),('BatteryLifeTime',wintypes.DWORD),('BatteryFullLifeTime',wintypes.DWORD)]


def windows_features():
    k=ctypes.windll.kernel32;return {n:bool(k.IsProcessorFeaturePresent(c)) for n,c in PF.items()}


def cpuid_features():
    try:
        from numpy._core._multiarray_umath import __cpu_features__ as f
    except ImportError:
        try:from numpy.core._multiarray_umath import __cpu_features__ as f
        except ImportError:return None
    return {n:bool(f.get(k,False)) for n,k in NUMPY.items()}


def cpu_name():
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
            return winreg.QueryValueEx(key,'ProcessorNameString')[0].strip()
    except OSError:return platform.processor()


def windows_version():
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\Microsoft\Windows NT\CurrentVersion') as key:
            get=lambda n:winreg.QueryValueEx(key,n)[0]
            build=int(get('CurrentBuildNumber'));ubr=get('UBR')
            try:display=get('DisplayVersion')
            except OSError:display=None
            # The registry ProductName says "Windows 10" on Windows 11; the build number is authoritative.
            return {'product':'Windows 11' if build>=22000 else 'Windows 10' if build>=10240 else 'older',
                    'display_version':display,'build':build,'ubr':ubr,'edition':get('EditionID')}
    except OSError:return {'product':platform.system(),'release':platform.release(),'version':platform.version()}


def memory():
    m=MEMORYSTATUSEX();m.dwLength=ctypes.sizeof(m);ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return {'total_bytes':m.ullTotalPhys,'available_bytes':m.ullAvailPhys,'load_percent':m.dwMemoryLoad,
            'commit_limit_bytes':m.ullTotalPageFile,'commit_available_bytes':m.ullAvailPageFile}


def power():
    s=SYSTEM_POWER_STATUS();ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s))
    return {'ac_online':{0:False,1:True}.get(s.ACLineStatus),'battery_present':s.BatteryFlag!=128 and s.BatteryFlag!=255,
            'battery_percent':None if s.BatteryLifePercent==255 else s.BatteryLifePercent,'battery_saver':bool(s.SystemStatusFlag&1)}


def display_adapters():
    cmd=['powershell','-NoProfile','-NonInteractive','-Command',
         'Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,AdapterRAM | ConvertTo-Json -Compress']
    try:out=subprocess.run(cmd,capture_output=True,text=True,timeout=60).stdout.strip()
    except (OSError,subprocess.TimeoutExpired):return None
    if not out:return []
    data=json.loads(out);data=data if isinstance(data,list) else [data]
    return [{'name':d.get('Name'),'driver':d.get('DriverVersion'),'adapter_ram_bytes':d.get('AdapterRAM')} for d in data]


def profile():
    win=windows_features();cpuid=cpuid_features()
    merged={n:(cpuid or {}).get(n,win.get(n)) for n in sorted(set(win)|set(cpuid or {}))}
    disagree=sorted(n for n in win if cpuid is not None and n in cpuid and win[n]!=cpuid[n])
    return {'cpu':{'name':cpu_name(),'logical_processors':os.cpu_count(),'architecture':platform.machine(),
                   'features':merged,'features_windows':win,'features_cpuid':cpuid,'source_disagreements':disagree,
                   'meets_lens_baseline':all(merged.get(n) for n in BASELINE),'baseline':list(BASELINE)},
            'memory':memory(),'windows':windows_version(),'display_adapters':display_adapters(),'power':power(),
            'python':sys.version.split()[0]}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path);args=ap.parse_args()
    p=profile();text=json.dumps(p,indent=1,ensure_ascii=False)
    if args.out:args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(text+'\n',encoding='utf-8')
    print(text)


if __name__=='__main__':main()
