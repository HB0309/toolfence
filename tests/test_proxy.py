"""C-2 — GuardedProxy and card message tests.

Covers:
  GRD-1   Stub registry accepts GuardedProxy as drop-in replacement
  GRD-2   Every tool is wrapped (even reads) so provenance is always captured
  GRD-8   tool.execute() is NEVER called when guard_on=True and decision is hold
  GRD-10  datamark applied to untrusted result when datamark_on=True
  GRD-11  Three card message templates produce correct text + [["Allow","Decline"]] buttons
  GRD-12  Read-class tools always pass (even in tainted session, untrusted args)

Test inventory
--------------
  test_hold_blocks_execute                  -- guard_on=True, irreversible → execute not called
  test_hold_returns_paused_sentinel         -- result contains "paused" on hold
  test_held_call_event_fields               -- HeldCallEvent has correct fields
  test_card_irreversible                    -- card template: irreversible
  test_card_tainted_session                 -- card template: tainted_session (N count)
  test_card_untrusted_argument              -- card template: untrusted_argument (arg name)
  test_card_buttons                         -- buttons always [["Allow","Decline"]]
  test_datamark_on_untrusted               -- datamark_on=True marks untrusted result
  test_transparent_passthrough             -- guard_on=False, datamark_on=False: unchanged
  test_datamark_only                        -- guard_on=False, datamark_on=True: mark but no hold
  test_stub_registry_accepts_proxy          -- dict registry accepts GuardedProxy (GRD-1)
  test_read_class_always_passes            -- read class never holds (GRD-12)
  test_provenance_recorded_after_execute   -- record_tool_result called on pass
  test_taint_set_after_untrusted_result    -- taint marked after untrusted read
  test_import_checks_proxy                  -- proxy.py: no nanobot, no LLM, no engine
  test_import_checks_card                   -- card.py: no nanobot, no LLM, no engine
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
from toolfence.guard.card import build_card_message
from toolfence.guard.confirm import ConfirmGrant
from toolfence.guard.datamark import is_datamarked
from toolfence.guard.decision import GuardDecision
from toolfence.guard.provenance import ProvenanceStore
from toolfence.guard.proxy import GuardedProxy
from toolfence.guard.taint import SessionTaint

# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------

_SURFACE_PATH = Path(__file__).parent.parent / "fixtures" / "surface_fixture.json"


def _load_surface() -> SurfaceFile:
    return SurfaceFile.model_validate(json.loads(_SURFACE_PATH.read_text(encoding="utf-8")))


# Tool names from fixture
_IRREVERSIBLE_TOOL = "mcp_galaxium_cancel_booking_endpoint_cancel_booking_id_post"        # irreversible, first-party
_STATE_CHANGING_TOOL = "mcp_galaxium_create_hold_quotes_quote_id_holds_post"              # state-changing, first-party
_READ_TOOL = "mcp_galaxium_get_flights_flights_get"                                       # read, first-party
_UNTRUSTED_READ_TOOL = "mcp_galaxium_get_flight_reviews_flights_flight_id_reviews_get"   # read, untrusted


def _make_tool(name: str, result: str = "ok") -> Any:
    """Return a minimal async tool mock."""
    tool = MagicMock()
    tool.name = name
    tool.schema = {"type": "object", "properties": {}}
    tool.description = f"Mock tool {name}"
    tool.execute = AsyncMock(return_value=result)
    return tool


def _make_proxy(
    tool: Any,
    *,
    surface_map: SurfaceFile | None = None,
    provenance: ProvenanceStore | None = None,
    taint: SessionTaint | None = None,
    decision: GuardDecision | None = None,
    on_held: Any = None,
    guard_on: bool = True,
    datamark_on: bool = False,
) -> tuple[GuardedProxy, list[HeldCallEvent]]:
    """Construct a GuardedProxy with sensible defaults; return (proxy, held_events)."""
    surface = surface_map or _load_surface()
    prov = provenance or ProvenanceStore()
    tnt = taint or SessionTaint()
    dec = decision or GuardDecision()
    held_events: list[HeldCallEvent] = []
    callback = on_held or held_events.append
    proxy = GuardedProxy(
        tool,
        surface,
        prov,
        tnt,
        dec,
        callback,
        ConfirmGrant(),
        guard_on=guard_on,
        datamark_on=datamark_on,
    )
    return proxy, held_events


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# GRD-8 — hold blocks execute
# ---------------------------------------------------------------------------

def test_hold_blocks_execute() -> None:
    """guard_on=True, irreversible tool: tool.execute() must NOT be called."""
    tool = _make_tool(_IRREVERSIBLE_TOOL)
    proxy, _ = _make_proxy(tool, guard_on=True)

    # Irreversible tool always holds regardless of provenance.
    # Supply a user-typed arg so provenance is not the trigger.
    prov = ProvenanceStore()
    prov.record_user_message("BK-001")
    proxy2, _ = _make_proxy(tool, provenance=prov, guard_on=True)

    _run(proxy2.execute(booking_id="BK-001"))

    tool.execute.assert_not_called()


def test_hold_returns_paused_sentinel() -> None:
    """Result contains 'paused' when a call is held."""
    tool = _make_tool(_IRREVERSIBLE_TOOL)
    proxy, _ = _make_proxy(tool, guard_on=True)

    result = _run(proxy.execute(booking_id="X"))

    assert "paused" in result.lower(), f"Expected 'paused' in result, got {result!r}"
    tool.execute.assert_not_called()


# ---------------------------------------------------------------------------
# GRD-8 — HeldCallEvent correctness
# ---------------------------------------------------------------------------

def test_held_call_event_fields() -> None:
    """HeldCallEvent emitted with correct reason, tool_name, and arguments_hash."""
    tool = _make_tool(_IRREVERSIBLE_TOOL)
    proxy, held = _make_proxy(tool, guard_on=True)

    params = {"booking_id": "BK-999"}
    _run(proxy.execute(**params))

    assert len(held) == 1, "Expected exactly one HeldCallEvent"
    ev = held[0]
    assert ev.tool_name == _IRREVERSIBLE_TOOL
    assert ev.reason == "irreversible"
    assert ev.untrusted_arg_name is None
    # arguments_hash must be SHA-256 of json.dumps(params, sort_keys=True)
    import hashlib
    expected_hash = hashlib.sha256(
        json.dumps(params, sort_keys=True).encode()
    ).hexdigest()
    assert ev.arguments_hash == expected_hash


def test_held_call_event_tainted_session() -> None:
    """HeldCallEvent reason='tainted_session' on state-changing call after untrusted read."""
    surface = _load_surface()
    prov = ProvenanceStore()
    tnt = SessionTaint()
    tnt.mark_tainted()  # simulate having already read untrusted result

    tool = _make_tool(_STATE_CHANGING_TOOL)
    proxy, held = _make_proxy(
        tool, surface_map=surface, provenance=prov, taint=tnt, guard_on=True
    )

    # Record arg as user-typed so branch 3 doesn't fire first
    prov.record_user_message("QT-777")
    _run(proxy.execute(quote_id="QT-777"))

    assert len(held) == 1
    ev = held[0]
    assert ev.reason == "tainted_session"
    assert ev.untrusted_arg_name is None


def test_held_call_event_untrusted_argument() -> None:
    """HeldCallEvent reason='untrusted_argument', untrusted_arg_name set correctly."""
    surface = _load_surface()
    prov = ProvenanceStore()
    # Do NOT record the arg in provenance → defaults to "untrusted"
    tnt = SessionTaint()  # not tainted

    tool = _make_tool(_STATE_CHANGING_TOOL)
    proxy, held = _make_proxy(
        tool, surface_map=surface, provenance=prov, taint=tnt, guard_on=True
    )

    _run(proxy.execute(quote_id="UNKNOWN"))

    assert len(held) == 1
    ev = held[0]
    assert ev.reason == "untrusted_argument"
    assert ev.untrusted_arg_name == "quote_id"


# ---------------------------------------------------------------------------
# GRD-11 — card message templates
# ---------------------------------------------------------------------------

def _make_event(
    reason: str,
    untrusted_read_count: int = 3,
    untrusted_arg_name: str | None = "booking_id",
) -> HeldCallEvent:
    return HeldCallEvent(
        tool_name="some_tool",
        arguments={"booking_id": "BK-1"},
        arguments_hash="abc123",
        reason=reason,  # type: ignore[arg-type]
        untrusted_read_count=untrusted_read_count,
        untrusted_arg_name=untrusted_arg_name,
    )


def test_card_irreversible() -> None:
    """Card template for 'irreversible' reason."""
    text, buttons = build_card_message(_make_event("irreversible"))
    assert text == "This action is irreversible. Allow or Decline?"


def test_card_tainted_session() -> None:
    """Card template for 'tainted_session' reason includes count."""
    text, buttons = build_card_message(_make_event("tainted_session", untrusted_read_count=7))
    assert text == "This came after reading 7 untrusted result(s). Allow or Decline?"


def test_card_untrusted_argument() -> None:
    """Card template for 'untrusted_argument' reason includes arg name."""
    text, buttons = build_card_message(_make_event("untrusted_argument", untrusted_arg_name="flight_id"))
    assert text == "The value of 'flight_id' came from an untrusted source. Allow or Decline?"


def test_card_buttons() -> None:
    """Buttons are always [['Allow', 'Decline']] regardless of reason."""
    for reason in ("irreversible", "tainted_session", "untrusted_argument"):
        _, buttons = build_card_message(_make_event(reason))
        assert buttons == [["Allow", "Decline"]], (
            f"Expected [['Allow','Decline']] for reason={reason!r}, got {buttons!r}"
        )


# ---------------------------------------------------------------------------
# GRD-10 — datamark on untrusted result
# ---------------------------------------------------------------------------

def test_datamark_on_untrusted() -> None:
    """datamark_on=True: untrusted tool result is datamarked before return."""
    raw_result = "Review: excellent flight."
    tool = _make_tool(_UNTRUSTED_READ_TOOL, result=raw_result)
    proxy, _ = _make_proxy(tool, guard_on=True, datamark_on=True)

    result = _run(proxy.execute(flight_id="F1"))

    assert is_datamarked(result), "Expected result to be datamarked"
    assert raw_result in result, "Original content must be preserved inside datamark"


def test_datamark_not_applied_to_first_party() -> None:
    """datamark_on=True: first-party tool result is NOT datamarked."""
    raw_result = "flight list"
    tool = _make_tool(_READ_TOOL, result=raw_result)
    proxy, _ = _make_proxy(tool, guard_on=False, datamark_on=True)

    result = _run(proxy.execute())

    assert not is_datamarked(result), "First-party result must not be datamarked"
    assert result == raw_result


# ---------------------------------------------------------------------------
# Transparent pass-through and datamark-only mode
# ---------------------------------------------------------------------------

def test_transparent_passthrough() -> None:
    """guard_on=False, datamark_on=False: result passes through completely unchanged."""
    raw_result = "some first-party data"
    tool = _make_tool(_READ_TOOL, result=raw_result)
    proxy, held = _make_proxy(tool, guard_on=False, datamark_on=False)

    result = _run(proxy.execute())

    assert result == raw_result
    assert held == []
    tool.execute.assert_called_once()


def test_datamark_only_mode() -> None:
    """guard_on=False, datamark_on=True: untrusted result datamarked, no hold."""
    raw_result = "untrusted review data"
    tool = _make_tool(_UNTRUSTED_READ_TOOL, result=raw_result)
    proxy, held = _make_proxy(tool, guard_on=False, datamark_on=True)

    result = _run(proxy.execute(flight_id="F2"))

    # No hold emitted
    assert held == []
    # tool.execute called
    tool.execute.assert_called_once()
    # Result is datamarked
    assert is_datamarked(result)


# ---------------------------------------------------------------------------
# GRD-1 — stub registry accepts proxy
# ---------------------------------------------------------------------------

def test_stub_registry_accepts_proxy() -> None:
    """A plain dict registry accepts GuardedProxy as a drop-in for a raw tool (GRD-1)."""
    tool = _make_tool(_READ_TOOL)
    proxy, _ = _make_proxy(tool, guard_on=True)

    # Build a dict registry keyed by tool name.
    registry: dict[str, Any] = {proxy.name: proxy}

    assert proxy.name in registry
    assert registry[proxy.name] is proxy
    # Proxy exposes .name, .schema, .description like the original tool.
    assert registry[proxy.name].name == _READ_TOOL
    assert registry[proxy.name].schema is not None
    assert registry[proxy.name].description is not None


# ---------------------------------------------------------------------------
# GRD-12 — read always passes
# ---------------------------------------------------------------------------

def test_read_class_always_passes() -> None:
    """Read-class tool never holds — even in tainted session with untrusted arg (GRD-12)."""
    tnt = SessionTaint()
    tnt.mark_tainted()  # fully tainted session
    prov = ProvenanceStore()
    # arg not recorded → untrusted

    tool = _make_tool(_READ_TOOL, result="flights data")
    proxy, held = _make_proxy(tool, provenance=prov, taint=tnt, guard_on=True)

    result = _run(proxy.execute(origin="CDG"))  # arg is untrusted

    assert held == [], "Read-class tool must never hold"
    tool.execute.assert_called_once()
    assert result == "flights data"


# ---------------------------------------------------------------------------
# Provenance and taint side effects
# ---------------------------------------------------------------------------

def test_provenance_recorded_after_execute() -> None:
    """After execute, result tokens are findable via provenance store."""
    prov = ProvenanceStore()
    tool = _make_tool(_READ_TOOL, result="flight123")
    proxy, _ = _make_proxy(tool, provenance=prov, guard_on=False)

    _run(proxy.execute())

    # "flight123" was returned by a first-party tool — should resolve as first-party
    label = prov.resolve_argument("flight123")
    assert label == "first-party"


def test_taint_set_after_untrusted_result() -> None:
    """After reading an untrusted tool result, session is marked tainted."""
    tnt = SessionTaint()
    assert not tnt.is_tainted()

    tool = _make_tool(_UNTRUSTED_READ_TOOL, result="review content")
    proxy, _ = _make_proxy(tool, taint=tnt, guard_on=True)

    _run(proxy.execute(flight_id="F3"))

    assert tnt.is_tainted(), "Session must be tainted after reading untrusted result"


def test_untrusted_read_count_tracked() -> None:
    """untrusted_read_count in HeldCallEvent reflects the session-wide count.

    Two separate proxy instances share the same SessionTaint.  The read proxy
    reads one untrusted result; the state-changing proxy then gets held.
    The HeldCallEvent.untrusted_read_count must be 1 (not 0) because both
    proxies share the taint object that holds the counter.
    """
    tnt = SessionTaint()
    prov = ProvenanceStore()
    surface = _load_surface()

    # First: read an untrusted result via the read proxy.
    read_tool = _make_tool(_UNTRUSTED_READ_TOOL, result="review data")
    read_proxy, _ = _make_proxy(
        read_tool, surface_map=surface, provenance=prov, taint=tnt,
        guard_on=True, datamark_on=False
    )
    _run(read_proxy.execute(flight_id="F4"))

    # Verify the shared taint object recorded the read.
    assert tnt.untrusted_read_count == 1, "SessionTaint must record the untrusted read"

    # Now trigger a hold on the state-changing tool (session is tainted).
    state_tool = _make_tool(_STATE_CHANGING_TOOL)
    prov.record_user_message("QT-123")
    held: list[HeldCallEvent] = []
    state_proxy = GuardedProxy(
        state_tool, surface, prov, tnt, GuardDecision(), held.append, ConfirmGrant(), guard_on=True
    )
    _run(state_proxy.execute(quote_id="QT-123"))

    assert len(held) == 1
    assert held[0].reason == "tainted_session"
    # The count on the event must reflect the session-wide counter (1), not the
    # state_proxy's own per-instance counter (which would have been 0 under the old bug).
    assert held[0].untrusted_read_count == 1, (
        "HeldCallEvent.untrusted_read_count must reflect session-wide count via shared taint"
    )


# ---------------------------------------------------------------------------
# __getattr__ forwarding
# ---------------------------------------------------------------------------

def test_getattr_forwarding() -> None:
    """GuardedProxy forwards unknown attribute lookups to the wrapped tool."""
    tool = _make_tool(_READ_TOOL)
    tool.read_only = True  # custom attribute
    proxy, _ = _make_proxy(tool)

    assert proxy.read_only is True  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Import boundary checks
# ---------------------------------------------------------------------------

def _check_no_forbidden_imports(src: Path, label: str) -> None:
    """Assert that *src* contains no import statements for forbidden packages.

    Checks for ``import <pkg>`` and ``from <pkg>`` patterns only — docstring
    mentions of a package name are not import violations.
    """
    source_text = src.read_text(encoding="utf-8")
    # Packages that must never be imported from guard/ modules.
    forbidden_import_roots = [
        "nanobot",
        "toolfence.engine",
        "openai",
        "anthropic",
        "cohere",
        "google.generativeai",
        "litellm",
    ]
    for pkg in forbidden_import_roots:
        assert f"import {pkg}" not in source_text, (
            f"{label} must not contain 'import {pkg}' (import boundary violation)"
        )
        assert f"from {pkg}" not in source_text, (
            f"{label} must not contain 'from {pkg}' (import boundary violation)"
        )


def test_import_checks_proxy() -> None:
    """guard/proxy.py must not import nanobot, any LLM client, or toolfence.engine."""
    src = Path(__file__).parent.parent / "toolfence" / "guard" / "proxy.py"
    _check_no_forbidden_imports(src, "guard/proxy.py")


def test_import_checks_card() -> None:
    """guard/card.py must not import nanobot, any LLM client, or toolfence.engine."""
    src = Path(__file__).parent.parent / "toolfence" / "guard" / "card.py"
    _check_no_forbidden_imports(src, "guard/card.py")


# ---------------------------------------------------------------------------
# await_decision optional kwarg tests
# ---------------------------------------------------------------------------

def test_await_decision_allow_calls_tool() -> None:
    """await_decision=True + matching grant → tool.execute() called, real result returned."""
    tool = _make_tool(_IRREVERSIBLE_TOOL, result="booking cancelled")
    cg = ConfirmGrant()
    held: list[HeldCallEvent] = []

    async def _allow(event: HeldCallEvent) -> bool:
        # Simulate Track B storing the grant when it calls await_decision.
        cg.store_pending(event.tool_name, event.arguments_hash)
        return True

    proxy = GuardedProxy(
        tool,
        _load_surface(),
        ProvenanceStore(),
        SessionTaint(),
        GuardDecision(),
        held.append,
        cg,
        guard_on=True,
        await_decision=_allow,
    )

    result = _run(proxy.execute(booking_id="BK-1"))
    assert result == "booking cancelled", f"Expected real result, got {result!r}"
    tool.execute.assert_called_once()
    assert len(held) == 1, "on_held must still be called even when await_decision is provided"


def test_await_decision_deny_returns_decline_sentinel() -> None:
    """await_decision=False → tool not called, decline sentinel returned."""
    tool = _make_tool(_IRREVERSIBLE_TOOL)
    cg = ConfirmGrant()
    held: list[HeldCallEvent] = []

    async def _deny(event: HeldCallEvent) -> bool:
        return False

    proxy = GuardedProxy(
        tool,
        _load_surface(),
        ProvenanceStore(),
        SessionTaint(),
        GuardDecision(),
        held.append,
        cg,
        guard_on=True,
        await_decision=_deny,
    )

    result = _run(proxy.execute(booking_id="BK-2"))
    assert "Declined" in result, f"Expected decline sentinel, got {result!r}"
    assert "Do not retry" in result, f"Expected retry instruction in sentinel, got {result!r}"
    tool.execute.assert_not_called()


def test_await_decision_allow_but_grant_not_stored_returns_decline() -> None:
    """await_decision=True but consume_grant fails (grant not stored) → decline sentinel."""
    tool = _make_tool(_IRREVERSIBLE_TOOL)
    cg = ConfirmGrant()  # nothing stored
    held: list[HeldCallEvent] = []

    async def _allow_without_storing(event: HeldCallEvent) -> bool:
        return True  # returns True but forgot to store_pending

    proxy = GuardedProxy(
        tool,
        _load_surface(),
        ProvenanceStore(),
        SessionTaint(),
        GuardDecision(),
        held.append,
        cg,
        guard_on=True,
        await_decision=_allow_without_storing,
    )

    result = _run(proxy.execute(booking_id="BK-3"))
    assert "Declined" in result, f"Expected decline sentinel when grant missing, got {result!r}"
    tool.execute.assert_not_called()


def test_no_await_decision_returns_hold_sentinel() -> None:
    """Without await_decision (None), the original hold sentinel is returned unchanged."""
    tool = _make_tool(_IRREVERSIBLE_TOOL)
    proxy, held = _make_proxy(tool, guard_on=True)

    result = _run(proxy.execute(booking_id="BK-4"))
    assert "paused" in result.lower(), f"Expected hold sentinel, got {result!r}"
    tool.execute.assert_not_called()
    assert len(held) == 1
