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


# ---------------------------------------------------------------------------
# FIX 1: path traversal
# ---------------------------------------------------------------------------

def test_path_traversal_blocked(tmp_path: Path) -> None:
    """GET /static/../../../../pyproject.toml must return 404 (path traversal blocked)."""
    import http.client
    import socket

    port = _free_port()
    proc = subprocess.Popen(
        [
            _PYTHON, "-m", "toolfence", "serve",
            "--host", "127.0.0.1",
            "--port", str(port),
            "--results-dir", str(tmp_path),
        ],
        cwd=str(_REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for server to start
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                break
        except OSError:
            time.sleep(0.1)

    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        # Send traversal path literally — http.client does NOT normalise ".."
        conn.request("GET", "/static/../../../../pyproject.toml")
        resp = conn.getresponse()
        assert resp.status == 404, (
            f"Expected 404 for path traversal attempt, got {resp.status}"
        )
        conn.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


# ---------------------------------------------------------------------------
# FIX 3: /api/results excludes non-TrialRecord JSON
# ---------------------------------------------------------------------------

def test_api_results_excludes_non_trial_records(tmp_path: Path) -> None:
    """GET /api/results must include valid TrialRecords only; surface.json shape is excluded."""
    import shutil

    # Copy one valid TrialRecord fixture into tmp_path
    shutil.copy(_FIXTURE_DIR / "run-01.json", tmp_path / "run-01.json")

    # Write a non-TrialRecord JSON file (surface.json shape)
    surface_like = {"version": 1, "tools": []}
    (tmp_path / "surface.json").write_text(
        json.dumps(surface_like), encoding="utf-8"
    )

    port = _free_port()
    proc = subprocess.Popen(
        [
            _PYTHON, "-m", "toolfence", "serve",
            "--host", "127.0.0.1",
            "--port", str(port),
            "--results-dir", str(tmp_path),
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

    try:
        status, body = _get(base_url + "/api/results")
        assert status == 200, f"Expected 200 from GET /api/results, got {status}"
        records = json.loads(body)
        assert isinstance(records, list), "Expected JSON array"
        assert len(records) == 1, (
            f"Expected exactly 1 record (valid TrialRecord only), got {len(records)}"
        )
        # Confirm the surface-shaped file is not in the results
        for rec in records:
            assert "version" not in rec or "trial_id" in rec, (
                "surface.json shape should not appear in /api/results"
            )
        assert records[0].get("trial_id") == "spike-run-01", (
            "Expected the valid TrialRecord (spike-run-01) in results"
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


# ---------------------------------------------------------------------------
# Multi-run support (Sub-Task 2)
# ---------------------------------------------------------------------------

def _start_server(tmp_path: Path) -> tuple[str, subprocess.Popen]:
    """Start a dashboard server against tmp_path; return (base_url, proc).

    Caller is responsible for terminating the process.
    """
    import socket

    port = _free_port()
    proc = subprocess.Popen(
        [
            _PYTHON, "-m", "toolfence", "serve",
            "--host", "127.0.0.1",
            "--port", str(port),
            "--results-dir", str(tmp_path),
        ],
        cwd=str(_REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                break
        except OSError:
            time.sleep(0.1)
    return base_url, proc


def _stop_server(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _make_run_dirs(tmp_path: Path, names: list[str]) -> None:
    """Create named subdirectories under tmp_path, each with a valid TrialRecord JSON."""
    import shutil

    src = _FIXTURE_DIR / "run-01.json"
    for name in names:
        sub = tmp_path / name
        sub.mkdir()
        shutil.copy(src, sub / "run-01.json")


def test_api_runs_with_subfolders(tmp_path: Path) -> None:
    """GET /api/runs returns sorted list of subfolder names that contain *.json."""
    _make_run_dirs(tmp_path, ["run_a", "run_b"])
    base_url, proc = _start_server(tmp_path)
    try:
        status, body = _get(base_url + "/api/runs")
        assert status == 200, f"Expected 200 from /api/runs, got {status}"
        runs = json.loads(body)
        assert runs == ["run_a", "run_b"], f"Expected ['run_a', 'run_b'], got {runs}"
    finally:
        _stop_server(proc)


def test_api_runs_flat_returns_empty(tmp_path: Path) -> None:
    """GET /api/runs returns [] when results dir has only flat *.json files."""
    import shutil

    shutil.copy(_FIXTURE_DIR / "run-01.json", tmp_path / "run-01.json")
    base_url, proc = _start_server(tmp_path)
    try:
        status, body = _get(base_url + "/api/runs")
        assert status == 200, f"Expected 200 from /api/runs, got {status}"
        runs = json.loads(body)
        assert runs == [], f"Expected [], got {runs}"
    finally:
        _stop_server(proc)


def test_api_summary_with_run_param(tmp_path: Path) -> None:
    """GET /api/summary?run=run_a returns 200 with a valid summary containing 'disclaimer'."""
    _make_run_dirs(tmp_path, ["run_a"])
    base_url, proc = _start_server(tmp_path)
    try:
        status, body = _get(base_url + "/api/summary?run=run_a")
        assert status == 200, f"Expected 200 from /api/summary?run=run_a, got {status}"
        summary = json.loads(body)
        assert "disclaimer" in summary, "Expected 'disclaimer' key in summary JSON"
        assert summary["disclaimer"], "Expected non-empty disclaimer"
    finally:
        _stop_server(proc)


def test_api_results_with_run_param(tmp_path: Path) -> None:
    """GET /api/results?run=run_a returns 200 JSON array with at least 1 record."""
    _make_run_dirs(tmp_path, ["run_a"])
    base_url, proc = _start_server(tmp_path)
    try:
        status, body = _get(base_url + "/api/results?run=run_a")
        assert status == 200, f"Expected 200 from /api/results?run=run_a, got {status}"
        records = json.loads(body)
        assert isinstance(records, list), "Expected JSON array"
        assert len(records) >= 1, f"Expected at least 1 record, got {len(records)}"
    finally:
        _stop_server(proc)


def test_api_run_path_traversal_rejected(tmp_path: Path) -> None:
    """GET /api/summary?run=../secret must return 400."""
    import http.client
    import socket

    base_url, proc = _start_server(tmp_path)
    try:
        port = int(base_url.split(":")[-1])
        # Use http.client to send the raw query string without normalisation
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/api/summary?run=..%2Fsecret")
        resp = conn.getresponse()
        assert resp.status == 400, (
            f"Expected 400 for path traversal attempt (?run=../secret), got {resp.status}"
        )
        conn.close()
    finally:
        _stop_server(proc)


def test_api_run_slash_rejected(tmp_path: Path) -> None:
    """GET /api/summary?run=a/b must return 400."""
    import http.client

    base_url, proc = _start_server(tmp_path)
    try:
        port = int(base_url.split(":")[-1])
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/api/summary?run=a%2Fb")
        resp = conn.getresponse()
        assert resp.status == 400, (
            f"Expected 400 for slash in run name (?run=a/b), got {resp.status}"
        )
        conn.close()
    finally:
        _stop_server(proc)


def test_api_run_not_found(tmp_path: Path) -> None:
    """GET /api/summary?run=nonexistent returns 404 when no such subfolder exists."""
    base_url, proc = _start_server(tmp_path)
    try:
        status, _ = _get(base_url + "/api/summary?run=nonexistent")
        assert status == 404, (
            f"Expected 404 for missing run subfolder, got {status}"
        )
    finally:
        _stop_server(proc)


# ---------------------------------------------------------------------------
# Sub-Task 3: tool-call detail keys present in /api/results
# ---------------------------------------------------------------------------

def test_api_results_includes_tool_calls(server_url: str) -> None:
    """GET /api/results must return records whose trace.tool_calls entries have
    the required keys: name, params, result, provenance, guard_decision."""
    status, body = _get(server_url + "/api/results")
    assert status == 200, f"Expected 200 from GET /api/results, got {status}"
    records = json.loads(body)
    assert isinstance(records, list), "Expected JSON array from /api/results"

    # Find the first record with a non-null trace containing tool_calls
    trace_record = None
    for rec in records:
        trace = rec.get("trace")
        if trace and trace.get("tool_calls"):
            trace_record = rec
            break

    assert trace_record is not None, (
        "Expected at least one record with a non-null trace and tool_calls"
    )

    tool_calls = trace_record["trace"]["tool_calls"]
    required_keys = {"name", "params", "result", "provenance", "guard_decision"}
    for i, tc in enumerate(tool_calls):
        missing = required_keys - set(tc.keys())
        assert not missing, (
            f"tool_calls[{i}] is missing keys {missing}; got keys {set(tc.keys())}"
        )
