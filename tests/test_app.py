"""Lens Windows app. (1) The native host's --self-test runs the real UI against a real agent through the bridge in a
window that is never shown. (2) UI behaviour runs in headless Microsoft Edge (no window) with a mock bridge:
untrusted memory text is rendered as text only, abstention, consent toggle, timeline grouping, status pill, first-run
onboarding. (3) The agent's consent, exclusions, autostart and tray commands, without any visible window or icon."""
import ctypes
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
import wave
import winreg
ROOT=Path(__file__).resolve().parents[1]
REL=ROOT/'build/engine/Release'
UI=ROOT/'engine/app/ui'
EDGE=Path(r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
sys.path.insert(0,str(ROOT/'tests'))
from test_agent import Pipe

MOCK=r"""
window.__calls = [];
window.__state = Object.assign({ observe: false, mic: false, phone: false, paused: false, onboarded: true, autostart: false, exclusions: {} }, window.__preset || {});
window.__lensMock = (req) => {
  window.__calls.push(req);
  if (req.op === 'status') return { ok: true, observe_screen: __state.observe, observer_running: __state.observe && !__state.paused, paused: __state.paused, stored: 3,
      semantic: 'verified', microphone: __state.mic, voice_running: __state.mic && !__state.paused, phone_link: __state.phone, onboarded: __state.onboarded,
      autostart: __state.autostart, exclusions: __state.exclusions, data_dir: 'D:/LensTestData' };
  if (req.op === 'set_consent') {
    if ('observe_screen' in req) __state.observe = req.observe_screen; if ('microphone' in req) __state.mic = req.microphone;
    if ('phone_link' in req) __state.phone = req.phone_link; if ('onboarded' in req) __state.onboarded = req.onboarded;
    return { ok: true, observe_screen: __state.observe, microphone: __state.mic, phone_link: __state.phone, onboarded: __state.onboarded };
  }
  if (req.op === 'set_exclusions') { __state.exclusions = { excluded_processes: req.excluded_processes, private_title_markers: req.private_title_markers };
      return Object.assign({ ok: true }, __state.exclusions); }
  if (req.op === 'set_autostart') { __state.autostart = req.enabled; return { ok: true, autostart: req.enabled }; }
  if (req.op === 'pause' || req.op === 'resume') { __state.paused = req.op === 'pause'; return { ok: true, paused: __state.paused }; }
  if (req.op === 'recall' && req.query === 'nothing') return { ok: true, not_found: true, results: [] };
  if (req.op === 'recall') return { ok: true, not_found: false, results: [{
      source: { id: 's1', text: 'FULL <img src=x onerror="window.__pwned=1"> text', timestamp: '2026-10-27T09:30:00Z', source_application: 'chrome.exe', source_locator: 'window:Paper <b>bold</b> - Chrome' },
      evidence: { quote: 'Quote <script>window.__pwned=2</script> and <img src=x onerror="window.__pwned=3">' },
      episode: { application: 'chrome.exe', observation_count: 4, duration_seconds: 300 } }] };
  if (req.op === 'episodes') return { ok: true, episodes: [
      { started_at: '2026-10-27T09:00:00Z', ended_at: '2026-10-27T09:10:00Z', application: 'winword.exe', title: 'Budget memo', observation_count: 3 },
      { started_at: '2026-10-27T08:00:00Z', ended_at: '2026-10-27T08:20:00Z', application: 'chrome.exe', title: 'Vendor contract', observation_count: 5 },
      { started_at: '2026-10-26T17:00:00Z', ended_at: '2026-10-26T17:05:00Z', application: 'code.exe', title: 'repo', observation_count: 2 }] };
  if (req.op === 'action_pending') return { ok: true, actions: __state.decided ? [] : [{ id: 'act-1', capability: 'laptop.remember', requested_by: 'paired device Pixel',
      requested_utc: '2026-10-27T09:00:00Z', params: { text: 'Remember <img src=x onerror="window.__pwned=4">' }, status: 'pending_confirmation' }] };
  if (req.op === 'action_decide') { __state.decided = true; return { ok: true, action: { id: req.id, status: req.approve ? 'executed' : 'denied' } }; }
  if (req.op === 'stats') return { ok: true, source_count: 10, embedded_sources: 8, compressed_sources: 4, schema_version: 7 };
  return { ok: false, error: 'unsupported_operation' };
};
"""
SCENARIO=r"""
(async () => {
  const out = {};
  const settle = () => new Promise((r) => setTimeout(r, 50));
  try {
    await settle();
    document.getElementById('ask-input').value = 'paper i read';
    document.getElementById('ask-form').requestSubmit(); await settle();
    const card = document.querySelector('.result');
    out.results = document.querySelectorAll('.result').length;
    out.quote = card.querySelector('.quote').textContent;
    out.window = card.querySelector('.window').textContent;
    out.episode = card.querySelector('.episode').textContent;
    out.injected_elements = document.querySelectorAll('.results img, .results script, .results b').length;
    out.pwned = window.__pwned || 0;
    card.querySelector('.source-btn').click(); out.source_shown = !card.querySelector('.source').hidden;
    document.getElementById('ask-input').value = 'nothing';
    document.getElementById('ask-form').requestSubmit(); await settle();
    out.abstain = document.querySelector('.empty strong') ? document.querySelector('.empty strong').textContent : '';
    const toggle = document.getElementById('observe-toggle');
    toggle.checked = true; toggle.dispatchEvent(new Event('change')); await settle();
    out.consent_calls = __calls.filter((c) => c.op === 'set_consent').map((c) => c.observe_screen);
    out.pill = document.getElementById('capture-text').textContent;
    window.lensUi.show('privacy'); await settle();
    out.privacy_nav = document.querySelector('.nav[data-view="privacy"]').textContent;
    out.request_text = document.querySelector('.request-text strong').textContent;
    out.request_injected = document.querySelectorAll('.requests img').length;
    document.querySelector('.request .primary').click(); await settle(); await settle();
    out.decide_calls = __calls.filter((c) => c.op === 'action_decide').map((c) => [c.id, c.approve]);
    out.after_nav = document.querySelector('.nav[data-view="privacy"]').textContent;
    window.lensUi.show('timeline'); await settle();
    out.days = document.querySelectorAll('.day').length; out.rows = document.querySelectorAll('.episode-row').length;
    window.lensUi.show('status'); await settle();
    out.stats = [...document.querySelectorAll('.stat .value')].map((n) => n.textContent);
    out.selftest = typeof window.lensSelfTest;
  } catch (e) { out.error = String(e && e.stack || e); }
  const pre = document.createElement('pre'); pre.id = 'scenario-result'; pre.textContent = JSON.stringify(out); document.body.append(pre);
})();
"""


ONBOARDING=r"""
(async () => {
  const out = {};
  const settle = () => new Promise((r) => setTimeout(r, 50));
  const ob = document.getElementById('onboarding');
  const mutations = () => __calls.filter((c) => c.op.startsWith('set_') || c.op === 'pause' || c.op === 'resume');
  const addExclusion = (index, text) => {
    const form = ob.querySelectorAll('.excl form')[index]; form.querySelector('input').value = text; form.requestSubmit();
  };
  try {
    await settle(); await settle();
    out.visible = !ob.hidden;
    out.step = ob.querySelector('.ob-step.active').dataset.step;
    out.data_dir = document.getElementById('ob-data-dir').textContent;
    out.explains = ob.querySelector('.ob-step[data-step="1"]').textContent.includes('nothing is captured');
    ob.querySelector('.ob-step.active [data-next]').click(); await settle();
    out.defaults = ['ob-screen', 'ob-mic', 'ob-phone', 'ob-autostart'].map((id) => document.getElementById(id).checked);
    document.getElementById('ob-screen').checked = true;
    ob.querySelector('.ob-step.active [data-next]').click(); await settle();
    addExclusion(0, 'Slack'); addExclusion(0, 'C:\\Apps\\Signal.exe'); addExclusion(1, '  Bank Statement '); addExclusion(0, 'slack.exe');
    out.chips = [...ob.querySelectorAll('.chip span')].map((n) => n.textContent);
    ob.querySelector('.chip button').click(); await settle();
    out.before_finish = mutations().length;  // nothing reaches the agent before Finish
    document.getElementById('ob-finish').click(); await settle(); await settle();
    out.finish_calls = mutations();
    out.hidden_after = ob.hidden;
    out.pill = document.getElementById('capture-text').textContent;
    window.lensUi.show('privacy'); await settle();
    out.privacy_chips = [...document.querySelectorAll('#privacy-exclusions .chip span')].map((n) => n.textContent);
    out.privacy_toggles = ['observe-toggle', 'mic-toggle', 'phone-toggle', 'autostart-toggle'].map((id) => document.getElementById(id).checked);
    const mic = document.getElementById('mic-toggle'); mic.checked = true; mic.dispatchEvent(new Event('change')); await settle();
    const auto = document.getElementById('autostart-toggle'); auto.checked = true; auto.dispatchEvent(new Event('change')); await settle();
    document.getElementById('pause-button').click(); await settle();
    out.paused_pill = document.getElementById('capture-text').textContent;
    out.pause_label = document.getElementById('pause-button').textContent;
    const form = document.querySelector('#privacy-exclusions .excl form'); form.querySelector('input').value = 'teams'; form.requestSubmit();
    document.getElementById('exclusions-save').click(); await settle();
    out.saved = document.getElementById('exclusions-saved').textContent;
    const n = __calls.length;
    window.lensUi.openOnboarding({ data_dir: 'x' }); document.getElementById('ob-skip').click(); await settle();
    out.skip_calls = __calls.slice(n).filter((c) => c.op.startsWith('set_'));
    out.all_calls = mutations();
  } catch (e) { out.error = String(e && e.stack || e); }
  const pre = document.createElement('pre'); pre.id = 'scenario-result'; pre.textContent = JSON.stringify(out); document.body.append(pre);
})();
"""


def run_in_headless_edge(test,scenario,preset=''):
    """Runs the bundled UI with the mock bridge and a scenario in headless Edge (no window); returns the scenario's JSON."""
    with tempfile.TemporaryDirectory() as tmp:
        d=Path(tmp)/'ui';shutil.copytree(UI,d)
        (d/'mock.js').write_text(preset+MOCK,encoding='utf-8');(d/'scenario.js').write_text(scenario,encoding='utf-8')
        html=(d/'index.html').read_text(encoding='utf-8').replace('<script src="app.js"></script>','<script src="mock.js"></script><script src="app.js"></script><script src="scenario.js"></script>')
        (d/'harness.html').write_text(html,encoding='utf-8')
        p=subprocess.run([str(EDGE),'--headless=new','--disable-gpu','--no-first-run','--disable-extensions',f'--user-data-dir={Path(tmp)/"profile"}',
                          '--allow-file-access-from-files','--virtual-time-budget=10000','--dump-dom',(d/'harness.html').as_uri()],
                         capture_output=True,text=True,encoding='utf-8',timeout=120)
        m=re.search(r'<pre id="scenario-result">(.*?)</pre>',p.stdout,re.S);test.assertTrue(m,p.stdout[-2000:]+p.stderr[-1000:])
        import html as h;out=json.loads(h.unescape(m.group(1)))
        test.assertNotIn('error',out,out.get('error'))
        return out


class AppUi(unittest.TestCase):
    def test_ui_behaviour_in_headless_edge(self):
        out=run_in_headless_edge(self,SCENARIO)
        self.assertEqual(out['results'],1);self.assertEqual(out['injected_elements'],0);self.assertEqual(out['pwned'],0)
        self.assertIn('<script>',out['quote']);self.assertIn('<b>bold</b>',out['window'])  # shown literally, not executed
        self.assertIn('Chrome session',out['episode']);self.assertTrue(out['source_shown'])
        self.assertEqual(out['abstain'],'No reliable evidence found')
        self.assertEqual(out['consent_calls'],[True]);self.assertEqual(out['pill'],'Observing')
        self.assertEqual(out['privacy_nav'],'Privacy (1)');self.assertIn('<img',out['request_text']);self.assertEqual(out['request_injected'],0)
        self.assertEqual(out['decide_calls'],[['act-1',True]]);self.assertEqual(out['after_nav'],'Privacy')
        self.assertEqual((out['days'],out['rows']),(2,3));self.assertEqual(out['stats'][:3],['10','8','4']);self.assertEqual(out['selftest'],'function')

    def test_first_run_onboarding_asks_before_anything_is_captured(self):
        out=run_in_headless_edge(self,ONBOARDING,'window.__preset = { onboarded: false };')
        self.assertTrue(out['visible']);self.assertEqual(out['step'],'1');self.assertEqual(out['data_dir'],'D:/LensTestData');self.assertTrue(out['explains'])
        self.assertEqual(out['defaults'],[False,False,False,False])  # every consent and autostart starts off
        self.assertEqual(out['chips'],['slack.exe','signal.exe','bank statement'])  # normalised, de-duplicated
        self.assertEqual(out['before_finish'],0)
        self.assertEqual(out['finish_calls'],[
            {'op':'set_exclusions','excluded_processes':['signal.exe'],'private_title_markers':['bank statement']},  # before capture starts
            {'op':'set_consent','observe_screen':True,'microphone':False,'phone_link':False,'onboarded':True}])
        self.assertTrue(out['hidden_after']);self.assertEqual(out['pill'],'Observing')
        self.assertEqual(out['privacy_chips'],['signal.exe','bank statement']);self.assertEqual(out['privacy_toggles'],[True,False,False,False])
        self.assertEqual(out['paused_pill'],'Paused');self.assertEqual(out['pause_label'],'Resume')
        self.assertEqual(out['saved'],'Saved')
        self.assertEqual(out['skip_calls'],[{'op':'set_consent','observe_screen':False,'microphone':False,'phone_link':False,'onboarded':True}])
        later=[c['op'] for c in out['all_calls'][2:]]
        self.assertEqual(later,['set_consent','set_autostart','pause','set_exclusions','set_consent'])
        self.assertEqual(out['all_calls'][2],{'op':'set_consent','microphone':True});self.assertEqual(out['all_calls'][3],{'op':'set_autostart','enabled':True})
        self.assertEqual(out['all_calls'][5]['excluded_processes'],['signal.exe','teams.exe'])


class AppHost(unittest.TestCase):
    def test_self_test_reaches_the_agent_without_showing_a_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            name=f'lens-app-test-{uuid.uuid4().hex[:8]}'
            agent=subprocess.Popen([str(REL/'lens-agent.exe'),'--data-dir',tmp,'--root',str(ROOT),'--pipe-name',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            pipe=Pipe(name)
            try:
                r=subprocess.run([str(REL/'lens-app.exe'),'--self-test','--pipe-name',name],capture_output=True,text=True,timeout=120)
                self.assertEqual(r.returncode,0,r.stdout+r.stderr);out=json.loads(r.stdout.strip().splitlines()[-1])
                self.assertTrue(out['ok']);self.assertEqual(out['stats']['schema_version'],8);self.assertFalse(out['status']['observe_screen'])
                self.assertEqual(out['ui'],'Lens');self.assertTrue(out['onboarding'])  # fresh data folder: first-run setup is shown
                pipe.ask({'op':'set_consent','onboarded':True})
                r=subprocess.run([str(REL/'lens-app.exe'),'--self-test','--pipe-name',name],capture_output=True,text=True,timeout=120)
                self.assertFalse(json.loads(r.stdout.strip().splitlines()[-1])['onboarding'])
            finally:
                pipe.ask({'op':'shutdown'});pipe.close();agent.wait(timeout=30)


WM_COMMAND=0x0111;ID_PAUSE,ID_RESUME,ID_OPEN,ID_QUIT=1001,1002,1003,1004
RUN_KEY=r'Software\Microsoft\Windows\CurrentVersion\Run'


def tray_window(name,timeout=10):
    """The agent's tray command window (class LensAgentTray, titled with the pipe name). Never visible."""
    end=time.time()+timeout
    while time.time()<end:
        w=ctypes.windll.user32.FindWindowW('LensAgentTray',name)
        if w:return w
        time.sleep(0.1)
    return 0


def real_autostart():
    """The real user's sign-in entry, read only (tests must never change it)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,RUN_KEY) as k:return winreg.QueryValueEx(k,'LensAgent')[0]
    except OSError:return None


def delete_scratch_key(sub):
    """Removes HKCU\\<sub> and its parent test key (both created only by the test)."""
    for path in (sub,sub.rsplit('\\',1)[0]):
        try:winreg.DeleteKey(winreg.HKEY_CURRENT_USER,path)
        except FileNotFoundError:pass


class AgentDesktop(unittest.TestCase):
    """Consent, exclusions, autostart and tray commands against a real agent. The observer follows an invisible synthetic
    window, the microphone is replaced by a silent WAV file, autostart writes a scratch HKCU key, and the tray runs
    without its notification icon (--tray-hidden): nothing visible, nothing of the user's read or changed."""
    def setUp(self):
        self.real_autostart=real_autostart()
        self.tmp=tempfile.TemporaryDirectory();self.data=Path(self.tmp.name);self.name=f'lens-desk-{uuid.uuid4().hex[:10]}'
        self.key=rf'Software\LensTest-{uuid.uuid4().hex[:10]}\Run'
        with wave.open(str(self.data/'silence.wav'),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0\0'*16000*3)
        self.app=subprocess.Popen([str(REL/'lens-observer-testapp.exe'),'--invisible','Desktop test window','Synthetic label',
                                   'Synthetic desktop note: the Okonkwo budget is due Tuesday.'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
        assert self.app.stdout.readline().strip()=='ready'
        (self.data/'config.json').write_text(json.dumps({'observer':{'min_interval_ms':300,'max_interval_ms':1000}}),encoding='utf-8')
        self.log=open(self.data/'agent.log','w+',encoding='utf-8')
        self.agent=subprocess.Popen([str(REL/'lens-agent.exe'),'--data-dir',str(self.data),'--root',str(ROOT),'--pipe-name',self.name,
                                     '--observer-follow',f'pid:{self.app.pid}','--voice-input-wav',str(self.data/'silence.wav'),
                                     '--autostart-key',self.key,'--tray-hidden'],stdout=subprocess.DEVNULL,stderr=self.log)
        self.pipe=Pipe(self.name)

    def tearDown(self):
        try:self.pipe.ask({'op':'shutdown'});self.pipe.close()
        except OSError:pass
        try:self.agent.wait(timeout=30)
        except subprocess.TimeoutExpired:self.agent.kill();self.agent.wait()
        self.log.close()
        self.app.stdin.write('quit\n');self.app.stdin.flush();self.app.wait(timeout=10);self.app.stdout.close();self.app.stdin.close()
        delete_scratch_key(self.key)
        self.assertEqual(real_autostart(),self.real_autostart)  # the user's own sign-in entry is untouched
        for _ in range(20):  # capture children may hold the inherited log handle for a moment after the agent exits
            try:self.tmp.cleanup();break
            except PermissionError:time.sleep(0.5)

    def config(self):return json.loads((self.data/'config.json').read_text(encoding='utf-8'))

    def test_consents_default_off_and_persist(self):
        s=self.pipe.ask({'op':'status'})
        for k in ['observe_screen','microphone','phone_link','onboarded','observer_running','voice_running','mesh_running','autostart','paused']:self.assertFalse(s[k],k)
        self.assertEqual(s['tray'],'hidden');self.assertEqual(s['exclusions'],{'excluded_processes':[],'private_title_markers':[]})
        self.assertEqual(self.pipe.ask({'op':'set_consent','microphone':'yes'})['error'],'invalid_request')
        self.assertEqual(self.pipe.ask({'op':'pause'})['error'],'observer_not_running')  # nothing to pause
        r=self.pipe.ask({'op':'set_consent','onboarded':True});self.assertTrue(r['onboarded']);self.assertFalse(r['observe_screen'])
        c=self.config();self.assertTrue(c['onboarded']);self.assertFalse(c['observe_screen']);self.assertFalse(c['microphone'])
        time.sleep(1.5);s=self.pipe.ask({'op':'status'});self.assertEqual((s['observed'],s['observer_running'],s['voice_running']),(0,False,False))
        self.assertNotIn('voice_started',(self.data/'agent.log').read_text(encoding='utf-8'))  # no microphone before consent
        r=self.pipe.ask({'op':'set_consent','microphone':True});self.assertTrue(r['microphone']);self.assertTrue(self.config()['microphone'])
        end=time.time()+10
        while time.time()<end and 'voice_started' not in (self.data/'agent.log').read_text(encoding='utf-8'):time.sleep(0.2)
        self.assertIn('voice_started',(self.data/'agent.log').read_text(encoding='utf-8'))
        self.assertTrue(self.pipe.ask({'op':'set_consent','microphone':False})['ok'])
        self.assertFalse(self.pipe.ask({'op':'status'})['voice_running']);self.assertFalse(self.config()['microphone'])

    def test_exclusions_are_validated_and_persisted(self):
        for bad in [{},{'excluded_processes':'slack.exe'},{'excluded_processes':[1]},{'private_title_markers':['a\nb']},{'excluded_processes':['']},
                    {'excluded_processes':['x']*201},{'excluded_processes':['x'*261]}]:
            self.assertEqual(self.pipe.ask({'op':'set_exclusions',**bad})['error'],'invalid_request',bad)
        r=self.pipe.ask({'op':'set_exclusions','excluded_processes':[' slack.exe '],'private_title_markers':['bank statement']})
        self.assertEqual((r['excluded_processes'],r['private_title_markers']),(['slack.exe'],['bank statement']))
        obs=self.config()['observer'];self.assertEqual(obs['excluded_processes'],['slack.exe']);self.assertEqual(obs['min_interval_ms'],300)
        self.assertEqual(self.pipe.ask({'op':'status'})['exclusions']['private_title_markers'],['bank statement'])
        # A title marker matching the synthetic window keeps it out of memory once observation is on.
        self.pipe.ask({'op':'set_exclusions','private_title_markers':['desktop test']})
        self.assertTrue(self.pipe.ask({'op':'set_consent','observe_screen':True})['observe_screen'])
        time.sleep(3);s=self.pipe.ask({'op':'status'});self.assertTrue(s['observer_running']);self.assertEqual(s['stored'],0)
        self.assertEqual(self.pipe.ask({'op':'search','query':'Okonkwo budget'})['sources'],[])

    def test_autostart_uses_a_per_user_run_value(self):
        r=self.pipe.ask({'op':'set_autostart','enabled':True});self.assertTrue(r['autostart'])
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,self.key) as k:value=winreg.QueryValueEx(k,'LensAgent')[0]
        self.assertEqual(value,f'"{REL/"lens-app.exe"}" --background --data-dir "{self.data}" --pipe-name "{self.name}"')
        self.assertTrue(self.pipe.ask({'op':'status'})['autostart'])
        self.assertFalse(self.pipe.ask({'op':'set_autostart','enabled':False})['autostart'])
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,self.key) as k:self.assertRaises(FileNotFoundError,winreg.QueryValueEx,k,'LensAgent')
        self.assertEqual(self.pipe.ask({'op':'set_autostart'})['error'],'invalid_request')

    def test_tray_pause_stops_all_capture_until_resume(self):
        w=tray_window(self.name);self.assertTrue(w)
        self.assertFalse(ctypes.windll.user32.IsWindowVisible(w))
        self.pipe.ask({'op':'set_consent','observe_screen':True,'microphone':True})
        end=time.time()+20
        while time.time()<end and self.pipe.ask({'op':'status'})['stored']<1:time.sleep(0.3)
        self.assertGreaterEqual(self.pipe.ask({'op':'status'})['stored'],1)
        ctypes.windll.user32.SendMessageW(w,WM_COMMAND,ID_PAUSE,0)  # same command as the tray menu's "Pause capture"
        s=self.pipe.ask({'op':'status'});self.assertTrue(s['paused']);self.assertFalse(s['voice_running'])
        before=s['stored']
        self.app.stdin.write('set Synthetic paused note: the Varga invoice must not be captured.\n');self.app.stdin.flush()
        time.sleep(3);s=self.pipe.ask({'op':'status'});self.assertEqual(s['stored'],before)
        self.assertEqual(self.pipe.ask({'op':'search','query':'Varga invoice'})['sources'],[])
        # Exclusion changes restart the observer; pause still holds.
        self.pipe.ask({'op':'set_exclusions','excluded_processes':['notepad.exe']})
        s=self.pipe.ask({'op':'status'});self.assertTrue(s['paused']);self.assertFalse(s['observer_running'])
        time.sleep(1.5);self.assertEqual(self.pipe.ask({'op':'status'})['stored'],before)
        ctypes.windll.user32.SendMessageW(w,WM_COMMAND,ID_RESUME,0)
        end=time.time()+20
        while time.time()<end and self.pipe.ask({'op':'status'})['stored']<=before:time.sleep(0.3)
        s=self.pipe.ask({'op':'status'});self.assertFalse(s['paused']);self.assertTrue(s['observer_running']);self.assertGreater(s['stored'],before)
        self.assertEqual(self.pipe.ask({'op':'search','query':'Varga invoice'})['sources'][0]['kind'],'screen_observation')
        ctypes.windll.user32.SendMessageW(w,WM_COMMAND,ID_QUIT,0)  # "Quit Lens"
        self.assertEqual(self.agent.wait(timeout=30),0)


if __name__=='__main__':unittest.main()
