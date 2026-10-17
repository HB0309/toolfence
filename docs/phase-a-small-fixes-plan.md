# Phase A Small Fixes Plan

## Overview

Four small, targeted fixes to polish Phase A. No Phase B work.

1. **Fix A** — `record_user_message` in `guard/provenance.py`: strip punctuation from user-message tokens the same way `_extract_tokens` strips tool-result tokens. Add two tests.
2. **Fix B** — `--surface` in `toolfence/cli/main.py`: make it optional when `--target` is given; error only when neither is provided.
3. **Fix C** — Update stale help text and docstring; remove a now-false comment about scripted-run placeholders.
4. **Fix D** — Remove the `rstrip('s') + "_id"` fallback from `nanobot_adapter.py:581`; replace with the literal `"review_id"` (the field is now always set on the profile, so no fallback is needed).

---

## Sub-Task 1 — Fix A: Strip punctuation from user-message tokens

**Status:** `[ ] pending`

### Intent

[`record_user_message`](../toolfence/guard/provenance.py:134) splits on whitespace and stores
each bare token verbatim. But [`_extract_tokens`](../toolfence/guard/provenance.py:79) (used for
tool results) strips [`_JSON_STRIP_CHARS`](../toolfence/guard/provenance.py:40) from each token.
The asymmetry means that a user message like `"I'm Alice (alice@example.com)."` stores
the token `alice@example.com).` — with a trailing `)` and `.` — rather than the bare
`alice@example.com`, so a later tool call using `alice@example.com` resolves as
`"untrusted"` instead of `"user"`.

The fix: in the `for token in text.split()` loop inside `record_user_message`, strip
`_JSON_STRIP_CHARS` from each `token` before adding it to `_user_values`. Keep the raw
token too (matching the pattern in `_extract_tokens` lines 83–84) so that exact-match
still works if the caller stored it un-stripped.

### Expected Outcomes

- `record_user_message("I'm Alice (alice@example.com).")` stores both `(alice@example.com).`
  (raw) and `alice@example.com` (stripped) in `_user_values`.
- `resolve_argument("alice@example.com")` → `"user"` for the message above.
- `resolve_argument("report.txt")` → `"user"` for message `"Summarise report.txt."`.

### Todo List

1. In [`toolfence/guard/provenance.py`](../toolfence/guard/provenance.py) inside
   `record_user_message`, change the `for token in text.split()` loop to mirror
   `_extract_tokens`: strip `_JSON_STRIP_CHARS` from each token, store the stripped
   form, and if it differs from the raw token, store the raw form too.
2. Add a test file `tests/test_provenance.py` with at least:
   - `test_email_in_brackets_with_trailing_period` — message `"I'm Alice (alice@example.com)."`,
     resolve `"alice@example.com"` → `"user"`.
   - `test_filename_at_end_of_sentence` — message `"Please summarise report.txt."`,
     resolve `"report.txt"` → `"user"`.

### Relevant Context

- Strip chars constant: [`toolfence/guard/provenance.py:40`](../toolfence/guard/provenance.py:40) — `_JSON_STRIP_CHARS`
- `_extract_tokens` pattern (lines 78–84): strips + keeps raw if different
- `record_user_message` loop: [`toolfence/guard/provenance.py:134`](../toolfence/guard/provenance.py:134)
- No existing provenance test file (confirmed by grep).

---

## Sub-Task 2 — Fix B: `--surface` optional when `--target` is given

**Status:** `[ ] pending`

### Intent

Currently `--surface` is `required=True` on the argparse run sub-parser
([`toolfence/cli/main.py:53`](../toolfence/cli/main.py:53)). This forces users to supply a dummy
`--surface` even when `--target` already provides the surface path via
`profile.surface`. The fix makes `--surface` optional (`required=False`, `default=None`)
and adds a validation block early in `_cmd_run`: if `surface_path is None and target_path is None`,
print a usage error and `sys.exit(1)`.

Since `--target` now requires `--live` (guard already in place), the resulting combinations are:
- `--surface <path>` alone → OK (scripted run)
- `--target <path> --live` → profile provides surface → OK
- neither → usage error
- `--surface` + `--target --live` → `--surface` is ignored (profile wins); that is
  already the existing behaviour (line 249: `surface_path = profile.surface`).

### Todo List

1. Change `run_p.add_argument("--surface", ...)` from `required=True` to
   `required=False, default=None` in [`toolfence/cli/main.py`](../toolfence/cli/main.py:53).
2. In `_cmd_run`, add a guard early (before the profile load block) that checks
   `surface_path is None and target_path is None` and emits:
   `"Error: --surface is required when --target is not given."` then `sys.exit(1)`.
   (When `--target` is given, `surface_path` will be set from `profile.surface` before the
   surface load block, so no `None` will reach `Path(surface_path).read_text()`.)
3. Update the `_cmd_run` signature to `surface_path: str | None`.
4. Add a test `test_surface_required_without_target` to `tests/test_target_profile.py`
   using `subprocess.run`, assert non-zero exit and stderr mentions `--surface`.
5. Verify the existing `test_target_without_live_fails` still passes (it passes `--surface`,
   so it should be unaffected).

### Relevant Context

- Argparse declaration: [`toolfence/cli/main.py:53`](../toolfence/cli/main.py:53)
- Guard for `--target` without `--live`: [`toolfence/cli/main.py:239`](../toolfence/cli/main.py:239)
- Profile overrides `surface_path`: [`toolfence/cli/main.py:249`](../toolfence/cli/main.py:249)

---

## Sub-Task 3 — Fix C: Update stale help text and docstring; remove placeholder comment

**Status:** `[ ] pending`

### Intent

Three stale strings need updating now that `--target` requires `--live`:

1. **`--target` help text** ([`toolfence/cli/main.py:62`](../toolfence/cli/main.py:62)):
   Currently says "Without --live the profile is validated but scripted adapters are still
   used." This is no longer true. Replace with: "Requires --live. Overrides --config,
   --surface, and the default probe list with values from the profile."

2. **`_cmd_run` docstring** ([`toolfence/cli/main.py:211`](../toolfence/cli/main.py:211)):
   Currently says "Without `--live` the profile is validated but scripted adapters are
   still used (unchanged behaviour for CI)." Replace that sentence with: "``--target``
   requires ``--live``; passing ``--target`` without ``--live`` is a usage error."

3. **"placeholder for scripted runs" comment** ([`toolfence/cli/main.py:328`](../toolfence/cli/main.py:328)):
   `# Use the normal-task fixture as a placeholder for scripted runs;` followed by
   `# the factory takes over for live runs.`
   This comment predates the `--target requires --live` guard. Remove both comment lines.

### Todo List

1. Edit `--target` help string in the argparse block.
2. Edit `_cmd_run` docstring.
3. Remove the two-line comment above `normal_fix_path = fixtures_probes_dir / "normal_task.json"` at line 328.

### Relevant Context

- Help text: [`toolfence/cli/main.py:62`](../toolfence/cli/main.py:62)
- Docstring: [`toolfence/cli/main.py:211`](../toolfence/cli/main.py:211)
- Comment: [`toolfence/cli/main.py:328`](../toolfence/cli/main.py:328)

---

## Sub-Task 4 — Fix D: Remove `rstrip` fallback from `nanobot_adapter.py`

**Status:** `[ ] pending`

### Intent

[`nanobot_adapter.py:581`](../toolfence/integration/nanobot_adapter.py:581) currently reads:

```python
pk_col = getattr(self, "_injection_id_column", None) or f"{inj_table.rstrip('s')}_id"
```

Since Fix 4 from the previous session added `id_column` as a **required** field on
`SqliteReviewInjection` and `live_factory.py` always passes it as `injection_id_column`,
`self._injection_id_column` is always set for any real profile run. The fallback
`f"{inj_table.rstrip('s')}_id"` only fires in tests that construct `NanobotAdapter`
without going through `make_live_factory_from_profile`. Replace it with the literal
`"review_id"` — a concrete fallback that is no longer a heuristic guess.

### Todo List

1. In [`toolfence/integration/nanobot_adapter.py`](../toolfence/integration/nanobot_adapter.py:581),
   change line 581 to:
   `pk_col = getattr(self, "_injection_id_column", None) or "review_id"`
2. Remove the no-longer-accurate comment on the same line if present.

### Relevant Context

- Line to change: [`toolfence/integration/nanobot_adapter.py:581`](../toolfence/integration/nanobot_adapter.py:581)
- `_injection_id_column` is set in `__init__` and plumbed from the profile in `live_factory.py`.
