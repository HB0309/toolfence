# AGENTS.md — Agent mode (coding)

This file provides guidance to agents when working with code in this repository.

## Hard import rules

- `toolfence/guard/` — zero nanobot imports, zero `toolfence.engine` imports. Tests enforce both with source-text checks.
- `toolfence/engine/verdict.py` and `scoring.py` — zero LLM client imports. Test checks for: `openai`, `anthropic`, `cohere`, `google.generativeai`, `litellm`.
- New Guard modules follow the same rule: if you add a file to `guard/`, add an import-check assertion in its test.

## Adding a new file

- Every new module gets a test file `tests/test_<module>.py`.
- Import-boundary tests check the source file text directly (not via `importlib`) — see `tests/test_datamark.py::test_datamark_no_engine_import` for the pattern.
- JSON Schemas are generated, never hand-edited. After changing a Pydantic model in `contracts/`, run `python scripts/generate_schemas.py` and commit the updated `.json`.

## GuardedProxy interface (C-2) — what Track B expects

Track B (`integration/installer.py`) wraps tools from nanobot's registry. It expects `GuardedProxy` to expose:
- `.name` (str property)
- `.schema` (any, optional)
- `.description` (str | None)
- `async execute(**params)` — signature must match `ProxyStub` in `contracts/guard.py`
- `__getattr__` forwarding for anything else

The `ProxyStub` in `contracts/guard.py` is the reference shape. `GuardedProxy` must be a drop-in replacement.

## Confirm grant flow (C-3)

`ConfirmGrant.consume_grant(tool_name, args_hash)` takes **no `source` parameter**. There is no `__source__` kwarg; `GuardedProxy.execute` does not pop any source key from params.

Approval comes exclusively from a Telegram inline-keyboard button tap:
1. `wrap_callback_query` (in `toolfence/integration/channel_adapter.py`) intercepts `TelegramChannel._on_callback_query` and calls `DecisionGate.resolve(True)` on a matching Allow tap.
2. `DecisionGate.await_decision` waits up to 120 s for that resolution; when `True` it calls `confirm_grant.store_pending(tool_name, args_hash)` — **this is the only `store_pending` call site in `toolfence/integration/`**.
3. `GuardedProxy.execute` awaits `await_decision` (passed in at construction time from the gateway launcher) and then calls `confirm_grant.consume_grant` to complete the grant.

`ConfirmGrant` has zero knowledge of button labels or "Allow"/"Decline" strings.

## nanobot reconnect re-wrap (GRD-3)

Track B's `installer.py` handles re-wrapping after MCP reconnect. When editing `guard/proxy.py`, do not assume the proxy instance persists across reconnects — the installer re-creates proxies from scratch on reconnect.

## Verdict priority order (already implemented — do not change)

`assign_verdict` in `engine/verdict.py`: inconclusive → leaked → held → refused. Do not change the order.
