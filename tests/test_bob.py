"""B-6a — ToolFence MCP server tests.

Covers:
  BOB-2   Tool list is exactly four named tools.
  BOB-3   scan_surface returns a SurfaceFile-schema-valid JSON string.
  BOB-4   run_eval returns a list of TrialRecord-schema-valid JSON objects;
          unknown channel / defense values return isError=True.
  BOB-5   propose_fix returns surface_proposal, enabled_tools, open_findings;
          enabled_tools matches config/nanobot.eval.json enabledTools.
  BOB-6   render_report markdown output contains the ENG-8 disclaimer.
  BOB-7   No .bob/rules-* file has been modified since the commit that added it.

Test inventory
--------------
  test_tool_list_is_exactly_four
  test_scan_surface_returns_valid_surface
  test_run_eval_returns_trial_records
  test_run_eval_unknown_channel_is_error
  test_run_eval_unknown_defense_is_error
  test_propose_fix_returns_surface_and_tools
  test_render_report_contains_disclaimer
  test_no_existing_bob_file_modified
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import jsonschema
import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT       = Path(__file__).parent.parent
_FIXTURES        = _REPO_ROOT / "fixtures"
_SCHEMA_DIR      = _REPO_ROOT / "toolfence" / "contracts" / "schemas"
_SURFACE_FIXTURE = _FIXTURES / "surface_fixture.json"
_FINDINGS_PATH   = _FIXTURES / "findings.json"
_NANOBOT_EVAL    = _REPO_ROOT / "config" / "nanobot.eval.json"

_SURFACE_SCHEMA_PATH = _SCHEMA_DIR / "surface.schema.json"
_TRIAL_SCHEMA_PATH   = _SCHEMA_DIR / "trial.schema.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run a coroutine synchronously (avoids pytest-asyncio dependency)."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# test_tool_list_is_exactly_four  (BOB-2)
# ---------------------------------------------------------------------------

def test_tool_list_is_exactly_four():
    from toolfence.bob.mcp_server import mcp

    tools = _run(mcp.list_tools())
    names = sorted(t.name for t in tools)
    assert names == ["propose_fix", "render_report", "run_eval", "scan_surface"], (
        f"Expected exactly 4 tools, got: {names}"
    )


# ---------------------------------------------------------------------------
# test_scan_surface_returns_valid_surface  (BOB-3)
# ---------------------------------------------------------------------------

def test_scan_surface_returns_valid_surface():
    from toolfence.bob.mcp_server import mcp

    schema = json.loads(_SURFACE_SCHEMA_PATH.read_text(encoding="utf-8"))

    # Use a fixture that is already a plain JSON tool list wrapped in surface format.
    # SurfaceScanner.scan_json accepts a SurfaceFile-shaped JSON or a bare list.
    result = _run(mcp.call_tool("scan_surface", {"source": str(_SURFACE_FIXTURE)}))
    assert not result.is_error, f"scan_surface returned error: {result.content}"

    data = json.loads(result.content[0].text)
    jsonschema.validate(instance=data, schema=schema)   # raises on failure


# ---------------------------------------------------------------------------
# test_run_eval_returns_trial_records  (BOB-4)
# ---------------------------------------------------------------------------

def test_run_eval_returns_trial_records():
    trial_schema = json.loads(_TRIAL_SCHEMA_PATH.read_text(encoding="utf-8"))

    from toolfence.bob.mcp_server import mcp

    # Run a single channel + single defense to keep the test fast.
    result = _run(mcp.call_tool("run_eval", {
        "surface_path": str(_SURFACE_FIXTURE),
        "channels": ["user-input"],
        "defenses": ["none"],
    }))
    assert not result.is_error, f"run_eval returned error: {result.content}"

    records = json.loads(result.content[0].text)
    assert isinstance(records, list)
    assert len(records) >= 1, "Expected at least one trial record"

    for rec in records:
        jsonschema.validate(instance=rec, schema=trial_schema)


# ---------------------------------------------------------------------------
# test_run_eval_unknown_channel_is_error  (BOB-4 validation)
# ---------------------------------------------------------------------------

def test_run_eval_unknown_channel_is_error():
    from toolfence.bob.mcp_server import mcp

    result = _run(mcp.call_tool("run_eval", {
        "surface_path": str(_SURFACE_FIXTURE),
        "channels": ["not-a-channel"],
    }))
    assert result.is_error
    assert "not-a-channel" in result.content[0].text


# ---------------------------------------------------------------------------
# test_run_eval_unknown_defense_is_error  (BOB-4 validation)
# ---------------------------------------------------------------------------

def test_run_eval_unknown_defense_is_error():
    from toolfence.bob.mcp_server import mcp

    result = _run(mcp.call_tool("run_eval", {
        "surface_path": str(_SURFACE_FIXTURE),
        "defenses": ["magic-defense"],
    }))
    assert result.is_error
    assert "magic-defense" in result.content[0].text


# ---------------------------------------------------------------------------
# test_propose_fix_returns_surface_and_tools  (BOB-5)
# ---------------------------------------------------------------------------

def test_propose_fix_returns_surface_and_tools():
    from toolfence.bob.mcp_server import mcp

    # Build a surface containing all nine traveller tools so the enabled_tools
    # comparison against nanobot.eval.json is meaningful.
    nanobot_cfg = json.loads(_NANOBOT_EVAL.read_text(encoding="utf-8"))
    expected_tools = sorted(
        nanobot_cfg["tools"]["mcpServers"]["galaxium"]["enabledTools"]
    )
    import hashlib
    full_surface = {
        "version": 1,
        "tools": [
            {
                "name": name,
                "route": f"GET /{name}",
                "action_class": "read",
                "trust_label": "first-party",
                "description_sha256": hashlib.sha256(name.encode()).hexdigest(),
            }
            for name in expected_tools
        ],
    }
    surface_json = json.dumps(full_surface)

    result = _run(mcp.call_tool("propose_fix", {
        "findings_path": str(_FINDINGS_PATH),
        "surface_json": surface_json,
    }))
    assert not result.is_error, f"propose_fix returned error: {result.content}"

    payload = json.loads(result.content[0].text)
    assert "enabled_tools" in payload
    assert "surface_proposal" in payload
    assert "open_findings" in payload

    # enabled_tools must match the nanobot.eval.json enabledTools list exactly.
    assert sorted(payload["enabled_tools"]) == expected_tools, (
        f"enabled_tools mismatch.\n  got:      {sorted(payload['enabled_tools'])}\n"
        f"  expected: {expected_tools}"
    )

    # open_findings must include F-07 and F-13 (partially_mitigated / reported_only).
    assert "F-07" in payload["open_findings"]
    assert "F-13" in payload["open_findings"]

    # Fully-mitigated findings must not appear.
    assert "F-01" not in payload["open_findings"]


# ---------------------------------------------------------------------------
# test_render_report_contains_disclaimer  (BOB-6)
# ---------------------------------------------------------------------------

def test_render_report_contains_disclaimer():
    from toolfence.bob.mcp_server import mcp
    from toolfence.engine.scoring import DISCLAIMER

    # Build a minimal set of trial records by calling run_eval first.
    eval_result = _run(mcp.call_tool("run_eval", {
        "surface_path": str(_SURFACE_FIXTURE),
        "channels": ["user-input"],
        "defenses": ["none"],
    }))
    assert not eval_result.is_error

    report_result = _run(mcp.call_tool("render_report", {
        "trials_json": eval_result.content[0].text,
        "run_id": "test-run-b6a",
    }))
    assert not report_result.is_error, f"render_report error: {report_result.content}"
    assert DISCLAIMER in report_result.content[0].text, (
        "ENG-8 disclaimer missing from rendered report"
    )


# ---------------------------------------------------------------------------
# test_no_existing_bob_file_modified  (BOB-7)
# ---------------------------------------------------------------------------

def test_no_existing_bob_file_modified():
    """Assert that Galaxium's .bob/ directory is untouched by ToolFence (BOB-7).

    Two checks:

    1. Patch files: none of the patch files in targets/galaxium-patches/ modifies
       a path under .bob/.  Checked by scanning each patch for ``diff --git``
       header lines that reference ``.bob/``.  Always runs.

    2. Live clone (optional): if targets/galaxium/ exists, assert that
       ``git -C targets/galaxium diff --name-only 6163380 -- .bob/``
       produces no output.  The SHA 6163380 is the pinned Galaxium commit
       (PG-1); any .bob/ change since that commit would be a violation.
       Skipped when targets/galaxium/ is absent (clone not fetched yet).
    """
    patches_dir = _REPO_ROOT / "targets" / "galaxium-patches"
    galaxium_dir = _REPO_ROOT / "targets" / "galaxium"

    # --- Check 1: patch files must not touch .bob/ ---
    patch_violations: list[str] = []
    for patch_file in sorted(patches_dir.glob("*.patch")):
        text = patch_file.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            # diff --git a/.bob/... b/.bob/...
            if line.startswith("diff --git") and ".bob/" in line:
                patch_violations.append(f"{patch_file.name}: {line.strip()}")

    assert not patch_violations, (
        "The following patches touch Galaxium's .bob/ directory:\n"
        + "\n".join(f"  {v}" for v in patch_violations)
    )

    # --- Check 2: live clone (skipped when absent) ---
    if not galaxium_dir.is_dir():
        pytest.skip("targets/galaxium/ not present — skipping live .bob/ check")

    result = subprocess.run(
        ["git", "-C", str(galaxium_dir), "diff", "--name-only", "6163380", "--", ".bob/"],
        capture_output=True, text=True,
    )
    changed = result.stdout.strip()
    assert not changed, (
        f"Galaxium's .bob/ has changed since pinned commit 6163380:\n"
        + "\n".join(f"  {p}" for p in changed.splitlines())
    )
