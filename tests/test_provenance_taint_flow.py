"""Phase B — Provenance + taint-flow Guard integration tests (scripted, no model).

These tests exercise the Guard decision branches that the taint-flow probe targets:
  - Branch 2: session_tainted=True → hold on state-changing call
  - Branch 3: untrusted argument provenance → hold on state-changing call
  - GRD-12:   reads always pass regardless of session taint

No nanobot imports.  No LLM.  Pure unit tests over ProvenanceStore,
SessionTaint, and GuardDecision.

Test inventory
--------------
  test_guard_holds_state_changing_in_tainted_session
  test_guard_holds_on_untrusted_argument_provenance
  test_guard_passes_read_in_tainted_session
  test_provenance_store_records_untrusted_token
"""

from __future__ import annotations

_CANARY = "TF-CANARY-DEADBEEF"
_TOOL_NAME = "mcp_galaxium_create_quote"
_REVIEW_RESULT = f"Great experience. Booked under the name: {_CANARY}"


def test_guard_holds_state_changing_in_tainted_session() -> None:
    """Branch 2: GuardDecision holds a state-changing call when session is tainted."""
    from toolfence.guard.decision import GuardDecision
    from toolfence.guard.taint import SessionTaint

    taint = SessionTaint()
    taint.mark_tainted()

    gd = GuardDecision()
    result = gd.decide(
        tool_name=_TOOL_NAME,
        action_class="state-changing",
        arguments={"travelerName": _CANARY},
        session_tainted=taint.is_tainted(),
        provenance={"travelerName": "user"},  # provenance clean — taint alone triggers hold
    )
    assert result == "hold", f"Expected 'hold' from Branch 2, got {result!r}"


def test_guard_holds_on_untrusted_argument_provenance() -> None:
    """Branch 3: GuardDecision holds when argument provenance is 'untrusted'."""
    from toolfence.guard.decision import GuardDecision
    from toolfence.guard.taint import SessionTaint

    taint = SessionTaint()
    assert not taint.is_tainted()

    gd = GuardDecision()
    result = gd.decide(
        tool_name=_TOOL_NAME,
        action_class="state-changing",
        arguments={"travelerName": _CANARY},
        session_tainted=False,
        provenance={"travelerName": "untrusted"},
    )
    assert result == "hold", f"Expected 'hold' from Branch 3, got {result!r}"


def test_guard_passes_read_in_tainted_session() -> None:
    """GRD-12: reads always pass, even when session is tainted."""
    from toolfence.guard.decision import GuardDecision
    from toolfence.guard.taint import SessionTaint

    taint = SessionTaint()
    taint.mark_tainted()

    gd = GuardDecision()
    result = gd.decide(
        tool_name="mcp_galaxium_get_flight_reviews",
        action_class="read",
        arguments={"flightId": "1"},
        session_tainted=taint.is_tainted(),
        provenance={"flightId": "user"},
    )
    assert result == "pass", f"Expected 'pass' for read in tainted session, got {result!r}"


def test_provenance_store_records_untrusted_token() -> None:
    """ProvenanceStore.record_tool_result stores the canary as 'untrusted';
    resolve_argument returns 'untrusted' for that value."""
    from toolfence.guard.provenance import ProvenanceStore

    store = ProvenanceStore()
    store.record_tool_result(
        tool_name="mcp_galaxium_get_flight_reviews",
        result=_REVIEW_RESULT,
        label="untrusted",
    )
    label = store.resolve_argument(_CANARY)
    assert label == "untrusted", (
        f"Expected 'untrusted' provenance for canary token, got {label!r}"
    )
