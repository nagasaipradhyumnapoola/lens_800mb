'use strict';
// Lens app UI. Talks only to the local agent through the native host (window.chrome.webview); tests inject
// window.__lensMock instead. Memory text is untrusted (it comes from screens and imports): it is only ever inserted
// with textContent, never as HTML.
(() => {
  const pending = new Map();
  let nextId = 1;
  const host = window.chrome && window.chrome.webview;
  if (host) {
    host.addEventListener('message', (event) => {
      const msg = event.data;
      const resolve = msg && pending.get(msg.id);
      if (resolve) { pending.delete(msg.id); resolve(msg.response); }
    });
  }
  function call(request) {
    if (window.__lensMock) return Promise.resolve(window.__lensMock(request));
    if (!host) return Promise.resolve({ ok: false, error: 'host_unavailable' });
    const id = nextId++;
    return new Promise((resolve) => {
      pending.set(id, resolve);
      host.postMessage(JSON.stringify({ id, request }));
      setTimeout(() => { if (pending.delete(id)) resolve({ ok: false, error: 'timeout' }); }, 60000);
    });
  }

  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const windowTitle = (locator) => (locator || '').replace(/^window:/, '');
  const appName = (app) => { const n = (app || 'Imported').replace(/\.exe$/i, ''); return n.charAt(0).toUpperCase() + n.slice(1); };
  function when(iso) {
    const d = new Date(iso);
    if (isNaN(d)) return '';
    const now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    return sameDay ? `Today ${time}` : `${d.toLocaleDateString([], { day: 'numeric', month: 'short', year: d.getFullYear() === now.getFullYear() ? undefined : 'numeric' })} ${time}`;
  }
  function minutes(seconds) { return seconds < 60 ? `${seconds}s` : `${Math.round(seconds / 60)} min`; }

  // Navigation
  document.querySelectorAll('.nav').forEach((b) => b.addEventListener('click', () => show(b.dataset.view)));
  function show(view) {
    document.querySelectorAll('.nav').forEach((b) => b.classList.toggle('active', b.dataset.view === view));
    document.querySelectorAll('.view').forEach((v) => v.classList.toggle('active', v.id === `view-${view}`));
    if (view === 'timeline') loadTimeline();
    if (view === 'status') loadStatus();
    if (view === 'privacy') { refreshCapture(); loadRequests(); }
  }

  // Ask
  const results = $('results');
  $('ask-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const query = $('ask-input').value.trim();
    if (!query) return;
    const button = e.target.querySelector('button');
    button.disabled = true;
    results.replaceChildren(el('p', 'muted', 'Searching your memory…'));
    const r = await call({ op: 'recall', query, limit: 5 });
    button.disabled = false;
    renderResults(r);
  });
  function renderResults(r) {
    results.replaceChildren();
    if (!r || !r.ok) { results.append(el('p', 'error', `Lens could not search right now (${(r && r.error) || 'unknown error'}).`)); return; }
    if (r.not_found || !r.results || !r.results.length) {
      const box = el('div', 'empty');
      box.append(el('strong', null, 'No reliable evidence found'), el('span', null, 'Lens did not find a memory that answers this. It will not guess.'));
      results.append(box);
      return;
    }
    const tpl = $('result-template');
    for (const item of r.results) {
      const node = tpl.content.firstElementChild.cloneNode(true);
      const src = item.source || {};
      node.querySelector('.app').textContent = appName(src.source_application);
      node.querySelector('.window').textContent = windowTitle(src.source_locator);
      const t = node.querySelector('time'); t.textContent = when(src.timestamp); t.dateTime = src.timestamp || '';
      node.querySelector('.quote').textContent = (item.evidence && item.evidence.quote) || src.text || '';
      const ep = item.episode;
      node.querySelector('.episode').textContent = ep ? `${appName(ep.application)} session · ${ep.observation_count} views · ${minutes(ep.duration_seconds)}` : '';
      const pre = node.querySelector('.source');
      node.querySelector('.source-btn').addEventListener('click', (e) => {
        pre.textContent = src.text || ''; pre.hidden = !pre.hidden; e.target.textContent = pre.hidden ? 'Show full source' : 'Hide source';
      });
      node.querySelector('.delete-btn').addEventListener('click', async (e) => {
        if (!window.confirm('Delete this memory permanently from this PC?')) return;
        const d = await call({ op: 'delete', consent: true, id: src.id });
        if (d && d.ok) node.remove(); else e.target.textContent = 'Delete failed';
      });
      node.dataset.sourceId = src.id || '';
      results.append(node);
    }
  }

  // Timeline
  async function loadTimeline() {
    const box = $('timeline');
    box.replaceChildren(el('p', 'muted', 'Loading…'));
    const r = await call({ op: 'episodes', limit: 100 });
    box.replaceChildren();
    if (!r || !r.ok) { box.append(el('p', 'error', 'Timeline unavailable.')); return; }
    if (!r.episodes.length) { const e = el('div', 'empty'); e.append(el('strong', null, 'Nothing here yet'), el('span', null, 'Sessions appear after Lens has observed or imported activity.')); box.append(e); return; }
    let day = null, group = null;
    for (const ep of r.episodes) {
      const d = new Date(ep.started_at).toDateString();
      if (d !== day) { day = d; group = el('div', 'day'); group.append(el('h2', null, new Date(ep.started_at).toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' }))); box.append(group); }
      const row = el('div', 'episode-row');
      const start = new Date(ep.started_at), end = new Date(ep.ended_at);
      const fmt = (x) => x.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      row.append(el('span', 'when', `${fmt(start)}–${fmt(end)}`), el('span', 'app', appName(ep.application)), el('span', 'what', ep.title || ''),
        el('span', 'count', `${ep.observation_count} views`));
      group.append(row);
    }
  }
  $('timeline-refresh').addEventListener('click', loadTimeline);

  // Privacy and capture state. Each consent toggle maps to one agent consent; capture follows the agent's answer.
  const consentToggles = [...document.querySelectorAll('input[data-consent]')];
  const autostart = $('autostart-toggle'), pause = $('pause-button');
  async function refreshCapture() {
    const s = await call({ op: 'status' });
    const pill = $('capture-pill'), text = $('capture-text');
    pill.classList.remove('on', 'paused');
    if (!s || !s.ok) {
      text.textContent = 'Lens is not running';
      for (const t of [...consentToggles, autostart]) t.disabled = true;
      pause.disabled = true; return s;
    }
    for (const t of consentToggles) { t.disabled = false; t.checked = !!s[t.dataset.consent]; }
    autostart.disabled = false; autostart.checked = !!s.autostart;
    const capturing = !!(s.observer_running || s.voice_running);
    pause.disabled = !(capturing || s.paused); pause.textContent = s.paused ? 'Resume' : 'Pause';
    if (s.paused) { pill.classList.add('paused'); text.textContent = 'Paused'; }
    else if (capturing) { pill.classList.add('on'); text.textContent = 'Observing'; }
    else text.textContent = 'Observation off';
    if (!editorsDirty.privacy) privacyEditor.set(s.exclusions);
    return s;
  }
  for (const t of consentToggles) t.addEventListener('change', async () => {
    t.disabled = true;
    await call({ op: 'set_consent', [t.dataset.consent]: t.checked });
    await refreshCapture();
  });
  autostart.addEventListener('change', async () => {
    autostart.disabled = true;
    await call({ op: 'set_autostart', enabled: autostart.checked });
    await refreshCapture();
  });
  pause.addEventListener('click', async () => {
    pause.disabled = true;
    await call({ op: pause.textContent === 'Pause' ? 'pause' : 'resume' });
    await refreshCapture();
  });

  // Exclusions editor: apps (process names) and window-title words the observer must skip, on top of its built-in list.
  const editorsDirty = { privacy: false };
  function exclusionEditor(box, onChange) {
    const groups = [
      { key: 'excluded_processes', label: 'Apps', placeholder: 'App file name, e.g. slack.exe',
        clean: (v) => { v = v.trim().toLowerCase().replace(/^.*[\\/]/, ''); return v && !/\.[a-z0-9]+$/.test(v) ? `${v}.exe` : v; } },
      { key: 'private_title_markers', label: 'Windows whose title contains', placeholder: 'Words, e.g. bank statement',
        clean: (v) => v.trim().toLowerCase() },
    ];
    const values = {};
    box.replaceChildren();
    for (const g of groups) {
      values[g.key] = [];
      const wrap = el('div', 'excl'), chips = el('ul', 'chips'), form = el('form'), input = el('input'), add = el('button', 'ghost', 'Add');
      input.placeholder = g.placeholder; input.maxLength = 260; input.setAttribute('aria-label', g.label); add.type = 'submit';
      const render = () => {
        chips.replaceChildren();
        for (const v of values[g.key]) {
          const chip = el('li', 'chip'), x = el('button', null, '×');
          x.type = 'button'; x.setAttribute('aria-label', `Remove ${v}`);
          x.addEventListener('click', () => { values[g.key] = values[g.key].filter((o) => o !== v); render(); onChange(); });
          chip.append(el('span', null, v), x); chips.append(chip);
        }
      };
      g.render = render;
      form.addEventListener('submit', (e) => {
        e.preventDefault();
        const v = g.clean(input.value);
        if (v && !values[g.key].includes(v) && values[g.key].length < 200) { values[g.key].push(v); render(); onChange(); }
        input.value = '';
      });
      form.append(input, add); wrap.append(el('h3', null, g.label), chips, form); box.append(wrap);
    }
    return {
      value: () => ({ excluded_processes: [...values.excluded_processes], private_title_markers: [...values.private_title_markers] }),
      set: (lists) => { for (const g of groups) { values[g.key] = [...((lists && lists[g.key]) || [])]; g.render(); } },
    };
  }
  const privacyEditor = exclusionEditor($('privacy-exclusions'), () => { editorsDirty.privacy = true; $('exclusions-saved').textContent = ''; });
  $('exclusions-save').addEventListener('click', async () => {
    const r = await call({ op: 'set_exclusions', ...privacyEditor.value() });
    $('exclusions-saved').textContent = r && r.ok ? 'Saved' : 'Could not save';
    if (r && r.ok) { editorsDirty.privacy = false; privacyEditor.set(r); }
  });

  // First run: explain what Lens captures and where it keeps it, then ask for each consent separately (all off by
  // default). Nothing is sent to the agent until Finish (or "Keep everything off"), so nothing is captured before it.
  const onboarding = $('onboarding');
  const obEditor = exclusionEditor($('ob-exclusions'), () => {});
  let obStep = 1;
  function obShow(step) {
    obStep = step;
    onboarding.querySelectorAll('.ob-step').forEach((n) => n.classList.toggle('active', Number(n.dataset.step) === step));
    onboarding.querySelectorAll('.ob-steps li').forEach((n) => {
      const k = Number(n.dataset.step); n.classList.toggle('active', k === step); n.classList.toggle('done', k < step);
    });
  }
  function openOnboarding(s) {
    $('ob-data-dir').textContent = (s && s.data_dir) || '%LOCALAPPDATA%\\Lens';
    for (const id of ['ob-screen', 'ob-mic', 'ob-phone', 'ob-autostart']) $(id).checked = false;
    obEditor.set(s && s.exclusions);
    $('ob-error').hidden = true;
    obShow(1); onboarding.hidden = false;
  }
  onboarding.querySelectorAll('[data-next]').forEach((b) => b.addEventListener('click', () => obShow(obStep + 1)));
  onboarding.querySelectorAll('[data-back]').forEach((b) => b.addEventListener('click', () => obShow(obStep - 1)));
  async function finishOnboarding(choices) {
    const steps = [];
    if (choices.exclusions) steps.push({ op: 'set_exclusions', ...choices.exclusions });  // before capture can start
    steps.push({ op: 'set_consent', observe_screen: choices.screen, microphone: choices.mic, phone_link: choices.phone, onboarded: true });
    if (choices.autostart) steps.push({ op: 'set_autostart', enabled: true });
    for (const req of steps) {
      const r = await call(req);
      if (!r || !r.ok) { $('ob-error').textContent = `Lens could not save your choices (${(r && r.error) || 'unknown error'}).`; $('ob-error').hidden = false; return false; }
    }
    onboarding.hidden = true;
    await refreshCapture();
    return true;
  }
  $('ob-skip').addEventListener('click', () => finishOnboarding({ screen: false, mic: false, phone: false, autostart: false }));
  $('ob-finish').addEventListener('click', async (e) => {
    e.target.disabled = true;
    await finishOnboarding({ screen: $('ob-screen').checked, mic: $('ob-mic').checked, phone: $('ob-phone').checked,
      autostart: $('ob-autostart').checked, exclusions: obEditor.value() });
    e.target.disabled = false;
  });

  // Requests from paired devices (safe actions): approve or deny; parameters are shown as text only.
  const describe = (a) => {
    if (a.capability === 'laptop.open_url') return `Open ${a.params.url}`;
    if (a.capability === 'laptop.remember') return `Remember: ${a.params.text}`;
    return `${a.capability} ${JSON.stringify(a.params)}`;
  };
  async function loadRequests() {
    const box = $('requests');
    const r = await call({ op: 'action_pending' });
    const list = (r && r.ok && r.actions) || [];
    const nav = document.querySelector('.nav[data-view="privacy"]');
    nav.textContent = list.length ? `Privacy (${list.length})` : 'Privacy';
    box.replaceChildren();
    if (!list.length) { box.append(el('p', 'muted', 'No requests waiting.')); return list; }
    for (const a of list) {
      const row = el('div', 'request');
      const text = el('div', 'request-text');
      text.append(el('strong', null, describe(a)), el('span', 'muted', ` — asked by ${a.requested_by}, ${when(a.requested_utc)}`));
      const yes = el('button', 'primary', 'Approve'), no = el('button', 'ghost', 'Deny');
      const decide = async (approve) => { yes.disabled = no.disabled = true; await call({ op: 'action_decide', id: a.id, approve }); loadRequests(); };
      yes.addEventListener('click', () => decide(true)); no.addEventListener('click', () => decide(false));
      row.append(text, no, yes); box.append(row);
    }
    return list;
  }

  // Status
  async function loadStatus() {
    const grid = $('status-grid');
    const [s, st] = await Promise.all([call({ op: 'status' }), call({ op: 'stats' })]);
    grid.replaceChildren();
    const stat = (label, value, small) => { const c = el('div', 'stat'); c.append(el('div', 'label', label), el('div', small ? 'value small' : 'value', String(value))); grid.append(c); };
    if (!st || !st.ok) { grid.append(el('p', 'error', 'Status unavailable.')); return; }
    stat('Memories', st.source_count);
    stat('Searchable by meaning', st.embedded_sources);
    stat('Compressed', st.compressed_sources);
    stat('Observed this session', s && s.ok ? s.stored : '—');
    stat('Understanding models', s && s.semantic === 'verified' ? 'Verified' : 'Keyword only', true);
    stat('Storage format', `Encrypted · schema ${st.schema_version}`, true);
  }

  // Self-test hook for the native host (--self-test): exercises the bridge end to end without showing anything.
  window.lensSelfTest = async () => {
    await ready;
    const status = await call({ op: 'status' });
    const stats = await call({ op: 'stats' });
    const result = { ok: !!(status && status.ok && stats && stats.ok), status, stats, ui: document.title, onboarding: !onboarding.hidden };
    if (host) host.postMessage(JSON.stringify({ selftest: result }));
    return result;
  };
  window.lensUi = { call, renderResults, loadTimeline, refreshCapture, loadStatus, loadRequests, show, openOnboarding };

  const ready = (async () => {
    const s = await refreshCapture();
    if (s && s.ok && !s.onboarded) openOnboarding(s);
    await loadRequests();
  })();
  setInterval(() => { refreshCapture(); loadRequests(); }, 15000);
})();
