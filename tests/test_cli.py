"""C-4 — CLI integration tests.

Covers:
  CLI-1  `toolfence scan` exits 0 and prints tool table
  CLI-2  `toolfence run` exits 0 and writes ≥1 JSON files
  CLI-3  `toolfence report` exits 0 and prints disclaimer + grid
  CLI-7  No API key or secret in committed tree outside .env.example

Test inventory
--------------
  test_scan_exits_zero           -- scan fixture surface; exit 0; tool name in stdout
  test_run_exits_zero            -- run against fixture surface; exit 0; ≥1 .json written
  test_report_exits_zero         -- report on run output; exit 0; disclaimer in stdout
  test_no_api_key_in_tree        -- grep committed tree for key pattern; assert no matches
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_SURFACE_FIXTURE = _REPO_ROOT / "fixtures" / "surface_fixture.json"
_PYTHON = sys.executable

# Disclaimer string that must appear in every report (ENG-8).
_DISCLAIMER = (
    "A clean result means the evaluation did not find a way through, "
    "not that none exists."
)

# One tool name that must appear in the scan output.
_EXPECTED_TOOL_NAME = "mcp_galaxium_get_flights_flights_get"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_cli(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run `python -m toolfence <args>` and return the completed process."""
    import os
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [_PYTHON, "-m", "toolfence"] + list(args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        cwd=str(_REPO_ROOT),
        env=env,
    )


# ---------------------------------------------------------------------------
# CLI-1 — scan
# ---------------------------------------------------------------------------

def test_scan_exits_zero() -> None:
    """toolfence scan <surface_fixture> exits 0 and contains a tool name in stdout."""
    result = _run_cli("scan", str(_SURFACE_FIXTURE))

    assert result.returncode == 0, (
        f"Expected exit 0 from scan, got {result.returncode}.\n"
        f"stderr: {result.stderr}"
    )
    assert _EXPECTED_TOOL_NAME in result.stdout, (
        f"Expected tool name {_EXPECTED_TOOL_NAME!r} in scan output.\n"
        f"stdout: {result.stdout}"
    )


def test_scan_prints_all_five_tools() -> None:
    """scan output must contain all 5 tools from the fixture surface."""
    surface_data = json.loads(_SURFACE_FIXTURE.read_text(encoding="utf-8"))
    expected_names = [t["name"] for t in surface_data["tools"]]

    result = _run_cli("scan", str(_SURFACE_FIXTURE))
    assert result.returncode == 0

    for name in expected_names:
        assert name in result.stdout, (
            f"Tool {name!r} missing from scan output.\nstdout: {result.stdout}"
        )


def test_scan_prints_action_classes() -> None:
    """scan output must contain action class labels."""
    result = _run_cli("scan", str(_SURFACE_FIXTURE))
    assert result.returncode == 0
    # All three action classes are present in the fixture
    for action_class in ("read", "state-changing", "irreversible"):
        assert action_class in result.stdout, (
            f"Action class {action_class!r} missing from scan output."
        )


# ---------------------------------------------------------------------------
# CLI-2 — run
# ---------------------------------------------------------------------------

def test_run_exits_zero(tmp_path: Path) -> None:
    """toolfence run exits 0 and writes ≥1 .json trial record files."""
    result = _run_cli(
        "run",
        "--surface", str(_SURFACE_FIXTURE),
        "--output", str(tmp_path),
    )

    assert result.returncode == 0, (
        f"Expected exit 0 from run, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    json_files = list(tmp_path.glob("*.json"))
    assert len(json_files) >= 1, (
        f"Expected ≥1 .json trial record in {tmp_path}, got {len(json_files)}."
    )


def test_run_writes_valid_trial_records(tmp_path: Path) -> None:
    """Each .json file written by run must be a valid TrialRecord."""
    from toolfence.contracts.trial import TrialRecord

    result = _run_cli(
        "run",
        "--surface", str(_SURFACE_FIXTURE),
        "--output", str(tmp_path),
    )
    assert result.returncode == 0

    json_files = list(tmp_path.glob("*.json"))
    assert len(json_files) >= 1

    for jf in json_files:
        data = json.loads(jf.read_text(encoding="utf-8"))
        # Should not raise
        rec = TrialRecord.model_validate(data)
        assert rec.trial_id, f"{jf.name}: trial_id is empty"


def test_run_produces_18_records(tmp_path: Path) -> None:
    """run with 2 attack probes × 6 defenses + 1 normal probe × 6 defenses = 18 records."""
    result = _run_cli(
        "run",
        "--surface", str(_SURFACE_FIXTURE),
        "--output", str(tmp_path),
    )
    assert result.returncode == 0

    json_files = list(tmp_path.glob("*.json"))
    assert len(json_files) == 18, (
        f"Expected 18 trial records (12 attack + 6 normal), got {len(json_files)}."
    )


def test_run_prints_progress(tmp_path: Path) -> None:
    """run prints trial-by-trial progress and a total count line to stdout."""
    result = _run_cli(
        "run",
        "--surface", str(_SURFACE_FIXTURE),
        "--output", str(tmp_path),
    )
    assert result.returncode == 0
    # Should mention total record count in output
    assert "18" in result.stdout or "record" in result.stdout.lower(), (
        f"Expected progress output mentioning records.\nstdout: {result.stdout}"
    )


# ---------------------------------------------------------------------------
# CLI-3 — report
# ---------------------------------------------------------------------------

def test_report_exits_zero(tmp_path: Path) -> None:
    """toolfence report on a run-output dir exits 0 and disclaimer in stdout."""
    # First produce records
    run_result = _run_cli(
        "run",
        "--surface", str(_SURFACE_FIXTURE),
        "--output", str(tmp_path),
    )
    assert run_result.returncode == 0, (
        f"run failed: {run_result.stderr}"
    )

    # Now report
    result = _run_cli("report", str(tmp_path))

    assert result.returncode == 0, (
        f"Expected exit 0 from report, got {result.returncode}.\n"
        f"stderr: {result.stderr}"
    )
    assert _DISCLAIMER in result.stdout, (
        "ENG-8 disclaimer missing from report output."
    )


def test_report_contains_inconclusive_column(tmp_path: Path) -> None:
    """report output must contain 'inconclusive' as its own column (ENG-7)."""
    _run_cli("run", "--surface", str(_SURFACE_FIXTURE), "--output", str(tmp_path))
    result = _run_cli("report", str(tmp_path))
    assert result.returncode == 0
    assert "inconclusive" in result.stdout.lower(), (
        "The 'inconclusive' column is missing from the report."
    )


def test_report_contains_both_sections(tmp_path: Path) -> None:
    """report output must contain both Normal-Task and Security sections (ENG-7)."""
    _run_cli("run", "--surface", str(_SURFACE_FIXTURE), "--output", str(tmp_path))
    result = _run_cli("report", str(tmp_path))
    assert result.returncode == 0
    assert "normal" in result.stdout.lower(), "Normal-task section missing from report."
    assert "security" in result.stdout.lower() or "attack" in result.stdout.lower(), (
        "Security section missing from report."
    )


# ---------------------------------------------------------------------------
# CLI-7 — no API key in committed tree
# ---------------------------------------------------------------------------

def test_no_api_key_in_tree() -> None:
    """No API key value appears in committed source code outside .env.example (CLI-7).

    Looks for _API_KEY=<non-empty-value> patterns in source code files only
    (.py, .json, .yaml, .yml, .toml, .env).  Documentation (.md, .txt) and
    session logs (bob_sessions/) are excluded because they legitimately reference
    variable *names* without values.

    The pattern _API_KEY=\\S+ would match a real key like:
        OPENROUTER_API_KEY=sk-abc123
    but NOT documentation like:
        - `.env.example` — `OPENROUTER_API_KEY=` (key name only)
    """
    # Pattern: _API_KEY= followed immediately by a character that would only
    # appear as part of a real key value (alphanumeric, hyphen, underscore).
    # This excludes empty assignments, docstring examples, and regex literals.
    pattern = re.compile(r"_API_KEY=[A-Za-z0-9\-_]{4,}")

    # Directories to skip entirely
    skip_dirs = {".git", ".venv", "venv", "targets", "__pycache__", ".bob",
                 "bob_sessions", "docs", "tests"}
    # The one file explicitly allowed to contain the variable name
    allowed_file = _REPO_ROOT / ".env.example"

    # Only check production source/config files — not tests or documentation
    extensions = {".py", ".json", ".yaml", ".yml", ".toml", ".env"}

    violations: list[str] = []

    for path in _REPO_ROOT.rglob("*"):
        if any(part in skip_dirs for part in path.parts):
            continue
        if path == allowed_file:
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() not in extensions:
            continue

        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            # Skip comment lines
            if stripped.startswith(("#", "//", "*")):
                continue
            if pattern.search(line):
                violations.append(f"{path.relative_to(_REPO_ROOT)}:{lineno}: {stripped}")

    assert not violations, (
        "API key value found in committed source tree (outside .env.example):\n"
        + "\n".join(violations)
    )
