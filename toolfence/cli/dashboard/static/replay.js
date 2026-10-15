/**
 * replay.js — ToolFence dashboard logic (C-6)
 *
 * Fetches /api/results and /api/summary from the local server.
 * No outbound network calls to any external host.
 * Builds the security grid, normal-task grid, trend table, and replay UI.
 *
 * Key constraint: "inconclusive" is always its own column — never folded.
 */

"use strict";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function esc(v) {
  if (v === null || v === undefined) return "—";
  return String(v)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function guardBadge(on) {
  return on
    ? '<span class="badge badge-on">on</span>'
    : '<span class="badge badge-off">off</span>';
}

function verdictBadge(v) {
  if (!v) return "—";
  const cls = {
    leaked: "badge-leaked",
    held: "badge-held",
    refused: "badge-refused",
    inconclusive: "badge-inconclusive",
  }[v] || "";
  return `<span class="badge ${cls}">${esc(v)}</span>`;
}

function pct(n, total) {
  if (!total) return "—";
  return (n / total * 100).toFixed(1) + "%";
}

// ---------------------------------------------------------------------------
// Security grid — built from /api/summary conditions
// ---------------------------------------------------------------------------

function buildSecurityGrid(conditions) {
  if (!conditions || conditions.length === 0) {
    return "<p style='color:#57606a;font-style:italic'>No attack trial records found.</p>";
  }

  const header = `
    <table id="security-table">
      <thead><tr>
        <th>Channel</th>
        <th>Defense</th>
        <th>Guard</th>
        <th class="num">Leaked</th>
        <th class="num">Held</th>
        <th class="num">Refused</th>
        <th class="num">Inconclusive</th>
        <th class="num">Skipped</th>
        <th class="num">Total</th>
        <th class="num">Leaked%</th>
        <th class="num">Held%</th>
        <th class="num">Refused%</th>
        <th class="num">Inconclusive%</th>
        <th class="num">Cards Shown</th>
      </tr></thead>
      <tbody>`;

  const rows = conditions.map(c => {
    const a = c.attack;
    const total = a.total || 0;
    return `<tr>
      <td>${esc(c.channel)}</td>
      <td>${esc(c.defense)}</td>
      <td>${guardBadge(c.guard_on)}</td>
      <td class="num">${a.leaked}</td>
      <td class="num">${a.held}</td>
      <td class="num">${a.refused}</td>
      <td class="num">${a.inconclusive}</td>
      <td class="num">${a.skipped}</td>
      <td class="num">${total}</td>
      <td class="num">${a.leaked_pct}%</td>
      <td class="num">${a.held_pct}%</td>
      <td class="num">${a.refused_pct}%</td>
      <td class="num">${a.inconclusive_pct}%</td>
      <td class="num">${c.cards_shown}</td>
    </tr>`;
  }).join("");

  return header + rows + "</tbody></table>";
}

// ---------------------------------------------------------------------------
// Normal-task grid — built from /api/summary normal_conditions
// ---------------------------------------------------------------------------

function buildNormalGrid(normalConditions, normalTasks) {
  if (!normalConditions || normalConditions.length === 0) {
    return "<p style='color:#57606a;font-style:italic'>No normal-task records found.</p>";
  }

  let html = `
    <table id="normal-table">
      <thead><tr>
        <th>Defense</th>
        <th>Guard</th>
        <th class="num">Success</th>
        <th class="num">Failed</th>
        <th class="num">Skipped</th>
        <th class="num">Undetermined</th>
        <th class="num">Total</th>
        <th class="num">Success%</th>
      </tr></thead>
      <tbody>`;

  html += normalConditions.map(nc => `<tr>
    <td>${esc(nc.defense)}</td>
    <td>${guardBadge(nc.guard_on)}</td>
    <td class="num">${nc.success}</td>
    <td class="num">${nc.failed}</td>
    <td class="num">${nc.skipped}</td>
    <td class="num">${nc.undetermined}</td>
    <td class="num">${nc.total}</td>
    <td class="num">${nc.success_pct}%</td>
  </tr>`).join("");

  html += "</tbody></table>";

  if (normalTasks) {
    html += `<p style="font-size:0.8rem;color:#57606a;margin-top:4px">
      Aggregate — Success: ${normalTasks.success} / ${normalTasks.total}
      (${normalTasks.success_pct}%) &nbsp;·&nbsp;
      Undetermined: ${normalTasks.undetermined}
    </p>`;
  }
  return html;
}

// ---------------------------------------------------------------------------
// Run comparison table — one row per run folder from /api/runs
// ---------------------------------------------------------------------------

function buildRunComparisonTable(runsData) {
  // runsData: [{name, summary}, ...]
  if (!runsData || runsData.length === 0) {
    return "";
  }

  let html = `
    <h2>Run Comparison</h2>
    <table id="run-comparison-table">
      <thead><tr>
        <th>Run</th>
        <th class="num">Leaked</th>
        <th class="num">Refused</th>
        <th class="num">Held</th>
        <th class="num">Normal success %</th>
        <th class="num">Cards shown</th>
      </tr></thead>
      <tbody>`;

  for (const { name, summary } of runsData) {
    const conditions = summary.conditions || [];
    let leaked = 0, refused = 0, held = 0, cardsShown = 0;
    for (const c of conditions) {
      leaked     += (c.attack && c.attack.leaked)   || 0;
      refused    += (c.attack && c.attack.refused)  || 0;
      held       += (c.attack && c.attack.held)     || 0;
      cardsShown += c.cards_shown                   || 0;
    }
    const nt = summary.normal_tasks;
    const normalPct = nt ? nt.success_pct + "%" : "—";
    html += `<tr>
      <td>${esc(name)}</td>
      <td class="num">${leaked}</td>
      <td class="num">${refused}</td>
      <td class="num">${held}</td>
      <td class="num">${normalPct}</td>
      <td class="num">${cardsShown}</td>
    </tr>`;
  }

  html += "</tbody></table>";
  return html;
}

// ---------------------------------------------------------------------------
// Trend table — one row per distinct run_id in /api/results
// ---------------------------------------------------------------------------

function buildTrendTable(records) {
  // Group by run_id, count verdicts per run
  const runs = {};
  for (const r of records) {
    const rid = r.run_id || "unknown";
    if (!runs[rid]) runs[rid] = { leaked: 0, held: 0, refused: 0, inconclusive: 0, total: 0 };
    const run = runs[rid];
    run.total++;
    if (r.kind === "attack") {
      if (r.verdict === "leaked")       run.leaked++;
      else if (r.verdict === "held")    run.held++;
      else if (r.verdict === "refused") run.refused++;
      else if (r.verdict === "inconclusive") run.inconclusive++;
    }
  }

  const runIds = Object.keys(runs);
  if (runIds.length === 0) {
    return "<p style='color:#57606a;font-style:italic'>No run data available.</p>";
  }

  let html = `
    <table class="trend-table">
      <thead><tr>
        <th>Run ID</th>
        <th class="num">Total</th>
        <th class="num">Leaked</th>
        <th class="num">Held</th>
        <th class="num">Refused</th>
        <th class="num">Inconclusive</th>
      </tr></thead>
      <tbody>`;

  for (const rid of runIds) {
    const run = runs[rid];
    html += `<tr>
      <td class="run-id">${esc(rid)}</td>
      <td class="num">${run.total}</td>
      <td class="num">${run.leaked}</td>
      <td class="num">${run.held}</td>
      <td class="num">${run.refused}</td>
      <td class="num">${run.inconclusive}</td>
    </tr>`;
  }

  html += "</tbody></table>";
  if (runIds.length < 2) {
    html += `<p style="font-size:0.8rem;color:#57606a;margin-top:4px">
      (Trend view shows multiple runs once more than one run_id is present in results/)
    </p>`;
  }
  return html;
}

// ---------------------------------------------------------------------------
// Replay logic
// ---------------------------------------------------------------------------

let _replayRecords = [];
let _replayIndex = 0;
let _replayTimer = null;
const REPLAY_INTERVAL_MS = 800;

function initReplay(records) {
  _replayRecords = records;
  _replayIndex = 0;

  const btn = document.getElementById("replay-btn");
  const counter = document.getElementById("replay-counter");
  const progress = document.getElementById("replay-progress");

  if (!records || records.length === 0) {
    btn.disabled = true;
    counter.textContent = "No records to replay.";
    return;
  }

  btn.disabled = false;
  counter.textContent = `0 / ${records.length} records`;
  progress.innerHTML = "";

  btn.addEventListener("click", function () {
    if (_replayTimer) {
      clearInterval(_replayTimer);
      _replayTimer = null;
      btn.textContent = "▶ Start Replay";
      return;
    }
    // Reset
    _replayIndex = 0;
    progress.innerHTML = "";
    counter.textContent = `0 / ${records.length} records`;
    btn.textContent = "⏸ Pause";

    _replayTimer = setInterval(function () {
      if (_replayIndex >= _replayRecords.length) {
        clearInterval(_replayTimer);
        _replayTimer = null;
        btn.textContent = "▶ Start Replay";
        return;
      }
      const rec = _replayRecords[_replayIndex];
      _replayIndex++;

      counter.textContent = `${_replayIndex} / ${records.length} records`;

      const card = document.createElement("div");
      card.className = "replay-card";
      card.setAttribute("data-trial-index", _replayIndex);
      card.innerHTML = `
        <span class="label">trial_id</span>
        <span class="value">${esc(rec.trial_id)}</span>
        &nbsp;|&nbsp;
        <span class="label">kind</span>
        <span class="value">${esc(rec.kind)}</span>
        &nbsp;|&nbsp;
        <span class="label">defense</span>
        <span class="value">${esc(rec.defense)}</span>
        &nbsp;|&nbsp;
        <span class="label">guard</span>
        ${guardBadge(rec.guard_on)}
        &nbsp;|&nbsp;
        <span class="label">verdict</span>
        ${rec.kind === "attack" ? verdictBadge(rec.verdict) : "<span style='color:#57606a'>—</span>"}
        ${rec.channel ? `&nbsp;|&nbsp;<span class="label">channel</span> <span class="value">${esc(rec.channel)}</span>` : ""}
      `;
      progress.prepend(card);
    }, REPLAY_INTERVAL_MS);
  });
}

// ---------------------------------------------------------------------------
// Bootstrap — fetch data and render
// ---------------------------------------------------------------------------

async function _renderGrids(summaryUrl, resultsUrl) {
  // Fetch summary for security + normal grids
  let summary = null;
  try {
    const resp = await fetch(summaryUrl);
    summary = await resp.json();
  } catch (e) {
    document.getElementById("security-loading").className = "error";
    document.getElementById("security-loading").textContent = "Failed to load summary: " + e;
    document.getElementById("normal-loading").className = "error";
    document.getElementById("normal-loading").textContent = "Failed to load summary.";
  }

  if (summary) {
    document.getElementById("security-loading").style.display = "none";
    document.getElementById("security-grid").innerHTML =
      buildSecurityGrid(summary.conditions);

    document.getElementById("normal-loading").style.display = "none";
    document.getElementById("normal-grid").innerHTML =
      buildNormalGrid(summary.normal_conditions, summary.normal_tasks);
  }

  // Fetch raw records for trend + replay
  let records = [];
  try {
    const resp = await fetch(resultsUrl);
    records = await resp.json();
  } catch (e) {
    document.getElementById("trend-note").className = "error";
    document.getElementById("trend-note").textContent = "Failed to load results: " + e;
  }

  if (records) {
    document.getElementById("trend-note").style.display = "none";
    document.getElementById("trend-grid").innerHTML = buildTrendTable(records);
    initReplay(records);
  }
}

async function bootstrap() {
  // Fetch run list first
  let runs = [];
  try {
    const resp = await fetch("/api/runs");
    runs = await resp.json();
  } catch (_e) {
    // ignore — fall through to flat-folder mode
  }

  if (Array.isArray(runs) && runs.length > 0) {
    // ---- Multi-run mode ----

    // Build run selector <select>
    const selectorEl = document.getElementById("run-selector-container");
    const select = document.createElement("select");
    select.id = "run-select";
    select.style.cssText = "margin-bottom:16px;padding:4px 8px;font-size:0.875rem;";
    for (const name of runs) {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      select.appendChild(opt);
    }
    const label = document.createElement("label");
    label.htmlFor = "run-select";
    label.textContent = "Run: ";
    label.style.cssText = "font-weight:600;margin-right:6px;font-size:0.875rem;";
    selectorEl.appendChild(label);
    selectorEl.appendChild(select);
    selectorEl.style.display = "";

    // Fetch summaries for all runs (for comparison table)
    const runsData = await Promise.all(
      runs.map(async name => {
        try {
          const r = await fetch("/api/summary?run=" + encodeURIComponent(name));
          const s = await r.json();
          return { name, summary: s };
        } catch (_e) {
          return { name, summary: { conditions: [], normal_tasks: null } };
        }
      })
    );

    // Render comparison table
    const compContainer = document.getElementById("run-comparison-container");
    compContainer.innerHTML = buildRunComparisonTable(runsData);
    compContainer.style.display = "";

    // Initial render: first run
    const firstRun = runs[0];
    await _renderGrids(
      "/api/summary?run=" + encodeURIComponent(firstRun),
      "/api/results?run=" + encodeURIComponent(firstRun)
    );

    // Change listener
    select.addEventListener("change", async function () {
      const chosen = this.value;
      await _renderGrids(
        "/api/summary?run=" + encodeURIComponent(chosen),
        "/api/results?run=" + encodeURIComponent(chosen)
      );
    });

  } else {
    // ---- Flat-folder mode (no subfolders) — original behaviour ----
    await _renderGrids("/api/summary", "/api/results");
  }
}

document.addEventListener("DOMContentLoaded", bootstrap);
