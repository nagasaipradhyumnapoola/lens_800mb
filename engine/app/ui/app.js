'use strict';
// Lens app UI. Talks only to the local agent through the native host (window.chrome.webview); tests inject
// window.__lensMock (agent) and window.__lensHostMock (host-only requests such as the file picker) instead.
// Memory text is untrusted (it comes from screens, chats and imports): it is only ever inserted with textContent or
// as SVG geometry, never as HTML. Every number shown comes from an agent or engine response; nothing is invented.
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
  function send(envelope, timeoutMs) {
    if (!host) return Promise.resolve({ ok: false, error: 'host_unavailable' });
    const id = nextId++;
    return new Promise((resolve) => {
      pending.set(id, resolve);
      host.postMessage(JSON.stringify({ id, ...envelope }));
      if (timeoutMs) setTimeout(() => { if (pending.delete(id)) resolve({ ok: false, error: 'timeout' }); }, timeoutMs);
    });
  }
  function call(request) {
    if (window.__lensMock) return Promise.resolve(window.__lensMock(request));
    return send({ request }, 60000);
  }
  function hostCall(name) {  // requests the native host answers itself (no timeout: a dialog waits for the user)
    if (window.__lensHostMock) return Promise.resolve(window.__lensHostMock(name));
    return send({ host: name }, 0);
  }

  // ---- helpers -------------------------------------------------------------------------------------------------
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const button = (cls, text, onClick, label) => {
    const b = el('button', cls, text); b.type = 'button'; if (label) b.setAttribute('aria-label', label);
    if (onClick) b.addEventListener('click', onClick); return b;
  };
  const memoryText = (tag, cls, text, language) => {  // untrusted text in any script: direction from content, language hint for fonts
    const n = el(tag, cls, text); n.dir = 'auto'; if (language && language !== 'und') n.lang = language; return n;
  };
  const windowTitle = (locator) => (locator || '').replace(/^window:/, '').replace(/^file:/, '');
  const appName = (app) => { const n = (app || 'Imported').replace(/\.exe$/i, ''); return n.charAt(0).toUpperCase() + n.slice(1); };
  const KINDS = { screen_observation: 'Screen', voice_note: 'Voice', imported_message: 'Imported message', imported_note: 'Imported note',
    note: 'Note', action_audit: 'Device action' };
  const kindLabel = (k) => KINDS[k] || (k || 'Memory');
  const TYPES = { person: 'Person', organization: 'Organisation', place: 'Place', project: 'Project', product: 'Product' };
  function when(iso) {
    const d = new Date(iso);
    if (isNaN(d)) return '';
    const now = new Date();
    const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (d.toDateString() === now.toDateString()) return `Today ${time}`;
    return `${d.toLocaleDateString([], { day: 'numeric', month: 'short', year: d.getFullYear() === now.getFullYear() ? undefined : 'numeric' })} ${time}`;
  }
  const fullDate = (iso) => { const d = new Date(iso); return isNaN(d) ? '' : d.toLocaleString([], { dateStyle: 'full', timeStyle: 'short' }); };
  const day = (iso) => { const d = new Date(iso); return isNaN(d) ? '' : d.toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' }); };
  const minutes = (seconds) => (seconds < 60 ? `${seconds}s` : `${Math.round(seconds / 60)} min`);
  const bytes = (n) => {
    if (n == null || isNaN(n)) return '—';
    const u = ['B', 'KB', 'MB', 'GB']; let i = 0; let v = Number(n);
    while (v >= 1000 && i < u.length - 1) { v /= 1000; i++; }
    return `${v >= 100 || i === 0 ? Math.round(v) : v.toFixed(1)} ${u[i]}`;
  };
  const errorText = (r) => (r && r.error) || 'unknown error';
  function loading(box, label) { box.setAttribute('aria-busy', 'true'); box.replaceChildren(el('p', 'loading', label || 'Loading…')); }
  function settled(box) { box.removeAttribute('aria-busy'); box.replaceChildren(); }
  function emptyState(box, title, detail) { const e = el('div', 'empty'); e.append(el('strong', null, title), el('span', null, detail)); box.append(e); }
  function failure(box, what, r) { settled(box); box.append(el('p', 'error', `${what} unavailable (${errorText(r)}).`)); }
  // UTF-8 byte offsets (what the engine reports) to string positions.
  const enc = new TextEncoder(), dec = new TextDecoder();
  function byteSpan(text, start, end) {
    const b = enc.encode(text);
    if (!(start >= 0 && end >= start && end <= b.length)) return null;
    return [dec.decode(b.slice(0, start)).length, dec.decode(b.slice(0, end)).length];
  }
  function utf8Prefix(text, maxBytes) {  // at most maxBytes of UTF-8, cut on a character boundary
    let out = '';
    for (const ch of text) { if (enc.encode(out + ch).length > maxBytes) break; out += ch; }
    return out;
  }

  // ---- navigation ----------------------------------------------------------------------------------------------
  const loaders = {};
  document.querySelectorAll('.nav').forEach((b) => b.addEventListener('click', () => show(b.dataset.view, true)));
  function show(view, focusHeading) {
    document.querySelectorAll('.nav').forEach((b) => {
      const on = b.dataset.view === view; b.classList.toggle('active', on);
      if (on) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
    });
    document.querySelectorAll('.view').forEach((v) => v.classList.toggle('active', v.id === `view-${view}`));
    const h = document.querySelector(`#view-${view} h1`);
    if (focusHeading && h) { h.tabIndex = -1; h.focus({ preventScroll: true }); }
    const load = loaders[view];
    return load ? load() : Promise.resolve();
  }

  // ---- Ask -----------------------------------------------------------------------------------------------------
  const results = $('results');
  $('ask-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const query = $('ask-input').value.trim();
    if (!query) return;
    const btn = e.target.querySelector('button');
    btn.disabled = true;
    loading(results, 'Searching your memory…');
    const r = await call({ op: 'recall', query, limit: 5 });
    btn.disabled = false;
    renderResults(r);
  });
  function renderResults(r) {
    settled(results);
    if (!r || !r.ok) { results.append(el('p', 'error', `Lens could not search right now (${errorText(r)}).`)); return; }
    if (r.not_found || !r.results || !r.results.length) {
      emptyState(results, 'No reliable evidence found', 'Lens did not find a memory that answers this. It will not guess.');
      return;
    }
    const tpl = $('result-template');
    for (const item of r.results) {
      const node = tpl.content.firstElementChild.cloneNode(true);
      const src = item.source || {}, ev = item.evidence || {};
      node.querySelector('.app').textContent = appName(src.source_application);
      node.querySelector('.window').textContent = windowTitle(src.source_locator);
      const t = node.querySelector('time'); t.textContent = when(src.timestamp); t.dateTime = src.timestamp || '';
      const q = node.querySelector('.quote'); q.textContent = ev.quote || src.text || '';
      if (src.language && src.language !== 'und') q.lang = src.language;
      const ep = item.episode;
      node.querySelector('.episode').textContent = ep ? `${appName(ep.application)} session · ${ep.observation_count} views · ${minutes(ep.duration_seconds)}` : '';
      if (!src.language || src.language === 'en' || src.language === 'und') {  // spoken replies are English-only for now
        const listen = node.querySelector('.listen-btn'); listen.hidden = false;
        listen.setAttribute('aria-label', `Listen to this memory from ${appName(src.source_application)}`);
        listen.addEventListener('click', () => speak(listen, `${appName(src.source_application)}, ${when(src.timestamp)}. ${utf8Prefix(ev.quote || src.text || '', 800)}`));
      }
      node.querySelector('.source-btn').addEventListener('click', () => openEvidence(src.id, { byte_offset: ev.byte_offset, byte_end: ev.byte_end, quote: ev.quote }));
      node.querySelector('.source-btn').setAttribute('aria-label', `Open evidence from ${appName(src.source_application)}, ${when(src.timestamp)}`);
      const del = node.querySelector('.delete-btn');
      del.setAttribute('aria-label', `Delete this memory from ${appName(src.source_application)}`);
      del.addEventListener('click', async (e) => {
        if (!window.confirm('Delete this memory permanently from this PC?')) return;
        const d = await call({ op: 'delete', consent: true, id: src.id });
        if (d && d.ok) node.remove(); else e.target.textContent = 'Delete failed';
      });
      node.dataset.sourceId = src.id || '';
      results.append(node);
    }
  }

  // Spoken replies: synthesised locally by the agent (lens-tts); one reply plays at a time, a second click stops it.
  let speaking = null;
  function stopSpeaking() {
    if (!speaking) return;
    speaking.audio.pause(); URL.revokeObjectURL(speaking.audio.src);
    speaking.button.textContent = 'Listen'; speaking.button.removeAttribute('aria-pressed'); speaking = null;
  }
  async function speak(btn, text) {
    const again = speaking && speaking.button === btn; stopSpeaking(); if (again) return;
    btn.disabled = true; btn.textContent = 'Preparing…';
    const r = await call({ op: 'speak', text });
    btn.disabled = false;
    if (!r || !r.ok || !r.audio_base64) { btn.textContent = 'Voice unavailable'; return; }
    const wav = Uint8Array.from(atob(r.audio_base64), (c) => c.charCodeAt(0));
    const audio = new Audio(URL.createObjectURL(new Blob([wav], { type: 'audio/wav' })));
    speaking = { audio, button: btn }; btn.textContent = 'Stop'; btn.setAttribute('aria-pressed', 'true');
    audio.addEventListener('ended', () => { if (speaking && speaking.audio === audio) stopSpeaking(); });
    audio.play().catch(() => { stopSpeaking(); btn.textContent = 'Voice unavailable'; });
  }

  // ---- Evidence viewer -----------------------------------------------------------------------------------------
  const drawer = $('evidence');
  let evOpener = null, evId = null;
  function closeEvidence() {
    drawer.hidden = true; evId = null;
    if (evOpener && document.contains(evOpener)) evOpener.focus();
  }
  $('ev-close').addEventListener('click', closeEvidence);
  drawer.addEventListener('click', (e) => { if (e.target === drawer) closeEvidence(); });
  drawer.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { e.preventDefault(); closeEvidence(); return; }
    if (e.key !== 'Tab') return;
    const f = [...drawer.querySelectorAll('button, [href], input, select, [tabindex]:not([tabindex="-1"])')].filter((n) => !n.disabled && n.offsetParent !== null);
    if (!f.length) return;
    if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
    else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
  });
  async function openEvidence(id, span) {
    if (!id) return;
    evOpener = document.activeElement; evId = id;
    drawer.hidden = false;
    const text = $('ev-text'), meta = $('ev-meta'), links = $('ev-links');
    $('ev-app').textContent = ''; $('ev-title').textContent = 'Loading…'; $('ev-status').textContent = '';
    meta.replaceChildren(); links.replaceChildren(); loading(text, 'Opening the source…');
    $('ev-delete').disabled = true;
    $('ev-close').focus();
    const r = await call({ op: 'find_source', id });
    if (evId !== id) return;
    settled(text);
    if (!r || !r.ok || r.not_found || !r.source) {
      $('ev-title').textContent = 'Source not found';
      text.append(el('p', 'muted', r && r.ok ? 'This memory no longer exists (it may have been deleted).' : `Could not open it (${errorText(r)}).`));
      return;
    }
    const s = r.source;
    $('ev-app').textContent = `${appName(s.source_application)} · ${kindLabel(s.kind)}`;
    $('ev-title').textContent = windowTitle(s.source_locator) || kindLabel(s.kind);
    const rows = [['When', fullDate(s.timestamp)], ['App', appName(s.source_application)], ['Window or file', windowTitle(s.source_locator)],
      ['Device', s.device], ['Kind', kindLabel(s.kind)], ['Language', s.language && s.language !== 'und' ? s.language : 'not detected'],
      ['How it was captured', s.provenance], ['Permission', s.consent_context && s.consent_context.mode]];
    for (const [k, v] of rows) if (v) { const dt = el('dt', null, k), dd = memoryText('dd', null, String(v)); meta.append(dt, dd); }
    if (s.language && s.language !== 'und') text.lang = s.language; else text.removeAttribute('lang');
    const body = s.text || '';
    let range = span && span.byte_end > span.byte_offset ? byteSpan(body, span.byte_offset, span.byte_end) : null;
    if (!range && span && span.quote) { const i = body.indexOf(span.quote); if (i >= 0) range = [i, i + span.quote.length]; }
    if (range) {
      const mark = el('mark', null, body.slice(range[0], range[1])); mark.id = 'ev-mark';
      text.append(document.createTextNode(body.slice(0, range[0])), mark, document.createTextNode(body.slice(range[1])));
      requestAnimationFrame(() => mark.scrollIntoView({ block: 'center' }));
    } else text.textContent = body;
    $('ev-delete').disabled = false;
    // Linked knowledge: facts recorded from this source, and the people/things named in the highlighted passage.
    const passage = (range ? body.slice(range[0], range[1]) : body).replace(/\s+/g, ' ').trim();
    const [facts, ents] = await Promise.all([call({ op: 'facts', source_id: id, limit: 20 }),
      passage ? call({ op: 'entities', query: utf8Prefix(passage, 256), limit: 20 }) : Promise.resolve(null)]);
    if (evId !== id) return;
    if (ents && ents.ok && ents.entities && ents.entities.length) {
      links.append(el('h3', 'section-label', 'Named in this passage'));
      const chips = el('div', 'chips');
      for (const e of ents.entities) chips.append(button('chip-btn', e.name, () => { closeEvidence(); show('people', true).then(() => openEntity(e.id)); }, `${e.name}, ${TYPES[e.type] || e.type}`));
      chips.querySelectorAll('button').forEach((b) => { b.dir = 'auto'; });
      links.append(chips);
    }
    if (facts && facts.ok && facts.facts && facts.facts.length) {
      links.append(el('h3', 'section-label', 'Facts Lens noted from this source'));
      const list = el('ul', 'facts');
      for (const f of facts.facts) list.append(factItem(f));
      links.append(list);
    }
  }
  $('ev-delete').addEventListener('click', async () => {
    const id = evId; if (!id || !window.confirm('Delete this memory permanently from this PC? Facts and links that came only from it are removed too.')) return;
    const d = await call({ op: 'delete', consent: true, id });
    if (d && d.ok) {
      document.querySelectorAll('[data-source-id]').forEach((n) => { if (n.dataset.sourceId === id) n.remove(); });
      $('ev-status').textContent = 'Deleted.'; closeEvidence();
    } else $('ev-status').textContent = `Delete failed (${errorText(d)}).`;
  });
  function factItem(f) {
    const li = el('li', 'fact');
    const quote = f.object || (f.sources && f.sources[0] && f.sources[0].quote) || '';
    if (quote) li.append(memoryText('q', 'fact-quote', quote));
    const bits = [f.type ? f.type.charAt(0).toUpperCase() + f.type.slice(1) : 'Fact'];
    if (f.subject && f.subject.name) bits.push(f.subject.name);
    if (f.value_date) bits.push(f.value_date); else if (f.value) bits.push(f.value);
    if (f.object_entity && f.object_entity.name) bits.push(f.object_entity.name);
    const line = memoryText('span', 'fact-meta', bits.join(' · '));
    li.append(line);
    if (f.certain === false) li.append(el('span', 'tag', 'subject inferred'));
    const src = f.sources && f.sources[0];
    if (src && src.source_id) li.append(button('link', 'Source', () => openEvidence(src.source_id, src), `Open the source of this ${f.type || 'fact'}`));
    return li;
  }

  // ---- Timeline ------------------------------------------------------------------------------------------------
  function timelineFilters() {
    const f = {};
    const app = $('tl-app').value.trim(); if (app) f.application_contains = [app];
    if ($('tl-kind').value) f.kind = $('tl-kind').value;
    if ($('tl-from').value) f.from = new Date(`${$('tl-from').value}T00:00:00`).toISOString();
    if ($('tl-to').value) { const d = new Date(`${$('tl-to').value}T00:00:00`); d.setDate(d.getDate() + 1); f.to = d.toISOString(); }
    return f;
  }
  $('timeline-filters').addEventListener('submit', (e) => { e.preventDefault(); loadTimeline(); });
  $('tl-clear').addEventListener('click', () => { for (const id of ['tl-app', 'tl-kind', 'tl-from', 'tl-to']) $(id).value = ''; loadTimeline(); });
  function dayGroup(box, iso, state) {
    const d = new Date(iso).toDateString();
    if (d !== state.day) {
      state.day = d; state.group = el('div', 'day');
      state.group.append(el('h2', null, new Date(iso).toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' })));
      box.append(state.group);
    }
    return state.group;
  }
  async function loadTimeline() {
    const box = $('timeline'), filters = timelineFilters(), filtered = Object.keys(filters).length > 0;
    loading(box);
    $('timeline-mode').textContent = filtered ? 'Memories matching your filters, newest first.' : 'Sessions Lens has grouped from what it observed or imported.';
    const r = filtered ? await call({ op: 'timeline', filters, limit: 100 }) : await call({ op: 'episodes', limit: 100 });
    settled(box);
    if (!r || !r.ok) { box.append(el('p', 'error', `Timeline unavailable (${errorText(r)}).`)); return; }
    const state = {};
    const fmt = (x) => x.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (filtered) {
      const rows = r.sources || [];
      if (!rows.length) { emptyState(box, 'Nothing matches', 'Try a wider date range or another app name.'); return; }
      for (const s of rows) {
        const row = button('episode-row memory-row', null, () => openEvidence(s.id), `Open ${kindLabel(s.kind)} from ${appName(s.source_application)}, ${when(s.timestamp)}`);
        row.dataset.sourceId = s.id;
        row.append(el('span', 'when', fmt(new Date(s.timestamp))), el('span', 'app', appName(s.source_application)),
          memoryText('span', 'what', (s.text || '').slice(0, 160), s.language), el('span', 'count', kindLabel(s.kind)));
        dayGroup(box, s.timestamp, state).append(row);
      }
      return;
    }
    if (!r.episodes.length) { emptyState(box, 'Nothing here yet', 'Sessions appear after Lens has observed or imported activity.'); return; }
    for (const ep of r.episodes) {
      const row = button('episode-row', null, () => openEvidence(ep.last_source_id || ep.first_source_id),
        `Open the latest memory of the ${appName(ep.application)} session ${fmt(new Date(ep.started_at))}`);
      row.append(el('span', 'when', `${fmt(new Date(ep.started_at))}–${fmt(new Date(ep.ended_at))}`), el('span', 'app', appName(ep.application)),
        memoryText('span', 'what', ep.title || ''), el('span', 'count', `${ep.observation_count} views`));
      dayGroup(box, ep.started_at, state).append(row);
    }
  }
  loaders.timeline = loadTimeline;
  $('timeline-mode').textContent = '';

  // ---- People and things ---------------------------------------------------------------------------------------
  $('people-form').addEventListener('submit', (e) => { e.preventDefault(); loadPeople(); });
  async function loadPeople() {
    const box = $('people-list'), q = $('people-q').value.trim(), type = $('people-type').value;
    loading(box);
    const req = { op: 'entities', limit: 100 }; if (q) req.query = q; if (type) req.type = type;
    const r = await call(req);
    settled(box);
    if (!r || !r.ok) { box.append(el('p', 'error', `People unavailable (${errorText(r)}).`)); return; }
    if (!r.entities.length) { emptyState(box, q ? 'No match' : 'No one yet', q ? 'Lens has not seen that name in your memories.' : 'Names appear after Lens consolidates what it observed or imported.'); return; }
    for (const e of r.entities) {
      const b = button('list-item', null, () => openEntity(e.id), `${e.name}, ${TYPES[e.type] || e.type}, ${e.mention_count} mentions`);
      b.dataset.entityId = e.id;
      b.append(memoryText('span', 'li-title', e.name), el('span', 'li-meta', `${TYPES[e.type] || e.type} · ${e.mention_count} mentions · ${day(e.last_seen)}`));
      box.append(b);
    }
  }
  loaders.people = loadPeople;
  async function openEntity(id) {
    const box = $('people-detail');
    document.querySelectorAll('#people-list .list-item').forEach((n) => n.classList.toggle('selected', n.dataset.entityId === id));
    loading(box);
    const r = await call({ op: 'entity_context', id, limit: 20 });
    settled(box);
    if (!r || !r.ok) { box.append(el('p', 'error', `Details unavailable (${errorText(r)}).`)); return; }
    if (r.not_found || !r.entity) { emptyState(box, 'Not found', 'This name is no longer in your memories.'); return; }
    const e = r.entity;
    box.append(el('p', 'eyebrow', TYPES[e.type] || e.type), memoryText('h2', 'detail-title', e.name),
      el('p', 'muted', `${e.mention_count} mentions in ${e.source_count} memories · first ${day(e.first_seen)} · last ${day(e.last_seen)}`));
    if (r.aliases && r.aliases.length > 1) {
      box.append(el('h3', 'section-label', 'Also written as'));
      const c = el('div', 'chips'); for (const a of r.aliases) c.append(memoryText('span', 'chip', a.alias)); box.append(c);
    }
    if (r.facts && r.facts.length) { box.append(el('h3', 'section-label', 'Facts')); const l = el('ul', 'facts'); for (const f of r.facts) l.append(factItem(f)); box.append(l); }
    if (r.projects && r.projects.length) {
      box.append(el('h3', 'section-label', 'Projects'));
      const c = el('div', 'chips');
      for (const p of r.projects) c.append(button('chip-btn', p.name, () => show('projects', true).then(() => openProject(p.id)), `Project ${p.name}`));
      box.append(c);
    }
    if (r.related && r.related.length) {
      box.append(el('h3', 'section-label', 'Often together with'));
      const c = el('div', 'chips');
      for (const x of r.related) c.append(button('chip-btn', x.name, () => openEntity(x.id), `${x.name}, ${x.shared_sources} shared memories`));
      box.append(c);
    }
    if (r.mentions && r.mentions.length) {
      box.append(el('h3', 'section-label', 'Where Lens saw it'));
      const list = el('div', 'rows');
      for (const m of r.mentions) {
        const row = button('row-btn', null, () => openEvidence(m.source_id, { byte_offset: m.byte_offset, byte_end: m.byte_end }),
          `Open the memory from ${appName(m.source_application)}, ${when(m.timestamp)}`);
        row.dataset.sourceId = m.source_id;
        row.append(el('span', 'row-meta', `${appName(m.source_application)} · ${when(m.timestamp)}`),
          memoryText('span', 'row-text', (m.excerpt && m.excerpt.text) || m.surface || ''));
        list.append(row);
      }
      box.append(list);
    }
  }

  // ---- Projects ------------------------------------------------------------------------------------------------
  async function loadProjects() {
    const box = $('projects-list');
    loading(box);
    const r = await call({ op: 'projects', limit: 100 });
    settled(box);
    if (!r || !r.ok) { box.append(el('p', 'error', `Projects unavailable (${errorText(r)}).`)); return; }
    if (!r.projects.length) { emptyState(box, 'No projects yet', 'Projects appear when Lens sees the same project name across your work.'); return; }
    for (const p of r.projects) {
      const b = button('list-item', null, () => openProject(p.id), `${p.name}, ${p.source_count} memories, ${p.fact_count} facts`);
      b.dataset.projectId = p.id;
      b.append(memoryText('span', 'li-title', p.name), el('span', 'li-meta', `${p.source_count} memories · ${p.fact_count} facts · ${day(p.last_seen)}`));
      box.append(b);
    }
  }
  loaders.projects = loadProjects;
  async function openProject(id) {
    const box = $('projects-detail');
    document.querySelectorAll('#projects-list .list-item').forEach((n) => n.classList.toggle('selected', n.dataset.projectId === id));
    loading(box);
    const r = await call({ op: 'project_context', id, limit: 20 });
    settled(box);
    if (!r || !r.ok) { box.append(el('p', 'error', `Project unavailable (${errorText(r)}).`)); return; }
    if (r.not_found || !r.project) { emptyState(box, 'Not found', 'This project is no longer in your memories.'); return; }
    const p = r.project;
    box.append(el('p', 'eyebrow', 'Project'), memoryText('h2', 'detail-title', p.name),
      el('p', 'muted', `${p.source_count} memories · ${p.episode_count} sessions · ${p.fact_count} facts · ${day(p.first_seen)} – ${day(p.last_seen)}`));
    const people = (r.entities || []).filter((e) => e.type === 'person');
    if (people.length) {
      box.append(el('h3', 'section-label', 'People'));
      const c = el('div', 'chips');
      for (const e of people) c.append(button('chip-btn', e.name, () => show('people', true).then(() => openEntity(e.id)), `${e.name}, ${e.shared_sources} shared memories`));
      box.append(c);
    }
    if (r.facts && r.facts.length) { box.append(el('h3', 'section-label', 'Facts')); const l = el('ul', 'facts'); for (const f of r.facts) l.append(factItem(f)); box.append(l); }
    if (r.episodes && r.episodes.length) {
      box.append(el('h3', 'section-label', 'Sessions'));
      const list = el('div', 'rows');
      for (const ep of r.episodes) list.append((() => { const d = el('div', 'row-static');
        d.append(el('span', 'row-meta', `${appName(ep.application)} · ${when(ep.started_at)} · ${ep.observation_count} views`), memoryText('span', 'row-text', ep.title || '')); return d; })());
      box.append(list);
    }
    if (r.sources && r.sources.length) {
      box.append(el('h3', 'section-label', 'Memories'));
      const list = el('div', 'rows');
      for (const s of r.sources) {
        const row = button('row-btn', null, () => openEvidence(s.source_id), `Open the memory from ${appName(s.source_application)}, ${when(s.timestamp)}`);
        row.dataset.sourceId = s.source_id;
        row.append(el('span', 'row-meta', `${appName(s.source_application)} · ${when(s.timestamp)}`), memoryText('span', 'row-text', (s.excerpt && s.excerpt.text) || ''));
        list.append(row);
      }
      box.append(list);
    }
  }

  // ---- Devices (pairing) ---------------------------------------------------------------------------------------
  let pairTimer = null;
  function stopPairing() { if (pairTimer) clearInterval(pairTimer); pairTimer = null; $('pairing-card').hidden = true; $('pair-qr').replaceChildren(); $('pair-text').textContent = ''; }
  async function loadDevices() {
    const link = $('devices-link'), list = $('devices-list');
    const s = await call({ op: 'status' });
    link.replaceChildren();
    if (!s || !s.ok) { link.append(el('p', 'error', `Lens is not running (${errorText(s)}).`)); return; }
    const on = !!s.phone_link;
    const head = el('div', 'card-head');
    const txt = el('div'); txt.append(el('h2', null, 'Phone link'), el('p', 'muted', on ? (s.mesh_running ? 'On. Paired devices can reach this PC on your local network.' : 'On, but the link is not running.') : 'Off. Turn it on to pair a phone or watch.'));
    head.append(txt, button(on ? 'ghost' : 'primary', on ? 'Turn off' : 'Turn on', async (e) => {
      e.target.disabled = true; await call({ op: 'set_consent', phone_link: !on }); stopPairing(); await loadDevices(); await refreshCapture();
    }, on ? 'Turn off phone link' : 'Turn on phone link'));
    link.append(head);
    $('pair-start').disabled = !s.mesh_running;
    loading(list);
    if (!s.mesh_running) { settled(list); emptyState(list, 'Phone link is off', 'No device can connect while it is off.'); return; }
    const [d, ms] = await Promise.all([call({ op: 'mesh_devices' }), call({ op: 'mesh_status' })]);
    settled(list);
    if (ms && ms.ok) link.append(el('p', 'muted small', `This PC's certificate ${String(ms.fingerprint || '').slice(0, 16)}… · port ${ms.port} · ${ms.connections} connected now`));
    if (!d || !d.ok) { list.append(el('p', 'error', `Device list unavailable (${errorText(d)}).`)); return; }
    if (!d.devices.length) { emptyState(list, 'No paired devices', 'Pair a phone or watch to search this PC’s memory from it.'); return; }
    for (const dev of d.devices) {
      const row = el('div', 'row-static device');
      const name = dev.name || 'Unnamed device', fp = String(dev.fingerprint || '');
      const info = el('div'); info.append(memoryText('span', 'li-title', name), el('span', 'row-meta', `Paired ${when(dev.paired_utc)} · ${fp.slice(0, 16)}…`));
      row.append(info, button('ghost danger-text', 'Revoke', async (e) => {
        if (!window.confirm(`Revoke ${name}? It will no longer be able to connect.`)) return;
        e.target.disabled = true; const r = await call({ op: 'mesh_unpair', fingerprint: fp });
        if (r && r.ok) loadDevices(); else { e.target.disabled = false; e.target.textContent = 'Revoke failed'; }
      }, `Revoke ${name}`));
      list.append(row);
    }
  }
  loaders.devices = loadDevices;
  $('pair-start').addEventListener('click', async () => {
    stopPairing();
    const r = await call({ op: 'mesh_pair_begin' });
    if (!r || !r.ok || !r.qr) { $('devices-list').prepend(el('p', 'error', `Could not start pairing (${errorText(r)}).`)); return; }
    const code = JSON.stringify(r.qr);
    $('pair-qr').replaceChildren(window.lensQr.svg(code, 'Pairing QR code for the Lens phone app'));
    $('pair-text').textContent = code;
    $('pairing-card').hidden = false;
    const ends = Date.now() + (r.expires_in_seconds || 300) * 1000;
    const tick = () => {
      const left = Math.max(0, Math.round((ends - Date.now()) / 1000));
      $('pair-expiry').textContent = left ? `Expires in ${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}` : 'Expired. Start pairing again.';
      if (!left) { clearInterval(pairTimer); pairTimer = null; $('pair-qr').replaceChildren(); $('pair-text').textContent = ''; }
    };
    tick(); pairTimer = setInterval(tick, 1000);
    $('pair-cancel').focus();
  });
  $('pair-cancel').addEventListener('click', () => { stopPairing(); loadDevices(); $('pair-start').focus(); });

  // ---- Import --------------------------------------------------------------------------------------------------
  let impPath = null, impPoll = null;
  const impFormat = $('imp-format'), impOrder = $('imp-order');
  const impRequest = () => ({ path: impPath, format: impFormat.value, ...(impFormat.value === 'whatsapp' ? { date_order: impOrder.value } : {}) });
  impFormat.addEventListener('change', () => { $('imp-order-label').hidden = impFormat.value !== 'whatsapp'; if (impPath) previewImport(); });
  impOrder.addEventListener('change', () => { if (impPath) previewImport(); });
  $('imp-pick').addEventListener('click', async () => {
    const r = await hostCall('pick_file');
    if (!r || !r.ok) { if (r && r.error !== 'cancelled') $('imp-file').textContent = `Could not open the file picker (${errorText(r)}).`; return; }
    impPath = r.path; $('imp-file').textContent = r.name || r.path;
    previewImport();
  });
  async function previewImport() {
    const box = $('imp-preview');
    loading(box, 'Reading the file…');
    const r = await call({ op: 'import_preview', ...impRequest() });
    settled(box);
    if (!r || !r.ok) { box.append(el('p', 'error', `This file cannot be imported as ${impFormat.options[impFormat.selectedIndex].text} (${errorText(r)}).`)); return; }
    const summary = el('p', null, `${r.records} memories found${r.skipped ? `, ${r.skipped} lines skipped` : ''}${r.first ? ` · ${day(r.first)} – ${day(r.last)}` : ''}.`);
    box.append(summary);
    if (r.sample && r.sample.length) {
      const list = el('ul', 'sample');
      for (const s of r.sample) { const li = el('li'); li.append(el('span', 'row-meta', when(s.timestamp)), memoryText('span', 'row-text', s.text)); list.append(li); }
      box.append(el('h3', 'section-label', 'First entries'), list);
    }
    if (r.records) box.append(button('primary', `Import ${r.records} memories`, startImport));
  }
  async function startImport(e) {
    e.target.disabled = true;
    const r = await call({ op: 'import_start', ...impRequest() });
    if (!r || !r.ok) { e.target.disabled = false; $('imp-preview').append(el('p', 'error', `Import did not start (${errorText(r)}).`)); return; }
    watchImport(r.import.id);
  }
  function renderProgress(job) {
    const pct = job.total ? Math.round((job.processed / job.total) * 100) : 100;
    const bar = $('imp-bar'); bar.setAttribute('aria-valuenow', String(pct)); bar.firstElementChild.style.width = `${pct}%`;
    $('imp-progress-text').textContent = `${job.processed} of ${job.total} · ${job.imported} added · ${job.deduplicated} already known · ${job.failed} not added`;
  }
  function watchImport(id) {
    $('imp-progress').hidden = false; $('imp-cancel').disabled = false; $('imp-cancel').dataset.id = id;
    if (impPoll) clearInterval(impPoll);
    const poll = async () => {
      const r = await call({ op: 'import_status', id });
      if (!r || !r.ok) return;
      renderProgress(r.import);
      if (r.import.status !== 'running') {
        clearInterval(impPoll); impPoll = null; $('imp-cancel').disabled = true;
        $('imp-progress-text').textContent += r.import.status === 'cancelled' ? ' · cancelled' : ' · finished';
        $('imp-preview').replaceChildren(); loadImports();
      }
    };
    poll(); impPoll = setInterval(poll, 500);
  }
  $('imp-cancel').addEventListener('click', async (e) => { e.target.disabled = true; await call({ op: 'import_cancel', id: e.target.dataset.id }); });
  async function loadImports() {
    const box = $('imports-list');
    loading(box);
    const r = await call({ op: 'import_status' });
    settled(box);
    if (!r || !r.ok) { box.append(el('p', 'error', `Imports unavailable (${errorText(r)}).`)); return; }
    if (!r.imports.length) { emptyState(box, 'No imports yet', 'Imported memories can be removed here, import by import.'); return; }
    for (const job of r.imports) {
      const row = el('div', 'row-static');
      const info = el('div');
      const status = { done: 'Finished', running: 'Importing', cancelled: 'Cancelled', deleted: 'Deleted', interrupted: 'Interrupted' }[job.status] || job.status;
      info.append(memoryText('span', 'li-title', job.file || 'Import'),
        el('span', 'row-meta', `${status} · ${when(job.started_utc)} · ${job.imported} added · ${job.deduplicated} already known · ${job.failed} not added`));
      row.append(info);
      if (job.status === 'running') { row.append(button('ghost', 'Show progress', () => watchImport(job.id))); if (!impPoll) watchImport(job.id); }
      else if (job.status !== 'deleted' && job.source_count) {
        row.append(button('ghost danger-text', 'Delete imported memories', async (e) => {
          if (!window.confirm(`Delete the ${job.source_count} memories this import added? Your original file is not touched.`)) return;
          e.target.disabled = true; const d = await call({ op: 'import_delete', id: job.id });
          if (d && d.ok) loadImports(); else { e.target.disabled = false; e.target.textContent = 'Delete failed'; }
        }, `Delete the memories imported from ${job.file}`));
      }
      box.append(row);
    }
  }
  $('imp-refresh').addEventListener('click', loadImports);
  loaders.import = loadImports;

  // ---- Privacy and capture state -------------------------------------------------------------------------------
  const consentToggles = [...document.querySelectorAll('input[data-consent]')];
  const autostart = $('autostart-toggle'), pause = $('pause-button');
  const editorsDirty = { privacy: false };
  let privacyEditor = null;
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
    if (privacyEditor && !editorsDirty.privacy) privacyEditor.set(s.exclusions);
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
  loaders.privacy = () => Promise.all([refreshCapture(), loadRequests()]);

  // Exclusions editor: apps (process names) and window-title words the observer must skip, on top of its built-in list.
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
      add.setAttribute('aria-label', `Add to ${g.label.toLowerCase()}`);
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
  privacyEditor = exclusionEditor($('privacy-exclusions'), () => { editorsDirty.privacy = true; $('exclusions-saved').textContent = ''; });
  $('exclusions-save').addEventListener('click', async () => {
    const r = await call({ op: 'set_exclusions', ...privacyEditor.value() });
    $('exclusions-saved').textContent = r && r.ok ? 'Saved' : 'Could not save';
    if (r && r.ok) { editorsDirty.privacy = false; privacyEditor.set(r); }
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
      text.append(memoryText('strong', null, describe(a)), el('span', 'muted', ` — asked by ${a.requested_by}, ${when(a.requested_utc)}`));
      const yes = el('button', 'primary', 'Approve'), no = el('button', 'ghost', 'Deny');
      yes.setAttribute('aria-label', `Approve: ${describe(a).slice(0, 80)}`); no.setAttribute('aria-label', `Deny: ${describe(a).slice(0, 80)}`);
      const decide = async (approve) => { yes.disabled = no.disabled = true; await call({ op: 'action_decide', id: a.id, approve }); loadRequests(); };
      yes.addEventListener('click', () => decide(true)); no.addEventListener('click', () => decide(false));
      row.append(text, no, yes); box.append(row);
    }
    return list;
  }

  // ---- Storage -------------------------------------------------------------------------------------------------
  async function loadStorage() {
    const grid = $('status-grid'), files = $('storage-files');
    loading(grid); loading(files);
    const [st, d] = await Promise.all([call({ op: 'stats' }), call({ op: 'diagnostics' })]);
    settled(grid); settled(files);
    if (!st || !st.ok) { grid.append(el('p', 'error', `Storage unavailable (${errorText(st)}).`)); return; }
    const stat = (label, value, small) => { const c = el('div', 'stat'); c.append(el('div', 'label', label), el('div', small ? 'value small' : 'value', String(value))); grid.append(c); };
    stat('Memories', st.source_count);
    stat('Searchable by meaning', st.embedded_sources);
    stat('Compressed', st.compressed_sources);
    stat('People and things', st.entity_count ?? '—');
    stat('Facts', st.fact_count ?? '—');
    stat('Projects', st.project_count ?? '—');
    stat('Compressed text', bytes(st.compressed_text_bytes), true);
    stat('Search vectors', st.vector_chunks ?? '—');
    stat('Encryption', `SQLCipher ${st.cipher_version || ''} · schema ${st.schema_version}`, true);
    if (!d || !d.ok) { files.append(el('p', 'error', `File sizes unavailable (${errorText(d)}).`)); return; }
    $('storage-dir').textContent = d.storage.data_dir;
    for (const f of d.storage.files) { const row = el('div', 'kv'); row.append(el('span', null, f.name), el('span', 'num', bytes(f.bytes))); files.append(row); }
    const total = el('div', 'kv total'); total.append(el('span', null, 'Total'), el('span', 'num', bytes(d.storage.total_bytes))); files.append(total);
  }
  loaders.storage = loadStorage;
  const loadStatus = loadStorage;  // kept for callers of the earlier Status view

  // ---- Diagnostics ---------------------------------------------------------------------------------------------
  async function loadDiagnostics() {
    const grid = $('diag-grid'), procs = $('diag-processes'), cap = $('diag-capture');
    loading(grid); loading(procs); loading(cap);
    const [d, st] = await Promise.all([call({ op: 'diagnostics' }), call({ op: 'stats' })]);
    settled(grid); settled(procs); settled(cap);
    if (!d || !d.ok) { grid.append(el('p', 'error', `Diagnostics unavailable (${errorText(d)}).`)); return; }
    $('diag-updated').textContent = `Updated ${new Date().toLocaleTimeString()}`;
    const stat = (label, value, small) => { const c = el('div', 'stat'); c.append(el('div', 'label', label), el('div', small ? 'value small' : 'value', String(value))); grid.append(c); };
    stat('Background memory', bytes(d.memory.working_set));
    stat('Running for', d.uptime_seconds < 3600 ? `${Math.round(d.uptime_seconds / 60)} min` : `${(d.uptime_seconds / 3600).toFixed(1)} h`, true);
    stat('Screen observer', d.paused ? 'Paused' : d.observer_running ? 'Running' : 'Off', true);
    stat('Microphone', d.voice_running ? 'Listening' : d.paused ? 'Paused' : 'Off', true);
    stat('Observed / stored / failed', `${d.observed} / ${d.stored} / ${d.failed}`, true);
    stat('Understanding models', d.semantic === 'verified' ? 'Verified' : 'Keyword only', true);
    if (st && st.ok) {
      stat('Embedding model', st.embedding_model ? String(st.embedding_model).split('@')[0] : 'not configured', true);
      stat('Models in memory', st.models_loaded ? 'Loaded' : 'Unloaded (idle)', true);
    }
    const mb = d.memory.working_set / 1e6, meter = $('diag-meter');
    meter.setAttribute('aria-valuenow', String(Math.round(mb))); meter.setAttribute('aria-valuetext', `${Math.round(mb)} MB of 500 MB`);
    meter.firstElementChild.style.width = `${Math.min(100, (d.memory.working_set / d.memory.ceiling) * 100)}%`;
    for (const p of d.processes) {
      const row = el('div', 'kv'); row.append(el('span', null, p.name), el('span', 'num', `${bytes(p.working_set)} in use · ${bytes(p.private)} private`)); procs.append(row);
    }
    const capture = (label, c) => {
      const row = el('div', 'kv');
      if (!c) { row.append(el('span', null, label), el('span', 'muted', 'Nothing captured in this session')); cap.append(row); return; }
      const bits = [when(c.at), c.path === 'ocr' ? 'on-device OCR' : c.path === 'uia' ? 'accessibility text' : c.path];
      if (c.extract_ms != null) bits.push(`read in ${c.extract_ms} ms`);
      if (c.ocr_ms != null) bits.push(`OCR ${c.ocr_ms} ms`);
      if (c.store_ms != null) bits.push(`stored in ${c.store_ms} ms`);
      if (c.recognizers) bits.push(`recognisers ${[].concat(c.recognizers).join(', ')}`);
      if (c.language) bits.push(`language ${c.language}`);
      if (!c.ok) bits.push(`not stored (${c.error})`);
      row.append(el('span', null, label), el('span', 'num', bits.filter(Boolean).join(' · ')));
      cap.append(row);
    };
    capture('Screen', d.capture.screen); capture('Voice', d.capture.voice);
  }
  $('diag-refresh').addEventListener('click', loadDiagnostics);
  loaders.diagnostics = loadDiagnostics;

  // ---- First run -----------------------------------------------------------------------------------------------
  // Explain what Lens captures and where it keeps it, then ask for each consent separately (all off by default).
  // Nothing is sent to the agent until Finish (or "Keep everything off"), so nothing is captured before it.
  const onboarding = $('onboarding');
  const obEditor = exclusionEditor($('ob-exclusions'), () => {});
  let obStep = 1;
  function obShow(step) {
    obStep = step;
    onboarding.querySelectorAll('.ob-step').forEach((n) => n.classList.toggle('active', Number(n.dataset.step) === step));
    onboarding.querySelectorAll('.ob-steps li').forEach((n) => {
      const k = Number(n.dataset.step); n.classList.toggle('active', k === step); n.classList.toggle('done', k < step);
      if (k === step) n.setAttribute('aria-current', 'step'); else n.removeAttribute('aria-current');
    });
    const h = onboarding.querySelector('.ob-step.active h1'); if (h) { h.tabIndex = -1; h.focus({ preventScroll: true }); }
  }
  function openOnboarding(s) {
    $('ob-data-dir').textContent = (s && s.data_dir) || '%LOCALAPPDATA%\\Lens';
    for (const id of ['ob-screen', 'ob-mic', 'ob-phone', 'ob-autostart']) $(id).checked = false;
    obEditor.set(s && s.exclusions);
    $('ob-error').hidden = true;
    onboarding.hidden = false; obShow(1);
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
      if (!r || !r.ok) { $('ob-error').textContent = `Lens could not save your choices (${errorText(r)}).`; $('ob-error').hidden = false; return false; }
    }
    onboarding.hidden = true;
    await refreshCapture();
    $('ask-input').focus();
    return true;
  }
  $('ob-skip').addEventListener('click', () => finishOnboarding({ screen: false, mic: false, phone: false, autostart: false }));
  $('ob-finish').addEventListener('click', async (e) => {
    e.target.disabled = true;
    await finishOnboarding({ screen: $('ob-screen').checked, mic: $('ob-mic').checked, phone: $('ob-phone').checked,
      autostart: $('ob-autostart').checked, exclusions: obEditor.value() });
    e.target.disabled = false;
  });

  // ---- Self-test (native host --self-test): the bridge end to end, every view loaded against the real agent ----
  window.lensSelfTest = async () => {
    await ready;
    const status = await call({ op: 'status' });
    const stats = await call({ op: 'stats' });
    const views = {}, errors = [];
    const onError = (e) => errors.push(String((e && e.message) || e));
    window.addEventListener('error', onError);
    for (const v of ['timeline', 'people', 'projects', 'devices', 'import', 'privacy', 'storage', 'diagnostics', 'ask']) {
      const t0 = performance.now();
      try { await show(v); views[v] = { ms: Math.round(performance.now() - t0), errors: document.querySelectorAll(`#view-${v} .error`).length }; }
      catch (e) { views[v] = { ms: Math.round(performance.now() - t0), exception: String(e) }; }
    }
    window.removeEventListener('error', onError);
    const result = { ok: !!(status && status.ok && stats && stats.ok) && !errors.length, status, stats, ui: document.title, onboarding: !onboarding.hidden,
      ready_ms: readyMs, views, errors };
    if (host) host.postMessage(JSON.stringify({ selftest: result }));
    return result;
  };
  window.lensUi = { call, renderResults, loadTimeline, refreshCapture, loadStatus, loadStorage, loadDiagnostics, loadRequests, loadPeople, openEntity,
    loadProjects, openProject, loadDevices, loadImports, openEvidence, closeEvidence, show, openOnboarding };

  let readyMs = null;
  const ready = (async () => {
    const s = await refreshCapture();
    if (s && s.ok && !s.onboarded) openOnboarding(s);
    await loadRequests();
    readyMs = Math.round(performance.now());
  })();
  setInterval(() => { refreshCapture(); loadRequests(); }, 15000);
})();
