"""Tests for toolfence.engine.normal_success (ENG-7).

Covers:
  test_normal_success_standard_trace          — passing fixture → True
  test_normal_success_no_goal_tool            — goal tool absent → False
  test_normal_success_held_goal_tool          — goal tool held → False
  test_normal_success_error_status            — trace status != "ok" → False
  test_normal_success_goal_tool_errored       — tc.error set → False

  New (result-error detection):
  test_normal_success_http_422_result         — "Error calling ... 422" → False
  test_normal_success_json_error_result       — {"error": ...} result → False
  test_normal_success_retry_after_error       — failed then successful → True
  test_normal_success_real_smoke_trace        — real normal-smoke record → True
  test_is_error_result_cases                  — unit tests for _is_error_result

Import-boundary check:
  test_normal_success_no_engine_import        — normal_success.py must not import
                                               from toolfence.engine (circular)
"""

from __future__ import annotations

import json
from pathlib import Path

from toolfence.contracts.trace import Trace, TraceEntry, UsageInfo
from toolfence.engine.normal_success import (
    DEFAULT_GOAL_TOOL,
    _is_error_result,
    evaluate_normal_trial,
)

_REPO_ROOT = Path(__file__).parent.parent
_NORMAL_FIXTURE = _REPO_ROOT / "fixtures" / "probes" / "normal_task.json"
_SMOKE_RECORD = _REPO_ROOT / "fixtures" / "probes" / "live_normal_smoke.json"

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
    result: str | None = None,
) -> TraceEntry:
    # Default result: None when error is set, "ok" otherwise; caller can override.
    if result is None and error is None:
        result = "ok"
    return TraceEntry(
        name=name,
        params={},
        result=result,
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


# ---------------------------------------------------------------------------
# _is_error_result — unit tests
# ---------------------------------------------------------------------------

def test_is_error_result_cases() -> None:
    """_is_error_result correctly classifies all known result shapes."""
    # nanobot HTTP error string
    http_422 = (
        "Error calling get_user_endpoint_user_get. Status code: 422. "
        'Response: {"detail": {"error": "Invalid email"}}'
    )
    assert _is_error_result(http_422) is True, "HTTP error string must be True"

    # Galaxium proxy JSON error object
    json_error = '{"error": "Hold already exists", "code": "DUPLICATE_HOLD"}'
    assert _is_error_result(json_error) is True, "JSON error object must be True"

    # Clean JSON result (successful hold)
    clean_hold = (
        '{"holdId": "H-2026-000027", "quoteId": "Q-2026-000028", "status": "HELD"}'
    )
    assert _is_error_result(clean_hold) is False, "Clean JSON result must be False"

    # Plain string (not JSON, not error prefix)
    assert _is_error_result("ok") is False, "'ok' must be False"

    # None (held call — guard handles this separately)
    assert _is_error_result(None) is False, "None result must be False"

    # JSON array — not a dict → no top-level 'error' key
    assert _is_error_result('[{"flight_id": 1}]') is False, "JSON array must be False"

    # JSON dict with errorMessage key (Galaxium null errorMessage field) — not 'error'
    galaxium_held = '{"holdId": "H-001", "errorMessage": null, "status": "HELD"}'
    assert _is_error_result(galaxium_held) is False, (
        "JSON with 'errorMessage' but no 'error' key must be False"
    )


# ---------------------------------------------------------------------------
# New result-error detection tests
# ---------------------------------------------------------------------------

def test_normal_success_http_422_result() -> None:
    """A goal-tool call whose result is an HTTP 422 error string counts as failed.

    With only that one call and no successful retry, evaluate_normal_trial → False.
    """
    http_error = (
        "Error calling get_user_endpoint_user_get. Status code: 422. "
        'Response: {"detail": {"error": "Invalid email"}}'
    )
    trace = _make_trace(
        status="ok",
        tool_calls=[
            _make_entry(DEFAULT_GOAL_TOOL, guard_decision="pass", result=http_error),
        ],
    )
    assert evaluate_normal_trial(trace) is False, (
        "Expected False: sole goal-tool call has an HTTP 422 error result"
    )


def test_normal_success_json_error_result() -> None:
    """A goal-tool call whose result is {'error': ...} JSON counts as failed.

    With only that one call and no successful retry, evaluate_normal_trial → False.
    """
    json_error = '{"error": "Hold already exists", "code": "DUPLICATE_HOLD"}'
    trace = _make_trace(
        status="ok",
        tool_calls=[
            _make_entry(DEFAULT_GOAL_TOOL, guard_decision="pass", result=json_error),
        ],
    )
    assert evaluate_normal_trial(trace) is False, (
        "Expected False: sole goal-tool call has a JSON error result"
    )


def test_normal_success_retry_after_error() -> None:
    """A failed hold followed by a successful retry evaluates to True.

    First call: goal tool, pass, error=None, but result is an error payload.
    Second call: goal tool, pass, error=None, clean result.
    No Guard holds anywhere.  → True.
    """
    error_result = '{"error": "Quota exceeded"}'
    clean_result = (
        '{"holdId": "H-2026-000099", "quoteId": "Q-001", "status": "HELD"}'
    )
    trace = _make_trace(
        status="ok",
        tool_calls=[
            # Other tool first
            _make_entry("mcp_galaxium_get_flights_flights_get"),
            # First hold attempt: error result
            _make_entry(DEFAULT_GOAL_TOOL, guard_decision="pass", result=error_result),
            # Retry: successful
            _make_entry(DEFAULT_GOAL_TOOL, guard_decision="pass", result=clean_result),
        ],
    )
    assert evaluate_normal_trial(trace) is True, (
        "Expected True: second hold attempt succeeded"
    )


def test_normal_success_real_smoke_trace() -> None:
    """The real normal-smoke trial record (committed fixture) evaluates to True.

    The trace has a 422 error on the user-lookup call (not the goal tool)
    and a clean successful hold as the final goal-tool call.
    """
    from toolfence.contracts.trial import TrialRecord

    data = json.loads(_SMOKE_RECORD.read_text(encoding="utf-8"))
    record = TrialRecord.model_validate(data)
    result = evaluate_normal_trial(record.trace)
    assert result is True, (
        "Expected True for real normal-smoke record; "
        f"trace status={record.trace.status!r}, "
        f"goal calls={[tc.name for tc in record.trace.tool_calls if tc.name == DEFAULT_GOAL_TOOL]}"
    )
