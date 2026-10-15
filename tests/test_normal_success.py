"""Tests for toolfence.engine.normal_success (ENG-7).

Covers:
  test_normal_success_standard_trace    — passing fixture → True
  test_normal_success_no_goal_tool      — goal tool absent → False
  test_normal_success_held_goal_tool    — goal tool held → False
  test_normal_success_error_status      — trace status != "ok" → False

Import-boundary check:
  test_normal_success_no_engine_import  — normal_success.py must not import
                                          from toolfence.engine (circular)
"""

from __future__ import annotations

import json
from pathlib import Path

from toolfence.contracts.trace import Trace, TraceEntry, UsageInfo
from toolfence.engine.normal_success import DEFAULT_GOAL_TOOL, evaluate_normal_trial

_REPO_ROOT = Path(__file__).parent.parent
_NORMAL_FIXTURE = _REPO_ROOT / "fixtures" / "probes" / "normal_task.json"

# ---------------------------------------------------------------------------
# Shared builder helpers
# ---------------------------------------------------------------------------

_BASE_USAGE = UsageInfo(
    input_tokens=1000,
    output_tokens=100,
    reasoning_tokens=0,
    total_tokens=1100,
    generation_ms=0,
)


def _make_entry(
    name: str,
    guard_decision: str = "pass",
    error: str | None = None,
) -> TraceEntry:
    return TraceEntry(
        name=name,
        params={},
        result=None if error else "ok",
        error=error,
        duration_ms=10,
        provenance={},
        guard_decision=guard_decision,  # type: ignore[arg-type]
    )


def _make_trace(status: str = "ok", tool_calls: list[TraceEntry] | None = None) -> Trace:
    return Trace(
        run_id="test-run",
        session_key="test-session",
        model="test-model",
        host="test-host",
        timestamp="2026-01-01T00:00:00Z",
        status=status,  # type: ignore[arg-type]
        final_reply="done",
        tool_calls=tool_calls or [],
        usage=_BASE_USAGE,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_normal_success_standard_trace() -> None:
    """Loading the real normal_task.json fixture should evaluate to True."""
    raw = json.loads(_NORMAL_FIXTURE.read_text(encoding="utf-8"))
    trace = Trace.model_validate(raw)
    assert evaluate_normal_trial(trace) is True, (
        "Expected evaluate_normal_trial to return True for normal_task.json"
    )


def test_normal_success_no_goal_tool() -> None:
    """A trace with status='ok' but without the goal tool call returns False."""
    trace = _make_trace(
        status="ok",
        tool_calls=[_make_entry("mcp_galaxium_get_flights_flights_get")],
    )
    assert evaluate_normal_trial(trace) is False, (
        "Expected False when goal tool is absent from tool_calls"
    )


def test_normal_success_held_goal_tool() -> None:
    """A trace where the goal tool was called but held returns False."""
    trace = _make_trace(
        status="ok",
        tool_calls=[
            _make_entry("mcp_galaxium_get_flights_flights_get"),
            _make_entry(DEFAULT_GOAL_TOOL, guard_decision="hold"),
        ],
    )
    assert evaluate_normal_trial(trace) is False, (
        "Expected False when goal tool has guard_decision='hold'"
    )


def test_normal_success_error_status() -> None:
    """A trace with status='error' returns False even if goal tool is present and passed."""
    trace = _make_trace(
        status="error",
        tool_calls=[_make_entry(DEFAULT_GOAL_TOOL, guard_decision="pass")],
    )
    assert evaluate_normal_trial(trace) is False, (
        "Expected False when trace.status != 'ok'"
    )


def test_normal_success_goal_tool_errored() -> None:
    """A goal-tool call that passed the Guard but has an error returns False."""
    trace = _make_trace(
        status="ok",
        tool_calls=[
            _make_entry(DEFAULT_GOAL_TOOL, guard_decision="pass", error="upstream timeout"),
        ],
    )
    assert evaluate_normal_trial(trace) is False, (
        "Expected False when goal tool call has a non-None error"
    )


# ---------------------------------------------------------------------------
# Import-boundary test
# ---------------------------------------------------------------------------

def test_normal_success_no_engine_import() -> None:
    """normal_success.py must not import from toolfence.engine (circular boundary)."""
    source = (
        _REPO_ROOT / "toolfence" / "engine" / "normal_success.py"
    ).read_text(encoding="utf-8")
    # Allow self-reference in comments/docstrings but forbid actual engine imports.
    # We check for import lines referencing toolfence.engine.* (other than this file itself).
    import_lines = [
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith(("import ", "from "))
        and "toolfence.engine" in line
    ]
    assert import_lines == [], (
        f"normal_success.py must not import from toolfence.engine; found: {import_lines}"
    )
