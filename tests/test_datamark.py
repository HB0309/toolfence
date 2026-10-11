"""A-3 — Datamarking tests.

Covers:
  GRD-10  datamark_result wraps untrusted results; content preserved
  ENG-4   datamarking defense row in the evaluation matrix

Test inventory (A-3 unit tests)
--------------------------------
  test_datamark_wraps_string
  test_datamark_is_datamarked_true
  test_datamark_content_preserved
  test_datamark_idempotent
  test_datamark_not_datamarked_plain_string
  test_datamark_not_datamarked_partial_nanobot_only
  test_datamark_not_datamarked_partial_toolfence_only
  test_datamark_tool_name_in_wrapper
  test_datamark_no_engine_import

A-3 standalone integration test
---------------------------------
  test_a3_datamark_pipeline
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from toolfence.guard.datamark import (
    _NANOBOT_END,
    _NANOBOT_TAG,
    _TOOLFENCE_END,
    _TOOLFENCE_TAG_PREFIX,
    datamark_result,
    is_datamarked,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_TOOL_NAME = "mcp_galaxium_get_flight_reviews_flights__flight_id__reviews_get"
_PLAIN_CONTENT = "Review: Good flight, arrived on time. Rating: 5/5."
_MULTI_LINE_CONTENT = (
    '{"flight_id": 42, "review": "Great service!", "rating": 5, '
    '"reviewer": "Alice", "date": "2099-01-15"}'
)


# ===========================================================================
# A-3 unit tests — datamark_result
# ===========================================================================

def test_datamark_wraps_string() -> None:
    """datamark_result output contains the nanobot outer tag and ToolFence inner tag."""
    result = datamark_result(_PLAIN_CONTENT, _TOOL_NAME)
    assert _NANOBOT_TAG in result, "Nanobot outer tag missing from datamarked output"
    assert _NANOBOT_END in result, "Nanobot closing tag missing from datamarked output"
    assert _TOOLFENCE_TAG_PREFIX in result, "ToolFence inner tag missing from datamarked output"
    assert _TOOLFENCE_END in result, "ToolFence closing tag missing from datamarked output"


def test_datamark_is_datamarked_true() -> None:
    """is_datamarked returns True on the output of datamark_result."""
    result = datamark_result(_PLAIN_CONTENT, _TOOL_NAME)
    assert is_datamarked(result) is True


def test_datamark_content_preserved() -> None:
    """Original result_str is present verbatim inside the wrapper, unmodified."""
    result = datamark_result(_PLAIN_CONTENT, _TOOL_NAME)
    assert _PLAIN_CONTENT in result, (
        "Original content not found verbatim in datamarked output"
    )


def test_datamark_idempotent() -> None:
    """Calling datamark_result twice returns the same string as calling it once."""
    once = datamark_result(_PLAIN_CONTENT, _TOOL_NAME)
    twice = datamark_result(once, _TOOL_NAME)
    assert once == twice, (
        "datamark_result is not idempotent — double-wrapping occurred"
    )


def test_datamark_not_datamarked_plain_string() -> None:
    """is_datamarked returns False on a plain unmarked string."""
    assert is_datamarked(_PLAIN_CONTENT) is False
    assert is_datamarked("") is False
    assert is_datamarked("Some tool result without any tags.") is False


def test_datamark_not_datamarked_partial_nanobot_only() -> None:
    """is_datamarked returns False when only the nanobot tag is present (no ToolFence tag)."""
    partial = f"{_NANOBOT_TAG}\nsome content\n{_NANOBOT_END}"
    assert is_datamarked(partial) is False, (
        "is_datamarked should return False when ToolFence inner tag is absent"
    )


def test_datamark_not_datamarked_partial_toolfence_only() -> None:
    """is_datamarked returns False when only the ToolFence tag is present (no nanobot outer tag)."""
    partial = f"{_TOOLFENCE_TAG_PREFIX} | tool: some_tool]\nsome content\n{_TOOLFENCE_END}"
    assert is_datamarked(partial) is False, (
        "is_datamarked should return False when nanobot outer tag is absent"
    )


def test_datamark_tool_name_in_wrapper() -> None:
    """The tool_name argument appears inside the datamarked output for auditability."""
    result = datamark_result(_PLAIN_CONTENT, _TOOL_NAME)
    assert _TOOL_NAME in result, (
        f"tool_name {_TOOL_NAME!r} not found in datamarked output"
    )


def test_datamark_different_tool_names_produce_different_wrappers() -> None:
    """Two calls with different tool names produce output with different inner markers."""
    result_a = datamark_result(_PLAIN_CONTENT, "mcp_tool_alpha")
    result_b = datamark_result(_PLAIN_CONTENT, "mcp_tool_beta")
    assert "mcp_tool_alpha" in result_a
    assert "mcp_tool_beta" in result_b
    assert "mcp_tool_alpha" not in result_b
    assert "mcp_tool_beta" not in result_a


def test_datamark_no_engine_import() -> None:
    """guard/datamark.py must not import from toolfence.engine (component boundary).

    This enforces the architectural rule that guard/ has zero engine/ imports.
    """
    # Re-import fresh to get the actual module object
    mod_name = "toolfence.guard.datamark"
    if mod_name in sys.modules:
        mod = sys.modules[mod_name]
    else:
        mod = importlib.import_module(mod_name)

    # Inspect the module's globals for any engine imports
    engine_imports = [
        name for name, val in vars(mod).items()
        if isinstance(val, type(sys)) and "toolfence.engine" in getattr(val, "__name__", "")
    ]
    assert engine_imports == [], (
        f"guard/datamark.py imports engine modules: {engine_imports}"
    )

    # Also check the source file directly for any 'from toolfence.engine' or
    # 'import toolfence.engine' lines.
    src = Path(__file__).parent.parent / "toolfence" / "guard" / "datamark.py"
    source_text = src.read_text(encoding="utf-8")
    assert "toolfence.engine" not in source_text, (
        "guard/datamark.py contains an import from toolfence.engine"
    )
    assert "from toolfence.engine" not in source_text
    assert "import toolfence.engine" not in source_text


# ===========================================================================
# A-3 standalone integration test
# ===========================================================================

def test_a3_datamark_pipeline() -> None:
    """A-3 integration: full datamark pipeline on a realistic multi-line JSON result.

    Verifies:
    1. Wraps a real-world-shaped tool result correctly.
    2. is_datamarked is True on the output.
    3. Original content is present verbatim.
    4. Idempotent: second call returns unchanged string.
    5. Both nanobot outer tags appear before and after ToolFence inner tags
       (correct nesting order).
    6. tool_name appears in the output.

    This is the standalone A-3 completion gate.
    """
    tool_name = "mcp_galaxium_get_flight_reviews_flights__flight_id__reviews_get"
    content = _MULTI_LINE_CONTENT

    marked = datamark_result(content, tool_name)

    # 1. is_datamarked true
    assert is_datamarked(marked), "is_datamarked should be True after datamark_result"

    # 2. Content preserved verbatim
    assert content in marked, "Original content not found verbatim in output"

    # 3. Idempotent
    assert datamark_result(marked, tool_name) == marked, "Not idempotent"

    # 4. tool_name present
    assert tool_name in marked, "tool_name not found in output"

    # 5. Nesting order: nanobot outer tag comes before ToolFence inner tag
    nanobot_pos = marked.index(_NANOBOT_TAG)
    toolfence_pos = marked.index(_TOOLFENCE_TAG_PREFIX)
    nanobot_end_pos = marked.index(_NANOBOT_END)
    toolfence_end_pos = marked.index(_TOOLFENCE_END)

    assert nanobot_pos < toolfence_pos, (
        "Nanobot outer tag must come before ToolFence inner tag"
    )
    assert toolfence_end_pos < nanobot_end_pos, (
        "ToolFence closing tag must come before nanobot closing tag"
    )

    # 6. Both closing tags present
    assert _TOOLFENCE_END in marked
    assert _NANOBOT_END in marked
