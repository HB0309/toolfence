"""S-4 — ScriptedAdapter tests.

Runs the full adapter_contract suite against ScriptedAdapter backed by
fixture_3call.json, then adds ScriptedAdapter-specific checks:

  - Correct number and order of tool calls.
  - Result and error fields match the fixture exactly.
  - status and final_reply match the fixture.
  - Determinism: same fixture → same Trace on every replay.
  - Error fixture: status == "error", error field preserved verbatim.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from toolfence.engine.adapter import ScriptedAdapter

from adapter_contract import run_adapter_contract

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent
PROBES_DIR = REPO_ROOT / "fixtures" / "probes"
FIXTURE_3CALL = PROBES_DIR / "fixture_3call.json"
FIXTURE_ERROR = PROBES_DIR / "fixture_error.json"


# ---------------------------------------------------------------------------
# Contract suite
# ---------------------------------------------------------------------------

def test_scripted_adapter_passes_contract() -> None:
    """ScriptedAdapter satisfies every clause in the adapter contract."""
    adapter = ScriptedAdapter(FIXTURE_3CALL)
    run_adapter_contract(adapter)


# ---------------------------------------------------------------------------
# Fixture content checks
# ---------------------------------------------------------------------------

def test_three_calls_in_order() -> None:
    """The 3-call fixture replays exactly 3 tool calls in fixture order."""
    adapter = ScriptedAdapter(FIXTURE_3CALL)
    trace = adapter.run_turn("any prompt", "none")

    assert len(trace.tool_calls) == 3

    expected_names = [
        "mcp_galaxium_get_flights_flights_get",
        "mcp_galaxium_create_quote_quotes_post",
        "mcp_galaxium_create_hold_quotes_quote_id_holds_post",
    ]
    for i, (call, name) in enumerate(zip(trace.tool_calls, expected_names)):
        assert call.name == name, (
            f"tool_calls[{i}].name: expected {name!r}, got {call.name!r}"
        )


def test_result_and_error_fields_match_fixture() -> None:
    """result and error fields come back exactly as stored in the fixture."""
    adapter = ScriptedAdapter(FIXTURE_3CALL)
    trace = adapter.run_turn("any prompt", "none")

    # All three calls in the 3-call fixture have result set and error == null.
    for i, call in enumerate(trace.tool_calls):
        assert call.error is None, (
            f"tool_calls[{i}].error should be None; got {call.error!r}"
        )
        assert call.result is not None, (
            f"tool_calls[{i}].result should not be None"
        )


def test_status_and_reply_match_fixture() -> None:
    """Top-level status and final_reply are replayed from the fixture."""
    adapter = ScriptedAdapter(FIXTURE_3CALL)
    trace = adapter.run_turn("any prompt", "none")

    assert trace.status == "ok"
    assert trace.final_reply is not None and len(trace.final_reply) > 0


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_same_trace_on_every_replay() -> None:
    """Multiple run_turn() calls on the same adapter return identical data."""
    adapter = ScriptedAdapter(FIXTURE_3CALL)

    results = [adapter.run_turn("p", "none").model_dump() for _ in range(5)]

    for i in range(1, 5):
        assert results[0] == results[i], (
            f"Replay {i} differs from replay 0"
        )


def test_two_adapter_instances_same_fixture_agree() -> None:
    """Two independent ScriptedAdapter instances on the same file return the
    same Trace data (no mutable state shared between instances)."""
    a1 = ScriptedAdapter(FIXTURE_3CALL)
    a2 = ScriptedAdapter(FIXTURE_3CALL)

    assert a1.run_turn("p", "none").model_dump() == a2.run_turn("p", "none").model_dump()


# ---------------------------------------------------------------------------
# Error fixture replay
# ---------------------------------------------------------------------------

def test_error_fixture_status_is_error() -> None:
    """An error fixture replays with status == 'error'."""
    adapter = ScriptedAdapter(FIXTURE_ERROR)
    trace = adapter.run_turn("any prompt", "none")

    assert trace.status == "error"


def test_error_fixture_final_reply_is_none() -> None:
    """An error fixture replays with final_reply == None."""
    adapter = ScriptedAdapter(FIXTURE_ERROR)
    trace = adapter.run_turn("any prompt", "none")

    assert trace.final_reply is None


def test_error_fixture_error_field_preserved() -> None:
    """The error string in the tool call is replayed verbatim."""
    adapter = ScriptedAdapter(FIXTURE_ERROR)
    trace = adapter.run_turn("any prompt", "none")

    assert len(trace.tool_calls) == 1
    call = trace.tool_calls[0]
    assert call.error is not None
    assert "503" in call.error
    assert call.result is None


def test_error_fixture_passes_contract() -> None:
    """Even an error-status fixture satisfies the adapter contract."""
    adapter = ScriptedAdapter(FIXTURE_ERROR)
    run_adapter_contract(adapter)
