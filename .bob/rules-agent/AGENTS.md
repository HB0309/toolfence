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

## Confirm grant source checking (C-3)

`ConfirmGrant.consume_grant` must check `source == "user"`. A grant that arrives as a tool result (`source == "first-party"` or `"untrusted"`) must be **rejected**.

Grant detection is **button-click based, not button-label based.** Track B's launcher detects the native click callback (Telegram `_on_callback_query`) and calls `confirm_grant.store_pending(tool_name, args_hash)` directly. `ConfirmGrant` has zero knowledge of "Allow" / "Decline" strings.

The `source` kwarg in `GuardedProxy.execute` is extracted from `**params` using the key `"__source__"` (double-underscore prefix) to avoid collision with real tool parameters:
```python
source = params.pop("__source__", "first-party")
```
Track B passes `"__source__": "user"` in the kwargs when the trigger is a button-click callback.

## nanobot reconnect re-wrap (GRD-3)

Track B's `installer.py` handles re-wrapping after MCP reconnect. When editing `guard/proxy.py`, do not assume the proxy instance persists across reconnects — the installer re-creates proxies from scratch on reconnect.

## Verdict priority order (already implemented — do not change)

`assign_verdict` in `engine/verdict.py`: inconclusive → leaked → held → refused. Do not change the order.
