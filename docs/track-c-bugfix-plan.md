# Track C Bug-Fix Plan

## Overview

Three targeted fixes to Track C files, reported by a co-developer after C-6 shipped.
No new features, no refactors. All changes are confined to:

- `toolfence/cli/dashboard/server.py`
- `toolfence/cli/ci_checks.py`
- `tests/test_dashboard_server.py`
- `tests/test_ci.py`

After all fixes, the full test suite must pass: `pytest --skip-network -q`.

---

## Sub-Task 1 — Path traversal in `/static/` endpoint

**Status:** [ ] pending

### Intent

`do_GET` in `server.py` constructs `_STATIC_DIR / filename` from a user-supplied path
with no boundary check. A request like `GET /static/../../../../pyproject.toml` escapes
the static directory and serves arbitrary files from the repo. Fix by resolving the
candidate path and returning 404 if it is not inside `_STATIC_DIR`.

### Expected Outcomes

- `GET /static/../../../../pyproject.toml` returns **404** (not 200 with file content).
- `GET /static/index.html` still returns **200** (normal access unaffected).
- New test `test_path_traversal_blocked` in `tests/test_dashboard_server.py` passes.

### Todo List

1. In `server.py` `do_GET`, after `filename = path[len("/static/"):]`, add:
   ```python
   resolved = (_STATIC_DIR / filename).resolve()
   if not resolved.is_relative_to(_STATIC_DIR.resolve()):
       self._not_found()
       return
   ```
   (`Path.is_relative_to` is available in Python 3.9+; this project requires 3.12.)

2. Add `test_path_traversal_blocked` to `tests/test_dashboard_server.py`.
   - Must use `http.client` (raw TCP), NOT `urllib`, because `urllib` normalises `..`
     before sending and the traversal would never reach the server.
   - Start a server against a tmp dir with a known file (can reuse `server_url` fixture
     or spin up a fresh one).
   - Send raw request: `GET /static/../../../../pyproject.toml HTTP/1.0\r\n\r\n`
   - Assert response status is **404**.

### Relevant Context

- Fix location: `server.py` lines 49–51 (`do_GET` `/static/` branch).
- `_STATIC_DIR` is a module-level `Path` constant (`_HERE / "static"`).
- `_serve_file` is NOT the right place to add the check (it is also called for `/` root
  which is pre-resolved); the check belongs in `do_GET` before `_serve_file` is called.

---

## Sub-Task 2 — `surface_diff_check`: method extraction and action-class mismatch demotion

**Status:** [ ] pending

### Intent

Two related bugs in `ci_checks.py`:

**Part A — Method extraction:**
Line 85 does `tool.get("method") or "POST"`. The live tool list may contain `"route"`
(`"GET /flights"`) but no `"method"` key (matching the `SurfaceEntry` shape from
`contracts/surface.py`). Every `GET`/read tool then gets method `"POST"`, which
`suggest_action_class` maps to `"state-changing"`, causing false-positive failures.

Fix: extract the HTTP verb from the `route` field when `"method"` is absent.

**Part B — Action-class mismatch direction:**
REQUIREMENTS CLI-5 defines the hard-failure condition as a **"risen action class"** —
where the stored class is *less restrictive* than the heuristic suggests (e.g. stored
`"read"` but live heuristic says `"state-changing"`). A deliberate reviewer *upgrade*
(stored `"irreversible"` where heuristic says `"state-changing"`) is a safe override
and must NOT cause exit 1.

Fix: define a risk order and only fail when `risk(suggested) > risk(stored)`. When
`risk(suggested) <= risk(stored)`, print a warning to stderr but do not add to findings.

### Expected Outcomes

- A tool with `"route": "GET /flights"` and no `"method"` key is correctly treated as
  GET → `"read"` class → no mismatch. Exit 0. *(new test)*
- A tool stored as `"irreversible"` where heuristic suggests `"state-changing"` → exit 0
  with a stderr warning. *(new test)*
- A tool stored as `"read"` for a POST tool → heuristic suggests `"state-changing"` →
  risk rises → exit 1. *(existing `test_surface_diff_action_class_mismatch` still passes)*

### Todo List

1. In `ci_checks.py`, replace line 85:
   ```python
   method = tool.get("method") or "POST"
   ```
   with:
   ```python
   route = tool.get("route", "")
   method = tool.get("method") or (route.split()[0].upper() if route else "POST")
   ```

2. In `ci_checks.py`, add `import sys` to the top-level imports block (alongside the
   existing `import json` / `from pathlib import Path` lines). Do NOT use an inline
   `import sys` inside the function body — the top-level import is cleaner and already
   the convention in this file.

3. In `ci_checks.py`, add the risk-order dict above the `surface_diff_check` function:
   ```python
   _RISK: dict[str, int] = {"read": 0, "state-changing": 1, "irreversible": 2}
   ```

4. In `ci_checks.py`, replace the action-class mismatch block (currently lines 88–92):
   ```python
   if suggested != stored:
       findings.append(...)
   ```
   with:
   ```python
   if _RISK.get(suggested, 1) > _RISK.get(stored, 1):
       findings.append(
           f"Action-class mismatch for '{name}': "
           f"surface has '{stored}', live heuristic suggests '{suggested}'"
       )
   elif suggested != stored:
       print(
           f"Warning: '{name}' stored as '{stored}', "
           f"heuristic suggests '{suggested}' (reviewed override — ok)",
           file=sys.stderr,
       )
   ```

5. Add `test_surface_diff_action_class_override_ok` to `tests/test_ci.py`:
   - Surface stores `"irreversible"` for a tool where heuristic suggests `"state-changing"`.
   - Use a POST tool name with no irreversible keyword so heuristic returns `"state-changing"`.
   - Assert exit 0. Optionally capture stderr and assert the warning string is present.

6. Add `test_surface_diff_method_from_route` to `tests/test_ci.py`:
   - Live tool list has `"route": "GET /flights"` but NO `"method"` key.
   - Surface stores `"read"` for that tool.
   - Assert exit 0 (method correctly extracted from route, no false positive).

### Relevant Context

- Fix location: `ci_checks.py` lines 81–92 (action-class mismatch loop).
- `suggest_action_class(method, name)` lives in `toolfence/engine/surface.py` — do NOT modify.
- `_entry()` helper in `test_ci.py` uses `route=f"GET /{name}"` — the new tests
  should pass a `"route"` key in the live tool dict to exercise the extraction fix.
- `import sys` goes at the top of `ci_checks.py` alongside `import json`.

---

## Sub-Task 3 — `/api/results` must filter non-TrialRecord JSON with an explicit warning

**Status:** [ ] pending

### Intent

`_load_records` returns every `*.json` file in `results/`. When Track B's B-5 task
commits `results/surface.json`, that file will appear in the `/api/results` array and
break the dashboard's replay JS (which expects `trial_id`, `kind`, `verdict`, etc.).

`_serve_summary` already applies a `TrialRecord.model_validate` filter; `/api/results`
does not. Fix `/api/results` to apply the same filter.

**Crucially:** when a file is skipped, print an explicit warning to stderr so developers
can see that something in `results/` is not being served. **Do NOT silently discard.**

**Do NOT modify `_load_records`** — keep it as a raw loader. Apply the filter inline
inside `_serve_results`, matching the pattern in `_serve_summary`.

### Expected Outcomes

- `/api/results` returns only records that validate as `TrialRecord`.
- When a non-TrialRecord JSON file exists in `results/`, a warning line is printed to
  stderr naming the file (e.g. `"Warning: results/surface.json is not a valid TrialRecord — skipped"`).
- All 10 spike_converted records (valid TrialRecords) still appear in `/api/results`. *(existing test)*
- New test `test_api_results_excludes_non_trial_records` passes and verifies the warning.

### Todo List

1. In `server.py`, add `import sys` to the top-level imports (alongside `import json`).

2. In `server.py`, replace `_serve_results` (lines 74–77):
   ```python
   def _serve_results(self) -> None:
       from toolfence.contracts.trial import TrialRecord
       raw = _load_records(self.results_dir)
       records = []
       for r in raw:
           try:
               TrialRecord.model_validate(r)
               records.append(r)
           except Exception:  # noqa: BLE001
               pass
       body = json.dumps(records, default=str).encode("utf-8")
       self._send_json(body)
   ```
   with:
   ```python
   def _serve_results(self) -> None:
       import sys
       from toolfence.contracts.trial import TrialRecord
       raw_pairs = _load_records_with_names(self.results_dir)
       records = []
       for filename, r in raw_pairs:
           try:
               TrialRecord.model_validate(r)
               records.append(r)
           except Exception:  # noqa: BLE001
               print(
                   f"Warning: {filename} is not a valid TrialRecord — skipped",
                   file=sys.stderr,
               )
       body = json.dumps(records, default=str).encode("utf-8")
       self._send_json(body)
   ```

   **Note:** This requires adding a companion `_load_records_with_names` helper that
   returns `list[tuple[str, dict]]` (filename + parsed dict) so the warning can name
   the file. Keep the existing `_load_records` untouched — `_serve_summary` still uses it.

3. Add `_load_records_with_names(results_dir: Path) -> list[tuple[str, dict]]` to `server.py`:
   ```python
   def _load_records_with_names(results_dir: Path) -> list[tuple[str, dict]]:
       """Like _load_records but returns (filename, dict) pairs."""
       pairs: list[tuple[str, dict]] = []
       if not results_dir.is_dir():
           return pairs
       for jf in sorted(results_dir.glob("*.json")):
           try:
               pairs.append((jf.name, json.loads(jf.read_text(encoding="utf-8"))))
           except Exception:  # noqa: BLE001
               pass
       return pairs
   ```

4. Add `test_api_results_excludes_non_trial_records` to `tests/test_dashboard_server.py`:
   - Create a tmp results directory.
   - Copy `fixtures/spike_converted/run-01.json` into the tmp dir.
   - Write a non-TrialRecord JSON file (`surface.json`, shape `{"version": 1, "tools": []}`)
     into the tmp dir.
   - Start the server via **subprocess** (consistent with the existing `server_url` fixture
     pattern — use `_PYTHON -m toolfence serve --results-dir <tmp>`).
   - GET `/api/results` via `urllib`.
   - Assert the response list has exactly **1** record.
   - Assert the `surface.json` dict is not present in the response.

### Relevant Context

- `import sys` must go at the top-level imports block (same decision as ci_checks.py).
- The `_load_records_with_names` helper is a minimal addition — it duplicates the glob
  logic from `_load_records` but returns the filename alongside the dict. This is the
  minimal change that enables the warning without breaking `_serve_summary`'s existing
  call to `_load_records`.
- `test_server_no_env_reads` checks that `server.py` has no `os.environ` reads — `import sys`
  does not trigger this check, so the existing test continues to pass.
- Valid TrialRecord fixture: `fixtures/spike_converted/run-01.json`.

---

## Validation

After all three sub-tasks are complete, run:

```powershell
pytest tests/test_dashboard_server.py tests/test_ci.py -v
pytest --skip-network -q
```

Both must be **green with zero new failures**.

Commit message: `fix(cli): server path-traversal, surface-diff warnings, results filter`
