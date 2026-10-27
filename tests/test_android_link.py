"""End-to-end phone ↔ laptop link: the Android companion (instrumented test on an emulator) pairs with a real
lens-agent/lens-mesh on this machine, recalls laptop memory over TLS 1.3 and contributes a note; the laptop then
verifies that note's device and provenance were set by the laptop. Skipped when no emulator/device is connected."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
ROOT=Path(__file__).resolve().parents[1]
REL=ROOT/'build/engine/Release'
ANDROID=ROOT/'android'
ADB=Path(os.environ.get('LOCALAPPDATA',''))/'Android/Sdk/platform-tools/adb.exe'
JDK=r'C:\Program Files\Eclipse Adoptium\jdk-17.0.20.1+1'
sys.path.insert(0,str(ROOT/'tests'))
from test_agent import Pipe


def device_connected():
    if not ADB.exists():return False
    out=subprocess.run([str(ADB),'devices'],capture_output=True,text=True,timeout=30).stdout.splitlines()[1:]
    return any(l.strip().endswith('device') for l in out)


@unittest.skipUnless(device_connected(),'no Android emulator or device connected')
class AndroidLink(unittest.TestCase):
    def test_companion_pairs_recalls_and_contributes(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp);name=f'lens-android-test-{uuid.uuid4().hex[:8]}'
            (data/'config.json').write_text(json.dumps({'phone_link':True,'mesh_port':0,'mesh_bind':'127.0.0.1'}),encoding='utf-8')
            agent=subprocess.Popen([str(REL/'lens-agent.exe'),'--data-dir',str(data),'--root',str(ROOT),'--pipe-name',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            pipe=Pipe(name)
            try:
                pipe.ask({'op':'add','consent':True,'id':'laptop-1','text':'Synthetic memo: the Halvorsen contract renewal is due on 14 November.',
                          'language':'en','timestamp':'2026-10-27T09:00:00Z','device':'laptop','kind':'screen_observation','provenance':'synthetic-test'})
                qr=pipe.ask({'op':'mesh_pair_begin'})['qr'];qr['hosts']=['10.0.2.2']  # emulator alias for the host loopback
                code=base64.b64encode(json.dumps(qr).encode()).decode()
                env={**os.environ,'JAVA_HOME':JDK}
                p=subprocess.run([str(ANDROID/'gradlew.bat'),':app:connectedDebugAndroidTest','--console=plain',
                                  f'-Pandroid.testInstrumentationRunnerArguments.pairingCode={code}'],cwd=ANDROID,env=env,capture_output=True,text=True,timeout=3600)
                self.assertEqual(p.returncode,0,p.stdout[-4000:]+p.stderr[-2000:])
                hit=pipe.ask({'op':'search','query':'Marlow venue deposit'})['sources'][0]
                self.assertEqual(hit['device'],'Lens test phone');self.assertTrue(hit['provenance'].startswith('lens-mesh paired device'))
                self.assertEqual(hit['source_application'],'lens-companion')
                self.assertEqual([d['name'] for d in pipe.ask({'op':'mesh_devices'})['devices']],['Lens test phone'])  # wrong-pin attempt never paired
            finally:
                pipe.ask({'op':'shutdown'});pipe.close();agent.wait(timeout=60)


if __name__=='__main__':unittest.main()
