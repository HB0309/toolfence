"""C-5 — CI checks tests.

Covers:
  CLI-4  GitHub Action runs pytest (first step) and surface-diff check
  CLI-5  surface_diff_check exits non-zero with tool name for each failure type

Test inventory
--------------
  test_surface_diff_unknown_tool         -- live list has a tool absent from surface → exit 1
  test_surface_diff_changed_hash         -- live tool has different description → exit 1
  test_surface_diff_action_class_mismatch -- surface stores wrong action class → exit 1
  test_guard_wiring_check_bare_tool       -- bare tool in registry → exit 1 with tool name

All tests use fixture data only — no network.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from toolfence.cli.ci_checks import guard_wiring_check, surface_diff_check
from toolfence.contracts.surface import SurfaceEntry, SurfaceFile
from toolfence.engine.surface import description_sha256

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_surface(*entries: SurfaceEntry) -> SurfaceFile:
    return SurfaceFile(version=1, tools=list(entries))


def _entry(
    name: str,
    *,
    action_class: str = "read",
    trust_label: str = "first-party",
    description: str = "A test tool.",
) -> SurfaceEntry:
    return SurfaceEntry(
        name=name,
        route=f"GET /{name}",
        action_class=action_class,  # type: ignore[arg-type]
        trust_label=trust_label,  # type: ignore[arg-type]
        description_sha256=description_sha256(description),
    )


def _write_surface(surface: SurfaceFile) -> Path:
    """Write *surface* to a temp file and return its path."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    tmp.write(json.dumps(surface.model_dump()))
    tmp.close()
    return Path(tmp.name)


# ---------------------------------------------------------------------------
# Stub registry for guard_wiring_check tests
# ---------------------------------------------------------------------------

class _StubTool:
    def __init__(self, name: str) -> None:
        self.name = name

    async def execute(self, **params: Any) -> Any:
        return "ok"


class _StubRegistry:
    def __init__(self, tools: dict[str, Any]) -> None:
        self._tools = tools

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())


# ===========================================================================
# CLI-5 test 1 — unknown tool in live list
# ===========================================================================

def test_surface_diff_unknown_tool() -> None:
    """Live list contains a tool not present in surface → exit 1, tool name in message."""
    known_name = "mcp_galaxium_get_flights_flights_get"
    unknown_name = "mcp_galaxium_new_mystery_endpoint_post"

    surface = _make_surface(_entry(known_name))
    surface_path = _write_surface(surface)

    live_tool_list = [
        {"name": known_name, "description": "A test tool.", "method": "GET"},
        {"name": unknown_name, "description": "A brand new tool.", "method": "POST"},
    ]

    exit_code, message = surface_diff_check(surface_path, live_tool_list)

    assert exit_code == 1, (
        f"Expected exit code 1 for unknown tool, got {exit_code}. Message: {message}"
    )
    assert unknown_name in message, (
        f"Expected unknown tool name '{unknown_name}' in message.\nGot: {message}"
    )


# ===========================================================================
# CLI-5 test 2 — changed description hash
# ===========================================================================

def test_surface_diff_changed_hash() -> None:
    """Live tool has a different description → description drift → exit 1, tool name in message."""
    tool_name = "mcp_galaxium_get_flights_flights_get"
    original_description = "Original description for the tool."

    # Surface is committed with a hash of original_description.
    surface = _make_surface(
        SurfaceEntry(
            name=tool_name,
            route="GET /flights",
            action_class="read",  # type: ignore[arg-type]
            trust_label="first-party",  # type: ignore[arg-type]
            description_sha256=description_sha256(original_description),
        )
    )
    surface_path = _write_surface(surface)

    # Live list has the same tool but a different description.
    live_tool_list = [
        {
            "name": tool_name,
            "description": "CHANGED description — someone edited the tool.",
            "method": "GET",
        }
    ]

    exit_code, message = surface_diff_check(surface_path, live_tool_list)

    assert exit_code == 1, (
        f"Expected exit code 1 for hash drift, got {exit_code}. Message: {message}"
    )
    assert tool_name in message, (
        f"Expected tool name '{tool_name}' in message.\nGot: {message}"
    )


# ===========================================================================
# CLI-5 test 3 — action-class mismatch
# ===========================================================================

def test_surface_diff_action_class_mismatch() -> None:
    """Surface stores 'read' for a POST tool; heuristic suggests 'state-changing' → exit 1."""
    tool_name = "mcp_galaxium_create_quote_post"
    description = "Creates a quote."

    # Surface incorrectly stores "read" for a POST tool with no irreversible keyword.
    surface = _make_surface(
        SurfaceEntry(
            name=tool_name,
            route="POST /quote",
            action_class="read",  # type: ignore[arg-type]  ← deliberately wrong
            trust_label="first-party",  # type: ignore[arg-type]
            description_sha256=description_sha256(description),
        )
    )
    surface_path = _write_surface(surface)

    # Live list says this is a POST tool → heuristic suggests "state-changing".
    live_tool_list = [
        {"name": tool_name, "description": description, "method": "POST"},
    ]

    exit_code, message = surface_diff_check(surface_path, live_tool_list)

    assert exit_code == 1, (
        f"Expected exit code 1 for action-class mismatch, got {exit_code}. Message: {message}"
    )
    assert tool_name in message, (
        f"Expected tool name '{tool_name}' in message.\nGot: {message}"
    )


# ===========================================================================
# CLI-5 test 4 — guard_wiring_check bare tool
# ===========================================================================

def test_guard_wiring_check_bare_tool() -> None:
    """Registry contains a bare (unwrapped) tool → exit 1, tool name in message."""
    bare_tool_name = "mcp_galaxium_cancel_booking__booking_id__post"
    registry = _StubRegistry({bare_tool_name: _StubTool(bare_tool_name)})

    exit_code, message = guard_wiring_check(registry)

    assert exit_code == 1, (
        f"Expected exit code 1 for bare tool, got {exit_code}. Message: {message}"
    )
    assert bare_tool_name in message, (
        f"Expected tool name '{bare_tool_name}' in message.\nGot: {message}"
    )


# ===========================================================================
# FIX 2a — action-class safe override (stored more restrictive than heuristic)
# ===========================================================================

def test_surface_diff_action_class_override_ok() -> None:
    """Stored 'irreversible' where heuristic suggests 'state-changing' → exit 0 (safe upgrade)."""
    tool_name = "mcp_galaxium_create_quote_post"
    description = "Creates a quote."

    # Reviewer deliberately stored "irreversible" for a POST tool with no irreversible keyword.
    # Heuristic would suggest "state-changing" — this is a safe, more-restrictive override.
    surface = _make_surface(
        SurfaceEntry(
            name=tool_name,
            route="POST /quote",
            action_class="irreversible",  # type: ignore[arg-type]  ← deliberate upgrade
            trust_label="first-party",  # type: ignore[arg-type]
            description_sha256=description_sha256(description),
        )
    )
    surface_path = _write_surface(surface)

    live_tool_list = [
        {"name": tool_name, "description": description, "method": "POST"},
    ]

    exit_code, message = surface_diff_check(surface_path, live_tool_list)

    assert exit_code == 0, (
        f"Expected exit 0 for safe override (stored more restrictive), got {exit_code}. "
        f"Message: {message}"
    )


# ===========================================================================
# FIX 2b — method extracted from route field (no "method" key in live dict)
# ===========================================================================

def test_surface_diff_method_from_route() -> None:
    """Live tool has 'route': 'GET /flights' but no 'method' key → extracted as GET → exit 0."""
    tool_name = "mcp_galaxium_get_flights_flights_get"
    description = "Lists available flights."

    surface = _make_surface(
        SurfaceEntry(
            name=tool_name,
            route="GET /flights",
            action_class="read",  # type: ignore[arg-type]
            trust_label="first-party",  # type: ignore[arg-type]
            description_sha256=description_sha256(description),
        )
    )
    surface_path = _write_surface(surface)

    # No "method" key — method must be extracted from "route"
    live_tool_list = [
        {"name": tool_name, "description": description, "route": "GET /flights"},
    ]

    exit_code, message = surface_diff_check(surface_path, live_tool_list)

    assert exit_code == 0, (
        f"Expected exit 0 when method is extracted from route (GET → read class), "
        f"got {exit_code}. Message: {message}"
    )


# ===========================================================================
# Bonus — clean surface returns exit 0
# ===========================================================================

def test_surface_diff_clean_surface() -> None:
    """A live list that exactly matches the committed surface → exit 0, message 'ok'."""
    tool_name = "mcp_galaxium_get_flights_flights_get"
    description = "Lists available flights."

    surface = _make_surface(
        SurfaceEntry(
            name=tool_name,
            route="GET /flights",
            action_class="read",  # type: ignore[arg-type]
            trust_label="first-party",  # type: ignore[arg-type]
            description_sha256=description_sha256(description),
        )
    )
    surface_path = _write_surface(surface)

    live_tool_list = [
        {"name": tool_name, "description": description, "method": "GET"},
    ]

    exit_code, message = surface_diff_check(surface_path, live_tool_list)

    assert exit_code == 0, (
        f"Expected exit 0 for clean surface, got {exit_code}. Message: {message}"
    )
    assert message == "ok"


# ===========================================================================
# Bonus — guard_wiring_check passes when all tools are GuardedProxy
# ===========================================================================

def test_guard_wiring_check_all_wrapped() -> None:
    """All tools wrapped in GuardedProxy → exit 0."""
    from toolfence.contracts.surface import SurfaceFile
    from toolfence.guard.confirm import ConfirmGrant
    from toolfence.guard.decision import GuardDecision
    from toolfence.guard.provenance import ProvenanceStore
    from toolfence.guard.proxy import GuardedProxy
    from toolfence.guard.taint import SessionTaint

    tool_name = "mcp_galaxium_get_flights_flights_get"
    raw_tool = _StubTool(tool_name)

    proxy = GuardedProxy(
        raw_tool,
        SurfaceFile(version=1, tools=[]),
        ProvenanceStore(),
        SessionTaint(),
        GuardDecision(),
        lambda event: None,
        ConfirmGrant(),
        guard_on=False,
        datamark_on=False,
    )

    registry = _StubRegistry({tool_name: proxy})

    exit_code, message = guard_wiring_check(registry)

    assert exit_code == 0, (
        f"Expected exit 0 when all tools are GuardedProxy, got {exit_code}. Message: {message}"
    )
    assert message == "ok"


# ===========================================================================
# Import boundary — ci_checks.py must not import nanobot
# ===========================================================================

def test_ci_checks_no_nanobot_import() -> None:
    """ci_checks.py source must not contain a nanobot import statement."""
    import re
    src = (
        Path(__file__).parent.parent / "toolfence" / "cli" / "ci_checks.py"
    ).read_text(encoding="utf-8")
    # Match actual import statements at the start of a line, not mentions in comments/docstrings.
    for pattern in (r"^from nanobot\b", r"^import nanobot\b"):
        assert not re.search(pattern, src, re.MULTILINE), (
            f"ci_checks.py must not import nanobot (matched pattern {pattern!r})"
        )


# ===========================================================================
# GitHub Action YAML — first step is pytest
# ===========================================================================

def test_ci_yml_first_step_is_pytest() -> None:
    """toolfence-ci.yml must exist and its first test step must be pytest tests/ --skip-network."""
    yml_path = (
        Path(__file__).parent.parent / ".github" / "workflows" / "toolfence-ci.yml"
    )
    assert yml_path.exists(), f"Expected {yml_path} to exist"
    content = yml_path.read_text(encoding="utf-8")
    assert "pytest tests/" in content, (
        "CI YAML must contain 'pytest tests/' as a step"
    )
    assert "--skip-network" in content, (
        "CI YAML must contain '--skip-network' flag"
    )
