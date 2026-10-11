"""A-1 — Surface scanner tests.

Covers:
  ENG-1  scan_json / scan_openapi / scan_mcp produce a schema-valid SurfaceFile
  ENG-2  suggest_action_class heuristics (GET→read, POST→state-changing,
         cancel/confirm/internal→irreversible)
  ENG-3  description hash drift detection
  BASE-1 surface fixture validates against surface.schema.json
  BASE-2 get_action_class returns "state-changing" for unknown tool names

Test inventory
--------------
  test_heuristic_get_is_read
  test_heuristic_post_is_state_changing
  test_heuristic_cancel_is_irreversible
  test_heuristic_confirm_is_irreversible
  test_heuristic_internal_is_irreversible
  test_missing_tool_default_is_state_changing
  test_description_hash_mutation_detected
  test_surface_fixture_validates_against_schema
  test_scan_json_produces_valid_draft

  A-1 integration test (standalone):
  test_a1_scan_json_all_action_classes_represented
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import jsonschema
import pytest

from toolfence.contracts.surface import SurfaceFile
from toolfence.engine.surface import (
    SurfaceScanner,
    check_description_drift,
    description_sha256,
    get_action_class,
    suggest_action_class,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
FIXTURES_DIR = REPO_ROOT / "fixtures"
SURFACE_FIXTURE = FIXTURES_DIR / "surface_fixture.json"
SCHEMA_PATH = REPO_ROOT / "toolfence" / "contracts" / "schemas" / "surface.schema.json"


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate_surface(instance: object) -> None:
    schema = _load_schema()
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls(schema).validate(instance)


# ===========================================================================
# ENG-2: suggest_action_class heuristics
# ===========================================================================

def test_heuristic_get_is_read() -> None:
    """GET with any name → 'read' (no keyword match)."""
    assert suggest_action_class("GET", "mcp_galaxium_get_flights_flights_get") == "read"
    assert suggest_action_class("get", "list_items") == "read"


def test_heuristic_post_is_state_changing() -> None:
    """POST with a plain name (no irreversible keyword) → 'state-changing'."""
    assert suggest_action_class("POST", "mcp_galaxium_create_hold_quotes_post") == "state-changing"
    assert suggest_action_class("PUT", "update_user") == "state-changing"
    assert suggest_action_class("DELETE", "remove_item") == "state-changing"
    assert suggest_action_class("PATCH", "update_seat") == "state-changing"


def test_heuristic_cancel_is_irreversible() -> None:
    """Name containing 'cancel' → 'irreversible' regardless of HTTP method."""
    assert suggest_action_class("POST", "mcp_galaxium_cancel_booking__booking_id__post") == "irreversible"
    # GET with cancel in name is still irreversible (name-check takes priority)
    assert suggest_action_class("GET", "cancel_booking_get") == "irreversible"


def test_heuristic_confirm_is_irreversible() -> None:
    """Name containing 'confirm' → 'irreversible'."""
    assert suggest_action_class("POST", "mcp_galaxium_confirm_hold_holds__hold_id__confirm_post") == "irreversible"


def test_heuristic_internal_is_irreversible() -> None:
    """Name containing 'internal' → 'irreversible'."""
    assert suggest_action_class(
        "POST",
        "mcp_galaxium_create_booking_from_hold_internal_bookings_from_hold_post",
    ) == "irreversible"


# ===========================================================================
# BASE-2: get_action_class fallback
# ===========================================================================

def test_missing_tool_default_is_state_changing() -> None:
    """A tool name absent from the surface defaults to 'state-changing' (BASE-2)."""
    surface = SurfaceFile.model_validate(
        json.loads(SURFACE_FIXTURE.read_text(encoding="utf-8"))
    )
    result = get_action_class(surface, "mcp_galaxium_nonexistent_tool")
    assert result == "state-changing"


def test_known_tool_action_class_returned() -> None:
    """A tool that IS in the surface returns its stored action class."""
    surface = SurfaceFile.model_validate(
        json.loads(SURFACE_FIXTURE.read_text(encoding="utf-8"))
    )
    assert get_action_class(surface, "mcp_galaxium_get_flights_flights_get") == "read"
    assert get_action_class(surface, "mcp_galaxium_cancel_booking__booking_id__post") == "irreversible"
    assert get_action_class(surface, "mcp_galaxium_create_hold_quotes__quote_id__holds_post") == "state-changing"


# ===========================================================================
# ENG-3: description hash drift detection
# ===========================================================================

def test_description_hash_mutation_detected() -> None:
    """Mutating one tool description causes check_description_drift to return that name."""
    surface = SurfaceFile.model_validate(
        json.loads(SURFACE_FIXTURE.read_text(encoding="utf-8"))
    )

    # Build a live_tools list that matches the surface exactly, then mutate one entry.
    live_tools = [
        {"name": e.name, "description": "original description for " + e.name}
        for e in surface.tools
    ]
    # First: update the surface hashes to match our "original" descriptions.
    from toolfence.contracts.surface import SurfaceEntry
    updated_entries = [
        SurfaceEntry(
            name=e.name,
            route=e.route,
            action_class=e.action_class,
            trust_label=e.trust_label,
            description_sha256=description_sha256("original description for " + e.name),
        )
        for e in surface.tools
    ]
    from toolfence.contracts.surface import SurfaceFile as SF
    aligned_surface = SF(version=1, tools=updated_entries)

    # No mutation → no drift
    assert check_description_drift(aligned_surface, live_tools) == []

    # Mutate the first tool's description in the live list
    target_name = live_tools[0]["name"]
    live_tools[0] = {"name": target_name, "description": "CHANGED description"}
    drifted = check_description_drift(aligned_surface, live_tools)
    assert drifted == [target_name], (
        f"Expected [{target_name!r}] in drift list; got {drifted}"
    )


def test_description_hash_no_drift_when_unchanged() -> None:
    """check_description_drift returns empty list when descriptions match."""
    surface = SurfaceFile.model_validate(
        json.loads(SURFACE_FIXTURE.read_text(encoding="utf-8"))
    )
    # Build live_tools from the actual surface hashes (reverse-engineer is not
    # possible, so we use a fresh surface built from known descriptions).
    desc = "stable description"
    from toolfence.contracts.surface import SurfaceEntry, SurfaceFile as SF
    entry = SurfaceEntry(
        name="mcp_tool_a",
        route="GET /a",
        action_class="read",
        trust_label="first-party",
        description_sha256=description_sha256(desc),
    )
    small_surface = SF(version=1, tools=[entry])
    live_tools = [{"name": "mcp_tool_a", "description": desc}]
    assert check_description_drift(small_surface, live_tools) == []


# ===========================================================================
# BASE-1: surface fixture validates against schema
# ===========================================================================

def test_surface_fixture_validates_against_schema() -> None:
    """fixtures/surface_fixture.json must pass surface.schema.json (BASE-1)."""
    raw = json.loads(SURFACE_FIXTURE.read_text(encoding="utf-8"))
    _validate_surface(raw)  # raises jsonschema.ValidationError on failure


def test_surface_fixture_loads_as_pydantic_model() -> None:
    """fixtures/surface_fixture.json must parse into a valid SurfaceFile."""
    raw = json.loads(SURFACE_FIXTURE.read_text(encoding="utf-8"))
    surface = SurfaceFile.model_validate(raw)
    assert surface.version == 1
    assert len(surface.tools) == 5


# ===========================================================================
# ENG-1: scan_json produces a schema-valid draft
# ===========================================================================

def test_scan_json_produces_valid_draft() -> None:
    """scan_json on a minimal tool list must return a schema-valid SurfaceFile."""
    scanner = SurfaceScanner()
    tool_list = [
        {
            "name": "mcp_galaxium_get_flights_flights_get",
            "description": "Lists available flights.",
            "method": "GET",
            "route": "GET /flights",
        },
        {
            "name": "mcp_galaxium_cancel_booking__booking_id__post",
            "description": "Cancels a booking.",
            "method": "POST",
            "route": "POST /cancel/{booking_id}",
        },
    ]
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump({"tools": tool_list}, f)
        tmp_path = f.name

    surface = scanner.scan_json(tmp_path)
    assert isinstance(surface, SurfaceFile)
    _validate_surface(surface.model_dump())
    assert len(surface.tools) == 2


def test_scan_json_bare_list() -> None:
    """scan_json also accepts a bare JSON array (not wrapped in {"tools": ...})."""
    scanner = SurfaceScanner()
    tool_list = [
        {"name": "mcp_test_read_get", "description": "Read only.", "method": "GET", "route": "GET /read"},
    ]
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(tool_list, f)
        tmp_path = f.name

    surface = scanner.scan_json(tmp_path)
    assert len(surface.tools) == 1
    assert surface.tools[0].action_class == "read"


# ===========================================================================
# ENG-1: scan_openapi produces a schema-valid draft (fixture-based)
# ===========================================================================

def test_scan_openapi_from_file() -> None:
    """scan_openapi reads an OpenAPI spec file and produces a valid SurfaceFile."""
    openapi_spec = {
        "openapi": "3.0.0",
        "info": {"title": "Test", "version": "1.0"},
        "paths": {
            "/flights": {
                "get": {
                    "summary": "List flights",
                    "description": "Returns available flights.",
                    "responses": {},
                }
            },
            "/cancel/{booking_id}": {
                "post": {
                    "summary": "Cancel booking",
                    "description": "Cancels a booking by ID.",
                    "responses": {},
                }
            },
        },
    }
    scanner = SurfaceScanner()
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(openapi_spec, f)
        tmp_path = f.name

    surface = scanner.scan_openapi(tmp_path)
    assert isinstance(surface, SurfaceFile)
    _validate_surface(surface.model_dump())
    assert len(surface.tools) == 2

    names = [t.name for t in surface.tools]
    # GET /flights → "get_flights"
    assert any("flights" in n for n in names)
    # POST /cancel/{booking_id} → irreversible (contains "cancel")
    cancel_entry = next((t for t in surface.tools if "cancel" in t.name), None)
    assert cancel_entry is not None
    assert cancel_entry.action_class == "irreversible"


# ===========================================================================
# ENG-1: scan_mcp produces a schema-valid draft (mocked HTTP)
# ===========================================================================

def test_scan_mcp_with_mock_server() -> None:
    """scan_mcp fetches /tools from an MCP server and produces a valid SurfaceFile."""
    mock_response_body = json.dumps({
        "tools": [
            {"name": "mcp_galaxium_get_flights_flights_get", "description": "List flights."},
            {"name": "mcp_galaxium_cancel_booking__booking_id__post", "description": "Cancel booking."},
        ]
    }).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.read.return_value = mock_response_body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    scanner = SurfaceScanner()
    with patch("toolfence.engine.surface.urlopen", return_value=mock_resp):
        surface = scanner.scan_mcp("http://localhost:8001")

    assert isinstance(surface, SurfaceFile)
    _validate_surface(surface.model_dump())
    assert len(surface.tools) == 2

    cancel_entry = next((t for t in surface.tools if "cancel" in t.name), None)
    assert cancel_entry is not None
    assert cancel_entry.action_class == "irreversible"


# ===========================================================================
# A-1 integration test — all action classes and trust labels represented
# ===========================================================================

def test_a1_scan_json_all_action_classes_represented() -> None:
    """A-1 integration: scan_json on surface_fixture.json covers all three action
    classes and both trust labels, and every entry is schema-valid.

    This test acts as the standalone A-1 completion gate: if it passes, the
    surface scanner is correctly wired to the contracts layer.
    """
    scanner = SurfaceScanner()
    surface = scanner.scan_json(SURFACE_FIXTURE)

    # Schema-valid output
    _validate_surface(surface.model_dump())

    action_classes = {e.action_class for e in surface.tools}
    trust_labels = {e.trust_label for e in surface.tools}

    assert "read" in action_classes, "Expected at least one 'read' tool"
    assert "state-changing" in action_classes, "Expected at least one 'state-changing' tool"
    assert "irreversible" in action_classes, "Expected at least one 'irreversible' tool"

    assert "first-party" in trust_labels, "Expected at least one 'first-party' tool"
    assert "untrusted" in trust_labels, "Expected at least one 'untrusted' tool"

    # Every name matches ^[a-z0-9_]+$
    import re
    for entry in surface.tools:
        assert re.fullmatch(r"[a-z0-9_]+", entry.name), (
            f"Tool name {entry.name!r} does not match ^[a-z0-9_]+$"
        )

    # Every SHA-256 is exactly 64 lowercase hex chars
    for entry in surface.tools:
        assert re.fullmatch(r"[0-9a-f]{64}", entry.description_sha256), (
            f"description_sha256 for {entry.name!r} is malformed"
        )
