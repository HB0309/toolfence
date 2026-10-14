"""tests/test_surface_baseline.py — B-5 surface map baseline checks.

Six tests, no network calls, no subprocess.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from toolfence.contracts.surface import SurfaceFile

_REPO = Path(__file__).parent.parent
_SURFACE_PATH = _REPO / "results" / "surface.json"
_DUMP_PATH = _REPO / "results" / "tool_dump.txt"
_EVAL_CONFIG_PATH = _REPO / "config" / "nanobot.eval.json"
_GATEWAY_CONFIG_PATH = _REPO / "config" / "nanobot.gateway.json"

# Truncated name for the internal booking-from-hold route (>64 chars → SHA-1 suffix)
_INTERNAL_ROUTE_NAME = "mcp_galaxium_create_booking_from_hold_internal_bookings_d31ac16e"
_REVIEWS_TOOL_NAME = "mcp_galaxium_get_flight_reviews_flights_flight_id_reviews_get"


@pytest.fixture(scope="module")
def surface() -> SurfaceFile:
    raw = json.loads(_SURFACE_PATH.read_text(encoding="utf-8"))
    return SurfaceFile.model_validate(raw)


@pytest.fixture(scope="module")
def surface_names(surface: SurfaceFile) -> set[str]:
    return {e.name for e in surface.tools}


# ---------------------------------------------------------------------------
# Test 1 — schema validity and entry count
# ---------------------------------------------------------------------------

def test_surface_schema_valid(surface: SurfaceFile) -> None:
    """results/surface.json must be schema-valid and contain exactly 22 entries."""
    assert len(surface.tools) == 22, (
        f"Expected 22 entries, got {len(surface.tools)}. "
        "Update count here if the tool set deliberately changes."
    )


# ---------------------------------------------------------------------------
# Test 2 — internal route is irreversible (PG-5)
# ---------------------------------------------------------------------------

def test_internal_route_irreversible(surface: SurfaceFile) -> None:
    """The internal booking-from-hold route must be classified irreversible (PG-5)."""
    entry = next((e for e in surface.tools if e.name == _INTERNAL_ROUTE_NAME), None)
    assert entry is not None, (
        f"Entry '{_INTERNAL_ROUTE_NAME}' not found in surface. "
        "Ensure dump_live_tools.py was run with --all-tools."
    )
    assert entry.action_class == "irreversible", (
        f"Internal route action_class is '{entry.action_class}', expected 'irreversible'."
    )


# ---------------------------------------------------------------------------
# Test 3 — reviews tool is untrusted (PG-5)
# ---------------------------------------------------------------------------

def test_reviews_tool_untrusted(surface: SurfaceFile) -> None:
    """The flight-reviews tool must have trust_label='untrusted' (PG-5)."""
    entry = next((e for e in surface.tools if e.name == _REVIEWS_TOOL_NAME), None)
    assert entry is not None, (
        f"Entry '{_REVIEWS_TOOL_NAME}' not found in surface. "
        "Re-run dump_live_tools.py --all-tools after B-1a (reviews route patch) is applied."
    )
    assert entry.trust_label == "untrusted", (
        f"Reviews tool trust_label is '{entry.trust_label}', expected 'untrusted'."
    )


# ---------------------------------------------------------------------------
# Test 4 — enabledTools narrowing (PG-6)
# ---------------------------------------------------------------------------

def test_enabled_tools_narrowing(surface_names: set[str]) -> None:
    """All enabledTools must be in surface; internal route must be in surface but not enabledTools."""
    raw = json.loads(_EVAL_CONFIG_PATH.read_text(encoding="utf-8"))
    enabled: list[str] = (
        raw.get("tools", {})
        .get("mcpServers", {})
        .get("galaxium", {})
        .get("enabledTools", [])
    )
    # Strip any '*' wildcard entry
    enabled_names = {n for n in enabled if n != "*"}

    missing_from_surface = enabled_names - surface_names
    assert not missing_from_surface, (
        f"enabledTools entries missing from surface.json: {sorted(missing_from_surface)}"
    )

    assert _INTERNAL_ROUTE_NAME in surface_names, (
        f"Internal route '{_INTERNAL_ROUTE_NAME}' is missing from surface.json."
    )
    assert _INTERNAL_ROUTE_NAME not in enabled_names, (
        f"Internal route '{_INTERNAL_ROUTE_NAME}' should NOT be in enabledTools."
    )


# ---------------------------------------------------------------------------
# Test 5 — eval and gateway configs have file, cliApps, my turned off
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("config_path", [_EVAL_CONFIG_PATH, _GATEWAY_CONFIG_PATH])
def test_configs_narrowed(config_path: Path) -> None:
    """Both configs must have file, cliApps and my disabled."""
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    tools = raw.get("tools", {})

    for key in ("file", "cliApps", "my"):
        block = tools.get(key, {})
        assert block.get("enable") is False, (
            f"{config_path.name}: tools.{key}.enable should be false, "
            f"got {block.get('enable')!r}."
        )


# ---------------------------------------------------------------------------
# Test 6 — every name and hash in tool_dump.txt matches surface.json
# ---------------------------------------------------------------------------

def _parse_dump(path: Path) -> dict[str, str]:
    """Parse tool_dump.txt and return {name: sha256} for every entry."""
    name_re = re.compile(r"^name:\s+(\S+)$")
    sha_re = re.compile(r"^sha256:\s+([0-9a-f]{64})$")
    result: dict[str, str] = {}
    current_name: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = name_re.match(line)
        if m:
            current_name = m.group(1)
            continue
        m = sha_re.match(line)
        if m and current_name is not None:
            result[current_name] = m.group(1)
            current_name = None
    return result


def test_dump_matches_surface(surface: SurfaceFile) -> None:
    """Every (name, sha256) pair in tool_dump.txt must match the committed surface.json.

    Skipped when tool_dump.txt is absent (first checkout before dump has been run).
    After running ``dump_live_tools.py --all-tools``, this test must pass without
    any manual SHA edits.
    """
    if not _DUMP_PATH.exists():
        pytest.skip("results/tool_dump.txt not found — run dump_live_tools.py --all-tools first")

    dump = _parse_dump(_DUMP_PATH)
    assert dump, "tool_dump.txt parsed to an empty dict — check the file format"

    surface_map = {e.name: e.description_sha256 for e in surface.tools}

    mismatches: list[str] = []
    for name, dump_sha in sorted(dump.items()):
        if name not in surface_map:
            mismatches.append(f"  {name}: in dump but missing from surface.json")
            continue
        if surface_map[name] != dump_sha:
            mismatches.append(
                f"  {name}:\n"
                f"    dump   = {dump_sha}\n"
                f"    surface= {surface_map[name]}"
            )

    assert not mismatches, (
        "Hashes in tool_dump.txt do not match surface.json — "
        "re-run dump_live_tools.py --all-tools and update surface.json:\n"
        + "\n".join(mismatches)
    )
