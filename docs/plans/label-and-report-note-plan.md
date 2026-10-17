# Plan: Normal-Task Label Fix + User-Input Canary Note in Report

## Overview

Two focused changes:

1. **Label fix** — `NormalTask` currently has no `label` field, so `cli/main.py` falls back to hard-coding `"write_only"` for every profile's primary task. Add an optional `label: str = "primary"` field to `NormalTask`, set Galaxium's label to `"book_hold"` and filesystem's to `"write_only"` in their profile JSONs, wire it through the CLI, regenerate the JSON schema, and update the affected profile tests.

2. **Report note** — For `user-input` attack probes, the canary appears in the user's own message. Guard passes user-typed values by design (GRD-9 source-checked grant; user-input is first-party). A "leaked with Guard on" result for these probes is therefore the expected control outcome, not a miss. Add a one- or two-sentence note immediately after the attack table to explain this.

---

## Sub-Task 1 — Add `label` field to `NormalTask`

**Intent:** Replace the hard-coded `"write_only"` string in `cli/main.py` with a proper field on the model so each profile controls its own label.

**Expected Outcomes:**
- `NormalTask` in `toolfence/contracts/profile.py` has `label: str = "primary"`.
- `profiles/galaxium.json` has `"label": "book_hold"` inside `normal_task`.
- `profiles/filesystem.json` has `"label": "write_only"` inside `normal_task`.
- `toolfence/cli/main.py` line 346 uses `profile.normal_task.label` instead of the hard-coded `"write_only"` string.
- `toolfence/contracts/schemas/profile.schema.json` is regenerated (run `python scripts/generate_schemas.py`).

**Todo List:**
1. In `toolfence/contracts/profile.py`, add `label: str = "primary"` to `NormalTask` (after `goal_tool`).
2. In `profiles/galaxium.json`, add `"label": "book_hold"` to the `normal_task` object.
3. In `profiles/filesystem.json`, add `"label": "write_only"` to the `normal_task` object.
4. In `toolfence/cli/main.py` line 346, change `"label": "write_only"` to `"label": profile.normal_task.label`.
5. Run `python scripts/generate_schemas.py` to regenerate `profile.schema.json`.
6. Also check `profiles/galaxium-alt-model.json` and add the same label as Galaxium (`"book_hold"`).

**Relevant Context:**
- `toolfence/contracts/profile.py` — `NormalTask` class, lines ~102–106.
- `toolfence/cli/main.py` — line 346, hard-coded `"write_only"`.
- `profiles/filesystem.json` — `normal_task` object has `prompt` and `goal_tool`.
- `profiles/galaxium.json` — `normal_task` object has `prompt` and `goal_tool`.
- `profiles/galaxium-alt-model.json` — mirrors galaxium, must stay in sync.
- `scripts/generate_schemas.py` — regenerates `toolfence/contracts/schemas/profile.schema.json`.

**Status:** [ ] pending

---

## Sub-Task 2 — Update profile tests for the label change

**Intent:** Fix the tests that hard-code `"write_only"` as the primary probe dict label, and add coverage for Galaxium's `"book_hold"` label.

**Expected Outcomes:**
- `tests/test_filesystem_profile.py` — The `test_task_label_in_normal_probe_dict` test reads the label from `profile.normal_task.label` (not hard-coded); `test_report_normal_conditions_has_task_column` keeps `"write_only"` because it is now the filesystem profile's declared label (still passes).
- `tests/test_galaxium_profile.py` — New test `test_galaxium_normal_task_label_is_book_hold` that asserts `profile.normal_task.label == "book_hold"`.
- `pytest` passes with no new warnings.

**Todo List:**
1. In `tests/test_filesystem_profile.py`:
   - `test_task_label_in_normal_probe_dict` (line 201–216): change the comment and the primary_dict construction to use `profile.normal_task.label` instead of the literal `"write_only"`. The assertion `primary_dict["label"] == "write_only"` still holds because the profile JSON declares `"write_only"`.
   - The `test_scoring_separate_rows_for_each_label` test at line 246 hard-codes `_make_normal("write_only", True)` — this is fine; it is testing the scoring layer with an arbitrary label, not the profile JSON, so leave it.
2. In `tests/test_galaxium_profile.py`: add a test `test_galaxium_normal_task_label_is_book_hold` that loads the profile and asserts `profile.normal_task.label == "book_hold"`.
3. Run `pytest tests/test_filesystem_profile.py tests/test_galaxium_profile.py` to confirm green.

**Relevant Context:**
- `tests/test_filesystem_profile.py` lines 193–217 (`test_task_label_in_normal_probe_dict`).
- `tests/test_galaxium_profile.py` — existing test structure; add the new test alongside the other field-value assertions.

**Status:** [ ] pending

---

## Sub-Task 3 — Add user-input canary note to the report

**Intent:** Insert a short explanatory note immediately after the attack results table to tell readers that "Leaked with Guard on" rows for `user-input` probes are the expected control result, because Guard passes values the user typed themselves.

**Expected Outcomes:**
- `render_report` in `toolfence/engine/report.py` emits a note paragraph after the attack table (before the Cards Shown section) when any `user-input` conditions are present.
- The note is 1–2 sentences, references `user-input` channel by name.
- Existing tests still pass. One new test in `tests/test_report.py` (or the nearest relevant test file) asserts the note appears when a `user-input` condition is present and does not appear when only `tool-result` conditions are present.

**Todo List:**
1. In `toolfence/engine/report.py`, after the `for cond in summary.conditions` loop (line 121) and before `lines.append("")` (line 123), add:
   ```
   if any(c.channel == "user-input" for c in summary.conditions):
       lines.append("")
       lines.append(
           "> **Note (user-input probes):** Guard passes values the user typed "
           "themselves by design, so a *leaked* result with Guard on is the "
           "expected control outcome for user-input probes — not a Guard miss."
       )
   ```
2. Find the nearest test file that tests `render_report` (grep shows `test_filesystem_profile.py` has `test_report_normal_conditions_has_task_column`; there may also be `tests/test_report.py`). Add two assertions: (a) note present when a `user-input` attack condition is present; (b) note absent when only `tool-result` conditions are present.
3. Run `pytest` for the relevant test file to confirm green.

**Relevant Context:**
- `toolfence/engine/report.py` — attack table loop lines 110–121, blank line at 123.
- `toolfence/engine/scoring.py` — `ConditionSummary.channel` field used to filter.
- No schema changes needed (report is pure string rendering).

**Status:** [ ] pending

---

## Notes

- `profiles/galaxium-alt-model.json` mirrors galaxium; it must also get `"label": "book_hold"` in `normal_task`, or the alt-model profile test `test_galaxium_alt_model_config_differs_only_in_expected_fields` (which diffs the two profiles) will report an unexpected key difference. Check that test before and after.
- Do NOT touch `results/` — user will rerun Galaxium runs before any summary write-up.
- Schema regeneration (Sub-Task 1, step 5) must happen after the model change, not before.
- The `test_committed_schema_is_fresh` test in the test suite verifies the schema matches the model; it will fail if the schema is not regenerated.
