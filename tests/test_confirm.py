"""C-3 — ConfirmGrant and GuardedProxy confirm-flow tests (GRD-9).

Test inventory
--------------
  test_consume_matching_user_grant           -- store then consume with source="user" → True, consumed
  test_consume_wrong_args_hash               -- store then consume with wrong hash → False, not consumed
  test_consume_wrong_source                  -- store then consume with source="first-party" → False
  test_proxy_confirm_retry_passes            -- hold → store_pending → retry __source__="user" → execute called
  test_proxy_confirm_retry_different_args    -- hold → retry different args → hold again, execute not called
  test_import_check_confirm                  -- confirm.py: no nanobot, no LLM, no engine, no button labels
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from toolfence.contracts.guard import HeldCallEvent
from toolfence.contracts.surface import SurfaceFile
from toolfence.guard.confirm import ConfirmGrant
from toolfence.guard.decision import GuardDecision
from toolfence.guard.provenance import ProvenanceStore
from toolfence.guard.proxy import GuardedProxy
from toolfence.guard.taint import SessionTaint

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SURFACE_PATH = Path(__file__).parent.parent / "fixtures" / "surface_fixture.json"

# An irreversible tool — always held by Guard regardless of provenance.
_IRREVERSIBLE_TOOL = "mcp_galaxium_cancel_booking__booking_id__post"


def _load_surface() -> SurfaceFile:
    return SurfaceFile.model_validate(json.loads(_SURFACE_PATH.read_text(encoding="utf-8")))


def _make_tool(name: str, result: str = "ok") -> Any:
    tool = MagicMock()
    tool.name = name
    tool.schema = {"type": "object"}
    tool.description = f"Mock {name}"
    tool.execute = AsyncMock(return_value=result)
    return tool


def _make_proxy(
    tool: Any,
    confirm_grant: ConfirmGrant,
    *,
    guard_on: bool = True,
) -> tuple[GuardedProxy, list[HeldCallEvent]]:
    surface = _load_surface()
    prov = ProvenanceStore()
    tnt = SessionTaint()
    dec = GuardDecision()
    held: list[HeldCallEvent] = []
    proxy = GuardedProxy(
        tool,
        surface,
        prov,
        tnt,
        dec,
        held.append,
        confirm_grant,
        guard_on=guard_on,
    )
    return proxy, held


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _args_hash(params: dict[str, Any]) -> str:
    """Compute the same SHA-256 hash that GuardedProxy uses."""
    import hashlib
    canonical = json.dumps(params, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Test 1 — matching user grant is consumed once, second call returns False
# ---------------------------------------------------------------------------

def test_consume_matching_user_grant() -> None:
    """store_pending then consume_grant with matching data and source='user' → True.
    A second call with the same data → False (grant is consumed and cleared).
    """
    cg = ConfirmGrant()
    cg.store_pending("my_tool", "abc123")

    result = cg.consume_grant("my_tool", "abc123", source="user")
    assert result is True, "Expected True for matching user grant"

    # Grant is cleared — second attempt must fail.
    result2 = cg.consume_grant("my_tool", "abc123", source="user")
    assert result2 is False, "Expected False — grant was already consumed"


# ---------------------------------------------------------------------------
# Test 2 — wrong args_hash → False, grant not consumed
# ---------------------------------------------------------------------------

def test_consume_wrong_args_hash() -> None:
    """store_pending then consume_grant with a different args_hash → False.
    The stored grant must not be cleared on mismatch.
    """
    cg = ConfirmGrant()
    cg.store_pending("my_tool", "correct_hash")

    result = cg.consume_grant("my_tool", "wrong_hash", source="user")
    assert result is False, "Expected False for args_hash mismatch"

    # Grant still valid — correct hash should succeed now.
    result2 = cg.consume_grant("my_tool", "correct_hash", source="user")
    assert result2 is True, "Grant should still be pending after failed attempt"


# ---------------------------------------------------------------------------
# Test 3 — wrong source → False
# ---------------------------------------------------------------------------

def test_consume_wrong_source() -> None:
    """store_pending then consume_grant with source='first-party' → False.
    A tool-result-driven retry must not be able to consume the grant.
    """
    cg = ConfirmGrant()
    cg.store_pending("my_tool", "abc123")

    # Simulate a tool-driven retry (not a user button-click).
    result = cg.consume_grant("my_tool", "abc123", source="first-party")
    assert result is False, "Expected False: source='first-party' must not consume grant"

    # Grant still valid — a user click should still work.
    result2 = cg.consume_grant("my_tool", "abc123", source="user")
    assert result2 is True, "Grant should still be pending after rejected non-user attempt"


# ---------------------------------------------------------------------------
# Test 4 — proxy integration: hold → store_pending → retry with __source__="user"
# ---------------------------------------------------------------------------

def test_proxy_confirm_retry_passes() -> None:
    """Full integration: Guard holds the call, Track B stores a pending grant,
    then retries with __source__='user' → tool.execute() is called, result returned.
    """
    cg = ConfirmGrant()
    tool = _make_tool(_IRREVERSIBLE_TOOL, result="booking cancelled")
    proxy, held = _make_proxy(tool, cg, guard_on=True)

    params = {"booking_id": "BK-42"}

    # First call — should be held.
    result1 = _run(proxy.execute(**params))
    assert "paused" in result1.lower(), f"Expected hold sentinel, got {result1!r}"
    tool.execute.assert_not_called()
    assert len(held) == 1, "Expected one HeldCallEvent"

    # Track B stores the pending grant using the hash from the HeldCallEvent.
    ev = held[0]
    cg.store_pending(ev.tool_name, ev.arguments_hash)

    # Retry with __source__="user" — grant should be consumed, execute called.
    result2 = _run(proxy.execute(**params, __source__="user"))
    assert result2 == "booking cancelled", f"Expected real result, got {result2!r}"
    tool.execute.assert_called_once()


# ---------------------------------------------------------------------------
# Test 5 — proxy integration: hold → retry with different args → hold again
# ---------------------------------------------------------------------------

def test_proxy_confirm_retry_different_args() -> None:
    """If retried with different arguments (different hash), Guard holds again.
    tool.execute() must NOT be called.
    """
    cg = ConfirmGrant()
    tool = _make_tool(_IRREVERSIBLE_TOOL, result="booking cancelled")
    proxy, held = _make_proxy(tool, cg, guard_on=True)

    original_params = {"booking_id": "BK-42"}

    # First call — held.
    _run(proxy.execute(**original_params))
    tool.execute.assert_not_called()
    assert len(held) == 1

    ev = held[0]
    # Store a grant for the original hash.
    cg.store_pending(ev.tool_name, ev.arguments_hash)

    # Retry with DIFFERENT arguments — hash won't match stored grant.
    different_params = {"booking_id": "BK-99"}
    result = _run(proxy.execute(**different_params, __source__="user"))
    assert "paused" in result.lower(), (
        f"Expected hold sentinel for different args, got {result!r}"
    )
    tool.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Test 6 — import boundary: confirm.py has no nanobot, no LLM, no engine,
#           no button-label strings ("Allow", "Decline")
# ---------------------------------------------------------------------------

def test_import_check_confirm() -> None:
    """guard/confirm.py must not import nanobot, any LLM client, or toolfence.engine.
    It must also contain no button-label string literals ("Allow" / "Decline").
    """
    src = Path(__file__).parent.parent / "toolfence" / "guard" / "confirm.py"
    source_text = src.read_text(encoding="utf-8")

    forbidden_imports = [
        "nanobot",
        "toolfence.engine",
        "openai",
        "anthropic",
        "cohere",
        "google.generativeai",
        "litellm",
    ]
    for pkg in forbidden_imports:
        assert f"import {pkg}" not in source_text, (
            f"confirm.py must not contain 'import {pkg}' (import boundary violation)"
        )
        assert f"from {pkg}" not in source_text, (
            f"confirm.py must not contain 'from {pkg}' (import boundary violation)"
        )

    # No button-label knowledge in ConfirmGrant.
    assert '"Allow"' not in source_text, (
        "confirm.py must not contain button-label string 'Allow'"
    )
    assert '"Decline"' not in source_text, (
        "confirm.py must not contain button-label string 'Decline'"
    )
    assert "'Allow'" not in source_text, (
        "confirm.py must not contain button-label string 'Allow'"
    )
    assert "'Decline'" not in source_text, (
        "confirm.py must not contain button-label string 'Decline'"
    )
