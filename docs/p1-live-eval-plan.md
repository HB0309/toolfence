# P-1 Live Evaluation Plan

## Overview

Run the ToolFence evaluation matrix against the real Granite model using
`NanobotAdapter` as the live adapter.  Produce two result sets, each with Guard
off and Guard on rows within the same run:

- `results/full/` — all Galaxium tools exposed to the agent (`config/nanobot.eval.full.json`)
- `results/narrowed/` — PG-6 traveller-safe 9-tool set (`config/nanobot.eval.json`)

The runs differ by `--config` (which controls `enabledTools` in the nanobot
config and therefore which tools the agent can reach).  `--surface` is always
`results/surface.json`; it feeds Guard only and stays fixed.

Also run the PG-8 gate (10 normal tasks with Guard on from the narrowed config)
and record results in `docs/notes/guard-gate-results.md`.

**Scope constraints**

- No changes inside `nanobot/` or `targets/`.
- API key comes only from `OPENROUTER_API_KEY` in the environment.
- Traces are written exactly as returned; they are never edited or fabricated.
  If nothing leaks, report that.
- `booking.db` is backed up before each live trial and restored after using
  `sqlite3.backup()` — Galaxium keeps the DB open, so file-copy is not safe.
- Smoke output (`results/full-smoke/`) is local only; it is not committed.

**Trial budget**

Each trial is one full agent loop.  A trial is the unit to minimise.

| Run | Trials | Notes |
|---|---|---|
| Smoke (single trial) | 1 | `--probe cancel-user-input-001 --defense none --guard off` |
| Full | 18 | 2 probes × 6 defenses + 1 normal × 6 defenses |
| Narrowed | 18 | same matrix, narrowed config |
| PG-8 gate | 10 | normal task × 10, guard on |
| **Total** | **47** | |

---

## Sub-tasks

### P1-1 — Fix `run_normal` to honour `adapter_factory`

**Status:** `[x] done`

**Intent**

[`runner.py:337`](../toolfence/engine/runner.py) always calls `adapter.run_turn(...)` —
the adapter stored in the probe tuple — regardless of whether
`self._adapter_factory` is set.  Live normal trials therefore always replay the
fixture recording instead of calling the model.  `run_attack` (lines 265–272)
already has the correct factory branch; mirror it into `run_normal`.

The factory receives `channel="normal"` for normal trials (so the `NanobotAdapter`
closure can distinguish them from attack trials and pass `canary=None`,
`review_body=None`).

**Expected Outcomes**

- When `adapter_factory` is `None`, `run_normal` is unchanged.
- When set, each normal trial calls
  `self._adapter_factory(defense, "normal", prompt)` and uses the returned
  adapter's `run_turn`.
- The two existing factory tests in [`tests/test_runner.py`](../tests/test_runner.py)
  still pass.
- One new test `test_runner_factory_used_in_run_normal` confirms the factory is
  called for normal trials when set and not called when absent.

**Todo List**

1. Read [`runner.py:302–358`](../toolfence/engine/runner.py) to confirm there
   are no other branches in `run_normal`.
2. After `trace = adapter.run_turn(prompt, defense.name)` at line 337, add the
   same `if self._adapter_factory is not None` branch used in `run_attack`,
   passing `channel="normal"` and `probe_text=prompt`.
3. Add `test_runner_factory_used_in_run_normal` to `tests/test_runner.py`.
4. Run `pytest tests/test_runner.py` — must be green.

**Relevant Context**

- `run_attack` factory branch: [`runner.py:265–272`](../toolfence/engine/runner.py)
- `run_normal` loop: [`runner.py:329–356`](../toolfence/engine/runner.py)
- Existing factory tests: [`test_runner.py:456–557`](../tests/test_runner.py)

---

### P1-2 — Fix `cards_shown` to count held calls from the trace

**Status:** `[x] done`

**Intent**

`cards_shown` is hardcoded to `0` in both [`runner.py:292`](../toolfence/engine/runner.py)
(attack records) and [`runner.py:354`](../toolfence/engine/runner.py) (normal
records).  For live runs, Guard actually holds calls and that count should be
recorded.  The information is already in the trace: count the `TraceEntry`
objects whose `guard_decision == "hold"`.

`TraceEntry.guard_decision` is `Literal["pass", "hold"]`
([`contracts/trace.py:38`](../toolfence/contracts/trace.py)), so the count is:

```python
sum(1 for c in trace.tool_calls if c.guard_decision == "hold")
```

**Expected Outcomes**

- Both `TrialRecord` construction sites in `runner.py` compute `cards_shown`
  from the trace rather than hard-coding `0`.
- The scripted-adapter tests still pass because `fixture_user_input.json` etc.
  already have `guard_decision` fields on every `tool_call` entry.
- One new test asserts that a trace with two held calls produces `cards_shown=2`.

**Todo List**

1. Add a helper `_count_held(trace: Trace) -> int` in `runner.py` (one line).
2. Replace `cards_shown=0` at line 292 with `cards_shown=_count_held(trace)`.
3. Replace `cards_shown=0` at line 354 with `cards_shown=_count_held(trace)`.
4. Add the assertion test to `tests/test_runner.py`.
5. Run `pytest tests/test_runner.py`.

**Relevant Context**

- `TraceEntry.guard_decision`: [`contracts/trace.py:38`](../toolfence/contracts/trace.py)
- Both hardcoded `0` sites: [`runner.py:292`](../toolfence/engine/runner.py) and
  [`runner.py:354`](../toolfence/engine/runner.py)

---

### P1-3 — Add `--live`, `--config`, `--probe`, `--defense`, `--guard` flags to `toolfence run`

**Status:** `[x] done`

**Intent**

Add five new flags to `toolfence run` in
[`toolfence/cli/main.py`](../toolfence/cli/main.py):

**`--live`** (store_true) — switches from the scripted adapter to
`NanobotAdapter`.  When absent, behaviour is unchanged.  Requires
`OPENROUTER_API_KEY` in the environment; exit 1 with a clear message before any
model calls if it is missing.

**`--config PATH`** (default `config/nanobot.eval.json`) — path to the nanobot
JSON config.  Passed as `config_path` to every `NanobotAdapter` instance.  This
is the only thing that differs between the full and narrowed runs.

**`--probe PROBE_ID|normal`** (optional) — when set to a probe ID (e.g.
`cancel-user-input-001`), restricts attack trials to that probe and skips all
normal trials.  When set to the literal value `"normal"`, skips all attack trials
and runs only normal trials.  Omitting `--probe` runs both attack and normal
trials.  The `--defense` and `--guard` filters still apply within whichever set
runs.

The smoke command `--probe cancel-user-input-001 --defense none --guard off`
matches exactly 1 attack trial (1 probe × 1 defense row) and 0 normal trials
= **1 total trial**.

**`--defense DEFENSE_NAME`** (optional) — restricts both attack and normal trials
to rows where `DefenseConfig.name` matches (`"none"`, `"datamarking"`, or
`"instructional"`).

**`--guard on|off`** (optional) — restricts both attack and normal trials to rows
where `DefenseConfig.guard_on` is `True` (`on`) or `False` (`off`).

Print a warning and exit 0 if all filters together produce zero trials.

**Expected Outcomes**

- `toolfence run --surface ...` with no new flags: identical to today.
- Smoke command `--probe cancel-user-input-001 --defense none --guard off` is
  exactly 1 trial (0 normal trials).
- `--probe normal` runs only normal trials; attack trials are skipped.
- `--config` is forwarded into the `NanobotAdapter` factory (via `live_factory`).
- `--guard on` restricts to `guard_on=True` rows; `--guard off` to `guard_on=False`.
- New CLI tests in `tests/test_cli.py` cover: factory wired when `--live`, filter
  logic for `--probe`, `--probe normal`, `--defense`, `--guard`.

**Todo List**

1. Add `--live`, `--config`, `--probe`, `--defense`, `--guard` to `run_p` in
   `main.py`.
2. Update `main()` dispatch to pass all five to `_cmd_run`.
3. In `_cmd_run`:
   a. If `live=True`, call `make_live_factory` from
      `toolfence.integration.live_factory` (P1-5) to get the adapter factory
      and run the Galaxium health check before building the runner.
   b. If `--probe` is a probe ID: filter `attack_probes` to that ID, set
      `normal_probes = []`.
   c. If `--probe normal`: set `attack_probes = []`, leave `normal_probes` unchanged.
   d. Apply `--defense` filter to `defenses` list.
   e. Apply `--guard` filter to `defenses` list.
   f. Warn and exit 0 if nothing is left to run.
4. Add CLI tests.
5. Run `pytest tests/test_cli.py`.

**Relevant Context**

- Current `_cmd_run`: [`cli/main.py:136–234`](../toolfence/cli/main.py)
- `NanobotAdapter.__init__` signature:
  [`nanobot_adapter.py:420–443`](../toolfence/integration/nanobot_adapter.py)
- `DefenseConfig` fields: [`runner.py:59–76`](../toolfence/engine/runner.py)
- `DEFAULT_DEFENSES` matrix: [`runner.py:80–87`](../toolfence/engine/runner.py)

---

### P1-4 — Create `config/nanobot.eval.full.json`

**Status:** `[x] done`

**Intent**

`config/nanobot.eval.json` already has `enabledTools` set to the explicit 9-tool
traveller set.  The full run needs all Galaxium tools exposed to the agent.

The nanobot config schema (`targets/nanobot/nanobot/config/schema.py:375`)
defines the default value of `enabledTools` as `["*"]`, which enables all tools
from that MCP server.  The full config is therefore identical to `nanobot.eval.json`
except `enabledTools` is set to `["*"]` — no enumeration of individual tool names
required.

**Expected Outcomes**

- `config/nanobot.eval.full.json` exists and is valid JSON.
- Its `mcpServers.galaxium.enabledTools` value is exactly `["*"]`.
- It has the same model, provider, and timeout settings as `nanobot.eval.json`.
- A test asserts that `nanobot.eval.full.json` parses as valid JSON and that
  `enabledTools` is `["*"]`.

**Todo List**

1. Copy `config/nanobot.eval.json` to `config/nanobot.eval.full.json`.
2. Replace the `enabledTools` array with `["*"]`.
3. Add a test that loads the file and asserts `enabledTools == ["*"]`.
4. Run `pytest` to confirm green.

**Relevant Context**

- Existing narrowed config: [`config/nanobot.eval.json`](../config/nanobot.eval.json)
  — 9 explicit tool names in `enabledTools`
- Nanobot schema default: `targets/nanobot/nanobot/config/schema.py:375`
  — default `enabledTools` is `["*"]`
- AGENTS.md note: "nanobot config is JSON, not YAML; model and provider are under
  `agents.defaults`"

---

### P1-5 — Create `toolfence/integration/live_factory.py`

**Status:** `[x] done`

**Intent**

The live adapter factory has three responsibilities that are needed in two places
(the CLI and `scripts/run_pg8_gate.py`): the Galaxium health check, the
`booking.db` backup/restore, and constructing `NanobotAdapter` with the right
settings for the current trial.  Putting all three in
`toolfence/integration/live_factory.py` keeps them reusable and testable without
duplicating logic.

**Module: `toolfence/integration/live_factory.py`**

Public surface:

```python
def check_galaxium_health(url: str = "http://localhost:8001/") -> None:
    """Raise RuntimeError if the Galaxium backend is not reachable."""

def make_live_factory(
    config_path: str,
    surface_path: str,
    run_id: str,
    db_path: str = "targets/galaxium/booking_system_backend/booking.db",
) -> Callable[[DefenseConfig, str, str], AgentAdapter]:
    """Return a factory that the runner calls once per trial.

    The returned factory:
    1. Reads guard_on and datamark_on from the DefenseConfig argument.
    2. Constructs a NanobotAdapter with those settings plus channel/review_body
       derived from the channel argument.
    3. Wraps it in _DbBackupAdapter so booking.db is restored after every trial.
    """
```

**`_DbBackupAdapter` inner class** (not exported):

- `__init__(self, inner: AgentAdapter, db_path: str)`
- `run_turn(prompt, defense)`: before calling `inner.run_turn`, open a
  `sqlite3.connect(db_path)` connection to the source and a second connection to
  `db_path + ".bak"`, call `src.backup(dst)`, close both.  In a `finally` block,
  restore with `sqlite3.connect(db_path + ".bak").backup(sqlite3.connect(db_path))`.
  This is safe even when Galaxium holds the DB open.

**`check_galaxium_health`** uses `urllib.request.urlopen` (stdlib only — no new
dependency).  Raises `RuntimeError` with a clear message on any exception or
non-2xx status so callers can print and exit.

**Guard setting**: the factory reads `defense.guard_on` and `defense.datamark_on`
directly from the `DefenseConfig` passed by the runner.  The caller (`_cmd_run`,
`run_pg8_gate.py`) does not need to specify Guard settings separately.

**Expected Outcomes**

- `live_factory.py` is importable from both `toolfence/cli/main.py` and
  `scripts/run_pg8_gate.py`.
- The DB is in its pre-trial state after every trial regardless of verdict.
- `check_galaxium_health` raises before any trial starts if the backend is down.
- Tests in `tests/test_live_factory.py`:
  - `check_galaxium_health` raises on connection error and on non-2xx.
  - `_DbBackupAdapter.run_turn` calls `sqlite3.backup()` and restores in `finally`
    even when `inner.run_turn` raises (mock both `sqlite3` and the inner adapter).
  - `make_live_factory` returns a callable that produces an `AgentAdapter` and
    sets `guard_on` / `datamark_on` from the `DefenseConfig`.
- No changes to `runner.py`, `guard/`, or `cli/main.py` beyond importing and
  calling `make_live_factory` / `check_galaxium_health`.

**Todo List**

1. Write `toolfence/integration/live_factory.py` with `check_galaxium_health`,
   `_DbBackupAdapter`, and `make_live_factory`.
2. In `_cmd_run` (`cli/main.py`), when `live=True`:
   a. Call `check_galaxium_health()` — print the `RuntimeError` message and
      `sys.exit(1)` if it raises.
   b. Call `make_live_factory(config_path, surface_path, run_id)` to get the
      factory; pass it as `adapter_factory=` to `EvaluationRunner`.
3. In `scripts/run_pg8_gate.py` (P1-9), import and call the same two functions.
4. Write `tests/test_live_factory.py` with the three test groups above.
5. Run `pytest tests/test_live_factory.py` and `pytest tests/test_cli.py`.

**Relevant Context**

- `NanobotAdapter.__init__` signature:
  [`nanobot_adapter.py:420–443`](../toolfence/integration/nanobot_adapter.py)
- `AgentAdapter` Protocol: [`engine/adapter.py:23–32`](../toolfence/engine/adapter.py)
- `sqlite3.backup()` docs: stdlib, Python 3.7+; signature
  `src_conn.backup(dst_conn)` — works while other connections hold the DB open.
- Health endpoint: `GET http://localhost:8001/` — strip `/mcp` from the URL in
  `nanobot.eval.json`.

---

### P1-6 — Add `--live`, `--config`, `--probe`, `--defense`, `--guard` flags to CLI

**Status:** `[x] done`

*(This sub-task was previously P1-3 in the ordering.  Renumbered here because
P1-5 now defines `live_factory.py` which P1-6 imports.)*

See P1-3 Intent, Expected Outcomes, and Todo List above — no content change,
only the dependency note that step 3a now calls `make_live_factory` and
`check_galaxium_health` from `toolfence.integration.live_factory` (P1-5) rather
than inlining that logic.

---

### P1-7 — Run full (all tools, Guard off + Guard on)

**Status:** `[ ] pending`

**Intent**

Execute the first live run using the full-tool config.  Records go to
`results/full/`.  The run uses `DEFAULT_DEFENSES` (all 6 rows), so it produces
guard-off and guard-on rows in the same output folder.  This gives a baseline
leak rate across all tools.

**Trial count:** 18 (12 attack + 6 normal).

**Smoke command first (1 trial — output is local only, not committed):**

```powershell
toolfence run `
  --surface results/surface.json `
  --config config/nanobot.eval.full.json `
  --live `
  --probe cancel-user-input-001 --defense none --guard off `
  --output results/full-smoke
```

Inspect the single record, then delete `results/full-smoke/` before proceeding.

**Full command:**

```powershell
toolfence run `
  --surface results/surface.json `
  --config config/nanobot.eval.full.json `
  --live `
  --output results/full
```

**Expected Outcomes**

- `results/full/` contains 18 valid `TrialRecord` JSON files.
- Verdicts are whatever the model produces; not edited.
- `results/full-smoke/` is deleted after inspection; it is not committed.
- `toolfence report results/full` prints the aggregate.

**Todo List**

1. Confirm prerequisites: `OPENROUTER_API_KEY` set, `config/nanobot.eval.full.json`
   exists (P1-4 done), Galaxium backend up, `booking.db` accessible.
2. Run the smoke command; inspect the single record for schema validity.
3. Delete `results/full-smoke/`.
4. Run the full command.
5. Run `toolfence report results/full > docs/notes/full-report.md`.

**Note — run-20261015 discarded:** The first full run (run-20261015) was
discarded because 12 of 18 trials stalled at an empty-email user-lookup
(the model called the lookup tool with no email, received a 422, and asked
for Alice's email instead of proceeding).  Root cause: neither the normal
probe nor the attack probe carried Alice's identity.  Fixed before any
measured run by prepending `"I'm Alice (alice@example.com)."` to
`NORMAL_TASK_PROMPT` in `toolfence/engine/runner.py` (imported by
`toolfence/cli/main.py`) and to the `content` field of
`toolfence/engine/probes/cancel-user-input.json`.  No result files from
run-20261015 are committed.  P1-9's `run_pg8_gate.py` must import
`NORMAL_TASK_PROMPT` from `toolfence.engine.runner` and use it as the
normal probe content.

---

### P1-8 — Run narrowed (9-tool traveller set, Guard off + Guard on)

**Status:** `[ ] pending`

**Intent**

Repeat the eval matrix using the narrowed nanobot config (`nanobot.eval.json`,
the existing 9-tool `enabledTools` list).  `--surface` remains
`results/surface.json` — only the agent-visible tool set shrinks.  Guard off and
Guard on rows are again in the same output folder.

**Trial count:** 18.

**Command:**

```powershell
toolfence run `
  --surface results/surface.json `
  --config config/nanobot.eval.json `
  --live `
  --output results/narrowed
```

**Expected Outcomes**

- `results/narrowed/` contains 18 valid records.
- `toolfence report results/narrowed` saved to `docs/notes/narrowed-report.md`.

**Todo List**

1. Run the command (P1-7 smoke must have succeeded first).
2. Run `toolfence report results/narrowed > docs/notes/narrowed-report.md`.

---

### P1-9 — PG-8 gate: 10 normal tasks with Guard on

**Status:** `[ ] pending`

**Intent**

PG-8 requires Guard to not break normal task completion.  Run 10 independent
normal-task trials with Guard on from the narrowed config.  At least 8 must
satisfy the four-condition pass rule in
[`evaluate_normal_trial`](../toolfence/engine/normal_success.py).

The simplest implementation is a small standalone script
`scripts/run_pg8_gate.py`.  It imports `make_live_factory` and
`check_galaxium_health` from `toolfence.integration.live_factory` (P1-5),
constructs an `EvaluationRunner` with 10 copies of the normal probe and a single
`DefenseConfig("none", guard_on=True, datamark_on=False)`, runs it, and writes
the results table.  Guard is wired via the `DefenseConfig` — the factory reads
`defense.guard_on` directly, so no Guard setting is passed separately.

**Trial count:** 10.

**Expected Outcomes**

- `docs/notes/guard-gate-results.md` records:
  - Run ID and timestamp.
  - Pass count / 10 and PASS / FAIL (≥ 8 = PASS).
  - Per-trial `trial_id` and `task_success`.
  - Honest note on any `inconclusive` trial.
- If fewer than 8 pass, the note explains the cause and the gate is FAILED.

**Todo List**

1. Write `scripts/run_pg8_gate.py`:
   - Calls `check_galaxium_health()` first; prints error and exits 1 if it raises.
   - Calls `make_live_factory("config/nanobot.eval.json", "results/surface.json",
     run_id)` to obtain the factory.
   - Passes 10 copies of the normal probe dict and `adapter_factory=factory` to
     a single `EvaluationRunner` instance with
     `defenses=[DefenseConfig("none", guard_on=True, datamark_on=False)]`.
   - Runs `runner.run_normal(run_id)`, collects the 10 records.
   - Prints and writes the results table to `docs/notes/guard-gate-results.md`.
2. Run the script.
3. Verify the markdown file.

**Relevant Context**

- `make_live_factory` / `check_galaxium_health`:
  [`integration/live_factory.py`](../toolfence/integration/live_factory.py) (P1-5)
- Four-condition pass rule:
  [`normal_success.py:34–67`](../toolfence/engine/normal_success.py)
- Default goal tool: `mcp_galaxium_create_hold_quotes_quote_id_holds_post`
  ([`normal_success.py:31`](../toolfence/engine/normal_success.py))

---

### P1-10 — Render and commit all reports

**Status:** `[x] done`

**Intent**

Generate markdown reports for both runs and the gate, commit all result and
report files, and mark P-1 complete in `docs/IMPLEMENTATION_PLAN.md`.

**Expected Outcomes**

- `docs/notes/full-report.md` — from `results/full/`
- `docs/notes/narrowed-report.md` — from `results/narrowed/`
- `docs/notes/guard-gate-results.md` — written by P1-9
- All result JSON files, config, and reports committed on branch `P1-live-eval`.

**Todo List**

1. `toolfence report results/full > docs/notes/full-report.md`
2. `toolfence report results/narrowed > docs/notes/narrowed-report.md`
3. Verify `docs/notes/guard-gate-results.md` was written by P1-9.
4. Commit everything: `results/full/`, `results/narrowed/`, all reports,
   `config/nanobot.eval.full.json`.
5. Mark P-1 done in `docs/IMPLEMENTATION_PLAN.md`.

---

## Files Changed

| File | Change |
|---|---|
| `toolfence/engine/runner.py` | P1-1: `adapter_factory` branch in `run_normal`; P1-2: `cards_shown` from trace |
| `toolfence/cli/main.py` | P1-3/P1-6: `--live`, `--config`, `--probe`, `--defense`, `--guard`; calls `live_factory` |
| `toolfence/integration/live_factory.py` | P1-5: new file — health check, DB backup/restore, `make_live_factory` |
| `config/nanobot.eval.full.json` | P1-4: new file — `enabledTools: ["*"]` config |
| `scripts/run_pg8_gate.py` | P1-9: PG-8 gate runner; imports `live_factory` |
| `tests/test_runner.py` | P1-1: factory in `run_normal`; P1-2: `cards_shown` assertion |
| `tests/test_live_factory.py` | P1-5: health-check, DB backup/restore, factory tests |
| `tests/test_cli.py` | P1-3/P1-6: filter tests; `--live` wiring test |
| `docs/notes/full-report.md` | P1-10: committed report |
| `docs/notes/narrowed-report.md` | P1-10: committed report |
| `docs/notes/guard-gate-results.md` | P1-9/P1-10: gate table |

**Files NOT changed:** anything inside `nanobot/`, `targets/nanobot/`,
`targets/galaxium/` source, `.env`.

**Not committed:** `results/full-smoke/` (local smoke-test scratch folder).

---

## Commands Reference

```powershell
# Set API key
$env:OPENROUTER_API_KEY = "<key>"

# Smoke trial (1 trial — local only, delete output after)
toolfence run --surface results/surface.json `
  --config config/nanobot.eval.full.json --live `
  --probe cancel-user-input-001 --defense none --guard off `
  --output results/full-smoke
# Inspect record, then: Remove-Item -Recurse results/full-smoke

# Full run (18 trials)
toolfence run --surface results/surface.json `
  --config config/nanobot.eval.full.json --live `
  --output results/full

# Narrowed run (18 trials)
toolfence run --surface results/surface.json `
  --config config/nanobot.eval.json --live `
  --output results/narrowed

# PG-8 gate (10 trials)
python scripts/run_pg8_gate.py

# Reports
toolfence report results/full > docs/notes/full-report.md
toolfence report results/narrowed > docs/notes/narrowed-report.md

# Full test suite (must stay green after every code change)
pytest
```

---

## Ordering Constraints

```
P1-1 (run_normal factory fix)    ─┐
P1-2 (cards_shown fix)            ├─ independent; implement together
P1-4 (full config)                ┘
         │
         ▼
P1-5 (live_factory.py: health check + DB backup + factory)
         │
         ▼
P1-3/P1-6 (CLI flags — imports live_factory) ──────────────────► P1-7 full run
P1-9 (run_pg8_gate.py — imports live_factory) ─────────────────► P1-10 reports
P1-7 (full run smoke must pass) ──────────────────────────────► P1-8 narrowed run
P1-8 (narrowed run) ──────────────────────────────────────────► P1-10 reports
P1-10 (reports + commit)
```
