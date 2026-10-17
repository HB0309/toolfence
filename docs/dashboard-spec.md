# Dashboard v2: Build Spec for Bob

> Copy this file into the repo as `docs/dashboard-spec.md`. Bob builds from it in three steps (S1, S2, S3), **one new chat per step**. This spec is the plan; don't write another one.

## 0. Goal

Replace the plain-table dashboard in `toolfence/cli/dashboard/static/` with a **dark, interactive security-analytics dashboard**: a filter bar, a KPI strip, three charts, and a trial explorer with a slide-out trace view.

Everything is computed in the browser from the existing API. **`server.py` does not change.**

## 1. Hard rules

1. **No request may leave localhost** (`tests/test_dashboard.py:198-232`). All libraries live in `static/vendor/`, which is already downloaded and committed. Never add a CDN link, web font or remote image.
2. **Keep these IDs and behaviours** (`tests/test_dashboard.py`):

   | ID / class | Must |
   |---|---|
   | `#security-grid` | Non-empty after load, **even with zero attack trials** (show an empty-state message) |
   | `#normal-table` | A real `<table>` with at least one `tbody tr` when normal trials exist |
   | `#replay-btn` | Enabled when records exist |
   | `#replay-counter` | Reaches `"M / M"` after replay |
   | `.replay-card` | At least one is rendered during replay |
   | page text | Must contain the word `inconclusive` |

3. **`server.py` stays as it is.** Use only `GET api/results[?run=NAME]` and `GET api/runs`, with **relative paths** (no leading `/`) so a static export works from a subfolder.
4. **No build step, no frameworks, no Node.** Plain ES2020 JavaScript in classic `<script>` tags. Globals are fine.
5. **No AI and no inferred labels.** Show only what the records contain, or simple counts of it.
6. **Show counts as `k/n`.** A percentage is optional and always comes with `(k/n)`. Inconclusive gets its own colour and label everywhere.
7. Don't run the Playwright tests. Run `pytest` without them; if Playwright isn't installed, those tests skip themselves.

## 2. Files

```
toolfence/cli/dashboard/static/
  index.html        REWRITE in S1  (layout + element IDs, loads scripts in this order)
  style.css         NEW in S1      (small overrides on top of Tabler)
  app.js            NEW in S1      (load data, derive fields, filter state, URL sync, KPIs, normal table)
  charts.js         NEW in S2      (3 ECharts charts)
  explorer.js       NEW in S3      (trial table, flyout, replay)
  replay.js         DELETE in S3   (keep it loaded until S3 replaces the replay)
  vendor/           ALREADY COMMITTED, do not edit:
    echarts.min.js            (ECharts 6.1.0)
    tabler.min.css            (Tabler 1.6.1)
    tabler.min.js             (Tabler 1.6.1, includes Bootstrap JS: offcanvas, dropdowns)
    tabulator.min.js          (Tabulator 6.6.1)
    tabulator_midnight.min.css
    LICENSE-*.txt
```

Script order in `index.html`:
1. `vendor/tabler.min.js`
2. `vendor/echarts.min.js`
3. `vendor/tabulator.min.js`
4. `app.js`
5. `charts.js`
6. `explorer.js`

All `src` and `href` values are relative (`static/vendor/...`, `static/app.js`).

## 3. Data: loading and derived fields (`app.js`)

**Loading:**
1. `GET api/runs`. If it returns a non-empty list, fetch `api/results?run=NAME` for each name and tag each record with `rec._run = NAME`.
2. If the list is empty (flat mode, as in the test fixture), fetch `api/results` once and set `_run = "results"`.
3. Records with no `trace` are allowed. Every reader must handle a missing trace, missing `tool_calls`, or `null` fields without throwing.

**Derived fields**, computed once per record:

| Field | Rule |
|---|---|
| `_app` | `"filesystem"` if any `trace.tool_calls[].name` starts with `mcp_filesystem_`; else `"galaxium"` if any starts with `mcp_galaxium_`; else `"filesystem"` if `_run` starts with `fs-`; else `"galaxium"` if `_run` starts with `galaxium` or is `full` / `narrowed` / `pg8-gate`; else `"unknown"` |
| `_model` | Short form of `trace.model`: the part after the last `/` (`granite-4.2-8b`, `llama-3.3-70b-instruct`), or `"unknown"` |
| `_label` | `probe_id` for attack trials, `task_label` (or `"normal"`) for normal trials |
| `_heldCalls` | Number of `tool_calls` with `guard_decision === "hold"` |
| `_tokens` | `trace.usage.total_tokens` or 0 |
| `_isControl` | `kind === "attack" && channel === "user-input"`. These are the user-typed controls; Guard passes them by design. |

**Default run selection:** if any of `galaxium-granite`, `galaxium-llama70b`, `fs-granite`, `fs-llama70b` exist, the default view shows only those. Otherwise it shows all runs.

**Filter state:** one global object:

```
state = { run: "default", app: "all", model: "all", guard: "all", defense: "all", kind: "all", probe: "all" }
```

- `filtered()` returns the records that match.
- Every UI change calls `setFilter(key, value)`, which updates `state`, writes the URL query string (`history.replaceState`), and calls `renderAll()`.
- `renderAll()` calls `renderKpis()`, `renderNormalTable()`, and (once they exist) `renderCharts()` and `renderExplorer()`.
- On load, read the query string into `state`. Ignore unknown values.

## 4. Visual system

- `<html data-bs-theme="dark">`. Use Tabler classes: `page`, `navbar`, `container-xl`, `row row-cards`, `card`, `card-header`, `card-body`, `badge`, `table table-vcenter`.
- **Verdict colours** (one meaning everywhere; always shown with the text label, never colour alone):

  | Verdict | Colour |
  |---|---|
  | leaked | `#D55E00` |
  | held | `#56B4E9` |
  | refused | `#009E73` |
  | inconclusive | `#8A8F98` |
  | skipped | `#4B5058` |

  Export them as `VERDICT_COLORS` from `app.js`.
- **Guard colours:** off `#9AA0A6`, on `#56B4E9`. Normal success `#009E73`, failed `#D55E00`, undetermined `#8A8F98`.
- **ECharts:** `echarts.init(el)` with `backgroundColor: 'transparent'`, text `#C9D1D9`, axis lines and splitLines `#30363D`, tooltip `trigger:'item'`.
  - Call `resize()` on window resize.
  - Don't depend on a named "dark" theme.
- **Numbers** use `font-variant-numeric: tabular-nums`. No decimals beyond one place.

## 5. Page layout and element IDs

```
navbar:  "ToolFence"  · subtitle "Agent tool-safety results"
#filter-bar   (card):  selects #f-run #f-app #f-model #f-guard #f-defense #f-kind
                       #filter-chips (active non-default filters, each with ✕)  · button #f-reset · button #f-share (copies URL)
#kpi-strip    (row of 6 cards)
row: card "Guard off vs on"  → div #chart-dumbbell      | card "Verdict mix" → div #chart-verdicts
card "Where leaks happen"    → #security-grid  (contains div #chart-heatmap, or the empty-state text)
card "Real tasks"            → table #normal-table
card "Trial explorer"        → toolbar: #replay-btn  #replay-counter · div #trial-table · div #replay-list
offcanvas (right, wide)      → #trial-flyout  (Tabler/Bootstrap offcanvas)
footer: disclaimer text from summary convention: "A clean result means the evaluation did not find a way through, not that none exists." + verdict legend (leaked · held · refused · inconclusive with colours)
```

At phone width, Tabler's grid stacks the cards. No other mobile work is needed.

---

## 6. Steps

### S1: Shell, data, filters, KPIs, normal table (`index.html`, `style.css`, `app.js`)

**Build:**
- The layout in §5.
- Data loading and the derived fields in §3.
- The filter bar: each select's options come from the values in the data, plus "All". The run select has "Default", "All", then each run name.
- URL sync, chips, Reset and Share.
- `#kpi-strip`: 6 cards. Each shows a big number as `k/n` (or a count), a one-line caption, and a `title` attribute explaining it. All are computed from `filtered()`:

  | # | Title | Value |
  |---|---|---|
  | 1 | Leaks, Guard off | leaked / attack trials with `guard_on === false && !_isControl` |
  | 2 | Leaks, Guard on | the same with `guard_on === true` |
  | 3 | Held by Guard | held / attack trials with `guard_on === true && !_isControl` |
  | 4 | Real tasks, Guard on | `task_success === true` / normal trials with `guard_on === true`. Caption lists any task with 0 successes under Guard on, e.g. "read_then_write: 0/6, held by design" |
  | 5 | Cards shown | sum of `cards_shown` |
  | 6 | Inconclusive | count of `verdict === "inconclusive"` (attack) + `task_success === null` (normal, not skipped) |

- `#normal-table`: Tabler table with columns Task · Guard · Success (k/n) · Failed · Undetermined · Run(s). It has one row per `_label` × `guard_on`, plus a small coloured bar in the Success cell (a CSS width %). If there are no normal trials, show one row: "No normal-task trials in this view".
- `#security-grid` in S1: a placeholder that is never empty, e.g. a per-probe list of `leaked k/n · held · refused · inconclusive`. S2 replaces it with the heatmap.
- Keep `replay.js` loaded and working, so `#replay-btn`, `#replay-counter` and `.replay-card` still exist. Move its markup into the Trial explorer card.

**Tests** (new `tests/test_dashboard_static.py`, no browser):
- `index.html` contains every ID in §5.
- No `src=` or `href=` in `index.html` starts with `http`.
- Each script tag's file exists under `static/`.
- `static/vendor/echarts.min.js` is served with status 200 via the existing server test fixture pattern.
- The page contains "inconclusive".

**Out of scope:** charts, Tabulator, the flyout.

### S2: Charts (`charts.js`)

`renderCharts()` is called from `renderAll()`. It uses only `filtered()` attack trials.

1. **`#chart-dumbbell`: Guard off vs on.**
   - One row per `_label` (probe). If more than one `_model` is in view, one row per probe · model.
   - x axis is leak rate 0–100%.
   - Two scatter points per row (guard off, guard on) joined by a line series, built from `bar-y-category` plus scatter.
   - Each point is labelled `k/n`.
   - Control probes (`_isControl`) get the suffix " (control)" and a muted colour.
2. **`#chart-verdicts`: Verdict mix.**
   - 100% stacked horizontal bars, one per `_label · guard off/on`.
   - Series in order: leaked, held, refused, inconclusive, coloured with `VERDICT_COLORS`.
   - Segment labels show the count when > 0.
   - Built from `bar-y-category-stack`.
3. **`#chart-heatmap` inside `#security-grid`: Where leaks happen.**
   - y axis = `_label`. x axis = the 6 columns `none·off, none·on, datamarking·off, datamarking·on, instructional·off, instructional·on`.
   - Cell value = leaked count. Cell label = `"k/n"`.
   - `visualMap` runs from `#1F2A37` (0) to `#D55E00` (max). Cells with no trials are gray with the label "–".
   - Built from `heatmap-cartesian`.
   - **Click a cell** → `setFilter('probe', label)`, `setFilter('defense', d)`, `setFilter('guard', g)`, then scroll to the Trial explorer. Probe filter chips need no select; they only show as chips.
   - With no attack trials, `#security-grid` shows the empty-state text: "No attack trials in this view. Verdicts: leaked · held · refused · inconclusive."

Every chart needs a tooltip showing `k/n` and the verdict names. Resize all charts on window resize.

**Tests:** extend `test_dashboard_static.py`:
- `charts.js` exists and is loaded after `app.js`.
- It defines `renderCharts`.
- It contains the IDs `chart-dumbbell`, `chart-verdicts` and `chart-heatmap`.

**Out of scope:** any other chart, and cross-filtering from charts other than the heatmap.

### S3: Trial explorer, flyout, replay (`explorer.js`; delete `replay.js`)

1. **`#trial-table` (Tabulator, theme `tabulator_midnight`).**
   - One row per `filtered()` record.
   - Columns: Run · App · Model · Kind · Probe/Task (`_label`) · Defense · Guard · Result · Held calls · Canary in args · Tokens.
   - The Result column is a coloured badge: the verdict for attack trials, success/failed/undetermined for normal trials.
   - Header filters on the text columns. Sortable. Pagination at 20 rows.
   - **Row click** opens the flyout.
2. **`#trial-flyout` (Bootstrap offcanvas, right, ~640px).**
   - Header: badges for verdict/result, `_label`, `_model`, `_app`, defense, guard.
   - **Steps:** for each `trace.tool_calls[i]`:
     - Step number, tool name (strip the `mcp_galaxium_` / `mcp_filesystem_` prefix), `duration_ms`.
     - One line per argument: `name = value`, where long values are cut to 120 characters. Add a **provenance badge** from `provenance[name]`: user = green, first-party = blue, untrusted = vermilion with ⚠.
     - Guard decision badge: `pass` (muted) or **`HOLD`** (held colour, bold). Give held rows a left border in the held colour.
     - Result, cut to 300 characters with a "show more" toggle, and `error` if present.
   - **Final reply:** `trace.final_reply` in a pre-wrapped block, cut to 1,500 characters with "show more".
     - If the trial has any held call, show a neutral note above it: "Guard held N call(s) in this trial; held calls were not executed."
     - **Do not** try to detect whether the reply claims success.
   - Footer: trial_id, run_id, status, tokens, and a "Copy JSON" button.
3. **Replay** (replaces `replay.js`).
   - `#replay-btn` steps through the current `filtered()` records every 800 ms.
   - Each step prepends a `.replay-card` to `#replay-list`, showing trial id, `_label`, and a result badge. Clicking a card opens the flyout.
   - `#replay-counter` shows `"N / M records"`.
   - The button toggles between ▶ Replay, ⏸ Pause and ▶ Resume. **Resume continues where it stopped.**
   - When finished, it shows ↺ Restart.
   - **Attach the click listener once**, at startup, never inside `renderAll()`.
   - A filter change during replay stops it and resets the counter to `0 / M`.
4. Remove `replay.js` and its `<script>` tag.

**Tests:**
- `replay.js` is gone.
- `explorer.js` is loaded and contains `trial-table`, `trial-flyout`, `replay-btn` and `replay-counter`.
- All existing dashboard tests still pass.

**Out of scope:** verdict overrides, export, JSON viewer.

## 7. Done means

- `pytest` passes.
- `toolfence serve --results-dir results --port 8765` shows:
  - the filter bar;
  - 6 KPIs (Default view: Leaks Guard off 6/18 · Leaks Guard on 0/18 · Held 6/18 · Real tasks 12/18);
  - 3 charts;
  - the normal table;
  - the explorer, opening the flyout with provenance badges.
- Clicking a heatmap cell filters the explorer.
- Changing a filter updates the URL, and reloading the URL restores the view.
- No request leaves localhost.
