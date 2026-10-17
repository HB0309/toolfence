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
    const args = tc.args ?? tc.params ?? {};
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

    // --- tool calls section: name + all args + full result (collapsible) ---
    let toolCallsInner = '';
    if (tcs.length === 0) {
      toolCallsInner = '<span style="color:#8A8F98">—</span>';
    } else {
      for (const tc of tcs) {
        const dispName = (tc.name ?? '(unknown)').replace(/^mcp_(galaxium|filesystem)_/i, '');
        const isHeld   = tc.guard_decision === 'hold';
        const heldMark = isHeld
          ? `<span style="color:${VERDICT_COLORS.held};font-weight:bold;margin-left:4px">HOLD</span>`
          : '';

        // All args as key=value pairs
        const args = tc.args ?? tc.params ?? {};
        const argPairs = Object.entries(args)
          .map(([k, v]) => {
            const vs = String(v ?? '');
            return `<div style="margin-left:8px"><span style="color:#8A8F98">${_esc(k)}</span>=<span style="color:#C9D1D9">${_esc(vs)}</span></div>`;
          }).join('');

        // Full result — use <details> so it's always accessible
        const rawResult = String(tc.result ?? tc.error ?? '').trim();
        let resultSnippet = '';
        if (rawResult) {
          const color      = tc.error ? '#D55E00' : '#8A8F98';
          const borderColor = tc.error ? '#D55E00' : '#30363D';
          const preview    = rawResult.slice(0, 80);
          const needsExpand = rawResult.length > 80;
          if (needsExpand) {
            resultSnippet =
              `<details style="margin-left:8px;margin-top:2px">` +
                `<summary style="cursor:pointer;font-size:0.72rem;color:${color};font-family:monospace;` +
                          `list-style:none;display:flex;align-items:flex-start;gap:4px">` +
                  `<span style="color:#8A8F98;flex-shrink:0">▶</span>` +
                  `<span style="word-break:break-all">${_esc(preview)}…</span>` +
                `</summary>` +
                `<pre style="margin:4px 0 0;padding:6px 8px;background:#0d1117;border-radius:3px;` +
                      `white-space:pre-wrap;word-break:break-all;font-size:0.72rem;color:${color};` +
                      `border-left:2px solid ${borderColor};max-height:240px;overflow-y:auto">${_esc(rawResult)}</pre>` +
              `</details>`;
          } else {
            resultSnippet =
              `<div style="margin-left:8px;font-size:0.72rem;color:${color};font-family:monospace;word-break:break-all">${_esc(rawResult)}</div>`;
          }
        }

        toolCallsInner +=
          `<div style="margin-bottom:4px;padding:4px 6px;background:#161b22;border-radius:3px;border-left:2px solid ${isHeld ? VERDICT_COLORS.held : '#30363D'}">` +
            `<div style="display:flex;align-items:center;flex-wrap:wrap;gap:4px">` +
              `<span style="color:#C9D1D9;font-weight:500">${_esc(dispName)}</span>${heldMark}` +
            `</div>` +
            argPairs +
            resultSnippet +
          `</div>`;
      }
    }
    const toolCallsHTML = `<div class="tool-calls mt-2" style="font-size:0.78rem">${toolCallsInner}</div>`;

    // --- content block: probe injection text or final reply (always fully readable) ---
    let contentHTML = '';
    if (rec.kind === 'attack') {
      // Find the tool result that carries the injection payload
      const canary = rec.canary ?? '';
      let injectedContent = '';
      for (const tc of tcs) {
        const r = String(tc.result ?? '').trim();
        if (r && (canary && r.includes(canary) ||
            tc.provenance && Object.values(tc.provenance).includes('untrusted'))) {
          injectedContent = r;
          break;
        }
      }
      // Fall back to first non-empty tool result
      if (!injectedContent) {
        for (const tc of tcs) {
          const r = String(tc.result ?? '').trim();
          if (r) { injectedContent = r; break; }
        }
      }
      if (injectedContent) {
        const preview     = injectedContent.slice(0, 120);
        const needsExpand = injectedContent.length > 120;
        const preBlock    =
          `<pre style="margin:4px 0 0;padding:6px 8px;background:#161b22;border-radius:3px;` +
               `white-space:pre-wrap;word-break:break-all;font-size:0.73rem;color:#C9D1D9;` +
               `border-left:2px solid #D55E00;overflow-y:auto;max-height:220px">${_esc(injectedContent)}</pre>`;
        if (needsExpand) {
          contentHTML =
            `<details class="mt-2" style="font-size:0.75rem">` +
              `<summary style="cursor:pointer;color:#8A8F98;font-size:0.7rem;` +
                        `text-transform:uppercase;letter-spacing:0.04em;list-style:none;` +
                        `display:flex;align-items:flex-start;gap:4px">` +
                `<span style="flex-shrink:0">▶ Injected content</span>` +
                `<span style="font-weight:normal;text-transform:none;letter-spacing:0;` +
                       `color:#C9D1D9;font-family:monospace;word-break:break-all;` +
                       `margin-left:4px">${_esc(preview)}…</span>` +
              `</summary>` +
              preBlock +
            `</details>`;
        } else {
          contentHTML =
            `<div class="mt-2" style="font-size:0.75rem">` +
              `<span style="color:#8A8F98;font-size:0.7rem;text-transform:uppercase;letter-spacing:0.04em">Injected content</span>` +
              preBlock +
            `</div>`;
        }
      }
    } else {
      // Normal trial — show the full final reply, collapsible if long
      const reply = String(rec.trace?.final_reply ?? '').trim();
      if (reply) {
        const preview     = reply.slice(0, 120);
        const needsExpand = reply.length > 120;
        const replyBlock  =
          `<div style="margin-top:4px;padding:6px 8px;background:#161b22;border-radius:3px;` +
               `font-size:0.73rem;color:#C9D1D9;border-left:2px solid #009E73;` +
               `overflow-y:auto;max-height:220px;word-break:break-word">${_esc(reply)}</div>`;
        if (needsExpand) {
          contentHTML =
            `<details class="mt-2" style="font-size:0.75rem">` +
              `<summary style="cursor:pointer;color:#8A8F98;font-size:0.7rem;` +
                        `text-transform:uppercase;letter-spacing:0.04em;list-style:none;` +
                        `display:flex;align-items:flex-start;gap:4px">` +
                `<span style="flex-shrink:0">▶ Final reply</span>` +
                `<span style="font-weight:normal;text-transform:none;letter-spacing:0;` +
                       `color:#C9D1D9;margin-left:4px;word-break:break-word">${_esc(preview)}…</span>` +
              `</summary>` +
              replyBlock +
            `</details>`;
        } else {
          contentHTML =
            `<div class="mt-2" style="font-size:0.75rem">` +
              `<span style="color:#8A8F98;font-size:0.7rem;text-transform:uppercase;letter-spacing:0.04em">Final reply</span>` +
              replyBlock +
            `</div>`;
        }
      }
    }

    const card = document.createElement('div');
    card.className = 'replay-card p-2 mb-2 rounded';
    card.style.cssText = 'background:#1c2128;cursor:pointer;font-size:0.82rem';
    card.innerHTML = `
      <div class="d-flex align-items-center gap-2 mb-1">
        <span class="text-muted" style="font-size:0.75rem">${_esc(rec.trial_id ?? '—')}</span>
        <span class="fw-semibold">${_esc(rec._label)}</span>
        ${_resultBadge(rec)}
        <span class="text-muted ms-auto" style="font-size:0.72rem">${_esc(rec.defense ?? 'none')} · ${rec.guard_on ? 'guard on' : 'guard off'}</span>
      </div>
      ${toolCallsHTML}
      ${contentHTML}
    `;
    // Open flyout on click, but don't fire when the user is toggling a <details> block
    card.addEventListener('click', (e) => {
      if (e.target.closest('details')) return;
      _openFlyout(rec);
    });
    // Prevent <details> toggle clicks from bubbling up to the card's flyout listener
    for (const det of card.querySelectorAll('details')) {
      det.addEventListener('click', (e) => e.stopPropagation());
    }
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
