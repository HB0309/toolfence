# Track C — Implementation Plan

> **Owner:** Track C developer + Bob agent
> **Branch:** TrackC (pulled from TrackA)
> **Written:** based on `docs/IMPLEMENTATION_PLAN.md`, `docs/REQUIREMENTS.md`, `docs/IDEA.md`,
> `docs/notes/nanobot-map.md`, and direct inspection of all implemented files.
>
> Read `docs/IMPLEMENTATION_PLAN.md` for the full shared design (contracts, repo layout,
> component boundaries, Guard decision rules). This file is Track C's execution guide only —
> it does not duplicate what is already in that document.

---

## Track C scope

Track C owns exactly these deliverables:

| Task | Deliverable | Depends on |
|---|---|---|
| A-3 | `toolfence/guard/datamark.py` | ✅ Already implemented by Track A — Track C now owns it |
| C-1 | Guard core: `decision.py`, `provenance.py`, `taint.py` | S-2 ✅ |
| C-2 | `guard/proxy.py`, `guard/card.py` | C-1, A-3 ✅ |
| C-3 | `guard/confirm.py`, update `proxy.py` | C-2 |
| C-4 | `cli/main.py`, `cli/ci_checks.py`, `.env.example` | A-1 ✅, A-4 ⚠️ (wait), A-5 ❌ |
| C-5 | `ci_checks.py` extensions, `.github/workflows/toolfence-ci.yml` | A-1 ✅, B-3 ❌ |
| C-6 | `cli/dashboard/server.py`, `static/index.html`, `static/replay.js` | A-4 ⚠️, A-5 ❌ |
| C-7 | `docs/deploy.md`, IBM Cloud Code Engine deploy | C-6 |

**Stop after C-3.** Wait for Track A's A-4 bug fix to land before starting C-4.
Track B's B-3 (nanobot Guard wiring) uses `GuardedProxy` from C-2 and `ConfirmGrant` from C-3;
C-2 and C-3 must ship before B-3 can complete its final gate.

---

## What Track C can depend on right now

All of the following are real, complete implementations — not stubs:

- **`toolfence/contracts/`** — all four contract modules + generated JSON Schemas.
- **`toolfence/engine/adapter.py`** — `AgentAdapter` Protocol, `ScriptedAdapter`.
- **`toolfence/engine/surface.py`** — `SurfaceScanner`, `get_action_class`, `suggest_action_class`, `check_description_drift`.
- **`toolfence/engine/probe.py`** — `generate_canary`, `ProbeBuilder`, `validate_probe_file`.
- **`toolfence/guard/datamark.py`** — `datamark_result`, `is_datamarked` (Track C owns this now).
- **`toolfence/engine/verdict.py`** — `assign_verdict`, `canary_in_args` (real implementation; A-4 bug is in the test suite, not the logic).
- **`toolfence/engine/scoring.py`** — `aggregate`, `DISCLAIMER`, `ResultSummary`.
- **`toolfence/engine/report.py`** — `render_report` (imports `DISCLAIMER` from `scoring`; re-exported).
- **`tests/adapter_contract.py`** — `run_adapter_contract` parametrised suite.
- **`fixtures/`** — `surface_fixture.json`, 10 converted spike traces, `fixture_3call.json`.

**Not yet available (do not depend on for C-1 through C-3):**
- `toolfence/engine/runner.py` (A-5) — needed by C-4/C-6 only.
- `results/surface.json` (B-5) — needed by C-5 only.
- `toolfence/integration/installer.py` (B-3) — Track B's code; not imported by `guard/`.

---

## Guard boundary reminder

`toolfence/guard/` must have **zero nanobot imports** and **zero `toolfence.engine` imports**.
Every new file added to `guard/` gets an import-check test (see `test_datamark.py::test_datamark_no_engine_import` for the pattern — check the source file text directly with `Path(...).read_text()`).

Changes to `guard/proxy.py` or `guard/decision.py` require Track B sign-off because `integration/installer.py` depends on the proxy interface.

---

## Sub-tasks

---

### C-1 — Guard core: decision, provenance, taint

**Status:** `[ ] pending`
**Depends on:** S-2 ✅
**Req IDs:** BASE-7, GRD-4, GRD-5, GRD-6, GRD-7, GRD-12

**Intent:**
Three independent, stateless-or-session-scoped Guard logic pieces with zero nanobot imports.
These are the building blocks every other Guard piece calls.

**Expected outcomes:**
- `GuardDecision.decide(...)` returns `"hold"` for all three hold-trigger cases and `"pass"` for the pass case (including reads in tainted sessions).
- `ProvenanceStore` resolves argument provenance correctly for user-typed, first-party, untrusted, and untraced values; file-label inheritance works.
- `SessionTaint` starts untainted; marks tainted on demand; never clears within a session.
- `pytest tests/test_guard_core.py` green (≥ 10 assertions).
- Import checks (no nanobot, no LLM, no `toolfence.engine`) pass in the test.

**Todo list:**

- [ ] Create `toolfence/guard/decision.py` — implement `GuardDecision` class with `decide(tool_name, action_class, arguments, session_tainted, provenance) -> Literal["pass", "hold"]`; four-branch rule exactly as in `docs/IMPLEMENTATION_PLAN.md §2.3`; no imports outside stdlib and `toolfence.contracts`.
- [ ] Create `toolfence/guard/provenance.py` — implement `ProvenanceStore` with: `record_user_message(text: str)`, `record_tool_result(tool_name: str, result: str, label: str)`, `record_file_path(path: str, label: str)`, `resolve_argument(value: Any) -> ProvenanceLabel`; normalise values (whitespace-collapse via `" ".join(str(v).split())`; numeric string↔int matching); untraced value → `"untrusted"` (fail-closed).
- [ ] Create `toolfence/guard/taint.py` — implement `SessionTaint` with `mark_tainted()` and `is_tainted() -> bool`; never clears within the session lifetime; fresh instance starts untainted.
- [ ] Create `tests/test_guard_core.py` — test all four `decide` branches; provenance `user`/`first-party`/`untrusted`/untraced; taint fresh→tainted, never clears; file-label inheritance (store path→label, query same path); read-class always passes (tainted session, untrusted arg → still `pass`); import checks (no nanobot, no LLM, no `toolfence.engine` in all three source files).
- [ ] Run `pytest tests/test_guard_core.py` and confirm green.

**Relevant context:**
- Decision rule (four branches): `docs/IMPLEMENTATION_PLAN.md §2.3` — irreversible → hold; state-changing + tainted → hold; state-changing + any untrusted arg → hold; else → pass.
- Req text: `docs/REQUIREMENTS.md §GRD-4` through `GRD-7`, `GRD-12`.
- `ProvenanceLabel` type alias is already defined in `toolfence/contracts/trace.py` as `Literal["user", "first-party", "untrusted"]` — import and reuse it.
- Import-check pattern: `tests/test_datamark.py::test_datamark_no_engine_import` — use `Path(...).read_text()` and assert the forbidden strings are absent.

---

### C-2 — GuardedProxy and card message

**Status:** `[ ] pending`
**Depends on:** C-1, A-3 (datamark — ✅ already done)
**Req IDs:** GRD-1, GRD-2, GRD-8, GRD-10, GRD-11

**Intent:**
`GuardedProxy` wraps **any** tool object (not just MCP tools) behind the same interface.
Two boolean switches (`guard_on`, `datamark_on`) control behaviour; when both are `False` the
proxy is fully transparent. This single class covers all six defense conditions in the evaluation
matrix. `build_card_message` provides the three human-readable hold-reason templates.

**Expected outcomes:**
- With `guard_on=True`: a hold blocks `tool.execute()` from being called; the returned result contains `"paused"`.
- With `guard_on=True`: `HeldCallEvent` is emitted via the `on_held` callback with correct `reason`, `arguments_hash`, `untrusted_read_count`, and `untrusted_arg_name`.
- With `guard_on=False, datamark_on=False`: result passes through completely unchanged.
- With `datamark_on=True` on an untrusted tool: result is datamarked before being returned.
- Three card message templates produce correct text + `[["Allow", "Decline"]]` buttons.
- A stub registry (`dict`) accepts `GuardedProxy` as a drop-in replacement for a raw tool.
- `pytest tests/test_proxy.py` green.

**Todo list:**

- [ ] Create `toolfence/guard/card.py` — implement `build_card_message(event: HeldCallEvent) -> tuple[str, list[list[str]]]`; three reason templates from `docs/IMPLEMENTATION_PLAN.md §2.3`; buttons always `[["Allow", "Decline"]]`.
- [ ] Create `toolfence/guard/proxy.py` — implement `GuardedProxy(tool, surface_map, provenance, taint, decision, on_held, *, guard_on: bool = True, datamark_on: bool = False)`; `.name` property forwarded; `async execute(**params)`; logic order: (1) if `guard_on`, resolve provenance per param via `provenance.resolve_argument`, call `decision.decide`, on `"hold"` compute `arguments_hash` (SHA-256 of `json.dumps(sorted canonical params)`), emit `HeldCallEvent` via `on_held`, return `"paused — needs your confirmation"` without calling `tool.execute()`; on `"pass"`, call `tool.execute(**params)`, record result in provenance store with trust label from `surface_map`; (2) if `datamark_on` and tool's trust label is `"untrusted"`, apply `datamark_result` to the result before returning; (3) always record result for provenance regardless of `guard_on`.
- [ ] Create `tests/test_proxy.py` — test all five proxy modes (hold blocks execute; three card templates; datamark on untrusted; transparent pass-through; datamark-only); stub registry dict accepts proxy (GRD-1); `tool.execute()` never called on hold (GRD-8); result contains `"paused"` on hold; import checks (no nanobot, no LLM).
- [ ] Run `pytest tests/test_proxy.py` and confirm green.

**Relevant context:**
- `HeldCallEvent` dataclass is in `toolfence/contracts/guard.py` — import from there.
- `datamark_result` and `is_datamarked` are in `toolfence/guard/datamark.py`.
- Trust label for a tool comes from `surface_map` (`SurfaceFile`): use `get_action_class` pattern from `engine/surface.py` but for trust label — iterate `surface.tools` to find the matching entry; default to `"first-party"` if absent.
- `arguments_hash`: `import hashlib, json` — `hashlib.sha256(json.dumps(sorted_params, sort_keys=True).encode()).hexdigest()`.
- Card message templates (exact strings): see `docs/IMPLEMENTATION_PLAN.md §2.3`.
- Track B's `integration/installer.py` will call `GuardedProxy(tool, ...)` — the constructor signature is the interface contract. Do not change it after C-2 ships without Track B sign-off.

---

### C-3 — Guard confirm flow

**Status:** `[ ] pending`
**Depends on:** C-2
**Req IDs:** GRD-9

**Intent:**
A held call can be retried when the user clicks Allow. `ConfirmGrant` stores the pending
grant (tool name + arguments hash) and validates that the retry matches exactly and originated
from a direct button-click user action — not from a tool result.

The grant originates from a **button click**, not a button label string match. Track B's
launcher detects the click event (via the channel's native callback — e.g. Telegram
`_on_callback_query`, confirmed in `nanobot-map.md §Open check 2`) and calls
`confirm_grant.store_pending(tool_name, args_hash)` directly. `ConfirmGrant` itself has no
knowledge of button labels; it only stores and validates (tool_name, args_hash, source) tuples.

`GuardedProxy.execute` accepts an optional `source: str = "first-party"` kwarg. Track B's
launcher passes `source="user"` when it knows the trigger was a button-click callback.
For tool-driven retries (not user-initiated), `source` is left at the default `"first-party"`,
which `ConfirmGrant.consume_grant` rejects.

**Expected outcomes:**
- A user-sourced grant that matches the held call's tool name and arguments hash → retry passes, `tool.execute()` called.
- A grant with different arguments → hold again (Guard holds the new arguments, not a blank pass).
- A grant with `source != "user"` (e.g. tool-result-driven retry) → rejected; call holds again.
- `ConfirmGrant` has no nanobot import and no knowledge of button label strings.
- `pytest tests/test_confirm.py` green (≥ 3 test cases matching GRD-9).
- `pytest tests/test_proxy.py` still green after `proxy.py` update.

**Todo list:**

- [ ] Create `toolfence/guard/confirm.py` — implement `ConfirmGrant` with:
  - `store_pending(tool_name: str, args_hash: str) -> None` — stores one pending grant; replaces any prior pending grant for this session.
  - `consume_grant(tool_name: str, args_hash: str, source: str) -> bool` — returns `True` only if `source == "user"` AND stored `tool_name` and `args_hash` both match; clears the stored grant on a successful match; returns `False` without clearing on any mismatch or wrong source.
  - No nanobot import; no button-label string matching.
- [ ] Update `toolfence/guard/proxy.py` — add `confirm_grant: ConfirmGrant` parameter to constructor (add it after `on_held`, before the keyword-only `*`); add `source: str = "first-party"` kwarg to `async execute(**params, source="first-party")` — NOTE: since `**params` captures all kwargs, `source` must be popped from `params` at the start of `execute` before passing to `tool.execute`: `source = params.pop("source", "first-party")`; at the start of `execute` (before `decision.decide`), compute `computed_hash`, call `confirm_grant.consume_grant(self.name, computed_hash, source)`; if `True`, skip `decide` and call `tool.execute(**params)` directly.
- [ ] Create `tests/test_confirm.py` — test cases:
  1. `store_pending` then `consume_grant` with matching tool_name, args_hash, `source="user"` → `True`, second call → `False` (consumed).
  2. `store_pending` then `consume_grant` with **different** args_hash → `False`, grant not consumed.
  3. `store_pending` then `consume_grant` with `source="first-party"` → `False`.
  4. Proxy integration: hold a call, `store_pending` with matching hash, retry with `source="user"` → `tool.execute()` called, result returned (not "paused").
  5. Proxy integration: hold a call, retry with different arguments → `hold` again, `tool.execute()` not called.
  6. Import check: `confirm.py` has no nanobot import, no button-label strings.
- [ ] Run `pytest tests/test_confirm.py` and `pytest tests/test_proxy.py` and confirm both green.

**Relevant context:**
- GRD-9 exact wording: `docs/REQUIREMENTS.md §GRD-9`.
- Button-click detection lives entirely in Track B's launcher (`scripts/launch_gateway.py`, `integration/channel_adapter.py`). Track C's `ConfirmGrant` is agnostic to how the click was detected — it only cares about `(tool_name, args_hash, source)`.
- `docs/notes/nanobot-map.md §Open check 2` — Telegram `_on_callback_query` receives the button press and re-enters the agent loop as a normal `InboundMessage`. Track B's launcher registers a `MessageBus` listener that intercepts this and calls `confirm_grant.store_pending(...)` with `source="user"` before the turn runs.
- `source` kwarg extraction from `**params`: use `source = params.pop("__source__", "first-party")` with a dunder-prefixed key to avoid colliding with any real tool parameter named `source`. Update the key name consistently in both `proxy.py` and `tests/test_confirm.py`. Document the chosen key name in the cross-track handoff note below.
- After C-3 ships, notify Track B of the final constructor signature and the `__source__` kwarg name.

---

## Cross-track coordination points

### Track C → Track B handoff (after C-2 ships)

Track B's `integration/installer.py` (B-3) wraps **every** tool in the registry (including
`read_file` and other built-in nanobot tools, not just `mcp_*`). The constructor signature
Track B must use after C-2 ships:

```python
GuardedProxy(
    tool,           # any object with .name, async .execute(**params); optionally .schema/.description
    surface_map,    # SurfaceFile from contracts/surface.py
    provenance,     # ProvenanceStore from guard/provenance.py
    taint,          # SessionTaint from guard/taint.py
    decision,       # GuardDecision from guard/decision.py
    on_held,        # callable(HeldCallEvent) -> None
    *,
    guard_on: bool = True,
    datamark_on: bool = False,
)
```

Read-class tools (e.g. `read_file`) are wrapped too — GRD-2 requires every tool to be wrapped
so provenance tracking captures file reads. GRD-12 guarantees reads always pass Guard regardless
of taint or argument provenance.

### Track C → Track B handoff (after C-3 ships)

After C-3 the final constructor signature gains one parameter:

```python
GuardedProxy(
    tool,
    surface_map,
    provenance,
    taint,
    decision,
    on_held,
    confirm_grant,  # ConfirmGrant from guard/confirm.py  ← NEW after C-3
    *,
    guard_on: bool = True,
    datamark_on: bool = False,
)
```

Track B's launcher must also:
1. Call `provenance_store.record_user_message(text)` before each turn — feeds GRD-4 user-provenance.
2. On a button-click callback (Telegram `_on_callback_query` or equivalent): call
   `confirm_grant.store_pending(tool_name, args_hash)` with the pending held call's data,
   then re-enter the agent loop with `source="user"` propagated via the `__source__` kwarg
   (exact key decided in C-3 — Track C documents it in the C-3 todo above and communicates
   it to Track B before B-3 finalises).
3. **Do not** call `confirm_grant.store_pending` on typed text — only on button-click callbacks.
   Typed text that happens to say "Allow" does not trigger a grant; only the native callback does.

### Track C waiting on Track A (A-4)

C-4 (`toolfence run` CLI subcommand) calls `EvaluationRunner` from A-5, which calls `assign_verdict` / `aggregate` / `render_report` from A-4. Do not start C-4 until Track A's A-4 bug is resolved and A-5 (`runner.py`) ships.

### Track C waiting on Track B (B-5)

C-5's CI surface-diff check reads `results/surface.json`. This file is produced by B-5. The surface-diff check logic can be written and unit-tested with `fixtures/surface_fixture.json` as a stand-in, but the integration test against the real surface must wait for B-5.

---

## After C-3: what comes next

Once C-1 through C-3 are green and Track A's A-4 bug is fixed and A-5 ships, the remaining
Track C tasks proceed in this order:

1. **C-4** — CLI (`toolfence scan`, `toolfence run`, `toolfence report`). Depends on A-1 ✅, A-4 (wait), A-5 (wait).
2. **C-5** — CI checks + GitHub Action. Depends on A-1 ✅, B-3 (Track B).
3. **C-6** — Dashboard. Depends on A-4 (wait), A-5 (wait).
4. **C-7** — IBM Cloud deploy. Depends on C-6.

Those tasks are not detailed here — they will be planned when the blockers clear.

---

## Session-by-session execution guide

Each sub-task below is sized for one Bob session. Start each session in **Agent mode**.
The agent must read `docs/track-c-plan.md` (this file) at the start of every session before
writing any code.

---

### Session 1 — C-1: Guard core

**Start prompt for agent:**
> Read `docs/track-c-plan.md` in full. Then implement sub-task C-1 exactly as specified:
> create `toolfence/guard/decision.py`, `toolfence/guard/provenance.py`,
> `toolfence/guard/taint.py`, and `tests/test_guard_core.py`.
> Run `pytest tests/test_guard_core.py` and confirm green before finishing.
> Do not create any other files. Do not touch any existing files.

**Files this session touches (and only these):**
- `toolfence/guard/decision.py` — new
- `toolfence/guard/provenance.py` — new
- `toolfence/guard/taint.py` — new
- `tests/test_guard_core.py` — new

**Done condition:** `pytest tests/test_guard_core.py` exits 0, ≥ 10 assertions.

**Git commit message:** `feat(guard): C-1 Guard core — decision, provenance, taint`

---

### Session 2 — C-2: GuardedProxy and card message

**Start prompt for agent:**
> Read `docs/track-c-plan.md` in full. C-1 is complete (decision.py, provenance.py, taint.py
> exist and their tests pass). Implement sub-task C-2 exactly as specified:
> create `toolfence/guard/card.py` and `toolfence/guard/proxy.py` (C-2 version — no
> `confirm_grant` parameter yet; that is added in C-3), and `tests/test_proxy.py`.
> Run `pytest tests/test_proxy.py` and confirm green before finishing.
> Do not touch C-1 files unless a genuine bug is found (if so, also re-run test_guard_core.py).

**Files this session touches:**
- `toolfence/guard/card.py` — new
- `toolfence/guard/proxy.py` — new
- `tests/test_proxy.py` — new

**Done condition:** `pytest tests/test_proxy.py` exits 0; all five proxy-mode tests pass; stub registry test passes.

**After this session:** Post the final `GuardedProxy` constructor signature (C-2 version, without
`confirm_grant`) as a comment in the PR / shared doc so Track B can begin B-3 with `ProxyStub`
as a stand-in. Track B knows C-3 will add one more parameter.

**Git commit message:** `feat(guard): C-2 GuardedProxy, HeldCallEvent emission, card message`

---

### Session 3 — C-3: ConfirmGrant and proxy update

**Start prompt for agent:**
> Read `docs/track-c-plan.md` in full. C-2 is complete (proxy.py and card.py exist and
> test_proxy.py passes). Implement sub-task C-3 exactly as specified:
> create `toolfence/guard/confirm.py` and update `toolfence/guard/proxy.py` to add the
> `confirm_grant` constructor parameter and `source` kwarg handling.
> Create `tests/test_confirm.py`. Run `pytest tests/test_confirm.py` and
> `pytest tests/test_proxy.py` — both must be green before finishing.
> The `source` kwarg must use the key `__source__` when extracted from `**params` to avoid
> colliding with any real tool parameter. Document this key name in a comment at the top of
> `confirm.py`.

**Files this session touches:**
- `toolfence/guard/confirm.py` — new
- `toolfence/guard/proxy.py` — updated (add `confirm_grant` param, `source` extraction)
- `tests/test_confirm.py` — new
- `tests/test_proxy.py` — may need small update if constructor signature changes break existing tests

**Done condition:** `pytest tests/test_confirm.py` green (≥ 6 assertions); `pytest tests/test_proxy.py` still green.

**After this session:** Post the final `GuardedProxy` constructor signature (C-3 version, with
`confirm_grant`) and the `__source__` kwarg key name to Track B. Track B can now finalise B-3.

**Git commit message:** `feat(guard): C-3 ConfirmGrant, confirm flow, proxy source kwarg`

---

### Session 4+ — C-4, C-5, C-6, C-7 (deferred — plan separately)

Do not start these sessions until:
- Track A's A-4 bug is resolved and `pytest tests/test_verdict.py` is confirmed green.
- Track A's A-5 (`toolfence/engine/runner.py`) ships.
- Track B's B-3 (`integration/installer.py`) ships (needed for C-5 Guard-wiring CI check).
- Track B's B-5 (`results/surface.json`) ships (needed for C-5 surface-diff CI check).

When those land, a new plan session will detail C-4 through C-7.

---

## General notes for every implementing agent

- **Read this file (`docs/track-c-plan.md`) first, every session.** Also read `docs/IMPLEMENTATION_PLAN.md §2` (shared contracts) and `docs/REQUIREMENTS.md` for the specific Req IDs listed in each sub-task.
- **Every new `guard/` file needs an import-boundary test.** Use `Path(...).read_text()` to check the source file directly; assert neither `"toolfence.engine"` nor `"nanobot"` appears in it. See `tests/test_datamark.py::test_datamark_no_engine_import` for the exact pattern.
- **`GuardedProxy.execute` must be `async def`.** nanobot's registry calls `await tool.execute(**params)`. `ProxyStub` in `contracts/guard.py` already demonstrates the correct signature.
- **`__getattr__` forwarding is required on `GuardedProxy`** — nanobot registry inspection checks `.read_only`, `.schema`, etc. Use `ProxyStub.__getattr__` in `contracts/guard.py` as the exact pattern.
- **`source` kwarg uses key `__source__`** (double-underscore prefix) when extracted from `**params` in `proxy.execute`. This prevents collision with any real tool parameter named `source`. Extract it at the very top of `execute`: `source = params.pop("__source__", "first-party")`.
- **Do not add `runner.py` or anything from A-5.** That is Track A's work.
- **`fixtures/surface_fixture.json`** — 5 tools, all three action classes, both trust labels. Load with `SurfaceFile.model_validate(json.loads(Path("fixtures/surface_fixture.json").read_text()))`. Use this in all Guard tests that need a `surface_map`.
- **`ProvenanceLabel`** is already defined in `toolfence/contracts/trace.py`. Import and reuse; do not redefine it.
- **`HeldCallEvent`** and **`ProxyStub`** are in `toolfence/contracts/guard.py`. Import from there.
