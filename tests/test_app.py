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
window.__lensHostMock = (name) => (name === 'pick_file' ? { ok: true, path: 'C:/exports/chat.txt', name: 'chat <img src=x onerror="window.__pwned=7">.txt' } : { ok: false, error: 'unsupported' });
window.confirm = () => true;
window.__lensMock = (req) => {
  window.__calls.push(req);
  const X = '<img src=x onerror="window.__pwned=9"><b>b</b><script>window.__pwned=8</script>';
  const T1 = 'Intro 漢字 తెలుగు then the Halvorsen <img src=x onerror="window.__pwned=5"> review is on Friday. End';
  const span = (text, part) => { const e = new TextEncoder(); const a = e.encode(text.slice(0, text.indexOf(part))).length; return [a, a + e.encode(part).length]; };
  const [hs, he] = span(T1, 'Halvorsen <img src=x onerror="window.__pwned=5"> review');
  window.__span = [hs, he];
  const fact = { id: 'f1', type: 'deadline', predicate: 'due', subject: { id: 'e1', type: 'person', name: 'Ravi ' + X }, value_date: '2026-10-30', certain: false,
    object: 'Report due Friday ' + X, sources: [{ source_id: 's1', quote: 'review', byte_offset: hs, byte_end: he }] };
  if (req.op === 'find_source') return req.id === 'gone' ? { ok: true, not_found: true, source: null } : { ok: true, not_found: false, source: { id: req.id, text: T1, language: 'te',
      timestamp: '2026-10-27T09:30:00Z', device: 'laptop ' + X, kind: 'screen_observation', provenance: 'lens-observer uia ' + X, source_application: 'chrome.exe',
      source_locator: 'window:Paper ' + X, consent_context: { mode: 'observer_explicit_consent' } } };
  if (req.op === 'facts') return { ok: true, facts: [fact] };
  const ents = [{ id: 'e1', type: 'person', name: 'Ravi ' + X, mention_count: 3, source_count: 2, first_seen: '2026-10-20T09:00:00Z', last_seen: '2026-10-27T09:00:00Z' },
    { id: 'e2', type: 'organization', name: 'Acme', mention_count: 1, source_count: 1, first_seen: '2026-10-21T09:00:00Z', last_seen: '2026-10-21T09:00:00Z' }];
  if (req.op === 'entities') return { ok: true, entities: req.type === 'place' ? [] : ents, not_found: false };
  if (req.op === 'entity_context') return { ok: true, not_found: false, entity: ents.find((e) => e.id === req.id) || ents[0],
      aliases: [{ alias: 'రవి' }, { alias: X }], facts: [fact], related: [{ id: 'e2', type: 'organization', name: 'Acme ' + X, shared_sources: 2 }],
      projects: [{ id: 'p1', name: 'Apollo ' + X, role: 'member' }],
      mentions: [{ source_id: 's1', byte_offset: hs, byte_end: he, excerpt: { text: '…Ravi ' + X }, source_application: 'chrome.exe', timestamp: '2026-10-27T09:30:00Z' }], episodes: [] };
  if (req.op === 'projects') return { ok: true, projects: [{ id: 'p1', name: 'Apollo ' + X, source_count: 4, fact_count: 1, episode_count: 2,
      first_seen: '2026-10-20T09:00:00Z', last_seen: '2026-10-27T09:00:00Z' }] };
  if (req.op === 'project_context') return { ok: true, not_found: false, project: { id: 'p1', name: 'Apollo ' + X, source_count: 4, fact_count: 1, episode_count: 2,
      first_seen: '2026-10-20T09:00:00Z', last_seen: '2026-10-27T09:00:00Z' }, entities: [{ id: 'e1', type: 'person', name: 'Ravi ' + X, shared_sources: 2 }],
      facts: [fact], episodes: [{ application: 'code.exe', title: 'Apollo ' + X, started_at: '2026-10-27T08:00:00Z', observation_count: 2 }],
      sources: [{ source_id: 's1', excerpt: { text: 'Apollo source ' + X }, source_application: 'chrome.exe', timestamp: '2026-10-27T09:30:00Z' }] };
  if (req.op === 'timeline') return { ok: true, sources: [{ id: 's1', text: 'Timeline ' + X, timestamp: '2026-10-27T09:30:00Z', source_application: 'chrome.exe',
      kind: 'screen_observation', language: 'zh' }] };
  if (req.op === 'mesh_status') return { ok: true, port: 47821, fingerprint: 'cd'.repeat(32), connections: 1 };
  if (req.op === 'mesh_devices') return { ok: true, devices: __state.revoked ? [] : [{ fingerprint: 'ab'.repeat(32), name: 'Pixel ' + X, paired_utc: '2026-10-26T10:00:00Z' }] };
  if (req.op === 'mesh_unpair') { __state.revoked = true; return { ok: true, removed: true }; }
  if (req.op === 'mesh_pair_begin') return { ok: true, qr: { v: 1, hosts: ['192.168.1.20', '10.0.0.7'], port: 47821, fp: 'ef'.repeat(32), token: '12'.repeat(16) }, expires_in_seconds: 300 };
  if (req.op === 'import_preview') return req.format === 'whatsapp' && !req.date_order ? { ok: false, error: 'date_order_required' } :
      { ok: true, records: 3, skipped: 1, sample: [{ timestamp: '2026-10-01T10:00:00Z', text: 'Msg ' + X, source_application: 'WhatsApp' }], first: '2026-10-01T10:00:00Z', last: '2026-10-02T10:00:00Z' };
  if (req.op === 'import_start') { __state.job = { id: 'imp-1', file: 'chat ' + X + '.txt', format: req.format, status: 'running', total: 3, processed: 0, imported: 0,
      deduplicated: 0, failed: 0, source_count: 0, started_utc: '2026-10-27T10:00:00Z' }; return { ok: true, import: __state.job }; }
  if (req.op === 'import_status') {
    const j = __state.job;
    if (req.id) { if (j.status === 'running') { j.processed++; j.imported = j.processed; j.source_count = j.processed; if (j.processed >= j.total) j.status = 'done'; } return { ok: true, import: j }; }
    return { ok: true, imports: j ? [j] : [], running: !!(j && j.status === 'running') };
  }
  if (req.op === 'import_cancel') { __state.job.status = 'cancelled'; return { ok: true }; }
  if (req.op === 'import_delete') { __state.job.status = 'deleted'; __state.job.source_count = 0; return { ok: true, deleted: 3 }; }
  if (req.op === 'diagnostics') return { ok: true, uptime_seconds: 4000, processes: [{ name: 'lens-agent.exe', pid: 1, working_set: 7e6, private: 2e6 },
      { name: 'lens-engine ' + X, pid: 2, working_set: 23e6, private: 3e6 }], memory: { working_set: 30e6, private: 5e6, ceiling: 8e8 },
      capture: { screen: { at: '2026-10-27T09:30:00Z', path: 'ocr', ocr_ms: 120, store_ms: 4, recognizers: ['te'], language: 'te', ok: true }, voice: null },
      observer_running: true, voice_running: false, paused: false, observed: 5, stored: 4, failed: 1, voiced: 0, semantic: 'verified',
      storage: { data_dir: 'D:/LensTestData', files: [{ name: 'memory.db', bytes: 123456 }, { name: X, bytes: 10 }], total_bytes: 123466 } };
  if (req.op === 'delete') return { ok: true, deleted: 1 };
  if (req.op === 'status') return { ok: true, observe_screen: __state.observe, observer_running: __state.observe && !__state.paused, paused: __state.paused, stored: 3,
      semantic: 'verified', microphone: __state.mic, voice_running: __state.mic && !__state.paused, phone_link: __state.phone, onboarded: __state.onboarded,
      autostart: __state.autostart, exclusions: __state.exclusions, data_dir: 'D:/LensTestData', mesh_running: __state.phone };
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
  if (req.op === 'recall' && req.query === 'telugu') return { ok: true, not_found: false, results: [{ source: { id: 's9', text: 'తెలుగు', language: 'te',
      timestamp: '2026-10-27T09:30:00Z', source_application: 'chrome.exe' }, evidence: { quote: 'తెలుగు' } }] };
  if (req.op === 'transcribe') return atob(req.audio_base64).slice(0, 4) === 'RIFF' ? { ok: true, transcript: { text: ' paper i read ', language: 'en' } } : { ok: false, error: 'audio_decode_failed' };
  if (req.op === 'speak') {  // 0.1 s of silence at 24 kHz, 16-bit mono
    const n = 2400, b = new Uint8Array(44 + 2 * n), v = new DataView(b.buffer), s = (o, t) => [...t].forEach((c, i) => b[o + i] = c.charCodeAt(0));
    s(0, 'RIFF'); v.setUint32(4, 36 + 2 * n, true); s(8, 'WAVEfmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, 24000, true); v.setUint32(28, 48000, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); s(36, 'data'); v.setUint32(40, 2 * n, true);
    return { ok: true, sample_rate: 24000, duration_s: 0.1, audio_base64: btoa(String.fromCharCode(...b)) };
  }
  if (req.op === 'recall') return { ok: true, not_found: false, results: [{
      source: { id: 's1', text: 'FULL <img src=x onerror="window.__pwned=1"> text', timestamp: '2026-10-27T09:30:00Z', source_application: 'chrome.exe', source_locator: 'window:Paper <b>bold</b> - Chrome' },
      evidence: { quote: 'Quote <script>window.__pwned=2</script> and <img src=x onerror="window.__pwned=3">', byte_offset: hs, byte_end: he },
      episode: { application: 'chrome.exe', observation_count: 4, duration_seconds: 300 } }] };
  if (req.op === 'episodes') return { ok: true, episodes: [
      { started_at: '2026-10-27T09:00:00Z', ended_at: '2026-10-27T09:10:00Z', application: 'winword.exe', title: 'Budget memo', observation_count: 3 },
      { started_at: '2026-10-27T08:00:00Z', ended_at: '2026-10-27T08:20:00Z', application: 'chrome.exe', title: 'Vendor contract', observation_count: 5 },
      { started_at: '2026-10-26T17:00:00Z', ended_at: '2026-10-26T17:05:00Z', application: 'code.exe', title: 'repo', observation_count: 2 }] };
  if (req.op === 'action_pending') return { ok: true, actions: __state.decided ? [] : [{ id: 'act-1', capability: 'laptop.remember', requested_by: 'paired device Pixel',
      requested_utc: '2026-10-27T09:00:00Z', params: { text: 'Remember <img src=x onerror="window.__pwned=4">' }, status: 'pending_confirmation' }] };
  if (req.op === 'action_decide') { __state.decided = true; return { ok: true, action: { id: req.id, status: req.approve ? 'executed' : 'denied' } }; }
  if (req.op === 'stats') return { ok: true, source_count: 10, embedded_sources: 8, compressed_sources: 4, schema_version: 8, entity_count: 2, fact_count: 1,
      project_count: 1, compressed_text_bytes: 2048, vector_chunks: 12, cipher_version: '4.6.1 community', embedding_model: 'intfloat/multilingual-e5-small@abc', models_loaded: false };
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
    card.querySelector('.source-btn').click(); await settle(); await settle();
    out.source_shown = !document.getElementById('evidence').hidden; out.mark = (document.getElementById('ev-mark') || {}).textContent;
    window.lensUi.closeEvidence();
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
    window.lensUi.show('storage'); await settle();
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
                          '--autoplay-policy=no-user-gesture-required',  # a scripted click is not a user gesture; a real one is
                          '--allow-file-access-from-files','--window-size=1280,900','--virtual-time-budget=20000','--dump-dom',(d/'harness.html').as_uri()],
                         capture_output=True,text=True,encoding='utf-8',timeout=120)
        m=re.search(r'<pre id="scenario-result">(.*?)</pre>',p.stdout,re.S);test.assertTrue(m,p.stdout[-2000:]+p.stderr[-1000:])
        import html as h;out=json.loads(h.unescape(m.group(1)))
        test.assertNotIn('error',out,out.get('error'))
        return out


LISTEN=r"""
(async () => {
  const out = {};
  const settle = () => new Promise((r) => setTimeout(r, 50));
  try {
    await settle();
    document.getElementById('ask-input').value = 'paper i read'; document.getElementById('ask-form').requestSubmit(); await settle();
    const btn = document.querySelector('.result .listen-btn');
    out.visible = !btn.hidden; out.label = btn.getAttribute('aria-label');
    btn.click(); await settle(); await settle();
    const calls = window.__calls.filter((c) => c.op === 'speak'); out.speak_calls = calls.length; out.text = calls.length ? calls[0].text : '';
    out.after = btn.textContent; out.injected = document.querySelectorAll('.results img, .results script').length; out.pwned = window.__pwned || 0;
    document.getElementById('ask-input').value = 'telugu'; document.getElementById('ask-form').requestSubmit(); await settle();
    out.non_english_hidden = document.querySelector('.result .listen-btn').hidden;
  } catch (e) { out.error = String(e && e.stack || e); }
  const pre = document.createElement('pre'); pre.id = 'scenario-result'; pre.textContent = JSON.stringify(out); document.body.append(pre);
})();
"""


VOICE_QUESTION=r"""
(async () => {
  const out = {};
  const settle = () => new Promise((r) => setTimeout(r, 50));
  try {
    await settle();
    const tone = new Float32Array(48000); for (let i = 0; i < tone.length; i++) tone[i] = 0.3 * Math.sin(i / 7);
    const wav = atob(window.lensUi.wav16k(tone, 48000)); out.wav_bytes = wav.length; out.riff = wav.slice(0, 4);
    out.rate = wav.charCodeAt(24) | (wav.charCodeAt(25) << 8) | (wav.charCodeAt(26) << 16);
    await window.lensUi.askByVoice(tone, 48000); await settle(); await settle();
    out.ops = window.__calls.map((c) => c.op).filter((o) => ['transcribe', 'recall', 'speak'].includes(o));
    out.query = document.getElementById('ask-input').value;
    out.recall_query = (window.__calls.find((c) => c.op === 'recall') || {}).query;
    out.mic_label = document.getElementById('ask-mic').getAttribute('aria-label');
  } catch (e) { out.error = String(e && e.stack || e); }
  const pre = document.createElement('pre'); pre.id = 'scenario-result'; pre.textContent = JSON.stringify(out); document.body.append(pre);
})();
"""


class AppUi(unittest.TestCase):
    def test_voice_question_is_transcribed_asked_and_answered_aloud(self):
        out=run_in_headless_edge(self,VOICE_QUESTION)
        self.assertEqual((out['riff'],out['rate'],out['wav_bytes']),('RIFF',16000,44+2*16000))  # 1 s at 48 kHz -> 16 kHz PCM
        self.assertEqual(out['ops'],['transcribe','recall','speak'])  # voice in, recall, voice out
        self.assertEqual(out['query'],'paper i read');self.assertEqual(out['recall_query'],'paper i read')
        self.assertEqual(out['mic_label'],'Ask by voice')

    def test_listen_speaks_the_evidence_locally(self):
        out=run_in_headless_edge(self,LISTEN)
        self.assertTrue(out['visible']);self.assertIn('Chrome',out['label']);self.assertEqual(out['speak_calls'],1)
        self.assertTrue(out['text'].startswith('Chrome, '));self.assertIn('Quote <script>',out['text'])  # the evidence quote, spoken as plain text
        self.assertIn(out['after'],['Stop','Listen']);self.assertEqual((out['injected'],out['pwned']),(0,0))  # Listen again once 0.1 s has played
        self.assertTrue(out['non_english_hidden'])

    def test_ui_behaviour_in_headless_edge(self):
        out=run_in_headless_edge(self,SCENARIO)
        self.assertEqual(out['results'],1);self.assertEqual(out['injected_elements'],0);self.assertEqual(out['pwned'],0)
        self.assertIn('<script>',out['quote']);self.assertIn('<b>bold</b>',out['window'])  # shown literally, not executed
        self.assertIn('Chrome session',out['episode']);self.assertTrue(out['source_shown']);self.assertIn('Halvorsen',out['mark'])
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


VIEWS=r"""
(async () => {
  const out = {};
  const settle = () => new Promise((r) => setTimeout(r, 60));
  const $ = (id) => document.getElementById(id);
  const calls = (op) => __calls.filter((c) => c.op === op);
  try {
    await settle();
    // Evidence viewer from a recall result: byte-offset highlight across multibyte scripts, provenance, links, keyboard close.
    $('ask-input').value = 'halvorsen'; $('ask-form').requestSubmit(); await settle();
    const opener = document.querySelector('.result .source-btn'); opener.focus(); opener.click(); await settle(); await settle();
    out.ev_open = !$('evidence').hidden; out.ev_mark = $('ev-mark').textContent; out.ev_lang = $('ev-text').lang; out.ev_dir = $('ev-text').dir;
    out.ev_meta = [...document.querySelectorAll('#ev-meta dt')].map((n) => n.textContent);
    out.ev_chips = document.querySelectorAll('#ev-links .chip-btn').length; out.ev_facts = document.querySelectorAll('#ev-links .fact').length;
    out.ev_inferred = !!document.querySelector('#ev-links .tag');
    out.ev_entity_query = calls('entities').slice(-1)[0].query;
    out.focus_in_drawer = $('evidence').contains(document.activeElement);
    $('evidence').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); await settle();
    out.ev_closed = $('evidence').hidden; out.focus_back = document.activeElement === opener;
    opener.click(); await settle(); await settle(); $('ev-delete').click(); await settle();
    out.delete_calls = calls('delete').map((c) => [c.id, c.consent]); out.result_removed = !document.querySelector('.result');
    // Timeline filters.
    await window.lensUi.show('timeline');
    $('tl-app').value = 'chrome'; $('tl-kind').value = 'screen_observation'; $('tl-from').value = '2026-10-20'; $('tl-to').value = '2026-10-27';
    $('timeline-filters').requestSubmit(); await settle();
    const tf = calls('timeline').slice(-1)[0]; out.tl_filters = tf.filters; out.tl_limit = tf.limit;
    out.tl_rows = document.querySelectorAll('#timeline .memory-row').length; out.tl_lang = document.querySelector('#timeline .what').lang;
    $('tl-clear').click(); await settle(); out.tl_after_clear = calls('episodes').length > 0 && document.querySelectorAll('#timeline .episode-row').length;
    // People.
    await window.lensUi.show('people'); await settle();
    out.people = document.querySelectorAll('#people-list .list-item').length;
    document.querySelector('#people-list .list-item').click(); await settle();
    out.person_title = document.querySelector('#people-detail .detail-title').textContent;
    out.person_aliases = [...document.querySelectorAll('#people-detail span.chip')].map((n) => n.textContent);
    out.person_sections = [...document.querySelectorAll('#people-detail .section-label')].map((n) => n.textContent);
    document.querySelector('#people-detail .row-btn').click(); await settle(); await settle();
    out.mention_mark = ($('ev-mark') || {}).textContent; window.lensUi.closeEvidence();
    $('people-type').value = 'place'; $('people-form').requestSubmit(); await settle();
    out.people_empty = document.querySelector('#people-list .empty strong').textContent; out.people_type_sent = calls('entities').slice(-1)[0].type;
    // Projects.
    await window.lensUi.show('projects'); await settle();
    document.querySelector('#projects-list .list-item').click(); await settle();
    out.project_sections = [...document.querySelectorAll('#projects-detail .section-label')].map((n) => n.textContent);
    // Devices: phone link off -> turn on -> pair (QR) -> revoke.
    await window.lensUi.show('devices'); await settle();
    out.devices_off = document.querySelector('#devices-list .empty strong').textContent; out.pair_disabled = $('pair-start').disabled;
    document.querySelector('#devices-link button').click(); await settle(); await settle();
    out.link_consent = calls('set_consent').slice(-1)[0];
    out.devices = document.querySelectorAll('#devices-list .device').length;
    $('pair-start').click(); await settle();
    out.qr_svg = !!document.querySelector('#pair-qr svg[role="img"][aria-label]'); out.pair_text = $('pair-text').textContent; out.expiry = $('pair-expiry').textContent;
    const q = window.lensQr.encode(out.pair_text); out.qr_rows = q.modules.map((r) => r.map((c) => (c ? 1 : 0)).join('')); out.qr_version = q.version;
    $('pair-cancel').click(); await settle(); out.pair_hidden = $('pairing-card').hidden;
    document.querySelector('#devices-list .device button').click(); await settle(); await settle();
    out.unpair = calls('mesh_unpair').map((c) => c.fingerprint); out.devices_after = document.querySelectorAll('#devices-list .device').length;
    // Import: pick -> preview -> import -> progress -> history -> delete.
    await window.lensUi.show('import'); await settle();
    $('imp-pick').click(); await settle(); await settle();
    out.imp_file = $('imp-file').textContent; out.preview_req = calls('import_preview').slice(-1)[0];
    out.preview_sample = document.querySelector('#imp-preview .sample .row-text').textContent;
    document.querySelector('#imp-preview .primary').click();
    for (let i = 0; i < 12; i++) await settle();
    await new Promise((r) => setTimeout(r, 2200));
    out.progress = $('imp-progress-text').textContent; out.bar = $('imp-bar').getAttribute('aria-valuenow');
    out.history = [...document.querySelectorAll('#imports-list .row-meta')].map((n) => n.textContent);
    document.querySelector('#imports-list .danger-text').click(); await settle(); await settle();
    out.import_delete = calls('import_delete').map((c) => c.id); out.history_after = document.querySelector('#imports-list .row-meta').textContent;
    $('imp-format').value = 'jsonl'; $('imp-format').dispatchEvent(new Event('change')); await settle();
    out.order_hidden = $('imp-order-label').hidden; out.jsonl_req = calls('import_preview').slice(-1)[0];
    // Storage and Diagnostics.
    await window.lensUi.show('storage'); await settle();
    out.storage = [...document.querySelectorAll('#status-grid .stat .value')].map((n) => n.textContent);
    out.storage_files = [...document.querySelectorAll('#storage-files .kv')].map((n) => n.textContent);
    await window.lensUi.show('diagnostics'); await settle();
    out.diag = [...document.querySelectorAll('#diag-grid .stat .value')].map((n) => n.textContent);
    out.diag_capture = document.querySelector('#diag-capture .kv .num').textContent; out.meter = $('diag-meter').getAttribute('aria-valuenow');
    out.diag_processes = document.querySelectorAll('#diag-processes .kv').length;
    // Untrusted text everywhere above was rendered as text.
    out.injected = document.querySelectorAll('img, b, iframe, object, embed, script:not([src])').length; out.pwned = window.__pwned || 0;
  } catch (e) { out.error = String(e && e.stack || e); }
  const pre = document.createElement('pre'); pre.id = 'scenario-result'; pre.textContent = JSON.stringify(out); document.body.append(pre);
})();
"""

# WCAG 2.2 AA checks on every view with data loaded: text contrast (1.4.3), accessible names (4.1.2), target size (2.5.8),
# no positive tabindex (2.4.3), focus indicator present (2.4.7), keyboard focusability of every control (2.1.1),
# page language (3.1.1), dialog semantics, and the drawer closes on Escape with focus restored.
AUDIT=r"""
(async () => {
  const out = { contrast: [], names: [], targets: [], tabindex: [], checked: { text: 0, controls: 0 } };
  const settle = () => new Promise((r) => setTimeout(r, 60));
  const parse = (c) => { const m = /rgba?\(([^)]+)\)/.exec(c || ''); if (!m) return null; const p = m[1].split(',').map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
  const lum = ({ r, g, b }) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const over = (top, base) => ({ r: top.r * top.a + base.r * (1 - top.a), g: top.g * top.a + base.g * (1 - top.a), b: top.b * top.a + base.b * (1 - top.a) });
  function background(node) {
    const layers = [];
    for (let n = node; n; n = n.parentElement) { const c = parse(getComputedStyle(n).backgroundColor); if (c && c.a > 0) { layers.push(c); if (c.a >= 1) break; } }
    let base = { r: 17, g: 18, b: 20 };
    for (let i = layers.length - 1; i >= 0; i--) base = over(layers[i], base);
    return base;
  }
  const visible = (n) => { const r = n.getBoundingClientRect(); const s = getComputedStyle(n); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const label = (n) => (n.id || n.className || n.tagName).toString().slice(0, 40);
  function nameOf(n) {
    if (n.getAttribute('aria-label')) return n.getAttribute('aria-label').trim();
    const by = n.getAttribute('aria-labelledby'); if (by) return by.split(' ').map((id) => (document.getElementById(id) || {}).textContent || '').join(' ').trim();
    if (n.labels && n.labels.length) return [...n.labels].map((l) => l.textContent).join(' ').trim();
    return (n.textContent || '').trim() || (n.getAttribute('title') || '').trim();
  }
  function audit(root, where) {
    for (const n of root.querySelectorAll('*')) {
      if (!visible(n) || n.closest('[hidden]') || n.closest('svg')) continue;
      const own = [...n.childNodes].some((c) => c.nodeType === 3 && c.textContent.trim());
      if (own && !n.closest(':disabled')) {
        const s = getComputedStyle(n), fg = parse(s.color), bg = background(n);
        const fgc = fg.a < 1 ? over(fg, bg) : fg;
        const L1 = lum(fgc), L2 = lum(bg), ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
        const size = parseFloat(s.fontSize), large = size >= 24 || (size >= 18.66 && Number(s.fontWeight) >= 700);
        out.checked.text++;
        if (ratio < (large ? 3 : 4.5)) out.contrast.push(`${where}:${label(n)} ${ratio.toFixed(2)} "${n.textContent.trim().slice(0, 30)}"`);
      }
    }
    for (const n of root.querySelectorAll('button, a[href], input, select, textarea, [tabindex], [role="img"]')) {
      if (n.type === 'hidden' || n.closest('[hidden]') || !visible(n)) continue;
      out.checked.controls++;
      if (!nameOf(n)) out.names.push(`${where}:${label(n)}`);
      if (n.tabIndex > 0) out.tabindex.push(`${where}:${label(n)}`);
      if (n.getAttribute('role') === 'img') continue;
      const r = n.getBoundingClientRect();
      if ((r.width < 24 || r.height < 24) && !n.disabled && n.tabIndex !== -1) out.targets.push(`${where}:${label(n)} ${Math.round(r.width)}x${Math.round(r.height)}`);
    }
  }
  try {
    await settle();
    $ = (id) => document.getElementById(id);
    out.lang = document.documentElement.lang;
    out.focus_rule = [...document.styleSheets].some((sh) => [...sh.cssRules].some((r) => r.selectorText && r.selectorText.includes(':focus-visible') && /outline/.test(r.cssText)));
    out.nav_focusable = [...document.querySelectorAll('.nav')].every((b) => { b.focus(); return document.activeElement === b; });
    document.getElementById('ask-input').value = 'halvorsen'; document.getElementById('ask-form').requestSubmit(); await settle();
    audit(document.querySelector('.rail'), 'rail'); audit(document.getElementById('view-ask'), 'ask');
    for (const v of ['timeline', 'people', 'projects', 'devices', 'import', 'privacy', 'storage', 'diagnostics']) {
      await window.lensUi.show(v); await settle();
      const first = document.querySelector(`#view-${v} .list-item`); if (first) { first.click(); await settle(); }
      if (v === 'import') { document.getElementById('imp-pick').click(); await settle(); await settle(); }
      audit(document.getElementById(`view-${v}`), v);
    }
    await window.lensUi.show('ask');
    document.querySelector('.result .source-btn').click(); await settle(); await settle();
    const d = document.getElementById('evidence');
    out.dialog = d.getAttribute('role') === 'dialog' && d.getAttribute('aria-modal') === 'true' && !!document.getElementById(d.getAttribute('aria-labelledby')).textContent;
    audit(d, 'evidence');
    window.lensUi.closeEvidence();
    window.lensUi.openOnboarding({ data_dir: 'D:/LensTestData' });
    const ob = document.getElementById('onboarding');
    for (let step = 1; step <= 3; step++) { audit(ob, `onboarding${step}`); const next = ob.querySelector('.ob-step.active [data-next]'); if (next) { next.click(); await settle(); } }
    out.ob_step_current = ob.querySelector('.ob-steps li[aria-current="step"]').dataset.step;
  } catch (e) { out.error = String(e && e.stack || e); }
  const pre = document.createElement('pre'); pre.id = 'scenario-result'; pre.textContent = JSON.stringify(out); document.body.append(pre);
})();
"""


def decode_qr(rows):
    """Decodes a module matrix with OpenCV's QR detector (independent of the encoder under test)."""
    import cv2,numpy as np
    m=np.array([[int(c) for c in r] for r in rows],dtype=np.uint8)
    img=cv2.resize(np.pad((1-m)*255,4,constant_values=255).astype(np.uint8),None,fx=8,fy=8,interpolation=cv2.INTER_NEAREST)
    return cv2.QRCodeDetector().detectAndDecode(img)[0]


class AppViews(unittest.TestCase):
    def test_every_view_renders_untrusted_text_safely_and_works(self):
        out=run_in_headless_edge(self,VIEWS)
        self.assertEqual(out['injected'],0);self.assertEqual(out['pwned'],0)  # XSS payloads in every view stayed text
        self.assertTrue(out['ev_open']);self.assertEqual(out['ev_mark'],'Halvorsen <img src=x onerror="window.__pwned=5"> review')  # UTF-8 offsets after 漢字/తెలుగు
        self.assertEqual((out['ev_lang'],out['ev_dir']),('te','auto'))
        for k in ['When','App','Window or file','Device','Kind','How it was captured','Permission']:self.assertIn(k,out['ev_meta'])
        self.assertEqual((out['ev_chips'],out['ev_facts']),(2,1));self.assertTrue(out['ev_inferred'])
        self.assertEqual(out['ev_entity_query'],'Halvorsen <img src=x onerror="window.__pwned=5"> review')
        self.assertTrue(out['focus_in_drawer']);self.assertTrue(out['ev_closed']);self.assertTrue(out['focus_back'])
        self.assertEqual(out['delete_calls'],[['s1',True]]);self.assertTrue(out['result_removed'])
        self.assertEqual(out['tl_filters'],{'application_contains':['chrome'],'kind':'screen_observation',
                                            'from':out['tl_filters']['from'],'to':out['tl_filters']['to']})
        self.assertEqual(out['tl_limit'],100);self.assertEqual(out['tl_rows'],1);self.assertEqual(out['tl_lang'],'zh');self.assertEqual(out['tl_after_clear'],3)
        self.assertEqual(out['people'],2);self.assertIn('<img',out['person_title']);self.assertEqual(out['person_aliases'][0],'రవి')
        self.assertEqual(out['person_sections'],['Also written as','Facts','Projects','Often together with','Where Lens saw it'])
        self.assertEqual(out['mention_mark'],out['ev_mark']);self.assertEqual((out['people_empty'],out['people_type_sent']),('No one yet','place'))
        self.assertEqual(out['project_sections'],['People','Facts','Sessions','Memories'])
        self.assertEqual(out['devices_off'],'Phone link is off');self.assertTrue(out['pair_disabled'])
        self.assertEqual(out['link_consent'],{'op':'set_consent','phone_link':True});self.assertEqual(out['devices'],1)
        self.assertTrue(out['qr_svg']);self.assertIn('Expires in 5:00',out['expiry']);self.assertTrue(out['pair_hidden'])
        qr=json.loads(out['pair_text']);self.assertEqual(qr,{'v':1,'hosts':['192.168.1.20','10.0.0.7'],'port':47821,'fp':'ef'*32,'token':'12'*16})
        self.assertEqual(decode_qr(out['qr_rows']),out['pair_text'])  # the in-app QR decodes to exactly the pairing code
        self.assertEqual(out['unpair'],['ab'*32]);self.assertEqual(out['devices_after'],0)
        self.assertIn('<img',out['imp_file']);self.assertEqual(out['preview_req'],{'op':'import_preview','path':'C:/exports/chat.txt','format':'whatsapp','date_order':'dmy'})
        self.assertIn('<img',out['preview_sample'])
        self.assertTrue(out['progress'].startswith('3 of 3 · 3 added'),out['progress']);self.assertEqual(out['bar'],'100')
        self.assertTrue(out['history'][0].startswith('Finished'),out['history']);self.assertEqual(out['import_delete'],['imp-1']);self.assertTrue(out['history_after'].startswith('Deleted'))
        self.assertTrue(out['order_hidden']);self.assertNotIn('date_order',out['jsonl_req'])
        self.assertEqual(out['storage'][:6],['10','8','4','2','1','1']);self.assertIn('Total123 KB',''.join(out['storage_files']))
        self.assertEqual(out['diag'][0],'30.0 MB');self.assertIn('on-device OCR',out['diag_capture']);self.assertIn('recognisers te',out['diag_capture'])
        self.assertEqual(out['meter'],'30');self.assertEqual(out['diag_processes'],2)

    def test_wcag_aa_checks_on_every_view(self):
        out=run_in_headless_edge(self,AUDIT)
        self.assertEqual(out['lang'],'en');self.assertTrue(out['focus_rule']);self.assertTrue(out['nav_focusable']);self.assertTrue(out['dialog'])
        self.assertGreater(out['checked']['text'],150);self.assertGreater(out['checked']['controls'],60)
        self.assertEqual(out['contrast'],[]);self.assertEqual(out['names'],[]);self.assertEqual(out['targets'],[]);self.assertEqual(out['tabindex'],[])
        self.assertEqual(out['ob_step_current'],'3')

    def test_qr_encoder_against_an_independent_decoder(self):
        payloads=['x',json.dumps({'v':1,'hosts':['192.168.1.20'],'port':47821,'fp':'a'*64,'token':'b'*32}),'汉字テルグ'*20,'y'*400]
        script='window.__out = %s.map((p) => window.lensQr.encode(p).modules.map((r) => r.map((c) => (c ? 1 : 0)).join("")));'%json.dumps(payloads)
        out=run_in_headless_edge(self,"(async () => { const out = {}; try { %s out.rows = window.__out; } catch (e) { out.error = String(e); }"
                                 " const pre = document.createElement('pre'); pre.id = 'scenario-result'; pre.textContent = JSON.stringify(out); document.body.append(pre); })();"%script)
        for payload,rows in zip(payloads,out['rows']):self.assertEqual(decode_qr(rows),payload)


# Spec §1a languages with short synthetic phrases; the font file each one resolves to on Windows 11.
LANGS={'en':('Meeting notes','segoeui.ttf'),'zh':('会议记录','msyh.ttc'),'es':('Notas de la reunión','segoeui.ttf'),'ar':('ملاحظات الاجتماع','segoeui.ttf'),
       'fr':('Notes de réunion','segoeui.ttf'),'pt':('Notas da reunião','segoeui.ttf'),'ru':('Заметки о встрече','segoeui.ttf'),'id':('Catatan rapat','segoeui.ttf'),
       'de':('Besprechung über Größe','segoeui.ttf'),'ja':('会議のメモ','YuGothR.ttc'),'hi':('बैठक के नोट्स','Nirmala.ttc'),'bn':('সভার নোট','Nirmala.ttc'),
       'te':('సమావేశ గమనికలు','Nirmala.ttc'),'mr':('बैठकीच्या नोंदी','Nirmala.ttc'),'ta':('கூட்டக் குறிப்புகள்','Nirmala.ttc'),'ur':('میٹنگ کے نوٹس','segoeui.ttf'),
       'gu':('મીટિંગ નોંધો','Nirmala.ttc')}
FAMILY={'segoeui.ttf':'Segoe UI','msyh.ttc':'Microsoft YaHei UI','YuGothR.ttc':'Yu Gothic UI','Nirmala.ttc':'Nirmala UI'}


def cmap_codepoints(path):
    """Unicode code points mapped by a TrueType/OpenType font (first face of a collection): cmap formats 4 and 12."""
    import struct
    data=Path(path).read_bytes();base=0
    if data[:4]==b'ttcf':base=struct.unpack('>I',data[12:16])[0]
    n=struct.unpack('>H',data[base+4:base+6])[0];cmap=None
    for i in range(n):
        tag,_,off,_=struct.unpack('>4sIII',data[base+12+16*i:base+28+16*i])
        if tag==b'cmap':cmap=off
    count=struct.unpack('>H',data[cmap+2:cmap+4])[0];points=set()
    for i in range(count):
        pid,eid,off=struct.unpack('>HHI',data[cmap+4+8*i:cmap+12+8*i])
        if pid!=3 or eid not in (1,10):continue
        t=cmap+off;fmt=struct.unpack('>H',data[t:t+2])[0]
        if fmt==4:
            seg=struct.unpack('>H',data[t+6:t+8])[0]//2
            ends=struct.unpack(f'>{seg}H',data[t+14:t+14+2*seg]);starts=struct.unpack(f'>{seg}H',data[t+16+2*seg:t+16+4*seg])
            for a,b in zip(starts,ends):points.update(range(a,b+1))
        elif fmt==12:
            groups=struct.unpack('>I',data[t+12:t+16])[0]
            for g in range(groups):
                a,b,_=struct.unpack('>III',data[t+16+12*g:t+28+12*g]);points.update(range(a,b+1))
    return points


LANG_SCENARIO=r"""
(async () => {
  const out = {};
  try {
    const langs = %s;
    window.lensUi.renderResults({ ok: true, results: Object.entries(langs).map(([lang, text], i) => ({
      source: { id: 's' + i, text, language: lang, timestamp: '2026-10-27T09:30:00Z', source_application: 'notes.exe', source_locator: 'window:' + text },
      evidence: { quote: text } })) });
    out.render = [...document.querySelectorAll('.result .quote')].map((q) => {
      const s = getComputedStyle(q), r = document.createRange(); r.selectNodeContents(q);
      return { lang: q.lang, family: s.fontFamily, direction: s.direction, width: r.getBoundingClientRect().width, text: q.textContent };
    });
  } catch (e) { out.error = String(e && e.stack || e); }
  const pre = document.createElement('pre'); pre.id = 'scenario-result'; pre.textContent = JSON.stringify(out); document.body.append(pre);
})();
"""


class AppLanguages(unittest.TestCase):
    def test_17_languages_render_with_a_font_that_has_their_glyphs(self):
        out=run_in_headless_edge(self,LANG_SCENARIO%json.dumps({k:v[0] for k,v in LANGS.items()},ensure_ascii=False))
        self.assertEqual(len(out['render']),17)
        fonts={}
        for r in out['render']:
            lang=r['lang'];text,font=LANGS[lang];self.assertEqual(r['text'],text)
            self.assertGreater(r['width'],10,lang)
            self.assertEqual(r['direction'],'rtl' if lang in ('ar','ur') else 'ltr',lang)  # dir=auto follows the script
            # The resolved stack lists the family whose font file is checked below, ahead of generic fallbacks.
            self.assertIn(FAMILY[font],r['family'],lang)
            path=Path(r'C:\Windows\Fonts')/font;self.assertTrue(path.exists(),font)
            if font not in fonts:fonts[font]=cmap_codepoints(path)
            missing=[c for c in text if not c.isspace() and ord(c) not in fonts[font]]
            self.assertEqual(missing,[],f'{lang}: {font} lacks {missing}')


class AppHost(unittest.TestCase):
    def test_self_test_reaches_the_agent_without_showing_a_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            name=f'lens-app-test-{uuid.uuid4().hex[:8]}'
            agent=subprocess.Popen([str(REL/'lens-agent.exe'),'--data-dir',tmp,'--root',str(ROOT),'--pipe-name',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            pipe=Pipe(name)
            try:
                r=subprocess.run([str(REL/'lens-app.exe'),'--self-test','--pipe-name',name],capture_output=True,text=True,timeout=120)
                self.assertEqual(r.returncode,0,r.stdout+r.stderr);out=json.loads(r.stdout.strip().splitlines()[-1])
                self.assertTrue(out['ok']);self.assertEqual(out['stats']['schema_version'],9);self.assertFalse(out['status']['observe_screen'])
                self.assertEqual(out['ui'],'Lens');self.assertTrue(out['onboarding'])  # fresh data folder: first-run setup is shown
                # Every view loads against the real agent without a script error or an error state.
                self.assertEqual(out['errors'],[]);self.assertEqual(sorted(out['views']),sorted(['timeline','people','projects','devices','import','privacy','storage','diagnostics','ask']))
                for v,r in out['views'].items():self.assertNotIn('exception',r,v);self.assertEqual(r['errors'],0,v)
                self.assertLess(out['host_ready_ms'],15000);self.assertIsInstance(out['ready_ms'],int)
                print(f"\n  lens-app time to interactive: {out['host_ready_ms']} ms from process start (UI ready at {out['ready_ms']} ms); views {out['views']}")
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

    def test_diagnostics_report_real_measurements_without_content(self):
        d=self.pipe.ask({'op':'diagnostics'})
        names=[p['name'] for p in d['processes']];self.assertIn('lens-agent.exe',names);self.assertIn('lens-engine.exe',names)
        self.assertEqual(d['memory']['working_set'],sum(p['working_set'] for p in d['processes']));self.assertLess(d['memory']['working_set'],500_000_000)
        self.assertEqual(d['memory']['ceiling'],500_000_000);self.assertIn('memory.db',[f['name'] for f in d['storage']['files']])
        self.assertEqual(d['capture'],{'screen':None,'voice':None})
        self.pipe.ask({'op':'set_consent','observe_screen':True})
        end=time.time()+20
        while time.time()<end and not self.pipe.ask({'op':'diagnostics'})['capture']['screen']:time.sleep(0.3)
        d=self.pipe.ask({'op':'diagnostics'});c=d['capture']['screen']
        self.assertEqual(c['path'],'uia');self.assertTrue(c['ok']);self.assertIn('store_ms',c);self.assertTrue(c['at'].endswith('Z'))
        self.assertIn('lens-observer.exe',[p['name'] for p in d['processes']])
        self.assertNotIn('Okonkwo',json.dumps(d))  # telemetry carries timings and paths, never captured text

    def test_import_preview_start_and_delete_by_import(self):
        chat=self.data/'WhatsApp Chat.txt'
        chat.write_text('﻿[03/10/2026, 09:15:02] Asha: The Kestrel venue deposit is due Friday\n'
                        'second line of the same message\n'
                        '04/10/2026, 18:40 - Ravi: Booked the Kestrel caterer\n'
                        '04/10/2026, 18:41 - Ravi: <Media omitted>\n'
                        '05/10/2026, 07:00 - Asha: my password is hunter2\n'
                        '31/02/2026, 07:00 - Asha: impossible date\n',encoding='utf-8')
        self.assertEqual(self.pipe.ask({'op':'import_preview','path':str(chat),'format':'whatsapp'})['error'],'date_order_required')
        self.assertEqual(self.pipe.ask({'op':'import_preview','path':str(self.data/'missing.txt'),'format':'text'})['error'],'file_unreadable')
        p=self.pipe.ask({'op':'import_preview','path':str(chat),'format':'whatsapp','date_order':'dmy'})
        self.assertEqual(p['records'],3);self.assertEqual(p['skipped_by'],{'invalid_date':1,'media_or_empty':1})
        self.assertEqual(p['sample'][0]['text'],'Asha: The Kestrel venue deposit is due Friday\nsecond line of the same message')
        self.assertTrue(p['first'].startswith('2026-10-0'))
        job=self.pipe.ask({'op':'import_start','path':str(chat),'format':'whatsapp','date_order':'dmy'})['import']
        end=time.time()+30
        while time.time()<end and self.pipe.ask({'op':'import_status','id':job['id']})['import']['status']=='running':time.sleep(0.2)
        s=self.pipe.ask({'op':'import_status','id':job['id']})['import']
        self.assertEqual((s['status'],s['total'],s['imported'],s['failed']),('done',3,2,1));self.assertEqual(s['failed_by'],{'sensitive_content_excluded':1})
        self.assertEqual(s['source_count'],2);self.assertNotIn('source_ids',s)
        hit=self.pipe.ask({'op':'search','query':'Kestrel caterer'})['sources'][0]
        self.assertEqual((hit['kind'],hit['source_application']),('imported_message','WhatsApp'))
        sha=json.loads(hit['provenance'])['export_sha256'];self.assertEqual(json.loads(hit['provenance'])['format'],'WhatsApp')
        self.assertTrue(hit['source_locator'].startswith(f'sha256:{sha}#record='));self.assertNotIn('WhatsApp Chat',hit['source_locator'])  # no file name
        listed=self.pipe.ask({'op':'imports'})  # the engine's import listing (memory-lifecycle ops) sees the same import
        if listed.get('ok'):self.assertIn({'export_sha256':sha,'format':'WhatsApp','sources':2},[{k:i[k] for k in ('export_sha256','format','sources')} for i in listed['imports']])
        again=self.pipe.ask({'op':'import_start','path':str(chat),'format':'whatsapp','date_order':'dmy'})['import']  # same file again: deduplicated
        end=time.time()+30
        while time.time()<end and self.pipe.ask({'op':'import_status','id':again['id']})['import']['status']=='running':time.sleep(0.2)
        self.assertEqual(self.pipe.ask({'op':'import_status','id':again['id']})['import']['deduplicated'],2)
        self.assertEqual([i['id'] for i in self.pipe.ask({'op':'import_status'})['imports']],[again['id'],job['id']])
        self.assertEqual(self.pipe.ask({'op':'import_delete','id':job['id']})['deleted'],2)
        self.assertEqual(self.pipe.ask({'op':'search','query':'Kestrel'})['sources'],[])
        record=json.loads((self.data/'imports.json').read_text(encoding='utf-8'))
        self.assertEqual([i['status'] for i in record],['deleted','done']);self.assertNotIn('Kestrel',json.dumps(record))

    def test_import_cancel_and_formats(self):
        notes=self.data/'notes.txt';notes.write_text('\n\n'.join(f'Synthetic note {i} about the Brennan archive' for i in range(4000)),encoding='utf-8')
        lines=self.data/'notes.jsonl';lines.write_text('{"text":"Synthetic jsonl note","timestamp":"2026-10-01T10:00:00Z","language":"en"}\nnot json\n{"no_text":1}\n',encoding='utf-8')
        j=self.pipe.ask({'op':'import_preview','path':str(lines),'format':'jsonl'});self.assertEqual((j['records'],j['skipped']),(1,2))
        self.assertEqual(self.pipe.ask({'op':'import_preview','path':str(lines),'format':'pdf'})['error'],'unsupported_format')
        self.assertEqual(self.pipe.ask({'op':'import_preview','path':str(notes),'format':'text'})['records'],4000)
        job=self.pipe.ask({'op':'import_start','path':str(notes),'format':'text'})['import']
        self.assertEqual(self.pipe.ask({'op':'import_start','path':str(lines),'format':'jsonl'})['error'],'import_running')  # one at a time
        time.sleep(0.3);self.assertTrue(self.pipe.ask({'op':'import_cancel','id':job['id']})['ok'])
        end=time.time()+30
        while time.time()<end and self.pipe.ask({'op':'import_status','id':job['id']})['import']['status']=='running':time.sleep(0.1)
        s=self.pipe.ask({'op':'import_status','id':job['id']})['import'];self.assertEqual(s['status'],'cancelled');self.assertLess(s['processed'],4000)
        self.assertEqual(self.pipe.ask({'op':'import_delete','id':job['id']})['deleted'],s['imported'])


class AppMemory(unittest.TestCase):
    def test_app_idle_ram_and_time_to_interactive(self):
        """lens-app with WebView2, window never shown, held open after the UI is ready; its whole process tree is sampled."""
        import psutil
        with tempfile.TemporaryDirectory() as tmp:
            name=f'lens-app-ram-{uuid.uuid4().hex[:8]}'
            agent=subprocess.Popen([str(REL/'lens-agent.exe'),'--data-dir',tmp,'--root',str(ROOT),'--pipe-name',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            pipe=Pipe(name);pipe.ask({'op':'set_consent','onboarded':True})
            try:
                app=subprocess.Popen([str(REL/'lens-app.exe'),'--self-test','--self-test-hold','40000','--pipe-name',name],stdout=subprocess.PIPE,text=True)
                out=json.loads(app.stdout.readline());self.assertTrue(out['ok'],out)
                time.sleep(15)
                samples=[]
                for _ in range(10):
                    procs=[psutil.Process(app.pid)]+psutil.Process(app.pid).children(recursive=True)
                    ws=pv=0
                    for p in procs:
                        try:m=p.memory_full_info();ws+=m.rss;pv+=m.private
                        except psutil.Error:pass
                    samples.append((ws,pv,len(procs)));time.sleep(1)
                app.wait(timeout=60);app.stdout.close()
                agent_ws=pipe.ask({'op':'diagnostics'})['memory']['working_set']
                ws=max(s[0] for s in samples);pv=max(s[1] for s in samples)
                print(f"\n  lens-app idle (hidden window, {samples[-1][2]} processes incl. WebView2): {ws/1e6:.0f} MB working set, {pv/1e6:.0f} MB private;"
                      f" background agent tree {agent_ws/1e6:.0f} MB; time to interactive {out['host_ready_ms']} ms")
                self.assertLess(ws+agent_ws,500_000_000)  # app open plus the background system stays under the ceiling
            finally:
                pipe.ask({'op':'shutdown'});pipe.close();agent.wait(timeout=30)


if __name__=='__main__':unittest.main()
