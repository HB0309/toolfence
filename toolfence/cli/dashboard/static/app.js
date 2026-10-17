/**
 * app.js — ToolFence Dashboard S1
 *
 * Responsibilities:
 *  - Load data from api/runs + api/results (relative URLs, no leading /)
 *  - Compute derived fields per record
 *  - Maintain filter state + URL sync
 *  - Render: KPIs, normal table, security-grid placeholder
 *  - Export: VERDICT_COLORS, filtered(), setFilter(), renderAll()
 *
 * Kept on window (globals) so charts.js and explorer.js can call them.
 */

'use strict';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const VERDICT_COLORS = {
  leaked:       '#FF6A2B',
  held:         '#2FD4FF',
  refused:      '#1EE8A5',
  inconclusive: '#8A8F98',
  skipped:      '#4B5058',
};

const GUARD_COLOR_OFF = '#9AA0A6';
const GUARD_COLOR_ON  = '#2FD4FF';

/** Runs whose presence triggers the "default" view filter. */
// Run names that are excluded from the default view — everything else shows by default.
const _EXCLUDED_RUNS = new Set(['full', 'narrowed', 'pg8-gate']);
function _isDefaultRun(name) { return !_EXCLUDED_RUNS.has(name); }

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _allRecords = [];

let state = {
  run:     'default',
  app:     'all',
  model:   'all',
  guard:   'all',
  defense: 'all',
  kind:    'all',
  probe:   'all',
};

// ---------------------------------------------------------------------------
// Derived-field computation
// ---------------------------------------------------------------------------

function _deriveApp(rec) {
  const tcs = rec.trace?.tool_calls ?? [];
  for (const tc of tcs) {
    if (tc.name?.startsWith('mcp_filesystem_')) return 'filesystem';
    if (tc.name?.startsWith('mcp_galaxium_'))  return 'galaxium';
  }
  const run = rec._run ?? '';
  if (run.startsWith('fs-'))                      return 'filesystem';
  if (run.startsWith('galaxium') || run === 'full' || run === 'narrowed' || run === 'pg8-gate') return 'galaxium';
  return 'unknown';
}

function _deriveModel(rec) {
  const m = rec.trace?.model;
  if (!m) return 'unknown';
  const parts = m.split('/');
  return parts[parts.length - 1] || 'unknown';
}

function _deriveLabel(rec) {
  if (rec.kind === 'attack') return rec.probe_id ?? '(unknown probe)';
  return rec.task_label ?? 'normal';
}

function _deriveHeldCalls(rec) {
  const tcs = rec.trace?.tool_calls ?? [];
  return tcs.filter(tc => tc.guard_decision === 'hold').length;
}

function _deriveTokens(rec) {
  return rec.trace?.usage?.total_tokens ?? 0;
}

function _deriveIsControl(rec) {
  return rec.kind === 'attack' && rec.channel === 'user-input';
}

function _addDerivedFields(rec) {
  rec._app        = _deriveApp(rec);
  rec._model      = _deriveModel(rec);
  rec._label      = _deriveLabel(rec);
  rec._heldCalls  = _deriveHeldCalls(rec);
  rec._tokens     = _deriveTokens(rec);
  rec._isControl  = _deriveIsControl(rec);
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function _fetchJson(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`HTTP ${resp.status} for ${url}`);
  return resp.json();
}

async function loadData() {
  const _strip = document.getElementById('kpi-strip');
  if (_strip && !_strip.children.length) _strip.innerHTML = '<div class="tf-loading">Loading results…</div>';
  const runs = await _fetchJson('api/runs');

  if (runs.length > 0) {
    const batches = await Promise.all(
      runs.map(name =>
        _fetchJson(`api/results?run=${encodeURIComponent(name)}`)
          .then(records => records.map(r => { r._run = name; return r; }))
      )
    );
    _allRecords = batches.flat();
  } else {
    const records = await _fetchJson('api/results');
    records.forEach(r => { r._run = 'results'; });
    _allRecords = records;
  }

  _allRecords.forEach(_addDerivedFields);

  // Determine default run set
  const presentDefaultRuns = _allRecords
    .map(r => r._run)
    .filter(r => _isDefaultRun(r));
  window._hasDefaultRuns = new Set(presentDefaultRuns).size > 0;

  _populateSelects();
  _readUrlState();
  renderAll();
}

// ---------------------------------------------------------------------------
// Filter logic
// ---------------------------------------------------------------------------

function _defaultRunNames() {
  return [...new Set(_allRecords.map(r => r._run).filter(r => _isDefaultRun(r)))];
}

function filtered() {
  return _allRecords.filter(rec => {
    if (state.run === 'default') {
      if (window._hasDefaultRuns) {
        if (!_isDefaultRun(rec._run)) return false;
      }
    } else if (state.run !== 'all') {
      if (rec._run !== state.run) return false;
    }
    if (state.app     !== 'all' && rec._app     !== state.app)     return false;
    if (state.model   !== 'all' && rec._model   !== state.model)   return false;
    if (state.defense !== 'all' && rec.defense  !== state.defense) return false;
    if (state.kind    !== 'all' && rec.kind     !== state.kind)    return false;
    if (state.probe   !== 'all' && rec._label   !== state.probe)   return false;
    if (state.guard !== 'all') {
      const guardOn = state.guard === 'on';
      if (Boolean(rec.guard_on) !== guardOn) return false;
    }
    return true;
  });
}

function setFilter(key, value) {
  state[key] = value;
  _writeUrlState();
  renderAll();
}

// ---------------------------------------------------------------------------
// URL sync
// ---------------------------------------------------------------------------

function _writeUrlState() {
  const defaults = { run: 'default', app: 'all', model: 'all', guard: 'all',
                     defense: 'all', kind: 'all', probe: 'all' };
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(state)) {
    if (v !== defaults[k]) params.set(k, v);
  }
  const qs = params.toString();
  history.replaceState(null, '', qs ? '?' + qs : window.location.pathname);
}

function _readUrlState() {
  const params = new URLSearchParams(window.location.search);
  const keys = ['run', 'app', 'model', 'guard', 'defense', 'kind', 'probe'];
  for (const k of keys) {
    if (params.has(k)) state[k] = params.get(k);
  }
}

// ---------------------------------------------------------------------------
// Select population
// ---------------------------------------------------------------------------

function _unique(arr) { return [...new Set(arr)].sort(); }

function _buildOptions(el, values, currentVal, allLabel = 'All') {
  el.innerHTML = '';
  const addOpt = (val, label) => {
    const o = document.createElement('option');
    o.value = val;
    o.textContent = label;
    if (val === currentVal) o.selected = true;
    el.appendChild(o);
  };
  if (el.id === 'f-run') {
    addOpt('default', 'Default');
    addOpt('all', 'All');
    values.forEach(v => addOpt(v, v));
  } else {
    addOpt('all', allLabel);
    values.forEach(v => addOpt(v, v));
  }
}

function _populateSelects() {
  const runs    = _unique(_allRecords.map(r => r._run));
  const apps    = _unique(_allRecords.map(r => r._app));
  const models  = _unique(_allRecords.map(r => r._model));
  const guards  = ['on', 'off'];
  const defenses = _unique(_allRecords.map(r => r.defense).filter(Boolean));
  const kinds   = _unique(_allRecords.map(r => r.kind).filter(Boolean));

  _buildOptions(document.getElementById('f-run'),     runs,    state.run);
  _buildOptions(document.getElementById('f-app'),     apps,    state.app);
  _buildOptions(document.getElementById('f-model'),   models,  state.model);
  _buildOptions(document.getElementById('f-guard'),   guards,  state.guard);
  _buildOptions(document.getElementById('f-defense'), defenses, state.defense);
  _buildOptions(document.getElementById('f-kind'),    kinds,   state.kind);
}

// Wire select change events once
function _wireSelects() {
  const map = {
    'f-run': 'run', 'f-app': 'app', 'f-model': 'model',
    'f-guard': 'guard', 'f-defense': 'defense', 'f-kind': 'kind',
  };
  for (const [id, key] of Object.entries(map)) {
    document.getElementById(id).addEventListener('change', e => setFilter(key, e.target.value));
  }
  document.getElementById('f-reset').addEventListener('click', () => {
    state = { run: 'default', app: 'all', model: 'all', guard: 'all',
              defense: 'all', kind: 'all', probe: 'all' };
    _populateSelects();
    _writeUrlState();
    renderAll();
  });
  document.getElementById('f-share').addEventListener('click', () => {
    navigator.clipboard.writeText(window.location.href).catch(() => {});
  });
}

// ---------------------------------------------------------------------------
// Filter chips
// ---------------------------------------------------------------------------

function _renderChips() {
  const container = document.getElementById('filter-chips');
  container.innerHTML = '';
  const defaults = { run: 'default', app: 'all', model: 'all', guard: 'all',
                     defense: 'all', kind: 'all', probe: 'all' };
  for (const [k, v] of Object.entries(state)) {
    if (v === defaults[k]) continue;
    const chip = document.createElement('span');
    chip.className = 'chip';
    chip.textContent = `${k}: ${v}`;
    const rm = document.createElement('button');
    rm.className = 'chip-remove';
    rm.textContent = '✕';
    rm.setAttribute('aria-label', `Remove ${k} filter`);
    rm.addEventListener('click', () => setFilter(k, defaults[k]));
    chip.appendChild(rm);
    container.appendChild(chip);
  }
}

// ---------------------------------------------------------------------------
// KPIs
// ---------------------------------------------------------------------------

function _kv(k, n) {
  return n === 0 ? `${k}/0` : `${k}/${n}`;
}

function renderKpis() {
  const recs = filtered();
  const attack = recs.filter(r => r.kind === 'attack');
  const attackOffNonCtrl  = attack.filter(r => !r.guard_on && !r._isControl);
  const attackOnNonCtrl   = attack.filter(r =>  r.guard_on && !r._isControl);
  const normal  = recs.filter(r => r.kind === 'normal' || r.kind === 'task');
  const normalOn = normal.filter(r => r.guard_on);

  // KPI 1: Leaks guard off
  const leaksOff = attackOffNonCtrl.filter(r => r.verdict === 'leaked').length;
  const kpi1 = { title: 'Leaks, Guard off',
    value: `${leaksOff}/${attackOffNonCtrl.length}`,
    caption: 'agent copied untrusted data',
    color: leaksOff > 0 ? VERDICT_COLORS.leaked : undefined };

  // KPI 2: Leaks guard on
  const leaksOn = attackOnNonCtrl.filter(r => r.verdict === 'leaked').length;
  const kpi2 = { title: 'Leaks, Guard on',
    value: `${leaksOn}/${attackOnNonCtrl.length}`,
    caption: 'same probes, Guard on',
    color: leaksOn > 0 ? VERDICT_COLORS.leaked : VERDICT_COLORS.refused };

  // KPI 3: Held by guard
  const held = attackOnNonCtrl.filter(r => r.verdict === 'held').length;
  const kpi3 = { title: 'Held by Guard',
    value: `${held}/${attackOnNonCtrl.length}`,
    caption: 'stopped before it ran',
    color: VERDICT_COLORS.held };

  // KPI 4: Real tasks guard on
  const succNormalOn = normalOn.filter(r => r.task_success === true).length;
  const kpi4val = `${succNormalOn}/${normalOn.length}`;
  // Caption: list task labels with 0 successes under guard on
  const labelMap = {};
  for (const r of normalOn) {
    const lbl = r._label;
    if (!labelMap[lbl]) labelMap[lbl] = { succ: 0, total: 0 };
    labelMap[lbl].total++;
    if (r.task_success === true) labelMap[lbl].succ++;
  }
  const zeroLabels = Object.entries(labelMap)
    .filter(([, v]) => v.succ === 0 && v.total > 0)
    .map(([lbl, v]) => `${lbl} 0/${v.total}`);
  const kpi4caption = zeroLabels.length
    ? `held by design: ${zeroLabels.join(', ')}`
    : 'normal tasks completed';
  const kpi4 = { title: 'Real tasks, Guard on', value: kpi4val, caption: kpi4caption,
    color: VERDICT_COLORS.refused };

  // KPI 5: Cards shown
  const cards = recs.reduce((s, r) => s + (r.cards_shown ?? 0), 0);
  const kpi5 = { title: 'Approval cards', value: String(cards), caption: 'held calls a person would review' };

  // KPI 6: Inconclusive
  const incAttack = recs.filter(r => r.kind === 'attack' && r.verdict === 'inconclusive').length;
  const incNormal = recs.filter(r => (r.kind === 'normal' || r.kind === 'task') && r.task_success === null && r.verdict !== 'skipped').length;
  const incTotal = incAttack + incNormal;
  const kpi6 = { title: 'Inconclusive', value: String(incTotal),
    caption: `${incAttack} attack + ${incNormal} normal`,
    color: VERDICT_COLORS.inconclusive };

  const kpis = [kpi1, kpi2, kpi3, kpi4, kpi5, kpi6];
  const strip = document.getElementById('kpi-strip');
  strip.innerHTML = kpis.map(k => `
    <div class="col-sm-6 col-lg-2">
      <div class="card kpi-card" title="${_esc(k.title)}">
        <div class="card-body">
          <div class="kpi-value" style="${k.color ? `color:${k.color};--glow:${k.color}` : ''}">${_esc(k.value)}</div>
          <div class="kpi-title">${_esc(k.title)}</div>
          <div class="kpi-sub" title="${_esc(k.caption)}">${_esc(k.caption)}</div>
        </div>
      </div>
    </div>`).join('');
}

// ---------------------------------------------------------------------------
// Normal table
// ---------------------------------------------------------------------------

function renderNormalTable() {
  const recs = filtered();
  const normal = recs.filter(r => r.kind === 'normal' || r.kind === 'task');
  const tbody = document.querySelector('#normal-table tbody');
  if (!tbody) return;

  if (normal.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" class="text-muted text-center py-3">No normal-task trials in this view</td></tr>';
    return;
  }

  // Group by _label × guard_on
  const groups = {};
  for (const r of normal) {
    const key = `${r._label}___${r.guard_on ? 'on' : 'off'}`;
    if (!groups[key]) groups[key] = { label: r._label, guardOn: r.guard_on, recs: [], runs: new Set() };
    groups[key].recs.push(r);
    if (r._run) groups[key].runs.add(r._run);
  }

  const rows = Object.values(groups).sort((a, b) => {
    if (a.label < b.label) return -1;
    if (a.label > b.label) return 1;
    return (a.guardOn ? 1 : 0) - (b.guardOn ? 1 : 0);
  });

  tbody.innerHTML = rows.map(g => {
    const total = g.recs.length;
    const succ  = g.recs.filter(r => r.task_success === true).length;
    const fail  = g.recs.filter(r => r.task_success === false).length;
    const undet = g.recs.filter(r => r.task_success === null).length;
    const pct   = total > 0 ? Math.round((succ / total) * 100) : 0;
    const runsStr = [...g.runs].join(', ') || '—';
    const guardBadge = g.guardOn
      ? `<span class="badge badge-sm" style="background:${GUARD_COLOR_ON};color:#fff">on</span>`
      : `<span class="badge badge-sm" style="background:${GUARD_COLOR_OFF};color:#fff">off</span>`;
    const successCell = `
      <div class="success-bar-wrap">
        <span>${succ}/${total}</span>
        <div class="success-bar-bg">
          <div class="success-bar-fill" style="width:${pct}%"></div>
        </div>
      </div>`;
    return `<tr>
      <td>${_esc(g.label)}</td>
      <td>${guardBadge}</td>
      <td>${successCell}</td>
      <td>${fail}</td>
      <td>${undet}</td>
      <td style="font-size:0.8rem">${_esc(runsStr)}</td>
    </tr>`;
  }).join('');
}

// ---------------------------------------------------------------------------
// Security grid (S1 placeholder — never empty)
// ---------------------------------------------------------------------------

function renderSecurityGrid() {
  // In S2+ charts.js owns #security-grid via _renderHeatmap(); skip S1 rendering.
  if (typeof renderCharts === 'function') return;

  const recs = filtered();
  const attack = recs.filter(r => r.kind === 'attack');
  const grid = document.getElementById('security-grid');
  if (!grid) return;

  if (attack.length === 0) {
    grid.innerHTML = '<div class="text-muted py-2">No attack trials in this view. Verdicts: '
      + Object.entries(VERDICT_COLORS).map(([v, c]) =>
          `<span style="color:${c}">${_esc(v)}</span>`).join(' · ')
      + '</div>';
    return;
  }

  // Group by _label (probe)
  const byProbe = {};
  for (const r of attack) {
    const lbl = r._label;
    if (!byProbe[lbl]) byProbe[lbl] = [];
    byProbe[lbl].push(r);
  }

  const probes = Object.keys(byProbe).sort();
  grid.innerHTML = probes.map(probe => {
    const pr = byProbe[probe];
    const total = pr.length;
    const counts = {};
    for (const v of Object.keys(VERDICT_COLORS)) counts[v] = 0;
    for (const r of pr) if (r.verdict && counts[r.verdict] !== undefined) counts[r.verdict]++;

    const stats = Object.entries(VERDICT_COLORS)
      .filter(([v]) => counts[v] > 0)
      .map(([v, c]) => `<span style="color:${c}">${_esc(v)} ${counts[v]}/${total}</span>`)
      .join(' · ');

    return `<div class="probe-row">
      <span class="probe-name">${_esc(probe)}</span>
      <span class="probe-stats">${stats}</span>
    </div>`;
  }).join('');
}

// ---------------------------------------------------------------------------
// renderAll
// ---------------------------------------------------------------------------

function renderAll() {
  _renderChips();
  renderKpis();
  renderNormalTable();
  renderSecurityGrid(); // no-op when charts.js is loaded
  // renderCharts() wired in S2 via charts.js
  if (typeof renderCharts === 'function') renderCharts();
  // renderExplorer() called by explorer.js once it exists
  if (typeof renderExplorer === 'function') renderExplorer();
}

// ---------------------------------------------------------------------------
// HTML escape helper (exported for other scripts)
// ---------------------------------------------------------------------------

function _esc(v) {
  if (v == null) return '';
  return String(v)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  _wireSelects();
  loadData().catch(err => {
    console.error('ToolFence dashboard: data load failed', err);
  });
});
