# Dashboard Fixes Plan (P1-live-eval)

## Overview

Three targeted fixes to the ToolFence dashboard on branch `P1-live-eval`:

1. **Undetermined column** — the normal-task table in `replay.js` is missing the `Undetermined` column that the backend already produces in `NormalConditionSummary.undetermined`.
2. **Multi-run support** — `server.py` reads only flat `*.json` files; live results live in subfolders (`results/full/`, `results/narrowed/`, `results/pg8-gate/`). Add `/api/runs` endpoint, `?run=<name>` parameter on `/api/summary` and `/api/results`, a run-selector widget, and a per-run comparison table in the UI. Flat folders continue to work unchanged.
3. **Deploy doc cleanup** — `docs/deploy.md` references "the provided `Dockerfile`" which does not exist. Remove that phrase; also remove the "Alternatively … docker build" block (lines 57–63) which also requires a Dockerfile. The buildpacks command stays.

All dashboard constraints from AGENTS.md remain in force: stdlib `http.server` only, no outbound calls, no env-var reads, `inconclusive` always its own column, read-only.

---

## Sub-Task 1 — Add Undetermined column to normal-task table

**Intent**  
`NormalConditionSummary` already carries an `undetermined` field (task_success=None trials). The JS table at `replay.js:112–130` omits it. Adding the column makes the table truthful when some trials have not yet been evaluated.

**Expected Outcomes**  
- Table header has a new `Undetermined` column between `Skipped` and `Total`.
- Each row reads `nc.undetermined` for that cell.
- The aggregate paragraph under the table shows `undetermined` count (mirrors the `NormalTaskCounts.undetermined` field already on the summary).
- No other behaviour changes.

**Todo List**  
- [ ] In `replay.js` `buildNormalGrid` (lines 112–130): add `<th class="num">Undetermined</th>` after `Skipped` and before `Total`.
- [ ] Add the corresponding `<td class="num">${nc.undetermined}</td>` in the row template.
- [ ] Update the aggregate paragraph to also display `Undetermined: ${normalTasks.undetermined}`.

**Relevant Context**  
- `toolfence/cli/dashboard/static/replay.js` lines 104–141 (`buildNormalGrid`)
- `toolfence/engine/scoring.py` `NormalConditionSummary.undetermined` and `NormalTaskCounts.undetermined`

**Status** — [ ] pending

---

## Sub-Task 2 — Multi-run support in server + UI

**Intent**  
Results are organised in named subfolders (full, narrowed, pg8-gate). The server must expose these as selectable runs so the dashboard can show per-run summaries and a comparison table.

### Server changes (`server.py`)

**New helpers**  
- `_list_runs(results_dir)` → sorted list of subfolder names that contain at least one `*.json` file.  If there are no subfolders with JSON files, return an empty list (flat-folder mode, backward-compatible).
- `_resolve_run_dir(results_dir, run_name)` → validates `run_name`: reject any value containing `..` or `/` or `\` with a 400 response; return `results_dir / run_name` if it is an existing subdirectory, else 404. 
- `_load_records` and `_load_records_with_names` grow an optional `sub_dir: Path | None` parameter. When `sub_dir` is given, load from there; otherwise load from `results_dir` (preserves current flat-folder behaviour).

**New endpoint**  
`GET /api/runs` → JSON array of run names (strings). Empty array `[]` means the folder is flat (no subfolders) — the UI treats this as "single unnamed run".

**Modified endpoints**  
- `GET /api/results?run=<name>` — if `run` query param is absent, load from flat `results_dir` as today. If present, validate name and load from `results_dir/<name>/`.
- `GET /api/summary?run=<name>` — same logic; `run_id` passed to `aggregate()` becomes the run name (instead of hardcoded `"dashboard"`).

**Routing change**  
`do_GET` already strips the query string with `path = self.path.split("?")[0]`. A new helper `_query_param(key)` extracts a single query parameter value from `self.path`.  Add `elif path == "/api/runs"` branch.

**Security**  
- Reject `run` values containing `..`, `/`, or `\`. Return 400.
- Validate that the resolved path is a direct child of `results_dir` (`.is_relative_to` check).

### UI changes (`replay.js`, `index.html`)

**Run selector**  
- On `bootstrap()`, first fetch `/api/runs`.
- If the array is non-empty, render a `<select>` element above the grids (or in a header bar) showing each run name.  Default selection = first run.
- Changing the selector re-fetches `/api/summary?run=<name>` and `/api/results?run=<name>` and re-renders all grids/tables.
- If `/api/runs` returns `[]` (flat folder), no selector is shown and fetch calls remain without `?run=` (existing behaviour preserved).

**Comparison table**  
A new `buildRunComparisonTable(runsData)` function renders a table with one row per run showing: Run name, Leaked, Refused, Held, Normal success %, Cards shown. This is displayed above or below the trend table section.  Data is gathered by fetching `/api/summary?run=<name>` for each run returned by `/api/runs`.

**Expected Outcomes**  
- `GET /api/runs` returns `["full","narrowed","pg8-gate"]` for the live `results/` layout.
- `GET /api/summary?run=full` returns the summary for `results/full/` only.
- `GET /api/summary?run=../etc` returns 400.
- Flat-folder invocation (`--results-dir fixtures/spike_converted`) returns `[]` from `/api/runs`; all other endpoints behave exactly as before.
- Dashboard shows a run selector and comparison table when multiple runs are detected.
- New server tests cover `/api/runs` (subfolder and flat cases), `?run=` happy path, and `?run=` path-traversal rejection.

**Todo List**  
- [ ] Add `_list_runs(results_dir)` helper to `server.py`.
- [ ] Add `_resolve_run_dir` validation helper to `server.py` (returns `Path | None`, caller sends 400/404).
- [ ] Add `_query_param(self, key)` method to `_DashboardHandler`.
- [ ] Add `elif path == "/api/runs": self._serve_runs()` branch in `do_GET`.
- [ ] Add `_serve_runs()` method.
- [ ] Update `_serve_results()` to read `?run=` param, validate, and load from sub-dir when present.
- [ ] Update `_serve_summary()` same way; pass run name as `run_id` to `aggregate()`.
- [ ] Update docstring at top of `server.py` with new endpoint.
- [ ] In `replay.js` `bootstrap()`: fetch `/api/runs`, conditionally render run selector, attach change handler.
- [ ] Add `buildRunComparisonTable()` function in `replay.js`.
- [ ] Add placeholder elements in `index.html` for the run selector and comparison table.
- [ ] Add tests in `tests/test_dashboard_server.py`: `/api/runs` with subfolder layout, `/api/runs` flat layout returns `[]`, `?run=full` returns filtered summary, `?run=../secret` returns 400, `?run=` with slash returns 400.

**Relevant Context**  
- `toolfence/cli/dashboard/server.py` — all helper functions and handler methods
- `toolfence/cli/dashboard/static/replay.js` `bootstrap()` lines 282–322
- `toolfence/cli/dashboard/static/index.html` — DOM skeleton
- `tests/test_dashboard_server.py` — existing test patterns for fixtures

**Status** — [ ] pending

---

## Sub-Task 3 — Remove phantom Dockerfile reference from deploy.md

**Intent**  
`docs/deploy.md` line 43 says "using the provided `Dockerfile` (or the inline command below):" but no `Dockerfile` exists in the repo. Remove only that phrase; the buildpacks `ibmcloud ce build create` command and the "Alternatively, build locally" block both stay.

**Expected Outcomes**  
- The parenthetical phrase `(or the inline command below)` and the back-tick-quoted word `Dockerfile` are removed from the prose.
- The `docker build` block in the "Alternatively" section remains (it is a legitimate alternative if the user adds a Dockerfile themselves).
- No other content changes.

**Todo List**
- [ ] Edit `docs/deploy.md` lines 41–43: remove the clause `using the provided \`Dockerfile\` (or the inline command below)`. Keep the sentence readable: "The dashboard is served by `python -m toolfence serve` (stdlib `http.server` only — no extra dependencies beyond what `pip install -e .` provides). Build and push a container image:".
- [ ] Remove the "Alternatively, build locally and push to IBM Container Registry" block (lines 57–63, the `docker build` + `docker push` commands) — it also depends on a Dockerfile.

**Relevant Context**
- `docs/deploy.md` lines 41–43 and 57–63

**Design decisions confirmed by user**
- Comparison table goes above the existing trend table.
- `?run=` on a flat folder with a non-existent subfolder → 404.
- `/api/runs` returning `[]` causes the selector to be hidden silently.

**Status** — [ ] pending

---

## Sub-Task 4 — Run full pytest suite

**Intent**  
Confirm all existing tests pass plus the new server tests added in Sub-Task 2.

**Expected Outcomes**  
- `pytest` exits 0 with no new failures or warnings attributable to these changes.

**Todo List**  
- [ ] Run `pytest` and report outcome; fix any regressions.

**Status** — [ ] pending
