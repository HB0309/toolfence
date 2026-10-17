/**
 * explorer.js — S3: Trial table, flyout, replay.
 *
 * Depends on:
 *   - Tabulator (global, loaded before this script)
 *   - Bootstrap/Tabler offcanvas (via tabler.min.js)
 *   - app.js globals: filtered(), VERDICT_COLORS, setFilter(), _esc()
 *
 * Exposes:
 *   - renderExplorer()   (called from app.js renderAll())
 *
 * Replay rules (from spec §6/S3):
 *   - Listener attached ONCE at startup (DOMContentLoaded), never inside renderAll().
 *   - Filter change (detected at top of renderExplorer) stops replay; resets
 *     counter to 0 / M where M = new filtered() length.
 *   - Resume continues where it stopped.
 *   - States: idle → playing → paused → playing | finished.
 */

'use strict';

// ---------------------------------------------------------------------------
// Tabulator instance
// ---------------------------------------------------------------------------

let _tabulatorTable = null;

// ---------------------------------------------------------------------------
// Replay state
// ---------------------------------------------------------------------------

let _replayRecords   = [];      // snapshot of filtered() taken when replay starts
let _replayIndex     = 0;       // next record to emit (preserved across pause/resume)
let _replayTimer     = null;    // setInterval handle
let _replayState     = 'idle';  // 'idle' | 'playing' | 'paused' | 'finished'

// ---------------------------------------------------------------------------
// Provenance badge colours
// ---------------------------------------------------------------------------

const _PROV_COLORS = {
  'user':        { bg: '#1c4a2e', text: '#2da44e', label: 'user'        },
  'first-party': { bg: '#1a3a5c', text: '#56B4E9', label: 'first-party' },
  'untrusted':   { bg: '#4a1c1c', text: '#D55E00', label: '⚠ untrusted' },
};

function _provBadge(prov) {
  const c = _PROV_COLORS[prov] || { bg: '#2a2d35', text: '#8A8F98', label: prov || '?' };
  return `<span class="badge" style="background:${c.bg};color:${c.text};font-size:0.7rem">${_esc(c.label)}</span>`;
}

// ---------------------------------------------------------------------------
// Result badge for a record
// ---------------------------------------------------------------------------

function _resultBadge(rec) {
  if (rec.kind === 'attack') {
    const v     = rec.verdict ?? 'inconclusive';
    const color = VERDICT_COLORS[v] ?? '#8A8F98';
    return `<span class="badge" style="background:${color}22;color:${color};border:1px solid ${color}66">${_esc(v)}</span>`;
  }
  // normal trial
  if (rec.task_success === true)
    return `<span class="badge" style="background:#009E7322;color:#009E73;border:1px solid #009E7366">success</span>`;
  if (rec.task_success === false)
    return `<span class="badge" style="background:#D55E0022;color:#D55E00;border:1px solid #D55E0066">failed</span>`;
  return `<span class="badge" style="background:#8A8F9822;color:#8A8F98;border:1px solid #8A8F9866">undetermined</span>`;
}

// ---------------------------------------------------------------------------
// Flyout — opens Bootstrap offcanvas with per-trial detail
// ---------------------------------------------------------------------------

function _openFlyout(rec) {
  const body = document.getElementById('trial-flyout-body');
  if (!body) return;

  const guard = rec.guard_on ? 'Guard on' : 'Guard off';

  // --- header badges ---
  let headerHTML = `<div class="d-flex flex-wrap gap-1 mb-3">`;
  headerHTML += _resultBadge(rec);
  headerHTML += ` <span class="badge bg-secondary">${_esc(rec._label)}</span>`;
  headerHTML += ` <span class="badge bg-secondary">${_esc(rec._model)}</span>`;
  headerHTML += ` <span class="badge bg-secondary">${_esc(rec._app)}</span>`;
  headerHTML += ` <span class="badge bg-secondary">${_esc(rec.defense ?? 'none')}</span>`;
  const guardColor = rec.guard_on ? VERDICT_COLORS.held : '#9AA0A6';
  headerHTML += ` <span class="badge" style="background:${guardColor}33;color:${guardColor}">${_esc(guard)}</span>`;
  headerHTML += `</div>`;

  // --- held-call warning note ---
  const heldN = rec._heldCalls ?? 0;
  const heldNote = heldN > 0
    ? `<div class="alert alert-secondary py-2 mb-3" style="font-size:0.85rem">
         Guard held ${heldN} call(s) in this trial; held calls were not executed.
       </div>`
    : '';

  // --- tool call steps ---
  const tcs = rec.trace?.tool_calls ?? [];
  let stepsHTML = '';
  for (let i = 0; i < tcs.length; i++) {
    const tc     = tcs[i];
    const isHeld = tc.guard_decision === 'hold';
    const heldStyle = isHeld
      ? `border-left:3px solid ${VERDICT_COLORS.held};padding-left:0.5rem;`
      : '';

    // strip mcp_galaxium_ / mcp_filesystem_ prefix from tool name
    const rawName  = tc.name ?? '(unknown)';
    const dispName = rawName.replace(/^mcp_(galaxium|filesystem)_/i, '');

    // guard decision badge
    const gdBadge = isHeld
      ? `<span class="badge fw-bold" style="background:${VERDICT_COLORS.held}33;color:${VERDICT_COLORS.held}">HOLD</span>`
      : `<span class="badge bg-secondary" style="opacity:0.6">pass</span>`;

    // arguments with provenance badges
    const args = tc.args ?? {};
    const prov = tc.provenance ?? {};
    let argsHTML = '';
    for (const [argName, argVal] of Object.entries(args)) {
      const full   = String(argVal ?? '');
      const valStr = full.slice(0, 120);
      const cut    = full.length > 120 ? '…' : '';
      argsHTML += `<div class="ms-3 mb-1" style="font-size:0.82rem;font-family:monospace">
        <span class="text-muted">${_esc(argName)}</span> = <span>${_esc(valStr)}${cut}</span>
        ${_provBadge(prov[argName])}
      </div>`;
    }

    // result text with show-more toggle
    const result    = tc.result ?? '';
    const resultFull = String(result);
    const resultShort = resultFull.slice(0, 300);
    const resultCut   = resultFull.length > 300;
    const resultId    = `tc-result-${i}`;
    let resultHTML = '';
    if (resultFull) {
      resultHTML = `<div class="ms-3 mt-1" style="font-size:0.82rem">
        <span class="text-muted">result:</span>
        <span id="${resultId}-short">${_esc(resultShort)}${resultCut ? '…' : ''}</span>
        ${resultCut
          ? `<span id="${resultId}-full" style="display:none">${_esc(resultFull)}</span>
             <a href="#" class="ms-1" style="font-size:0.8rem"
               onclick="event.preventDefault();
                 document.getElementById('${resultId}-short').style.display='none';
                 document.getElementById('${resultId}-full').style.display='';
                 this.style.display='none';">show more</a>`
          : ''}
      </div>`;
    }
    if (tc.error) {
      resultHTML += `<div class="ms-3 mt-1 text-danger" style="font-size:0.82rem">error: ${_esc(tc.error)}</div>`;
    }

    stepsHTML += `<div class="mb-3 p-2 rounded" style="background:#1c2128;${heldStyle}">
      <div class="d-flex align-items-center gap-2 mb-1">
        <span class="text-muted" style="font-size:0.75rem">Step ${i + 1}</span>
        <span class="fw-semibold" style="font-size:0.88rem">${_esc(dispName)}</span>
        ${gdBadge}
        ${tc.duration_ms != null
          ? `<span class="text-muted ms-auto" style="font-size:0.75rem">${tc.duration_ms} ms</span>`
          : ''}
      </div>
      ${argsHTML}
      ${resultHTML}
    </div>`;
  }

  // --- final reply (max 1500 chars with show-more) ---
  const reply      = rec.trace?.final_reply ?? '';
  const replyFull  = String(reply);
  const replyShort = replyFull.slice(0, 1500);
  const replyCut   = replyFull.length > 1500;
  const replyId    = 'flyout-reply';
  let replyHTML = '';
  if (replyFull) {
    replyHTML = `<h6 class="mt-3 mb-1" style="font-size:0.85rem;color:#8A8F98">Final reply</h6>
      <pre id="${replyId}-short"
        style="white-space:pre-wrap;font-size:0.8rem;background:#1c2128;padding:0.75rem;border-radius:4px;overflow:auto;max-height:300px"
      >${_esc(replyShort)}${replyCut ? '…' : ''}</pre>
      ${replyCut
        ? `<pre id="${replyId}-full"
             style="display:none;white-space:pre-wrap;font-size:0.8rem;background:#1c2128;padding:0.75rem;border-radius:4px;overflow:auto"
           >${_esc(replyFull)}</pre>
           <a href="#" style="font-size:0.8rem"
             onclick="event.preventDefault();
               document.getElementById('${replyId}-short').style.display='none';
               document.getElementById('${replyId}-full').style.display='';
               this.style.display='none';">show more</a>`
        : ''}`;
  }

  // --- footer: metadata + Copy JSON ---
  const footerHTML = `<div class="mt-3 pt-2 border-top d-flex flex-wrap gap-3 align-items-center"
      style="font-size:0.78rem;color:#8A8F98">
    <span>trial_id: ${_esc(rec.trial_id ?? '—')}</span>
    <span>run_id: ${_esc(rec.run_id ?? rec._run ?? '—')}</span>
    <span>status: ${_esc(rec.status ?? '—')}</span>
    <span>tokens: ${rec._tokens ?? 0}</span>
    <button class="btn btn-sm btn-outline-secondary ms-auto" style="font-size:0.75rem"
      onclick="navigator.clipboard.writeText(JSON.stringify(window._flyoutRec, null, 2))">Copy JSON</button>
  </div>`;

  body.innerHTML = headerHTML + heldNote + stepsHTML + replyHTML + footerHTML;

  // stash full record for Copy JSON
  window._flyoutRec = rec;

  // open Bootstrap offcanvas
  const oc = document.getElementById('trial-flyout');
  if (oc && window.bootstrap?.Offcanvas) {
    bootstrap.Offcanvas.getOrCreateInstance(oc).show();
  }
}

// ---------------------------------------------------------------------------
// Tabulator trial table
// ---------------------------------------------------------------------------

function _resultFormatter(cell) {
  return _resultBadge(cell.getRow().getData()._rec);
}

function _boolFormatter(cell) {
  const v = cell.getValue();
  if (v === true)  return '<span style="color:#009E73">yes</span>';
  if (v === false) return '<span style="color:#D55E00">no</span>';
  return '<span style="color:#8A8F98">—</span>';
}

function _buildTableData(recs) {
  return recs.map(r => ({
    _rec:          r,
    run:           r._run ?? '—',
    app:           r._app,
    model:         r._model,
    kind:          r.kind ?? '—',
    label:         r._label,
    defense:       r.defense ?? 'none',
    guard:         r.guard_on,
    result:        null,           // rendered by formatter
    heldCalls:     r._heldCalls,
    canaryInArgs:  r.canary_in_args ?? false,
    tokens:        r._tokens,
  }));
}

// ---------------------------------------------------------------------------
// renderExplorer — called by app.js renderAll()
//
// On each call:
//  1. If a replay is active, stop it and reset counter to 0 / new-M.
//  2. Rebuild / refresh the Tabulator table with the current filtered() records.
// ---------------------------------------------------------------------------

function renderExplorer() {
  const recs = filtered();

  // --- stop any in-progress replay when filters change ---
  if (_replayState === 'playing' || _replayState === 'paused') {
    _replayStop();
    _replayState = 'idle';
    _replaySetBtn('▶ Replay');
    _replayRecords = [];
    _replayIndex   = 0;
    const list = document.getElementById('replay-list');
    if (list) list.innerHTML = '';
  }
  _replaySetCounter(0, recs.length);

  // --- Tabulator ---
  const el = document.getElementById('trial-table');
  if (!el) return;

  const tableData = _buildTableData(recs);

  if (_tabulatorTable) {
    _tabulatorTable.replaceData(tableData);
    return;
  }

  _tabulatorTable = new Tabulator('#trial-table', {
    data:           tableData,
    theme:          'midnight',
    layout:         'fitColumns',
    pagination:     true,
    paginationSize: 20,
    height:         '420px',
    rowClick: function(_e, row) {
      _openFlyout(row.getData()._rec);
    },
    columns: [
      { title: 'Run',        field: 'run',          headerFilter: true,  width: 110 },
      { title: 'App',        field: 'app',          headerFilter: true,  width: 100 },
      { title: 'Model',      field: 'model',        headerFilter: true,  width: 130 },
      { title: 'Kind',       field: 'kind',         headerFilter: true,  width: 75  },
      { title: 'Probe/Task', field: 'label',        headerFilter: true,  widthGrow: 2 },
      { title: 'Defense',    field: 'defense',      headerFilter: true,  width: 110 },
      { title: 'Guard',      field: 'guard',        formatter: _boolFormatter,   width: 70 },
      { title: 'Result',     field: 'result',       formatter: _resultFormatter, width: 110 },
      { title: 'Held',       field: 'heldCalls',    width: 60  },
      { title: 'Canary',     field: 'canaryInArgs', formatter: _boolFormatter,   width: 70 },
      { title: 'Tokens',     field: 'tokens',       width: 75  },
    ],
  });
}

// ---------------------------------------------------------------------------
// Replay helpers
// ---------------------------------------------------------------------------

function _replaySetCounter(n, total) {
  const el = document.getElementById('replay-counter');
  if (el) el.textContent = `${n} / ${total} records`;
}

function _replaySetBtn(label) {
  const btn = document.getElementById('replay-btn');
  if (btn) btn.textContent = label;
}

function _replayStop() {
  if (_replayTimer !== null) {
    clearInterval(_replayTimer);
    _replayTimer = null;
  }
}

function _replayStep() {
  if (_replayIndex >= _replayRecords.length) {
    _replayStop();
    _replayState = 'finished';
    _replaySetBtn('↺ Restart');
    _replaySetCounter(_replayRecords.length, _replayRecords.length);
    return;
  }
  const rec = _replayRecords[_replayIndex++];
  _replaySetCounter(_replayIndex, _replayRecords.length);

  // prepend a .replay-card to #replay-list
  const list = document.getElementById('replay-list');
  if (list) {
    const tcs = rec.trace?.tool_calls ?? [];
    const tcNames = tcs
      .map(tc => (tc.name ?? '').replace(/^mcp_(galaxium|filesystem)_/i, ''))
      .filter(Boolean);
    const toolCallsHTML = `<div class="tool-calls mt-1" style="font-size:0.75rem;color:#8A8F98">${
      tcNames.length
        ? tcNames.map(n => `<span class="me-1">${_esc(n)}</span>`).join('')
        : '<span>—</span>'
    }</div>`;

    const card = document.createElement('div');
    card.className = 'replay-card p-2 mb-1 rounded';
    card.style.cssText = 'background:#1c2128;cursor:pointer;font-size:0.82rem';
    card.innerHTML = `
      <div class="d-flex align-items-center gap-2">
        <span class="text-muted">${_esc(rec.trial_id ?? '—')}</span>
        <span>${_esc(rec._label)}</span>
        ${_resultBadge(rec)}
      </div>
      ${toolCallsHTML}
    `;
    card.addEventListener('click', () => _openFlyout(rec));
    list.insertBefore(card, list.firstChild);
  }
}

function _replayStartOrResume(fromBeginning) {
  if (fromBeginning) {
    _replayRecords = filtered().slice();
    _replayIndex   = 0;
    const list = document.getElementById('replay-list');
    if (list) list.innerHTML = '';
    _replaySetCounter(0, _replayRecords.length);
  }
  _replayState = 'playing';
  _replaySetBtn('⏸ Pause');
  _replayTimer = setInterval(_replayStep, 800);
}

// ---------------------------------------------------------------------------
// Attach replay button listener ONCE at DOMContentLoaded
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('replay-btn');
  if (!btn) return;

  btn.addEventListener('click', () => {
    if (_replayState === 'idle' || _replayState === 'finished') {
      _replayStartOrResume(true);
    } else if (_replayState === 'playing') {
      _replayStop();
      _replayState = 'paused';
      _replaySetBtn('▶ Resume');
    } else if (_replayState === 'paused') {
      _replayStartOrResume(false);   // resume — keeps _replayIndex intact
    }
  });
});
