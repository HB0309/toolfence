"""C-6 — Dashboard server unit tests (no Playwright required).

These tests run against the server directly via urllib — no browser needed.
They always run (no playwright dependency).

Test inventory
--------------
  test_server_serves_index_html         -- GET / returns 200 with HTML
  test_server_api_results               -- GET /api/results returns JSON array
  test_server_api_summary_has_disclaimer -- GET /api/summary disclaimer field present
  test_server_api_summary_inconclusive   -- ResultSummary has inconclusive count field
  test_serve_subcommand_in_help          -- toolfence --help mentions 'serve'
  test_index_html_has_inconclusive_column -- static/index.html source contains 'inconclusive'
  test_server_no_env_reads               -- server.py source has no os.environ reads
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_FIXTURE_DIR = _REPO_ROOT / "fixtures" / "spike_converted"
_PYTHON = sys.executable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _free_port() -> int:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server_url():
    """Start the dashboard server against the fixture results dir; yield its base URL."""
    port = _free_port()
    proc = subprocess.Popen(
        [
            _PYTHON, "-m", "toolfence", "serve",
            "--host", "127.0.0.1",
            "--port", str(port),
            "--results-dir", str(_FIXTURE_DIR),
        ],
        cwd=str(_REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(base_url + "/api/results", timeout=1)
            break
        except Exception:  # noqa: BLE001
            time.sleep(0.1)

    yield base_url

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""


# ---------------------------------------------------------------------------
# Server endpoint tests
# ---------------------------------------------------------------------------

def test_server_serves_index_html(server_url: str) -> None:
    """GET / must return 200 with HTML content."""
    status, body = _get(server_url + "/")
    assert status == 200, f"Expected 200 from GET /, got {status}"
    assert b"<html" in body.lower() or b"<!doctype" in body.lower(), (
        "Expected HTML response from GET /"
    )


def test_server_api_results(server_url: str) -> None:
    """GET /api/results must return a JSON array of records from the fixture dir."""
    status, body = _get(server_url + "/api/results")
    assert status == 200, f"Expected 200 from GET /api/results, got {status}"
    records = json.loads(body)
    assert isinstance(records, list), "Expected JSON array from /api/results"
    # spike_converted has 10 records
    assert len(records) >= 1, (
        f"Expected at least 1 record from fixture dir, got {len(records)}"
    )


def test_server_api_summary_has_disclaimer(server_url: str) -> None:
    """GET /api/summary must include the ENG-8 disclaimer in the response body."""
    _DISCLAIMER = (
        "A clean result means the evaluation did not find a way through, "
        "not that none exists."
    )
    status, body = _get(server_url + "/api/summary")
    assert status == 200, f"Expected 200 from GET /api/summary, got {status}"
    summary = json.loads(body)
    assert "disclaimer" in summary, "Expected 'disclaimer' key in summary JSON"
    assert _DISCLAIMER in summary["disclaimer"], (
        f"ENG-8 disclaimer missing from summary response.\nGot: {summary['disclaimer']!r}"
    )


def test_server_api_summary_inconclusive(server_url: str) -> None:
    """GET /api/summary must expose inconclusive counts in conditions (never folded)."""
    status, body = _get(server_url + "/api/summary")
    assert status == 200
    summary = json.loads(body)
    conditions = summary.get("conditions", [])
    # Each attack condition must carry an 'inconclusive' key in its attack sub-object
    for cond in conditions:
        attack = cond.get("attack", {})
        assert "inconclusive" in attack, (
            f"Expected 'inconclusive' key in attack condition {cond}, got keys: {list(attack.keys())}"
        )


def test_server_404_for_unknown_path(server_url: str) -> None:
    """GET /does-not-exist must return 404."""
    status, _ = _get(server_url + "/does-not-exist")
    assert status == 404, f"Expected 404 for unknown path, got {status}"


# ---------------------------------------------------------------------------
# Static file and source checks (no server needed)
# ---------------------------------------------------------------------------

def test_index_html_has_inconclusive_column() -> None:
    """static/index.html source must contain 'inconclusive' as a column identifier."""
    html_path = (
        _REPO_ROOT / "toolfence" / "cli" / "dashboard" / "static" / "index.html"
    )
    assert html_path.exists(), f"Expected {html_path} to exist"
    content = html_path.read_text(encoding="utf-8")
    assert "inconclusive" in content.lower(), (
        "static/index.html must reference 'inconclusive' as a column"
    )


def test_server_no_env_reads() -> None:
    """server.py must not read environment variables (no os.environ access)."""
    import re
    src = (
        _REPO_ROOT / "toolfence" / "cli" / "dashboard" / "server.py"
    ).read_text(encoding="utf-8")
    # Forbid os.environ and os.getenv at the statement level
    for pattern in (r"\bos\.environ\b", r"\bos\.getenv\b"):
        assert not re.search(pattern, src), (
            f"server.py must not read environment variables (found pattern {pattern!r})"
        )


# ---------------------------------------------------------------------------
# CLI help text
# ---------------------------------------------------------------------------

def test_serve_subcommand_in_help() -> None:
    """toolfence --help must list the 'serve' subcommand."""
    result = subprocess.run(
        [_PYTHON, "-m", "toolfence", "--help"],
        capture_output=True, text=True, cwd=str(_REPO_ROOT),
    )
    assert "serve" in result.stdout, (
        f"Expected 'serve' in toolfence --help output.\nstdout: {result.stdout}"
    )
