"""Milestone 9 packaging and per-user installer, exercised in temporary folders: the install root, the Start menu
folder and the data folder are temp dirs, and the sign-in entry goes to a scratch HKCU key that is deleted afterwards
(the user's real Run key is only read, to prove it is untouched). Uses Windows PowerShell 5.1, which every supported
Windows has. Nothing is shown: the agent runs with --tray-hidden and the app only in --self-test / --background."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
import winreg
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_agent import Pipe
from test_app import delete_scratch_key,real_autostart
PS=['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File']


def lens_processes_under(folder):
    """Lens processes whose executable lives under folder (read-only query)."""
    p=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',
                      "Get-Process -Name 'lens-*' -ErrorAction SilentlyContinue | Where-Object { $_.Path } | ForEach-Object { $_.Path }"],
                     capture_output=True,text=True,timeout=60)
    return [l for l in p.stdout.splitlines() if l.lower().startswith(str(folder).lower())]


class Installer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.dist=Path(cls.tmp.name)/'Lens'
        p=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/package_lens.py'),'--out',str(cls.dist)],capture_output=True,text=True,timeout=1800)
        assert p.returncode==0,p.stderr
        cls.manifest=json.loads((cls.dist/'manifest.json').read_text(encoding='utf-8'))

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def setUp(self):
        self.real_autostart=real_autostart()
        self.key=rf'Software\LensTest-{uuid.uuid4().hex[:10]}\Run'

    def tearDown(self):
        delete_scratch_key(self.key)
        self.assertEqual(real_autostart(),self.real_autostart)  # the user's own sign-in entry is untouched

    def scratch_value(self):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,self.key) as k:return winreg.QueryValueEx(k,'LensAgent')[0]
        except OSError:return None

    def test_package_footprint_and_manifest(self):
        self.assertLessEqual(self.manifest['installed_bytes'],500_000_000)
        paths={f['path'] for f in self.manifest['files']}
        for need in ['bin/lens-agent.exe','bin/lens-app.exe','bin/lens-engine.exe','bin/lens-voice.exe','bin/ggml-cpu-x64.dll','bin/vcruntime140.dll','bin/ui/index.html',
                     'third_party/embedding-lock.json','.tools/ocr-runtime/onnxruntime.dll','models/ggerganov--whisper.cpp/ggml-base-q5_1.bin']:self.assertIn(need,paths)
        self.assertFalse(any('testapp' in p or p.endswith('.pdb') for p in paths))

    def test_install_run_and_uninstall_in_isolation(self):
        with tempfile.TemporaryDirectory() as work:
            target=Path(work)/'Programs'/'Lens';data=Path(work)/'data'
            p=subprocess.run(PS+[str(self.dist/'install_lens.ps1'),'-InstallDir',str(target),'-NoShortcut','-RunKey','HKCU:\\'+self.key],capture_output=True,text=True,timeout=600)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            record=json.loads((target/'install.json').read_text(encoding='utf-8-sig'));self.assertFalse(record['autostart']);self.assertIsNone(self.scratch_value())
            name=f'lens-install-test-{uuid.uuid4().hex[:8]}'
            agent=subprocess.Popen([str(target/'bin/lens-agent.exe'),'--data-dir',str(data),'--pipe-name',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            pipe=Pipe(name)
            try:
                s=pipe.ask({'op':'status'});self.assertEqual(s['semantic'],'verified')  # root found, models verified in the install
                r=subprocess.run([str(target/'bin/lens-app.exe'),'--self-test','--pipe-name',name],capture_output=True,text=True,timeout=120)
                self.assertEqual(r.returncode,0,r.stdout);self.assertTrue(json.loads(r.stdout.strip().splitlines()[-1])['ok'])
            finally:
                pipe.ask({'op':'shutdown'});pipe.close();agent.wait(timeout=30)
            u=subprocess.run(PS+[str(target/'uninstall_lens.ps1'),'-InstallDir',str(target),'-DataDir',str(data)],capture_output=True,text=True,timeout=300)
            self.assertEqual(u.returncode,0,u.stdout+u.stderr);self.assertFalse(target.exists());self.assertTrue((data/'memory.db').exists())

    def test_first_run_flow_autostart_and_clean_uninstall(self):
        """install (opted in to autostart) -> sign-in launch -> onboarding shown -> consent -> agent running -> uninstall."""
        with tempfile.TemporaryDirectory() as work:
            target=Path(work)/'Programs'/'Lens';data=Path(work)/'data';programs=Path(work)/'StartMenu';name=f'lens-firstrun-{uuid.uuid4().hex[:8]}'
            p=subprocess.run(PS+[str(self.dist/'install_lens.ps1'),'-InstallDir',str(target),'-Autostart','-ProgramsDir',str(programs),'-RunKey','HKCU:\\'+self.key],
                             capture_output=True,text=True,timeout=600)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            app=target/'bin'/'lens-app.exe'
            self.assertEqual(self.scratch_value(),f'"{app}" --background')  # per-user Run value, windowless launcher
            self.assertTrue((programs/'Lens.lnk').exists())
            record=json.loads((target/'install.json').read_text(encoding='utf-8-sig'))
            self.assertTrue(record['autostart']);self.assertEqual(record['run_key'],'HKCU:\\'+self.key);self.assertFalse(record['code_signed'])
            try:
                # What sign-in runs (plus test isolation: own pipe and data folder, tray without its icon).
                b=subprocess.run([str(app),'--background','--tray-hidden','--pipe-name',name,'--data-dir',str(data)],capture_output=True,text=True,timeout=120)
                self.assertEqual(b.returncode,0,b.stdout+b.stderr)
                self.assertTrue(any(x.lower().endswith('lens-agent.exe') for x in lens_processes_under(target)))
                pipe=Pipe(name)
                s=pipe.ask({'op':'status'})
                self.assertEqual(s['tray'],'hidden');self.assertFalse(s['onboarded'])
                for k in ['observe_screen','microphone','phone_link','observer_running','voice_running','mesh_running']:self.assertFalse(s[k],k)  # nothing before consent
                r=subprocess.run([str(app),'--self-test','--pipe-name',name],capture_output=True,text=True,timeout=120)
                out=json.loads(r.stdout.strip().splitlines()[-1]);self.assertTrue(out['ok']);self.assertTrue(out['onboarding'])
                # The onboarding's Finish, as the UI sends it (screen stays off here: tests never observe the real screen).
                self.assertTrue(pipe.ask({'op':'set_exclusions','excluded_processes':['slack.exe'],'private_title_markers':[]})['ok'])
                self.assertTrue(pipe.ask({'op':'set_consent','observe_screen':False,'microphone':False,'phone_link':False,'onboarded':True})['onboarded'])
                r=subprocess.run([str(app),'--self-test','--pipe-name',name],capture_output=True,text=True,timeout=120)
                self.assertFalse(json.loads(r.stdout.strip().splitlines()[-1])['onboarding'])
                config=json.loads((data/'config.json').read_text(encoding='utf-8'))
                self.assertTrue(config['onboarded']);self.assertEqual(config['observer']['excluded_processes'],['slack.exe'])
                pipe.close()
                # Uninstall while the agent is running: it is asked to shut down, then everything recorded is removed.
                u=subprocess.run(PS+[str(target/'uninstall_lens.ps1'),'-InstallDir',str(target),'-DataDir',str(data),'-PipeName',name],
                                 capture_output=True,text=True,timeout=300)
                self.assertEqual(u.returncode,0,u.stdout+u.stderr)
                self.assertEqual(lens_processes_under(target),[]);self.assertFalse(target.exists())
                self.assertIsNone(self.scratch_value());self.assertFalse((programs/'Lens.lnk').exists())
                self.assertTrue((data/'memory.db').exists());self.assertTrue((data/'config.json').exists())  # memories kept by default
                self.assertIn('remain',u.stdout)
            finally:
                if lens_processes_under(target):
                    try:q=Pipe(name,timeout=5);q.ask({'op':'shutdown'});q.close();time.sleep(3)
                    except OSError:pass

    def test_tampered_package_is_refused(self):
        with tempfile.TemporaryDirectory() as work:
            copy=Path(work)/'Lens';shutil.copytree(self.dist,copy)
            with open(copy/'bin/ui/app.js','a',encoding='utf-8') as f:f.write('\n// tampered\n')
            p=subprocess.run(PS+[str(copy/'install_lens.ps1'),'-InstallDir',str(Path(work)/'target'),'-NoShortcut','-RunKey','HKCU:\\'+self.key],capture_output=True,text=True,timeout=600)
            self.assertNotEqual(p.returncode,0);self.assertIn('does not match',p.stdout+p.stderr);self.assertFalse((Path(work)/'target'/'bin').exists())


if __name__=='__main__':unittest.main()
