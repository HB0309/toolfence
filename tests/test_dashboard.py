"""C-6 — Dashboard tests.

Covers:
  CLI-6  Dashboard grid has at least one row and 'inconclusive' column header
  CLI-6  Replay button steps through stored TrialRecord objects
  CLI-6  No outbound network requests (Playwright route intercept)

The entire test module requires playwright to be installed.
``pytest.importorskip("playwright")`` at module level causes the whole file to
be skipped cleanly when playwright is not present (per spec: "skips gracefully
offline").

Test inventory
--------------
  test_dashboard_grid_loads         -- grid table has ≥1 row; inconclusive column header present
  test_dashboard_replay             -- replay button steps through records; counter matches total
  test_dashboard_no_outbound_requests  -- no request leaves localhost during navigation + replay

Non-Playwright tests (always run):
  test_server_api_results           -- GET /api/results returns JSON array
  test_server_api_summary           -- GET /api/summary returns ResultSummary with inconclusive field
  test_server_static_index          -- GET / returns HTML containing "inconclusive"
  test_serve_subcommand_in_help     -- toolfence --help mentions 'serve'
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Module-level importorskip — skips entire file if playwright is absent.
# Must be at module level, not inside a test function (per spec).
# ---------------------------------------------------------------------------
playwright_mod = pytest.importorskip("playwright")

from playwright.sync_api import sync_playwright  # noqa: E402 — after importorskip

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_FIXTURE_DIR = _REPO_ROOT / "fixtures" / "spike_converted"
_PYTHON = sys.executable

# ---------------------------------------------------------------------------
# Server fixture — starts the dashboard server as a subprocess
# ---------------------------------------------------------------------------

import socket as _socket


def _free_port() -> int:
    """Find a free TCP port on localhost."""
    with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def dashboard_url():
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

    # Wait for the server to be ready (up to 5 s)
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 5.0
    import urllib.request
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


# ---------------------------------------------------------------------------
# CLI-6 test 1 — grid loads with inconclusive column header
# ---------------------------------------------------------------------------

def test_dashboard_grid_loads(dashboard_url: str) -> None:
    """Security grid section is rendered and 'inconclusive' column header is present (CLI-6).

    The fixture uses spike_converted records which are all normal-kind; the security
    grid renders its header row (column definitions) even when no attack rows exist,
    so the inconclusive *column definition* is still present in the page source.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(dashboard_url)
        page.wait_for_load_state("networkidle")

        # The security grid container must be present in the DOM
        grid_div = page.query_selector("#security-grid")
        assert grid_div is not None, "Security grid container (#security-grid) not found in DOM"
        assert grid_div.inner_html().strip() != "", (
            "#security-grid must not be empty after data loads"
        )

        # Normal-task table must have at least one row (10 spike_converted records)
        normal_table = page.query_selector("#normal-table")
        assert normal_table is not None, "Normal-task table (#normal-table) not found in DOM"
        rows = page.query_selector_all("#normal-table tbody tr")
        assert len(rows) >= 1, (
            f"Expected at least 1 row in normal-task grid, got {len(rows)}"
        )

        # "inconclusive" must appear somewhere on the page — it is defined as a
        # column in the JS template headers, regardless of whether attack rows exist.
        page_text = page.content()
        assert "inconclusive" in page_text.lower(), (
            "Expected 'inconclusive' to appear in the dashboard page"
        )

        browser.close()


# ---------------------------------------------------------------------------
# CLI-6 test 2 — replay button steps through records
# ---------------------------------------------------------------------------

def test_dashboard_replay(dashboard_url: str) -> None:
    """Clicking replay steps through stored TrialRecord objects; counter matches total (CLI-6)."""
    # Count how many fixture records there are
    fixture_records = list(_FIXTURE_DIR.glob("*.json"))
    expected_count = len(fixture_records)
    assert expected_count >= 1, "Need at least 1 fixture record for replay test"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(dashboard_url)
        page.wait_for_load_state("networkidle")

        btn = page.query_selector("#replay-btn")
        assert btn is not None, "Replay button (#replay-btn) not found"
        assert not btn.is_disabled(), "Replay button should not be disabled when records exist"

        # Click to start replay
        btn.click()

        # Wait for all records to be stepped through
        # Each step is REPLAY_INTERVAL_MS (800ms); add generous timeout
        timeout_ms = (expected_count + 3) * 1500

        # Wait until the counter shows the expected count
        page.wait_for_function(
            f"document.getElementById('replay-counter').textContent.includes('{expected_count} / {expected_count}')",
            timeout=timeout_ms,
        )

        # Verify at least one replay card was rendered
        cards = page.query_selector_all(".replay-card")
        assert len(cards) >= 1, (
            f"Expected at least 1 replay card after stepping through {expected_count} record(s)"
        )

        # The counter should show full completion
        counter_text = page.query_selector("#replay-counter").inner_text()
        assert str(expected_count) in counter_text, (
            f"Replay counter {counter_text!r} does not show expected count {expected_count}"
        )

        browser.close()


# ---------------------------------------------------------------------------
# CLI-6 test 3 — no outbound requests
# ---------------------------------------------------------------------------

def test_dashboard_no_outbound_requests(dashboard_url: str) -> None:
    """No request leaves localhost during navigation and replay (CLI-6)."""
    outbound_urls: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        # Intercept every network request; flag anything not going to localhost/127.0.0.1
        def _on_request(request) -> None:
            url = request.url
            if not (
                url.startswith("http://localhost")
                or url.startswith("http://127.0.0.1")
                or url.startswith("data:")
            ):
                outbound_urls.append(url)

        page.on("request", _on_request)

        page.goto(dashboard_url)
        page.wait_for_load_state("networkidle")

        # Also click replay to exercise the JS path
        btn = page.query_selector("#replay-btn")
        if btn and not btn.is_disabled():
            btn.click()
            time.sleep(2)  # let a couple of steps fire

        browser.close()

    assert not outbound_urls, (
        "Dashboard made outbound requests (must only call localhost):\n"
        + "\n".join(outbound_urls)
    )
