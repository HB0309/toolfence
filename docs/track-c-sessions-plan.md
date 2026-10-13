# ToolFence — Track C Session Plan

> **Scope:** Track C tasks only — `guard/`, `cli/`, `.github/workflows/`, `docs/deploy.md`, `tests/` (C-owned tests).
> Track A (`engine/`) and Track B (`integration/`, `bob/`, `targets/`) are worked on by their own developers.
> This document drives individual Bob sessions, one task per session.
>
> **Current branch state (as of writing):**
> - C-1 ✅ done: `guard/decision.py`, `guard/provenance.py`, `guard/taint.py`, `tests/test_guard_core.py`
> - C-2 ✅ done: `guard/proxy.py`, `guard/card.py`, `tests/test_proxy.py`
> - C-3 ✅ done: `guard/confirm.py`, `tests/test_confirm.py`
> - C-1/C-2/C-3 correctness fixes ✅ committed: confirm flow, session counter, trust defaults
>
> **What to tell each Bob session:** Read this file fully before starting. Read the linked
> source files. Run `pytest <test-file>` at the end to confirm green.

---

## Cross-track coordination needed before Track C can proceed

Before or during certain C tasks, Track B and Track A must ship specific things.
The table below summarises them so you can relay messages now.

| C Task | Needs from | What | Blocking? |
|--------|-----------|------|-----------|
| C-4 (CLI `run`) | Track A — A-5 | `toolfence/engine/runner.py` and `EvaluationRunner` | Yes — C-4 CLI `run` subcommand calls `EvaluationRunner`. **A-5 is already done** (confirmed in codebase). No blocker. |
| C-4 (CLI `scan`) | Track A — A-1 | `SurfaceScanner` in `engine/surface.py` | **A-1 is already done** (confirmed in codebase). No blocker. |
| C-4 (CLI `report`) | Track A — A-4 | `render_report` in `engine/report.py` | **A-4 is already done** (confirmed in codebase). No blocker. |
| C-5 (CI guard-wiring check) | Track B — B-5 | `results/surface.json` committed (real surface map) | Partial blocker for integration tests only. C-5 unit tests can run against `fixtures/surface_fixture.json`. Full CI integration test needs the real `results/surface.json` from B-5. C-5 can be developed and unit-tested without B-5. |
| C-6 (Dashboard) | Track A — A-4, A-5 | `ResultSummary`, `render_report`, `TrialRecord` | **Both done**. No blocker. |
| C-7 (Deploy) | C-6 | Dashboard server working locally | C-7 cannot start until C-6 is done. |
| C-4 tests | Track B — B-4 | `NanobotAdapter` in `integration/nanobot_adapter.py` | **NOT needed for C-4 to build correctly**. CLI `run` defaults to `ScriptedAdapter`. `NanobotAdapter` is a Track B concern invoked only in live runs (`scripts/launch_nanobot.py`). C-4 tests use `ScriptedAdapter` only. |
| C-5 CI check | Track B — B-3 | `install_guard`, `verify_guard_invariant` | **B-3 already done**. `installer.py` is present. C-5 `guard_wiring_check` calls `verify_guard_invariant` — it can import it directly. |

**Message to relay to Track B (B-4b `channel_adapter.py`):**
C-4 CLI does NOT depend on `channel_adapter.py`. Track C has no dependency on B-4b.
B-4b consumes `build_card_message` from `guard/card.py` (C-2, already done) and
`HeldCallEvent` from `contracts/guard.py` (already done). B-4b can proceed independently.

**Message to relay to Track B (test_galaxium_patches.py):**
The `git apply` failure in `test_galaxium_patches.py` is likely a path-stripping issue.
The fix is to add `--directory=booking_system_backend` (or equivalent `-p1` strip) to the
`git apply` call in the test's `patched_tmp` fixture. This is a Track B test in a Track B file —
Track B owns the fix.

---

## Task order for Track C

```
C-4 (CLI)  →  C-5 (CI checks)  →  C-6 (Dashboard)  →  C-7 (Deploy)
```

All four have no blockers from other tracks at this point (confirmed above).

---

## C-4: CLI — scan, run, report

**Status:** `[x]` done
**PLAN spec ref:** §3 C-4, REQUIREMENTS §CLI-1 through CLI-3, CLI-7
**Depends on:** A-1 ✅, A-4 ✅, A-5 ✅ (all done in codebase)

### Intent

Implement the three `toolfence` subcommands: `scan`, `run`, `report`. Each must exit 0 on
success and print sensible output. The CLI entry point already resolves (`toolfence --help`)
because `pyproject.toml` wires `toolfence.cli.main:main`. We are filling in the body.

No live network. No nanobot in the CLI. All three subcommands use only `engine/` and
`guard/` modules — never `integration/`.

### Files to create / modify

| File | Action |
|------|--------|
| `toolfence/cli/main.py` | Create — `scan`, `run`, `report` subcommands |
| `.env.example` | Create if absent — `OPENROUTER_API_KEY=` (placeholder only) |
| `tests/test_cli.py` | Create — 4 tests (scan exit 0, run exit 0, report exit 0, no-secrets grep) |

### Subcommand behaviour

**`toolfence scan <path>`**
- Calls `SurfaceScanner().scan_json(path)` (import from `toolfence.engine.surface`)
- Prints a markdown table of name / route / action_class / trust_label
- Exit 0

**`toolfence run --surface <path> [--output <dir>]`**
- Loads `SurfaceFile` from `--surface` path
- Loads probe files from `toolfence/engine/probes/` using `validate_probe_file`
- Builds `ScriptedAdapter` instances from matching fixture files in `fixtures/probes/`
  (one per probe template)
- Constructs `EvaluationRunner(attack_probes, normal_probes, DEFAULT_DEFENSES, surface_map)`
- Calls `runner.run(run_id)` where `run_id` is a timestamp string
- Writes each `TrialRecord` as JSON to `--output` dir (default: `results/`)
- Prints progress (one line per trial) and final summary line
- Exit 0

**`toolfence report <results-dir>`**
- Reads all `*.json` files from `<results-dir>` as `TrialRecord`
- Calls `aggregate(records, run_id)` then `render_report(summary)`
- Prints the rendered markdown to stdout
- Exit 0

### Test cases (in `tests/test_cli.py`)

1. `test_scan_exits_zero` — runs `toolfence scan fixtures/surface_fixture.json`; asserts exit 0 and tool name in stdout
2. `test_run_exits_zero` — runs `toolfence run --surface fixtures/surface_fixture.json --output <tmp_dir>`; asserts exit 0 and ≥1 `.json` file written
3. `test_report_exits_zero` — calls `toolfence report` on the tmp dir from test 2; asserts exit 0 and disclaimer in stdout
4. `test_no_api_key_in_tree` — greps committed source tree for pattern `_API_KEY\s*=\s*\S` (outside `.env.example`); asserts no matches

### Important constraints

- `cli/main.py` must NOT import `toolfence.integration` or `nanobot`
- `cli/main.py` may import from `toolfence.engine`, `toolfence.guard`, `toolfence.contracts`
- The `run` subcommand uses `ScriptedAdapter` only — do not wire `NanobotAdapter`
- The probe fixtures needed by `run` are:
  - `toolfence/engine/probes/cancel-user-input.json` + `fixtures/probes/fixture_user_input.json`
  - `toolfence/engine/probes/cancel-tool-result.json` + `fixtures/probes/fixture_tool_result.json`
  - Normal task probe dict + `fixtures/probes/normal_task.json`
  (Same pattern as `tests/test_runner.py::_make_runner()` — read that for the exact pairing)
- Exit codes: use `sys.exit(0)` on success; `sys.exit(1)` on any error with a descriptive message
- No `argparse` sub-parser complexity needed — `if len(sys.argv) < 2` + `sys.argv[1]` dispatch is fine

### Relevant context

```
toolfence/engine/surface.py          — SurfaceScanner
toolfence/engine/runner.py           — EvaluationRunner, DEFAULT_DEFENSES, DefenseConfig
toolfence/engine/scoring.py          — aggregate
toolfence/engine/report.py           — render_report
toolfence/engine/adapter.py          — ScriptedAdapter
toolfence/engine/probe.py            — validate_probe_file
toolfence/contracts/surface.py       — SurfaceFile
toolfence/contracts/trial.py         — TrialRecord
tests/test_runner.py                 — _make_runner() shows exact probe/adapter pairing
fixtures/probes/fixture_user_input.json
fixtures/probes/fixture_tool_result.json
fixtures/probes/normal_task.json
toolfence/engine/probes/cancel-user-input.json
toolfence/engine/probes/cancel-tool-result.json
```

### Done when

`pytest tests/test_cli.py` green (4 tests).
`toolfence scan fixtures/surface_fixture.json` prints a table with all 5 fixture tools.
`toolfence --help` still resolves cleanly.

---

## C-5: CI checks — surface-diff and Guard-wiring

**Status:** `[ ]` pending
**PLAN spec ref:** §3 C-5, REQUIREMENTS §CLI-4, CLI-5
**Depends on:** A-1 ✅ (surface scanner), B-3 ✅ (installer + verify_guard_invariant)

### Intent

Two callable Python functions that the GitHub Action invokes, plus the Action YAML itself.
These are CI safety checks — they return `(exit_code: int, message: str)` so the Action
can post a PR comment. No network, no nanobot at CI time.

### Files to create / modify

| File | Action |
|------|--------|
| `toolfence/cli/ci_checks.py` | Create — `surface_diff_check`, `guard_wiring_check` |
| `.github/workflows/toolfence-ci.yml` | Create — GitHub Action |
| `tests/test_ci.py` | Create — 4 tests per CLI-5 |

### Function signatures

```python
# toolfence/cli/ci_checks.py

def surface_diff_check(
    surface_path: str | Path,
    live_tool_list: list[dict],
) -> tuple[int, str]:
    """
    Compare committed surface_path against live_tool_list.
    Returns (0, "ok") if clean, (1, message) on any failure.

    Three failure types (CLI-5):
    1. Unknown tool  — a tool in live_tool_list is absent from surface_path
       Message must contain the tool name.
    2. Risen action class — a tool's action_class in surface_path is more
       permissive than the live suggestion (e.g. was "irreversible", live says
       "state-changing" — means the heuristic would downgrade it).
       Actually: surface says X, live heuristic says Y and Y > X in risk.
       Simplest: flag any tool whose live-suggested class != stored class.
       Message must contain the tool name.
    3. Changed description hash — description_sha256 in surface does not match
       current description. Use check_description_drift from engine/surface.py.
       Message must contain the tool name.
    """

def guard_wiring_check(registry: Any) -> tuple[int, str]:
    """
    Verify all tools in registry._tools are GuardedProxy instances.
    Wraps verify_guard_invariant; returns (0, "ok") or (1, error message).
    """
```

### GitHub Action (`toolfence-ci.yml`)

```yaml
# .github/workflows/toolfence-ci.yml
name: ToolFence CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: pytest tests/ --skip-network   # full suite, no network
      - run: toolfence ci-check --surface results/surface.json
        continue-on-error: true             # post comment even on failure
```

Note: `toolfence ci-check` is a new subcommand added to `cli/main.py` that calls
`surface_diff_check` against `results/surface.json` with a stub live list (JSON from stdin
or from a file arg). In CI, it reads the surface file and compares against itself
(no live network) — the hash-drift check still catches any hand-edited surface file.

### Test cases (in `tests/test_ci.py`)

All four tests use fixture data only — no network.

1. `test_surface_diff_unknown_tool` — surface has 1 tool; live list has 2 tools (one unknown); assert exit 1 and unknown tool name in message
2. `test_surface_diff_changed_hash` — surface has tool with hash X; live list has same tool with different description; assert exit 1 and tool name in message
3. `test_surface_diff_action_class_mismatch` — surface stores "read" for a tool that live heuristic suggests "state-changing"; assert exit 1 and tool name in message
4. `test_guard_wiring_check_bare_tool` — build a stub registry with one bare tool; call `guard_wiring_check`; assert exit 1 and tool name in message

(The reconnect simulation test — GRD-3 — is covered by `test_installer.py` already.)

### Important constraints

- `ci_checks.py` imports from `engine/surface.py` (`check_description_drift`, `get_action_class`, `suggest_action_class`) and `integration/installer.py` (`verify_guard_invariant`)
- `ci_checks.py` must NOT import nanobot
- The Action YAML's **first test step** must be `pytest tests/ --skip-network` (per spec CLI-5)
- `results/surface.json` may not exist yet (B-5 pending) — the `ci-check` step in the YAML has `continue-on-error: true`

### Relevant context

```
toolfence/engine/surface.py          — check_description_drift, suggest_action_class, get_action_class
toolfence/integration/installer.py  — verify_guard_invariant
toolfence/contracts/surface.py       — SurfaceFile
tests/test_surface.py                — pattern for loading surface fixture
```

### Done when

`pytest tests/test_ci.py` green (4 tests).
`toolfence-ci.yml` exists; its first step is `pytest tests/ --skip-network`.

---

## C-6: Dashboard

**Status:** `[ ]` pending
**PLAN spec ref:** §3 C-6, REQUIREMENTS §CLI-6, CLI-8
**Depends on:** A-4 ✅, A-5 ✅ (both done — `ResultSummary`, `TrialRecord`, `render_report` all exist)

### Intent

A read-only results dashboard served by `stdlib http.server`. No Flask, no FastAPI,
no model calls, no API key reads, no environment variable reads. Serves pre-committed
JSON from `results/` (or a fixture results dir for tests). The dashboard has:

1. A grid: verdict counts + percentages per channel × defense condition (`inconclusive` always its own column)
2. A trend section (can be a simple table or vanilla-JS chart)
3. A "Replay" button that steps through stored `TrialRecord` objects one by one

### Files to create / modify

| File | Action |
|------|--------|
| `toolfence/cli/dashboard/server.py` | Create — stdlib http.server |
| `toolfence/cli/dashboard/static/index.html` | Create — results grid + replay button |
| `toolfence/cli/dashboard/static/replay.js` | Create — replay logic (vanilla JS) |
| `tests/test_dashboard.py` | Create — Playwright test (skips if playwright not installed) |

### Server behaviour

- Listens on `localhost:8080` (configurable via `--port`)
- `GET /` → serves `static/index.html`
- `GET /static/<filename>` → serves `static/<filename>`
- `GET /api/results` → reads all `*.json` from `results/` (or `--results-dir` arg), returns JSON array of `TrialRecord` dicts
- `GET /api/summary` → calls `aggregate(records, run_id="dashboard")`, returns `ResultSummary.model_dump()`
- All data is pre-committed — no model calls, no network out
- Server does NOT read any environment variable

### Dashboard constraints (from AGENTS.md — these are hard)

- `inconclusive` verdicts must appear in their own column — never folded into other columns
- Replay button steps through stored `TrialRecord` objects — no live execution
- Playwright test is `pytest.importorskip("playwright")` — skips gracefully offline

### Test cases (in `tests/test_dashboard.py`)

```python
playwright = pytest.importorskip("playwright")

def test_dashboard_grid_loads(page):
    # Start server subprocess against fixtures results dir
    # Navigate to localhost:8080
    # Assert grid table has at least one row
    # Assert "inconclusive" column header present

def test_dashboard_replay(page):
    # Click replay button
    # Assert at least one trial record step displayed
    # Assert replay progress matches stored record count

def test_dashboard_no_outbound_requests(page):
    # Use playwright route intercept to catch any request not to localhost
    # Navigate and interact
    # Assert no outbound requests fired
```

### Important constraints

- `server.py` must use only `http.server`, `json`, `pathlib`, `argparse` from stdlib
- No `import os.environ` reads (no env var reads at all)
- `inconclusive` column must be separate in both the HTML table and the JS that builds it
- The Playwright `pytest.importorskip("playwright")` call must be at the top of the test module (not inside a test function) so pytest can collect/skip cleanly

### Relevant context

```
toolfence/contracts/trial.py         — TrialRecord (shape of each JSON in results/)
toolfence/engine/scoring.py          — aggregate, ResultSummary
toolfence/engine/report.py           — DISCLAIMER (re-export for display)
fixtures/probes/fixture_user_input.json  — example TrialRecord-shaped fixture for testing
tests/test_runner.py                 — EvaluationRunner.run() produces TrialRecords with all fields
```

### Done when

`pytest tests/test_dashboard.py` green (or skipped if Playwright not installed).
Dashboard renders grid and trend from `results/` fixture; replay completes;
`inconclusive` column present; no outbound calls.
`toolfence --help` still shows a `serve` (or `dashboard`) subcommand.

---

## C-7: IBM Cloud deploy

**Status:** `[ ]` pending
**PLAN spec ref:** §3 C-7, REQUIREMENTS §CLI-8
**Depends on:** C-6 ✅ (dashboard server must work locally first)

### Intent

Documented, repeatable IBM Cloud Code Engine deploy of the dashboard. No API key on the
server. The deploy is a single `ibmcloud ce` command documented in `docs/deploy.md`.
A smoke test confirms the deployed dashboard is reachable (skippable offline with
`--skip-network`).

### Files to create / modify

| File | Action |
|------|--------|
| `docs/deploy.md` | Create — `ibmcloud ce` commands + explicit note: `OPENROUTER_API_KEY` must NOT be set |
| `tests/test_deploy_smoke.py` | Create — smoke test, skips with `--skip-network` |

### deploy.md contents (required sections)

1. **Prerequisites**: `ibmcloud` CLI installed, Code Engine plugin installed, logged in
2. **Build and push** (if using container image): `ibmcloud ce build` command, or note that the app uses `python -m toolfence serve` as its start command
3. **Create the app**: `ibmcloud ce application create --name toolfence-dashboard ...`
   - `--env` must NOT include `OPENROUTER_API_KEY`
   - `--port 8080`
   - `--min-scale 0` (serverless, cost-effective)
4. **Update the app**: `ibmcloud ce application update ...` (same constraints)
5. **Explicit warning box**: `> IMPORTANT: Do NOT set OPENROUTER_API_KEY or any secret in the Code Engine application. The dashboard serves only pre-committed JSON from results/ — no model calls are made at runtime.`
6. **Smoke test command**: `pytest tests/test_deploy_smoke.py`

### Test cases (in `tests/test_deploy_smoke.py`)

```python
def test_smoke_dashboard_reachable(skip_network):
    # Skip if --skip-network
    # GET the deployed URL (from env var TOOLFENCE_DEPLOY_URL)
    # Assert status 200 and "inconclusive" in response body

def test_smoke_no_api_key_in_server_env(skip_network):
    # GET /api/env-check endpoint (a safe endpoint that lists env var names but
    # NOT values) — or simply confirm OPENROUTER_API_KEY not in server config
    # by asserting the deploy.md text explicitly forbids it
    # This test reads docs/deploy.md and asserts the warning text is present
    pass
```

Note: `test_smoke_dashboard_reachable` requires `TOOLFENCE_DEPLOY_URL` env var.
If absent, skip. The second smoke test runs offline (reads docs/deploy.md).

### Important constraints

- `docs/deploy.md` must contain the word `OPENROUTER_API_KEY` in a `must NOT` context
- `pytest tests/test_deploy_smoke.py --skip-network` must exit 0 (all tests skipped or passed)
- No secret must appear outside `.env.example` in the committed tree (already verified by C-4)

### Relevant context

```
docs/setup.md                        — existing setup doc pattern to follow
toolfence/cli/dashboard/server.py    — the server being deployed (from C-6)
.env.example                         — exists after C-4
tests/conftest.py                    — --skip-network flag already registered
```

### Done when

`pytest tests/test_deploy_smoke.py --skip-network` exits 0.
`docs/deploy.md` contains the no-API-key warning.
`ibmcloud ce application create` command is present and documented.

---

## Summary: what a Bob session needs before starting

Every session should:

1. Read this file (`docs/track-c-sessions-plan.md`) fully
2. Read `docs/IMPLEMENTATION_PLAN.md` §3 for the task's spec entry
3. Read the "Relevant context" files listed for that task
4. Run `pytest tests/test_guard_core.py tests/test_proxy.py tests/test_confirm.py tests/test_installer.py -q` to confirm the existing baseline is green before touching anything
5. Implement the task
6. Run only the task's own test file (e.g. `pytest tests/test_cli.py -v`)
7. Run the full test suite with `pytest --skip-network -q` to confirm no regressions
8. Commit with message format: `feat(cli): C-4 — scan/run/report subcommands`

## Test commands per session

| Session | Test command to run at end |
|---------|---------------------------|
| C-4 | `pytest tests/test_cli.py -v` |
| C-5 | `pytest tests/test_ci.py -v` |
| C-6 | `pytest tests/test_dashboard.py -v` (skips if no Playwright) |
| C-7 | `pytest tests/test_deploy_smoke.py --skip-network -v` |

Full regression after each: `pytest --skip-network -q`

## Known skipped / deferred tests

The following test files exist but their target code is not yet implemented —
they will **fail** until the responsible developer ships the code.
Do NOT attempt to fix them in Track C sessions:

| Test file | Responsible | Status |
|-----------|-------------|--------|
| `tests/test_runner.py` | Track A (A-5) | ✅ A-5 done — should pass |
| `tests/test_verdict.py` | Track A (A-4) | ✅ A-4 done — should pass |
| `tests/test_surface.py` | Track A (A-1) | ✅ A-1 done — should pass |
| `tests/test_findings.py` | Track A (A-6) | 🔴 A-6 not done — will fail (`engine/findings.py` exists but `findings.json` and PG-8 fixtures needed) |
| `tests/test_galaxium_patches.py` | Track B | 🟡 Fails on `git apply` (path-strip issue) — Track B fix needed |
| `tests/test_installer.py` | Track B (B-3) | ✅ B-3 done — should pass |
| `tests/test_placeholder.py` | All | 🟡 Contains placeholder; passes by design |
| `tests/test_integration.py` | Track B (B-4b) | 🔴 B-4b not done — `channel_adapter.py` not yet written |
| `tests/test_nanobot_adapter.py` | Track B (B-4) | 🔴 B-4 not done — `nanobot_adapter.py` not yet written |
| `tests/test_surface_baseline.py` | Track B (B-5) | 🔴 B-5 not done — `results/surface.json` not committed |
| `tests/test_bob.py` | Track B (B-6a/b) | 🔴 B-6 not done |

## Task status tracker

| Task | Status | Session commit |
|------|--------|----------------|
| C-1 Guard core | ✅ done | committed |
| C-2 GuardedProxy + card | ✅ done | committed |
| C-3 Confirm flow | ✅ done | committed |
| C-1/C-2/C-3 correctness fixes | ✅ done | committed |
| C-4 CLI | ✅ done | `feat(cli): C-4 — scan/run/report subcommands` |
| C-5 CI checks | `[ ]` pending | — |
| C-6 Dashboard | `[ ]` pending | — |
| C-7 Deploy | `[ ]` pending | — |
