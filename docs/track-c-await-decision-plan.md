# Track C — await_decision Interface Plan

> **Owner:** Track C
> **Branch:** TrackC
> **Scope:** `toolfence/guard/proxy.py`, `toolfence/guard/card.py`, `tests/test_proxy.py`
>
> Track B is responsible for: `toolfence/integration/installer.py`, `toolfence/integration/channel_adapter.py`,
> `scripts/launch_gateway.py`, and `tests/test_integration.py`.
> Track C documents the new interface clearly so Track B can implement against it.

---

## Overview

The existing confirm flow uses `ConfirmGrant` inside `GuardedProxy`: Track B's launcher
calls `confirm_grant.store_pending(tool_name, args_hash)` when a button is tapped, and
`proxy.execute` polls `consume_grant` on every call to check for a pending approval.
This is a poll-based model.

The new design replaces it with a **push-based async callback** called `await_decision`.
`GuardedProxy.execute` now calls `await await_decision(event)` when a hold is triggered,
blocking until Track B's launcher resolves the decision (returning `True` for Allow,
`False` for Decline or timeout). The proxy no longer manages `ConfirmGrant` or polls
for pending grants internally. Track B owns the Future, deduplication, timeout, and button
handling; Track C only owns the proxy interface and the card text.

The card text gains one new instruction line ("Tap Allow or Decline, or reply 1 / 2.")
so users know they can type a reply if the channel does not render inline buttons.

---

## Ownership boundary

| File | Owner | Change |
|------|-------|--------|
| `toolfence/guard/proxy.py` | Track C | Replace `on_held` + `ConfirmGrant` with `await_decision` async callback |
| `toolfence/guard/card.py` | Track C | Add "Tap Allow or Decline, or reply 1 / 2." line to all three card templates |
| `tests/test_proxy.py` | Track C | Update for new proxy interface and new card text |
| `toolfence/integration/installer.py` | Track B | Update `install_guard` to pass `await_decision=...` instead of `on_held=...` and `confirm_grant=...` |
| `toolfence/integration/channel_adapter.py` | Track B | Implement `await_decision` callback using asyncio Future; `store_pending` call site |
| `scripts/launch_gateway.py` | Track B | asyncio Future deduplication, timeout, button tap and typed-reply handling |
| `tests/test_integration.py` | Track B | Tests for Future, deduplication, timeout, typed fallback |

---

## Interface contract Track C exports (after this plan)

Track B must implement against this exact signature.

### `GuardedProxy` constructor (after changes)

```python
GuardedProxy(
    tool,           # any object with .name, async .execute(**params)
    surface_map,    # SurfaceFile
    provenance,     # ProvenanceStore
    taint,          # SessionTaint
    decision,       # GuardDecision
    await_decision, # Callable[[HeldCallEvent], Awaitable[bool]]
                    # awaited on hold; True=allow, False=deny
    *,
    guard_on: bool = True,
    datamark_on: bool = False,
)
```

**Key differences from the C-3 constructor:**
- `on_held: Callable[[HeldCallEvent], None]` is **replaced** by `await_decision: Callable[[HeldCallEvent], Awaitable[bool]]`
- `confirm_grant: ConfirmGrant` parameter is **removed** — proxy no longer imports or uses `ConfirmGrant`
- `execute` is still `async def`; it now `await`s the `await_decision` callback

### `GuardedProxy.execute` behaviour (after changes)

```
1. Compute args_hash from params.
2. If guard_on:
   a. Resolve provenance per param.
   b. Determine action_class from surface_map.
   c. Call decision.decide(...).
   d. If "hold":
      - Build HeldCallEvent (same fields as before).
      - allowed = await self._await_decision(event)
      - If allowed is True: fall through to step 3 (call tool.execute).
      - If allowed is False: return _HOLD_SENTINEL.
3. Call tool.execute(**params).
4. Record result in provenance; update taint; apply datamark if needed.
5. Return result.
```

The `ConfirmGrant` consume-grant pre-check (step 1 in the old proxy) is **removed**.
There is no longer a separate "consume grant then skip Guard" fast path.
All decisions go through `await_decision`.

### `build_card_message` output (after changes)

All three card text templates gain an appended line:
`"\nTap Allow or Decline, or reply 1 / 2."`

The function signature and return type are unchanged:
`build_card_message(event: HeldCallEvent) -> tuple[str, list[list[str]]]`

The `buttons` return value remains `[["Allow", "Decline"]]`.

Full updated templates:

- `irreversible`: `"This action is irreversible. Allow or Decline?\nTap Allow or Decline, or reply 1 / 2."`
- `tainted_session`: `"This came after reading {N} untrusted result(s). Allow or Decline?\nTap Allow or Decline, or reply 1 / 2."`
- `untrusted_argument`: `"The value of '{arg}' came from an untrusted source. Allow or Decline?\nTap Allow or Decline, or reply 1 / 2."`

---

## Sub-tasks

---

### TC-AD-1 — Update `guard/card.py`: add instruction line

**Status:** `[ ] pending`

**Intent:**
Add the user-instruction line `"Tap Allow or Decline, or reply 1 / 2."` as an appended
second line to the card text produced by all three hold-reason templates. This is the only
change to `card.py`. No other logic changes.

**Expected Outcomes:**
- All three `build_card_message` return values now include the instruction line after a newline.
- The `buttons` return value remains `[["Allow", "Decline"]]` unchanged.
- No new imports, no signature change.
- `tests/test_proxy.py` card-text assertions are updated to match the new text.

**Todo List:**

1. In `toolfence/guard/card.py`, update all three text templates to append `"\nTap Allow or Decline, or reply 1 / 2."`:
   - `irreversible`: change `text = "This action is irreversible. Allow or Decline?"` to `text = "This action is irreversible. Allow or Decline?\nTap Allow or Decline, or reply 1 / 2."`
   - `tainted_session`: change `text = f"This came after reading {n} untrusted result(s). Allow or Decline?"` to `text = f"This came after reading {n} untrusted result(s). Allow or Decline?\nTap Allow or Decline, or reply 1 / 2."`
   - `untrusted_argument`: change `text = f"The value of '{arg}' came from an untrusted source. Allow or Decline?"` to `text = f"The value of '{arg}' came from an untrusted source. Allow or Decline?\nTap Allow or Decline, or reply 1 / 2."`
2. In `tests/test_proxy.py`, update the three card-text assertions:
   - `test_card_irreversible`: assert `text == "This action is irreversible. Allow or Decline?\nTap Allow or Decline, or reply 1 / 2."`
   - `test_card_tainted_session`: assert `text == "This came after reading 7 untrusted result(s). Allow or Decline?\nTap Allow or Decline, or reply 1 / 2."`
   - `test_card_untrusted_argument`: assert `text == "The value of 'flight_id' came from an untrusted source. Allow or Decline?\nTap Allow or Decline, or reply 1 / 2."`
3. Run `pytest tests/test_proxy.py -k "card"` and confirm the three card tests are green.

**Relevant Context:**
- `toolfence/guard/card.py` lines 45–57 — the three reason branches with their text strings.
- `tests/test_proxy.py` tests `test_card_irreversible`, `test_card_tainted_session`, `test_card_untrusted_argument` (lines ~232–248).
- No other file needs to change for this sub-task.

---

### TC-AD-2 — Refactor `guard/proxy.py`: replace `on_held`+`ConfirmGrant` with `await_decision`

**Status:** `[ ] pending`
**Depends on:** TC-AD-1 (card text is already updated before this runs)

**Intent:**
Replace the poll-based confirm flow with the push-based `await_decision` async callback.
Remove `ConfirmGrant` from the proxy entirely. The proxy now blocks at the hold point until
Track B's `await_decision` implementation resolves the Future.

This is a **breaking constructor signature change**. After this sub-task, Track B must
update `installer.py` to pass `await_decision=...` instead of `on_held=...` and
`confirm_grant=...`.

**Expected Outcomes:**
- `GuardedProxy.__init__` accepts `await_decision: Callable[[HeldCallEvent], Awaitable[bool]]` as the 6th positional argument (where `on_held` was).
- `confirm_grant: ConfirmGrant` constructor parameter is **removed**.
- `proxy.py` no longer imports `ConfirmGrant` from `guard/confirm.py`.
- `proxy.py` imports `Awaitable` from `typing` (or `collections.abc`).
- `execute` awaits `self._await_decision(event)` on hold; if the result is `True` the tool call proceeds; if `False` the sentinel is returned.
- The old "consume_grant then skip Guard" block (step 1 in current `execute`) is removed.
- All other proxy behaviour (provenance recording, taint, datamark, `__getattr__` forwarding) is unchanged.
- Import boundary is preserved: no nanobot import, no `toolfence.engine` import.

**Todo List:**

1. In `toolfence/guard/proxy.py`:
   a. Add `Awaitable` to the `typing` import: `from typing import Any, Awaitable, Callable`
   b. Remove the import of `ConfirmGrant`: delete `from toolfence.guard.confirm import ConfirmGrant`
   c. Update `GuardedProxy.__init__` signature: replace the `on_held: Callable[[HeldCallEvent], None]` parameter (6th positional) with `await_decision: Callable[[HeldCallEvent], Awaitable[bool]]`. Remove the `confirm_grant: ConfirmGrant` parameter entirely.
   d. In `__init__` body: replace `object.__setattr__(self, "_on_held", on_held)` with `object.__setattr__(self, "_await_decision", await_decision)`. Remove `object.__setattr__(self, "_confirm_grant", confirm_grant)`.
   e. In `execute`:
      - Remove the entire "Step 1 — Check for a pending user-approved confirm grant" block (the `args_hash_for_grant = _compute_hash(params)` / `if self._confirm_grant.consume_grant(...)` block).
      - Keep `args_hash` computation where needed: compute it inside the `if verdict == "hold":` branch as `args_hash = _compute_hash(params)`.
      - In the `if verdict == "hold":` branch, after building `event`:
        - Replace `self._on_held(event)` and `return _HOLD_SENTINEL` with:
          ```python
          allowed: bool = await self._await_decision(event)
          if not allowed:
              return _HOLD_SENTINEL
          # Fall through to step 3 — call the real tool.
          ```
      - After the `if verdict == "hold":` block, the execution falls through to step 3 (call `tool.execute`) when `allowed is True`.
   f. Update the module docstring to reflect the new design (remove references to `ConfirmGrant` and `consume_grant`; add description of `await_decision`).

2. Verify the `_compute_hash` helper is still present and used only inside `execute`.

3. Run `pytest tests/test_proxy.py` — it will fail because the proxy constructor changed. Proceed to TC-AD-3 to update the tests.

**Relevant Context:**
- Current `proxy.py` lines 118–140: `__init__` stores all parameters.
- Current `proxy.py` lines 162–186: the `consume_grant` fast path (to be removed).
- Current `proxy.py` lines 191–235: the `if self._guard_on:` block with the `if verdict == "hold":` branch (to be updated).
- The `_compute_hash` helper at lines 82–85 is still needed inside `execute`.
- `Awaitable` is in `typing` (Python 3.9+); `from typing import Awaitable` is fine.
- Import boundary check: `confirm.py` is no longer imported; double-check `proxy.py` source text has no `"toolfence.guard.confirm"` or `"ConfirmGrant"` after the change.

---

### TC-AD-3 — Update `tests/test_proxy.py` for new `await_decision` interface

**Status:** `[ ] pending`
**Depends on:** TC-AD-2

**Intent:**
All proxy tests use `_make_proxy` which currently passes a `ConfirmGrant()` to the
`GuardedProxy` constructor. The constructor signature has changed — update the helper
and all test cases that test confirm-flow behaviour.

The `_make_proxy` helper now accepts an `await_decision` callable instead of `on_held` +
`ConfirmGrant`. Since `await_decision` is async and returns `bool`, all test cases need
a minimal async stub implementation. Use `asyncio.coroutine`-based helpers or `AsyncMock`.

**Expected Outcomes:**
- All existing proxy tests pass with the new constructor.
- Three new test cases cover `await_decision` return values: `True` → tool called; `False` → sentinel returned.
- The card-text assertions already updated in TC-AD-1 still pass.
- `test_import_checks_proxy` still passes (no nanobot/engine import in `proxy.py`).
- `pytest tests/test_proxy.py` exits 0 with all tests green.

**Todo List:**

1. In `tests/test_proxy.py`, update `_make_proxy` helper:
   a. Remove the `ConfirmGrant()` argument from the `GuardedProxy(...)` call.
   b. Replace the `on_held` / `callback` parameter with an `await_decision` parameter.
   c. The default `await_decision` stub for tests that do not care about it should deny by default (return `False`) so existing hold tests (which expect `_HOLD_SENTINEL`) continue to work without any change to those tests.
      ```python
      async def _default_deny(event: HeldCallEvent) -> bool:
          return False
      ```
   d. Pass `await_decision or _default_deny` as the 6th positional arg to `GuardedProxy`.
   e. Remove the `ConfirmGrant` import from the test file.

2. Add three focused test cases for `await_decision` semantics:

   **`test_await_decision_allow_calls_tool`**
   - Set up an irreversible tool (always held by Guard).
   - Provide an `await_decision` stub that returns `True`.
   - Call `proxy.execute(...)`.
   - Assert `tool.execute` was called once.
   - Assert result equals the tool's return value (not the sentinel).

   **`test_await_decision_deny_returns_sentinel`**
   - Same setup, `await_decision` stub returns `False`.
   - Assert `tool.execute` was NOT called.
   - Assert result contains `"paused"`.

   **`test_await_decision_event_fields`**
   - Capture the `HeldCallEvent` passed to `await_decision` (store it in a list inside the stub).
   - Trigger a hold on an irreversible tool with known params.
   - Assert the event has correct `tool_name`, `reason == "irreversible"`, and correct `arguments_hash`.

3. Remove tests that tested the old `ConfirmGrant` consume-grant fast path
   (`test_proxy_confirm_retry_passes` and `test_proxy_confirm_retry_different_args` in
   `test_confirm.py` test this at the integration level — those are Track C's confirm tests
   but they used the old `consume_grant` path. Decide whether to keep or remove them;
   since `proxy.py` no longer calls `consume_grant`, those tests no longer test proxy
   behaviour. **Keep them in `test_confirm.py` as pure `ConfirmGrant` unit tests** if they
   still pass standalone — but update any proxy-integration tests in `test_confirm.py` that
   used `GuardedProxy` with the old constructor, since the constructor changed.)

4. Run `pytest tests/test_proxy.py -v` and confirm all tests pass.

5. Run `pytest tests/test_confirm.py -v` and confirm the standalone `ConfirmGrant` tests
   still pass (they do not use `GuardedProxy` directly for the pure unit tests).

6. Run `pytest --skip-network -q` to confirm no regressions.

**Relevant Context:**
- `_make_proxy` helper in `tests/test_proxy.py` lines 79–108 — needs updating.
- `test_confirm.py` proxy-integration tests (`test_proxy_confirm_retry_passes`,
  `test_proxy_confirm_retry_different_args`) use the old `GuardedProxy` constructor.
  These must be updated or removed from `test_confirm.py` since the proxy no longer
  uses `confirm_grant`. Keep the pure `ConfirmGrant` unit tests (`test_consume_matching_grant`,
  `test_consume_wrong_args_hash`) — they test `confirm.py` directly.
- `asyncio.run(coro)` pattern used throughout existing tests — use the same `_run()` helper.
- `AsyncMock` from `unittest.mock` can be used for the `await_decision` stub.

---

## Cross-track handoff note (Track C → Track B)

After TC-AD-1 through TC-AD-3 are complete, relay the following to Track B:

### New `GuardedProxy` constructor signature

```python
GuardedProxy(
    tool,
    surface_map,
    provenance,
    taint,
    decision,
    await_decision,  # Callable[[HeldCallEvent], Awaitable[bool]]
                     # replaces on_held + confirm_grant from C-3
    *,
    guard_on: bool = True,
    datamark_on: bool = False,
)
```

### What Track B must update

1. **`toolfence/integration/installer.py`**: The `install_guard` function currently passes
   `on_held` and `confirm_grant` to `GuardedProxy`. It must be updated to pass `await_decision`
   instead. The `await_decision` callable will be implemented in `channel_adapter.py`
   (an async function using asyncio Futures).

2. **`toolfence/integration/channel_adapter.py`** (B-4b):
   - Implement `await_decision(event: HeldCallEvent) -> bool` as an async function.
   - Keep one pending Future per `arguments_hash` (deduplication: same hash reuses the same Future).
   - On Allow (button tap or "1"): resolve the Future with `True` via the single `store_pending` helper.
   - On Decline (button tap or "2"): resolve with `False`.
   - Timeout: 120 s; on timeout, clear the pending Future and resolve with `False`.
   - `store_pending` in `ConfirmGrant` (`guard/confirm.py`) is still used here as the single
     call site for granting — but the proxy no longer polls it.

3. **`scripts/launch_gateway.py`** (B-4b):
   - Pass `await_decision=channel_adapter.await_decision` to `install_guard(...)`.
   - Register the button-tap callback (`wrap_callback_query` / `on_decision(approved: bool)`)
     and the typed-reply fallback in `publish_inbound`.

4. **`tests/test_integration.py`** (Track B):
   - Test Allow and "1" resolve True and grant.
   - Test Decline and "2" resolve False and don't grant.
   - Test other text while pending is answered and not forwarded.
   - Test duplicate hash sends one card.
   - Test timeout resolves False.

### `ConfirmGrant` still exists but proxy no longer uses it

`toolfence/guard/confirm.py` (Track C-owned) is unchanged. `ConfirmGrant.store_pending` is
still the single grant call site used by Track B's `channel_adapter.py`. Track B continues
to import `ConfirmGrant` from `toolfence.guard.confirm`. The difference is that the proxy
no longer imports or calls `ConfirmGrant` — that coordination moved to the `await_decision`
callback owned by Track B.

---

## Validation

After all three sub-tasks:

```powershell
pytest tests/test_proxy.py -v
pytest tests/test_confirm.py -v
pytest tests/test_guard_core.py -v
pytest --skip-network -q
```

All must be green with zero new failures.

Commit message: `feat(guard): TC-AD await_decision interface — proxy, card text`
