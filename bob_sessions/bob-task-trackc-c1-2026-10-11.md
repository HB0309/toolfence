# Track C — Session 1: AGENTS.md + Plan + C-1 Guard Core

**Status:** complete  **Date:** 2026-10-11  **Track:** C  **Branch:** TrackC

---

## Session goal

1. Analyse the codebase, produce `AGENTS.md` and mode-specific guidance files.
2. Write the Track C implementation plan (`docs/track-c-plan.md`).
3. Implement and verify C-1: `decision.py`, `provenance.py`, `taint.py`, `tests/test_guard_core.py`.

---

## What was confirmed about the codebase state

| Task | Status at session start |
|---|---|
| S-1 – S-4 (shared base) | ✅ Done — pyproject, contracts, schemas, fixtures, ScriptedAdapter |
| A-1 Surface scanner | ✅ Done |
| A-2 Canary + probe builder | ✅ Done |
| A-3 Datamarking (`guard/datamark.py`) | ✅ Done — written by Track A; Track C now owns it |
| A-4 Verdict / scoring / report | ⚠️ Code exists and is functionally complete; Track A developer has an open test-suite bug. Do NOT touch. |
| A-5 `runner.py` | ❌ Not started |
| All C-tasks | ❌ Not started at session open |

---

## Files created this session

### Documentation / guidance

| File | Purpose |
|---|---|
| `AGENTS.md` | Project-wide: commands, component boundaries, what's implemented, non-obvious patterns |
| `.bob/rules-agent/AGENTS.md` | Coding rules: import boundaries, proxy interface contract, `__source__` kwarg, confirm flow |
| `.bob/rules-ask/AGENTS.md` | Where docs live; counterintuitive nanobot config and target facts |
| `.bob/rules-plan/AGENTS.md` | Track C ownership, pending dependencies, locked architectural decisions |
| `docs/track-c-plan.md` | Full Track C plan: scope, dependencies, C-1/C-2/C-3 specs, cross-track handoffs, session start prompts, general agent notes |

### C-1 implementation

| File | What it does |
|---|---|
| `toolfence/guard/decision.py` | `GuardDecision.decide()` — four-branch rule (GRD-7, GRD-12) |
| `toolfence/guard/provenance.py` | `ProvenanceStore` — value recording + provenance resolution (GRD-4, GRD-6) |
| `toolfence/guard/taint.py` | `SessionTaint` — one-way flag, never clears (GRD-5) |
| `tests/test_guard_core.py` | 37 tests; all pass |

---

## Test result

```
37 passed in 0.26s   (tests/test_guard_core.py)
156 passed in 1.14s  (all other tests — no regressions)
```

---

## Bugs found and fixed during C-1

### Bug 1 — Import-check false positives in tests
**Symptom:** `test_no_nanobot_import_in_decision` failed because the word "nanobot"
appears in the module docstring ("no nanobot imports").
**Fix:** `_import_lines()` helper in `test_guard_core.py` filters to only
`import …` / `from …` lines before asserting. This pattern must be used in all future
Guard import-boundary tests (C-2, C-3).

### Bug 2 — JSON punctuation attached to provenance tokens
**Symptom:** `record_tool_result` called with a JSON string like
`'{"user_id": 1, "name": "Alice"}'` stored tokens as `'"Alice"}'` and `'1,'`
(punctuation attached), so `resolve_argument("Alice")` returned `"untrusted"`.
**Fix:** Added `_extract_tokens(text)` + `_JSON_STRIP_CHARS` to `provenance.py`.
Tokens are stripped of `{}[]",: \t\r\n` on both sides before storage.
**Note for Track B:** any tool result in JSON format will now have values correctly
extracted; the ProvenanceStore handles this transparently.

---

## Design decisions locked this session

| Decision | Resolution |
|---|---|
| `source` kwarg key in `proxy.execute` | `__source__` (dunder prefix) — popped from `**params` to avoid collision with real tool parameters |
| Button-click vs button-label grant detection | `ConfirmGrant` has zero knowledge of "Allow"/"Decline" strings; Track B's launcher calls `store_pending(tool_name, args_hash)` on the native callback event only |
| `confirm_grant.store_pending` caller | Track B's launcher calls it directly after detecting a native button-click callback |
| All tools wrapped (not just `mcp_*`) | `GuardedProxy` wraps every tool including `read_file` and built-ins; reads always pass (GRD-12) |

---

## Cross-track handoff state after this session

- **Track B** can now read `guard/decision.py`, `guard/provenance.py`, `guard/taint.py` to understand the interfaces they will call from `integration/installer.py`.
- **Track B** should wait for C-2 before starting B-3 in earnest (C-2 delivers `GuardedProxy` — the actual wrapper class).
- **Track A** A-4 bug remains open — do not touch, do not attempt to fix.

---

## Next session

**Session 2 — C-2: GuardedProxy and card message**

Copy-paste start prompt from `docs/track-c-plan.md §Session 2`:

> Read `docs/track-c-plan.md` in full. C-1 is complete (decision.py, provenance.py, taint.py
> exist and their tests pass). Implement sub-task C-2 exactly as specified:
> create `toolfence/guard/card.py` and `toolfence/guard/proxy.py` (C-2 version — no
> `confirm_grant` parameter yet; that is added in C-3), and `tests/test_proxy.py`.
> Run `pytest tests/test_proxy.py` and confirm green before finishing.
> Do not touch C-1 files unless a genuine bug is found (if so, also re-run test_guard_core.py).

**Files Session 2 will create:**
- `toolfence/guard/card.py` — new
- `toolfence/guard/proxy.py` — new (C-2 version, no `confirm_grant` yet)
- `tests/test_proxy.py` — new

**After Session 2:** post the C-2 `GuardedProxy` constructor signature to Track B.

**Git commit for this session:** `feat(guard): C-1 Guard core — decision, provenance, taint`
