"""S1 — Static dashboard tests (no browser required).

Tests verify that index.html has the correct structure, no external URLs are
referenced, all script/link src files exist, and the page mentions 'inconclusive'.
One additional test checks that echarts.min.js is served with 200 via the server
fixture already used in test_dashboard_server.py.

Test inventory
--------------
  test_index_has_all_required_ids       -- index.html contains every ID from §5
  test_index_no_external_urls           -- no src= or href= starts with http
  test_script_files_exist               -- every <script src=...> file exists under static/
  test_link_files_exist                 -- every <link href=...> CSS file exists under static/
  test_index_contains_inconclusive      -- page source contains the word 'inconclusive'
  test_echarts_served_200               -- GET /static/vendor/echarts.min.js returns 200
  test_app_js_exists                    -- static/app.js is present
  test_style_css_exists                 -- static/style.css is present
  test_verdict_colors_exported          -- app.js defines VERDICT_COLORS
  test_render_all_defined               -- app.js defines renderAll
"""

from __future__ import annotations

import re
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
_STATIC_DIR = _REPO_ROOT / "toolfence" / "cli" / "dashboard" / "static"
_INDEX = _STATIC_DIR / "index.html"
_PYTHON = sys.executable

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _free_port() -> int:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Required IDs (from spec §5)
# ---------------------------------------------------------------------------

# Every ID that must appear literally in the HTML source.
REQUIRED_IDS = [
    "filter-bar",
    "f-run",
    "f-app",
    "f-model",
    "f-guard",
    "f-defense",
    "f-kind",
    "filter-chips",
    "f-reset",
    "f-share",
    "kpi-strip",
    "chart-dumbbell",
    "chart-verdicts",
    "security-grid",
    "normal-table",
    "replay-btn",
    "replay-counter",
    "trial-table",
    "trial-flyout",
    "replay-list",
]


def test_index_has_all_required_ids() -> None:
    """index.html must contain every ID listed in §5."""
    assert _INDEX.exists(), f"Expected {_INDEX} to exist"
    html = _INDEX.read_text(encoding="utf-8")
    missing = [id_ for id_ in REQUIRED_IDS if f'id="{id_}"' not in html]
    assert not missing, (
        f"index.html is missing required IDs: {missing}\n"
        f"(checked for id=\"..\" pattern)"
    )


# ---------------------------------------------------------------------------
# No external URLs
# ---------------------------------------------------------------------------

def test_index_no_external_urls() -> None:
    """No src= or href= attribute in index.html may start with http."""
    assert _INDEX.exists(), f"Expected {_INDEX} to exist"
    html = _INDEX.read_text(encoding="utf-8")
    # Find all src="..." and href="..." values
    matches = re.findall(r'(?:src|href)=["\']([^"\']+)["\']', html, re.IGNORECASE)
    external = [m for m in matches if m.lower().startswith("http")]
    assert not external, (
        f"index.html must not reference external URLs.\n"
        f"Found external references: {external}"
    )


# ---------------------------------------------------------------------------
# Script and link files exist under static/
# ---------------------------------------------------------------------------

def test_script_files_exist() -> None:
    """Every <script src=...> in index.html must resolve to a file under static/."""
    assert _INDEX.exists(), f"Expected {_INDEX} to exist"
    html = _INDEX.read_text(encoding="utf-8")
    srcs = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)
    missing = []
    for src in srcs:
        # src values are like "static/vendor/tabler.min.js" or "static/app.js"
        # Strip leading "static/" prefix relative to the parent of static/
        if src.startswith("static/"):
            rel = src[len("static/"):]
        else:
            rel = src
        resolved = _STATIC_DIR / rel
        if not resolved.exists():
            missing.append(f"{src!r} → {resolved}")
    assert not missing, (
        f"index.html references script files that do not exist:\n"
        + "\n".join(f"  {m}" for m in missing)
    )


def test_link_files_exist() -> None:
    """Every <link href=...> CSS file in index.html must resolve to a file under static/."""
    assert _INDEX.exists(), f"Expected {_INDEX} to exist"
    html = _INDEX.read_text(encoding="utf-8")
    hrefs = re.findall(r'<link[^>]+href=["\']([^"\']+)["\']', html, re.IGNORECASE)
    missing = []
    for href in hrefs:
        if href.startswith("static/"):
            rel = href[len("static/"):]
        else:
            rel = href
        resolved = _STATIC_DIR / rel
        if not resolved.exists():
            missing.append(f"{href!r} → {resolved}")
    assert not missing, (
        f"index.html references CSS files that do not exist:\n"
        + "\n".join(f"  {m}" for m in missing)
    )


# ---------------------------------------------------------------------------
# 'inconclusive' must appear in the page source
# ---------------------------------------------------------------------------

def test_index_contains_inconclusive() -> None:
    """index.html must contain the word 'inconclusive'."""
    assert _INDEX.exists(), f"Expected {_INDEX} to exist"
    html = _INDEX.read_text(encoding="utf-8")
    assert "inconclusive" in html.lower(), (
        "index.html must contain the word 'inconclusive'"
    )


# ---------------------------------------------------------------------------
# app.js and style.css exist
# ---------------------------------------------------------------------------

def test_app_js_exists() -> None:
    """static/app.js must exist."""
    assert (_STATIC_DIR / "app.js").exists(), "static/app.js not found"


def test_style_css_exists() -> None:
    """static/style.css must exist."""
    assert (_STATIC_DIR / "style.css").exists(), "static/style.css not found"


# ---------------------------------------------------------------------------
# app.js must define key symbols
# ---------------------------------------------------------------------------

def test_verdict_colors_exported() -> None:
    """app.js must define VERDICT_COLORS."""
    src = (_STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "VERDICT_COLORS" in src, "app.js must define VERDICT_COLORS"


def test_render_all_defined() -> None:
    """app.js must define renderAll."""
    src = (_STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "function renderAll" in src, "app.js must define renderAll()"


def test_filtered_defined() -> None:
    """app.js must define filtered()."""
    src = (_STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "function filtered" in src, "app.js must define filtered()"


def test_set_filter_defined() -> None:
    """app.js must define setFilter()."""
    src = (_STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "function setFilter" in src, "app.js must define setFilter()"


# ---------------------------------------------------------------------------
# echarts.min.js served with status 200 (uses server fixture pattern)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def _server_url_for_static():
    """Start the dashboard server; yield base URL. Used only for the 200-check."""
    fixture_dir = _REPO_ROOT / "fixtures" / "spike_converted"
    port = _free_port()
    proc = subprocess.Popen(
        [
            _PYTHON, "-m", "toolfence", "serve",
            "--host", "127.0.0.1",
            "--port", str(port),
            "--results-dir", str(fixture_dir),
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


def test_echarts_served_200(_server_url_for_static: str) -> None:
    """GET /static/vendor/echarts.min.js must return 200."""
    url = _server_url_for_static + "/static/vendor/echarts.min.js"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    assert status == 200, (
        f"Expected 200 from GET /static/vendor/echarts.min.js, got {status}"
    )
