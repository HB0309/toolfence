# Dashboard Trace Detail Plan

## Overview

Extend the ToolFence dashboard replay section so that each trial card, as it
appears during replay, automatically shows the full per-tool-call detail from
the trial's `trace.tool_calls` array.  For every tool call the card renders:

- **Input** — the `params` dict (tool name + arguments)
- **Output** — the `result` string (or `error` if present)
- **Marked source** — the `provenance` dict: one label per argument name
  (`"user"` | `"first-party"` | `"untrusted"`)
- **Marked decision** — the `guard_decision` field (`"pass"` | `"hold"`)
- **Canary annotation** — if the trial has a non-null `canary` string and that
  string appears inside any argument value, the argument value is visually
  annotated (e.g. wrapped in a `<mark>` tag) to show where the injection
  candidate was placed

No new endpoints are required.  `/api/results` already returns the full
`TrialRecord` including its nested `trace.tool_calls`.  All work is in
`replay.js`, `index.html` (CSS only), and `tests/test_dashboard_server.py`
(one lightweight structural assertion).

All existing dashboard constraints remain in force:
- stdlib `http.server` only, no outbound calls, no env-var reads.
- `inconclusive` always its own column, never folded.
- Read-only; no live execution.

---

## Sub-Task 1 — Add tool-call detail to each replay card in `replay.js`

**Intent**
The `_replayTimer` interval currently builds a one-line summary card per
`TrialRecord`.  Extend the card to include a tool-call detail sub-section for
every entry in `rec.trace.tool_calls` (when `rec.trace` is non-null).
Each sub-section shows: tool name, params + provenance labels, result/error,
guard decision, and canary annotation when applicable.

**Expected Outcomes**
- Each replay card, as it appears, contains a `<div class="tool-calls">` block
  with one child `<div class="tool-call">` per entry in `rec.trace.tool_calls`.
- Each `tool-call` div shows:
  - Tool name (`rec.trace.tool_calls[i].name`)
  - Guard decision badge (`pass` or `hold`)
  - For each parameter: the parameter name, its value, and — if present in the
    `provenance` dict — a provenance badge (`user`, `first-party`, or
    `untrusted`)
  - If the param value contains the trial's canary string, the canary substring
    is wrapped in `<mark class="canary-hit">` inside the displayed value
  - The `result` string (or `error` if `result` is null and `error` is
    non-null), truncated to 300 characters with "…" appended if longer
- When `rec.trace` is null (skipped trials), the tool-call section is omitted
  entirely.
- No extra clicks; content is always expanded.
- The replay card for trials without canary (normal trials, `rec.canary` is
  null) still renders params and provenance; just no canary annotation.

**Todo List**
- [ ] In `replay.js`, add a helper `renderProvBadge(label)` that returns an
  HTML string: a `<span class="badge prov-{label}">{label}</span>`.
- [ ] Add a helper `renderGuardDecisionBadge(decision)` that returns a
  `<span class="badge guard-{decision}">{decision}</span>`.
- [ ] Add a helper `annotateCanary(text, canary)` that, when `canary` is a
  non-null/non-empty string and `text` includes it, returns the text with the
  canary substring replaced by `<mark class="canary-hit">{canary}</mark>`.
  When `canary` is null or not found in `text`, returns `esc(text)` unchanged.
  Must HTML-escape the surrounding text correctly (escape before inserting the
  `<mark>` tag).
- [ ] Add a helper `renderToolCalls(toolCalls, canary)` that takes
  `rec.trace.tool_calls` (an array) and the trial's `rec.canary` string, and
  returns an HTML string for the full tool-call sub-section.
  - For each tool call entry `tc`: tool name row, guard decision, then for each
    key in `tc.params`: show param name, provenance badge (from
    `tc.provenance[paramName]` if present, otherwise nothing), and the value
    with canary annotation applied.
  - After params: show result/error row (truncated to 300 chars).
- [ ] In the `_replayTimer` `setInterval` callback, replace the inline
  `card.innerHTML = ...` template with a call that also appends
  `renderToolCalls(rec.trace ? rec.trace.tool_calls : [], rec.canary)` into the
  card's tool-calls block.

**Relevant Context**
- `toolfence/cli/dashboard/static/replay.js` lines 298–330 (the `setInterval`
  callback that builds `card.innerHTML`)
- `replay.js` `esc()` helper (line 17) — must be reused for safe HTML escaping
- `toolfence/contracts/trace.py` — `TraceEntry` shape: `name`, `params`,
  `result`, `error`, `duration_ms`, `provenance`, `guard_decision`
- `toolfence/contracts/trial.py` — `TrialRecord.trace` is null only when
  `verdict == "skipped"`
- `results/fs-smoke/t-run-20261017-072113-0002.json` — real example with
  non-empty `provenance` dicts and `guard_decision: "hold"`
- `results/t-run-20261017-094507-0001.json` — real example with
  `guard_decision: "pass"` and empty `provenance` dicts

**Status** — [x] done

---

## Sub-Task 2 — Add CSS for new tool-call detail elements in `index.html`

**Intent**
The new HTML elements introduced by Sub-Task 1 need visual styles so the
detail is readable within the existing card layout.  All styles are added
inline in `index.html`'s `<style>` block.

**Expected Outcomes**
- `.tool-calls` block has a subtle top border and small top margin to separate
  it from the trial-level summary line.
- `.tool-call` entries have a light background, small padding, and a bottom
  border between entries.
- `.tool-call .tc-name` (tool name) is displayed in monospace, bold.
- `.prov-user` badge: green-tinted (reuse `badge-refused` palette or similar
  that already exists).
- `.prov-first-party` badge: blue-tinted.
- `.prov-untrusted` badge: orange/red-tinted (to signal risk).
- `.guard-pass` badge: green-tinted.
- `.guard-hold` badge: yellow-tinted (reuse `badge-held` palette).
- `mark.canary-hit`: highlighted background (yellow or orange) with a title
  tooltip `"canary string"` for accessibility.
- `.tc-result` (result/error text): monospace, font-size 0.75rem, max-height
  4em, overflow hidden with ellipsis (or just plain truncation is acceptable
  since the JS already truncates to 300 chars).
- No existing styles are modified; only new selectors are added.

**Todo List**
- [ ] In `index.html` `<style>` block, add CSS rules for:
  `.tool-calls`, `.tool-call`, `.tool-call .tc-name`, `.prov-user`,
  `.prov-first-party`, `.prov-untrusted`, `.guard-pass`, `.guard-hold`,
  `mark.canary-hit`, `.tc-result`, `.tc-param`, `.param-name`, `.param-value`

**Relevant Context**
- `toolfence/cli/dashboard/static/index.html` lines 56–68 — existing badge
  colour palette to reuse
- `toolfence/cli/dashboard/static/index.html` lines 100–110 — existing
  `.replay-card` styles to extend from

**Status** — [x] done

---

## Sub-Task 3 — Add a lightweight structural test for tool-call detail

**Intent**
Verify that the server returns full trace data (including `tool_calls`) in
`/api/results` and that the JS renders tool-call detail inside replay cards.
The first part (server data) is a simple Python assertion; the second (DOM)
requires Playwright and is added to the existing `test_dashboard.py` module.

**Expected Outcomes**
- `test_api_results_includes_tool_calls`: a new test in
  `tests/test_dashboard_server.py` that calls `GET /api/results` against the
  fixture dir, picks the first record that has `trace.tool_calls`, and asserts
  that each entry has `name`, `params`, `result`, `provenance`, and
  `guard_decision` keys.
- `test_dashboard_replay_shows_tool_calls`: a new Playwright test in
  `tests/test_dashboard.py` that starts the replay, waits for the first card to
  appear, and asserts `.tool-calls` is present inside the first `.replay-card`.

**Todo List**
- [ ] In `tests/test_dashboard_server.py`: add
  `test_api_results_includes_tool_calls` that hits `/api/results`, finds at
  least one record with a non-null `trace`, and for the first such record
  asserts each tool call has keys `name`, `params`, `result`, `provenance`,
  `guard_decision`.
- [ ] In `tests/test_dashboard.py`: add
  `test_dashboard_replay_shows_tool_calls` using the `dashboard_url` fixture;
  click replay, wait for the first `.replay-card` to appear, and assert it
  contains a child element with class `tool-calls`.

**Relevant Context**
- `tests/test_dashboard_server.py` — existing server test patterns; use the
  module-level `server_url` fixture already defined there
- `tests/test_dashboard.py` — existing Playwright tests; use `dashboard_url`
  fixture; note `pytest.importorskip("playwright")` guards the whole file
- `fixtures/spike_converted/` — fixture records used by the server fixture;
  these have `trace.tool_calls` arrays

**Status** — [x] done

---

## Sub-Task 4 — Run full pytest suite

**Intent**
Confirm all existing tests and the two new tests added in Sub-Task 3 pass with
no regressions.

**Expected Outcomes**
- `pytest` exits 0 with no new failures or warnings attributable to these
  changes.

**Todo List**
- [ ] Run `pytest` and report outcome; fix any regressions.

**Status** — [x] done — 537 passed, 3 skipped, 14 pre-existing failures (missing mcp/yaml modules and a pre-existing CLI assertion in test_target_profile.py; none attributable to these changes)

---

## Files Changed

| File | Change |
|---|---|
| `toolfence/cli/dashboard/static/replay.js` | Add `renderProvBadge`, `renderGuardDecisionBadge`, `annotateCanary`, `renderToolCalls` helpers; extend replay card inner HTML |
| `toolfence/cli/dashboard/static/index.html` | Add CSS rules for new tool-call detail elements |
| `tests/test_dashboard_server.py` | Add `test_api_results_includes_tool_calls` |
| `tests/test_dashboard.py` | Add `test_dashboard_replay_shows_tool_calls` |

No changes to `server.py`, `scoring.py`, any contract models, or any fixture
files.
