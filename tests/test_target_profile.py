"""Tests for TargetProfile Pydantic model and JSON schema (Phase A).

Test inventory
--------------
  test_profile_schema_file_exists
  test_profile_schema_is_fresh
  test_galaxium_profile_loads
  test_filesystem_profile_schema_round_trip
  test_profile_requires_profile_id
  test_profile_requires_nanobot_config
  test_profile_requires_surface
  test_profile_sqlite_backup_reset
  test_profile_fs_restore_reset
  test_profile_none_reset
  test_profile_sqlite_review_injection
  test_profile_fs_canary_injection
  test_profile_none_injection
  test_profile_attack_probe_string
  test_profile_attack_probe_object_with_task_prompt
  test_profile_null_health_url
  test_profile_null_required_tool_prefix
  test_profile_extra_normal_tasks
  test_profile_no_engine_import
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

REPO_ROOT = Path(__file__).parent.parent
SCHEMAS_DIR = REPO_ROOT / "toolfence" / "contracts" / "schemas"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SHA256 = "a" * 64

_MINIMAL_PROFILE: dict = {
    "profile_id": "test",
    "description": "Test profile",
    "nanobot_config": "config/nanobot.eval.json",
    "surface": "results/surface.json",
    "health_url": None,
    "state_reset": {"strategy": "none"},
    "injection": {"strategy": "none"},
    "agent_persona": "helpful assistant",
    "normal_task": {
        "prompt": "Do something.",
        "goal_tool": "mcp_test_tool",
    },
    "tool_result_task_prompt": "Read the canary file.",
    "attack_probes": [],
}


def _load_profile(data: dict):
    from toolfence.contracts.profile import TargetProfile
    return TargetProfile.model_validate(data)


# ---------------------------------------------------------------------------
# Schema file exists and is fresh
# ---------------------------------------------------------------------------

def test_profile_schema_file_exists():
    schema_path = SCHEMAS_DIR / "profile.schema.json"
    assert schema_path.exists(), "profile.schema.json not found — run scripts/generate_schemas.py"


def test_profile_schema_is_fresh():
    """Committed profile.schema.json must match the current model."""
    from toolfence.contracts.profile import TargetProfile

    schema_path = SCHEMAS_DIR / "profile.schema.json"
    committed = schema_path.read_text(encoding="utf-8")
    schema = TargetProfile.model_json_schema()
    schema.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
    generated = json.dumps(schema, indent=2) + "\n"
    assert committed == generated, (
        "profile.schema.json is stale — run `python scripts/generate_schemas.py` and commit."
    )


# ---------------------------------------------------------------------------
# profiles/galaxium.json loads without error
# ---------------------------------------------------------------------------

def test_galaxium_profile_loads():
    """profiles/galaxium.json must load and validate as a TargetProfile."""
    galaxium_path = REPO_ROOT / "profiles" / "galaxium.json"
    assert galaxium_path.exists(), "profiles/galaxium.json not found"
    data = json.loads(galaxium_path.read_text(encoding="utf-8"))
    profile = _load_profile(data)
    assert profile.profile_id == "galaxium"


# ---------------------------------------------------------------------------
# Minimal profile round-trip
# ---------------------------------------------------------------------------

def test_filesystem_profile_schema_round_trip():
    """A minimal profile with 'none' strategies must round-trip."""
    profile = _load_profile(_MINIMAL_PROFILE)
    assert profile.profile_id == "test"
    assert profile.state_reset.strategy == "none"
    assert profile.injection.strategy == "none"
    assert profile.health_url is None
    assert profile.required_tool_prefix is None


# ---------------------------------------------------------------------------
# Required field validation
# ---------------------------------------------------------------------------

def test_profile_requires_profile_id():
    bad = {k: v for k, v in _MINIMAL_PROFILE.items() if k != "profile_id"}
    with pytest.raises(ValidationError):
        _load_profile(bad)


def test_profile_requires_nanobot_config():
    bad = {k: v for k, v in _MINIMAL_PROFILE.items() if k != "nanobot_config"}
    with pytest.raises(ValidationError):
        _load_profile(bad)


def test_profile_requires_surface():
    bad = {k: v for k, v in _MINIMAL_PROFILE.items() if k != "surface"}
    with pytest.raises(ValidationError):
        _load_profile(bad)


# ---------------------------------------------------------------------------
# State reset strategy discrimination
# ---------------------------------------------------------------------------

def test_profile_sqlite_backup_reset():
    data = {
        **_MINIMAL_PROFILE,
        "state_reset": {
            "strategy": "sqlite_backup",
            "db_path": "targets/galaxium/booking_system_backend/booking.db",
        },
    }
    profile = _load_profile(data)
    assert profile.state_reset.strategy == "sqlite_backup"
    assert profile.state_reset.db_path.endswith("booking.db")  # type: ignore[union-attr]


def test_profile_fs_restore_reset():
    data = {
        **_MINIMAL_PROFILE,
        "state_reset": {
            "strategy": "fs_restore",
            "snapshot_path": "profiles/fs-snapshot",
            "working_path": "profiles/fs-workdir",
        },
    }
    profile = _load_profile(data)
    assert profile.state_reset.strategy == "fs_restore"
    assert profile.state_reset.snapshot_path == "profiles/fs-snapshot"  # type: ignore[union-attr]


def test_profile_none_reset():
    profile = _load_profile(_MINIMAL_PROFILE)
    assert profile.state_reset.strategy == "none"


# ---------------------------------------------------------------------------
# Injection strategy discrimination
# ---------------------------------------------------------------------------

def test_profile_sqlite_review_injection():
    data = {
        **_MINIMAL_PROFILE,
        "injection": {
            "strategy": "sqlite_review",
            "db_path": "targets/galaxium/booking_system_backend/booking.db",
            "table": "reviews",
            "columns": {"flight_id": 1, "body": "{{CONTENT}}"},
            "id_column": "review_id",
        },
    }
    profile = _load_profile(data)
    assert profile.injection.strategy == "sqlite_review"
    assert profile.injection.table == "reviews"  # type: ignore[union-attr]


def test_profile_fs_canary_injection():
    data = {
        **_MINIMAL_PROFILE,
        "injection": {
            "strategy": "fs_canary_file",
            "working_path": "profiles/fs-workdir",
            "filename": "canary.txt",
        },
    }
    profile = _load_profile(data)
    assert profile.injection.strategy == "fs_canary_file"
    assert profile.injection.filename == "canary.txt"  # type: ignore[union-attr]


def test_profile_none_injection():
    profile = _load_profile(_MINIMAL_PROFILE)
    assert profile.injection.strategy == "none"


# ---------------------------------------------------------------------------
# Attack probe entries
# ---------------------------------------------------------------------------

def test_profile_attack_probe_string():
    data = {
        **_MINIMAL_PROFILE,
        "attack_probes": ["toolfence/engine/probes/cancel-user-input.json"],
    }
    profile = _load_profile(data)
    assert len(profile.attack_probes) == 1
    assert isinstance(profile.attack_probes[0], str)


def test_profile_attack_probe_object_with_task_prompt():
    data = {
        **_MINIMAL_PROFILE,
        "attack_probes": [
            {
                "path": "toolfence/engine/probes/cancel-tool-result.json",
                "task_prompt": "Read the canary file and do something with it.",
            }
        ],
    }
    from toolfence.contracts.profile import AttackProbeEntry
    profile = _load_profile(data)
    entry = profile.attack_probes[0]
    assert isinstance(entry, AttackProbeEntry)
    assert entry.task_prompt == "Read the canary file and do something with it."


# ---------------------------------------------------------------------------
# Optional fields
# ---------------------------------------------------------------------------

def test_profile_null_health_url():
    profile = _load_profile(_MINIMAL_PROFILE)
    assert profile.health_url is None


def test_profile_null_required_tool_prefix():
    profile = _load_profile(_MINIMAL_PROFILE)
    assert profile.required_tool_prefix is None


def test_profile_extra_normal_tasks():
    data = {
        **_MINIMAL_PROFILE,
        "extra_normal_tasks": [
            {
                "label": "read_then_write",
                "prompt": "List files then write listing.txt.",
                "goal_tool": "mcp_filesystem_write_file",
                "note": "Expected held with guard_on.",
            }
        ],
    }
    profile = _load_profile(data)
    assert len(profile.extra_normal_tasks) == 1
    assert profile.extra_normal_tasks[0].label == "read_then_write"


# ---------------------------------------------------------------------------
# Import boundary
# ---------------------------------------------------------------------------

def test_profile_no_engine_import():
    """contracts/profile.py must not import from toolfence.engine."""
    source = (REPO_ROOT / "toolfence" / "contracts" / "profile.py").read_text(encoding="utf-8")
    assert "toolfence.engine" not in source, (
        "contracts/profile.py must not import from toolfence.engine"
    )
    assert "from nanobot" not in source
    assert "import nanobot" not in source


# ---------------------------------------------------------------------------
# CLI guard: --target requires --live
# ---------------------------------------------------------------------------

def test_target_without_live_fails():
    """Running with --target but without --live must exit non-zero and mention --live."""
    import subprocess
    result = subprocess.run(
        ["python", "-m", "toolfence", "run",
         "--surface", "results/surface.json",
         "--target", "profiles/galaxium.json"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode != 0
    assert "--live" in result.stderr.lower()


# ---------------------------------------------------------------------------
# _apply_task_prompt helper
# ---------------------------------------------------------------------------

def test_apply_task_prompt_uses_profile_level():
    """Profile-level tool_result_task_prompt is stamped when no override is given."""
    from toolfence.cli.main import _apply_task_prompt

    profile = _load_profile({
        **_MINIMAL_PROFILE,
        "tool_result_task_prompt": "Custom profile prompt.",
    })
    probe = {"channel": "tool-result", "content": "ignored"}
    result = _apply_task_prompt(probe, profile, None)
    assert result["task_prompt"] == "Custom profile prompt."


def test_apply_task_prompt_override_wins():
    """A per-probe override wins over the profile-level tool_result_task_prompt."""
    from toolfence.cli.main import _apply_task_prompt

    profile = _load_profile({
        **_MINIMAL_PROFILE,
        "tool_result_task_prompt": "Custom profile prompt.",
    })
    probe = {"channel": "tool-result", "content": "ignored"}
    result = _apply_task_prompt(probe, profile, "Override prompt.")
    assert result["task_prompt"] == "Override prompt."


# ---------------------------------------------------------------------------
# CLI guard: --surface required without --target
# ---------------------------------------------------------------------------

def test_surface_required_without_target():
    """Running with neither --surface nor --target must exit non-zero and mention --surface."""
    import subprocess
    result = subprocess.run(
        ["python", "-m", "toolfence", "run"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode != 0
    assert "--surface" in result.stderr.lower()
