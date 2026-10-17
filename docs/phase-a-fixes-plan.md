# Phase A Fixes Plan

## Overview

Three targeted fixes to complete Phase A of the target-profile work. Fix 1
(`prefix_ok` in `nanobot_adapter.py`) is already done. This plan covers:

- **Fix 2** — extract probe-stamping logic into a helper; add tests for
  profile-level `tool_result_task_prompt` and per-probe override.
- **Fix 3** — `--target` without `--live` must fail immediately with a usage
  error (non-zero exit).
- **Fix 4** — replace the `rstrip('s') + "_id"` heuristic with an explicit
  `id_column` field on `SqliteReviewInjection`; update `galaxium.json`; regenerate schemas.

No Phase B work.

---

## Sub-Task 1 — Fix 2: Extract probe-stamping helper and add tests

**Status:** `[ ] pending`

### Intent

The probe-stamping block (lines 289–301 of [`toolfence/cli/main.py`](../toolfence/cli/main.py:289))
determines the effective `task_prompt` for tool-result probes: per-probe override wins,
then profile-level `tool_result_task_prompt`. Extracting it into a small named
function makes it independently testable.

### Expected Outcomes

- A new function `_apply_task_prompt(probe_dict, profile, task_prompt_override)` in
  [`toolfence/cli/main.py`](../toolfence/cli/main.py) replaces the inline block.
- Two new tests in [`tests/test_target_profile.py`](../tests/test_target_profile.py):
  1. Profile-level `tool_result_task_prompt` is stamped onto a tool-result probe when
     no per-probe override is set — using a prompt that differs from
     `TOOL_RESULT_TASK_PROMPT`.
  2. A per-probe `task_prompt` override wins over the profile-level prompt.

### Todo List

1. Read lines 289–307 of `toolfence/cli/main.py` to confirm exact scope of the block.
2. Extract the block into `_apply_task_prompt(probe_dict, profile, task_prompt_override)` 
   at module level (above `_cmd_run`). It takes the raw probe dict, the profile object,
   and the optional per-probe override string; it returns the (possibly mutated) dict.
3. Replace the inline block in `_cmd_run` with a call to `_apply_task_prompt`.
4. Add to `tests/test_target_profile.py`:
   - `test_apply_task_prompt_uses_profile_level()` — import the helper, build a
     minimal tool-result probe dict (with `"channel": "tool-result"`), profile with a
     custom `tool_result_task_prompt`, no override; assert the dict gets that prompt.
   - `test_apply_task_prompt_override_wins()` — same setup but pass a per-probe
     override string; assert the override ends up in the dict.

### Relevant Context

- Probe-stamping block: [`toolfence/cli/main.py`](../toolfence/cli/main.py:289)
- Profile model: [`toolfence/contracts/profile.py`](../toolfence/contracts/profile.py:179)
- Existing test module: [`tests/test_target_profile.py`](../tests/test_target_profile.py)
- `_MINIMAL_PROFILE` helper dict in the test file is reusable as a base.

---

## Sub-Task 2 — Fix 3: `--target` without `--live` must fail

**Status:** `[ ] pending`

### Intent

Currently `--target` without `--live` silently loads the profile and continues with
scripted adapters. The intent is to make `--target` a live-only flag: if a user passes
`--target` without `--live` they get a clear usage error and non-zero exit immediately.

### Expected Outcomes

- In `_cmd_run`, immediately after the profile is loaded (around line 208), add a guard:
  if `profile is not None and not live`, print a usage error to stderr and `sys.exit(1)`.
- One new test in [`tests/test_target_profile.py`](../tests/test_target_profile.py) (or a
  new test file `tests/test_cli_run.py`) that invokes the CLI via `subprocess` (or
  `click.testing.CliRunner` / `argparse` directly) and asserts:
  - Exit code is non-zero.
  - Stderr contains a message indicating `--target` requires `--live`.

### Todo List

1. Locate the exact line after profile load in `_cmd_run` (around line 208).
2. Insert the guard block: `if profile is not None and not live: print(...); sys.exit(1)`.
3. Decide test approach: using `subprocess.run(["python", "-m", "toolfence", "run", ...])` is
   simplest — no extra test deps. Alternatively import `main` and mock `sys.argv`.
4. Add `test_target_without_live_fails()` in `tests/test_target_profile.py` — call the CLI
   with `--target profiles/galaxium.json --surface results/surface.json` (no `--live`),
   assert exit code != 0 and stderr contains guidance text.

### Relevant Context

- Guard insertion point: [`toolfence/cli/main.py`](../toolfence/cli/main.py:208)
- CLI entry: [`toolfence/cli/main.py`](../toolfence/cli/main.py:37) — `main()` calls `_cmd_run`.

---

## Sub-Task 3 — Fix 4: `id_column` field replaces the `rstrip('s')` heuristic

**Status:** `[ ] pending`

### Intent

`nanobot_adapter.py` line 581 derives the PK column name with
`f"{inj_table.rstrip('s')}_id"`. This breaks for any table whose name doesn't
follow that convention. Replacing it with an explicit `id_column: str` field on
`SqliteReviewInjection` makes the mapping transparent and testable.

### Expected Outcomes

- `SqliteReviewInjection` in [`toolfence/contracts/profile.py`](../toolfence/contracts/profile.py:67)
  gains a required `id_column: str` field.
- [`profiles/galaxium.json`](../profiles/galaxium.json) has `"id_column": "review_id"` added
  to the `"injection"` object.
- The heuristic `pk_col = f"{inj_table.rstrip('s')}_id"` in
  [`toolfence/integration/nanobot_adapter.py`](../toolfence/integration/nanobot_adapter.py:581)
  is replaced with `pk_col = inj.id_column` (where `inj` is the loaded
  `SqliteReviewInjection`). The comment is removed.
- `scripts/generate_schemas.py` is run (not hand-edited) and
  `toolfence/contracts/schemas/profile.schema.json` is regenerated.
- Existing test `test_profile_sqlite_review_injection` in
  [`tests/test_target_profile.py`](../tests/test_target_profile.py:178) is updated to
  include `"id_column": "review_id"` in its fixture dict (since `id_column` is required).
- `test_galaxium_profile_loads` continues to pass with the updated `galaxium.json`.

### Todo List

1. Add `id_column: str` to `SqliteReviewInjection` in `toolfence/contracts/profile.py`.
2. Add `"id_column": "review_id"` to the `"injection"` object in `profiles/galaxium.json`.
3. In `nanobot_adapter.py`, find where `pk_col` is derived (line 581) and replace the
   heuristic with `pk_col = inj_config.id_column`. This requires passing or accessing
   the `SqliteReviewInjection` object at that point — check how `inj_table` is already
   plumbed to understand what variable holds the full injection config.
4. Run `python scripts/generate_schemas.py` to regenerate `profile.schema.json`.
5. Update `test_profile_sqlite_review_injection` fixture to add `"id_column": "review_id"`.
6. Run `pytest` and report the total count.

### Relevant Context

- Model to change: [`toolfence/contracts/profile.py`](../toolfence/contracts/profile.py:67)
- Profile JSON: [`profiles/galaxium.json`](../profiles/galaxium.json:11)
- Heuristic: [`toolfence/integration/nanobot_adapter.py`](../toolfence/integration/nanobot_adapter.py:581)
- Schema generator: [`scripts/generate_schemas.py`](../scripts/generate_schemas.py)
- Tests affected: [`tests/test_target_profile.py`](../tests/test_target_profile.py:178)
