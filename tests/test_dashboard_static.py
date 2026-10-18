"""S1 + S2 + S3 — Static dashboard tests (no browser required).

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

S2 additions:
  test_charts_js_exists                 -- static/charts.js is present
  test_charts_js_loaded_after_app_js    -- charts.js <script> tag appears after app.js in index.html
  test_charts_js_defines_render_charts  -- charts.js defines renderCharts
  test_charts_js_references_chart_ids   -- charts.js contains the three chart IDs
  test_chart_heatmap_inside_security_grid -- #chart-heatmap is nested inside #security-grid in HTML

S3 additions:
  test_replay_js_gone                     -- replay.js does NOT exist under static/
  test_explorer_js_exists                 -- static/explorer.js is present
  test_explorer_js_loaded_after_charts_js -- explorer.js <script> tag appears after charts.js
  test_explorer_js_references_ids         -- explorer.js references trial-table, trial-flyout, replay-btn, replay-counter
  test_explorer_js_defines_render_explorer -- explorer.js defines renderExplorer
  test_replay_js_not_in_html              -- index.html has no <script src=...replay.js...> tag
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


# ===========================================================================
# S2 — charts.js tests
# ===========================================================================

def test_charts_js_exists() -> None:
    """static/charts.js must exist."""
    assert (_STATIC_DIR / "charts.js").exists(), "static/charts.js not found"


def test_charts_js_loaded_after_app_js() -> None:
    """charts.js <script> tag must appear after the app.js tag in index.html."""
    assert _INDEX.exists(), f"Expected {_INDEX} to exist"
    html = _INDEX.read_text(encoding="utf-8")
    # Find positions of the two script tags
    app_pos    = html.find('src="static/app.js"')
    charts_pos = html.find('src="static/charts.js"')
    assert app_pos    != -1, "index.html must contain a <script src=\"static/app.js\"> tag"
    assert charts_pos != -1, "index.html must contain a <script src=\"static/charts.js\"> tag"
    assert charts_pos > app_pos, (
        "charts.js script tag must appear after app.js script tag in index.html"
    )


def test_charts_js_defines_render_charts() -> None:
    """charts.js must define renderCharts."""
    src = (_STATIC_DIR / "charts.js").read_text(encoding="utf-8")
    assert "function renderCharts" in src, "charts.js must define renderCharts()"


def test_charts_js_references_chart_ids() -> None:
    """charts.js must reference the IDs chart-dumbbell, chart-verdicts and chart-heatmap."""
    src = (_STATIC_DIR / "charts.js").read_text(encoding="utf-8")
    for id_ in ("chart-dumbbell", "chart-verdicts", "chart-heatmap"):
        assert id_ in src, f"charts.js must reference the ID '{id_}'"


def test_chart_heatmap_inside_security_grid() -> None:
    """#chart-heatmap must be nested inside #security-grid in index.html."""
    assert _INDEX.exists(), f"Expected {_INDEX} to exist"
    html = _INDEX.read_text(encoding="utf-8")

    # Find the index of id="security-grid" and id="chart-heatmap"
    grid_pos    = html.find('id="security-grid"')
    heatmap_pos = html.find('id="chart-heatmap"')

    assert grid_pos    != -1, 'index.html must contain id="security-grid"'
    assert heatmap_pos != -1, 'index.html must contain id="chart-heatmap"'

    # heatmap must come AFTER the opening of security-grid
    assert heatmap_pos > grid_pos, (
        "#chart-heatmap must appear after the opening of #security-grid"
    )

    # The closing </div> for security-grid must come AFTER chart-heatmap.
    # Strategy: find the first </div> after heatmap_pos and verify it appears
    # before the second </div> that would close security-grid's parent.
    # Simpler: security-grid's content block ends before the card-body close;
    # just check that the next occurrence of 'id="chart-heatmap"' is between
    # id="security-grid" and the word 'Real tasks' (the next card).
    real_tasks_pos = html.find("Real tasks", grid_pos)
    assert real_tasks_pos == -1 or heatmap_pos < real_tasks_pos, (
        "#chart-heatmap must be inside #security-grid, not after it"
    )


# ===========================================================================
# S3 — explorer.js tests
# ===========================================================================

def test_replay_js_gone() -> None:
    """static/replay.js must NOT exist after S3 deletes it."""
    assert not (_STATIC_DIR / "replay.js").exists(), (
        "static/replay.js must be deleted in S3; it still exists"
    )


def test_explorer_js_exists() -> None:
    """static/explorer.js must exist."""
    assert (_STATIC_DIR / "explorer.js").exists(), "static/explorer.js not found"


def test_explorer_js_loaded_after_charts_js() -> None:
    """explorer.js <script> tag must appear after the charts.js tag in index.html."""
    assert _INDEX.exists(), f"Expected {_INDEX} to exist"
    html = _INDEX.read_text(encoding="utf-8")
    charts_pos   = html.find('src="static/charts.js"')
    explorer_pos = html.find('src="static/explorer.js"')
    assert charts_pos   != -1, 'index.html must contain a <script src="static/charts.js"> tag'
    assert explorer_pos != -1, 'index.html must contain a <script src="static/explorer.js"> tag'
    assert explorer_pos > charts_pos, (
        "explorer.js script tag must appear after charts.js script tag in index.html"
    )


def test_explorer_js_references_ids() -> None:
    """explorer.js must reference trial-table, trial-flyout, replay-btn and replay-counter."""
    src = (_STATIC_DIR / "explorer.js").read_text(encoding="utf-8")
    for id_ in ("trial-table", "trial-flyout", "replay-btn", "replay-counter"):
        assert id_ in src, f"explorer.js must reference the ID '{id_}'"


def test_explorer_js_defines_render_explorer() -> None:
    """explorer.js must define renderExplorer."""
    src = (_STATIC_DIR / "explorer.js").read_text(encoding="utf-8")
    assert "function renderExplorer" in src, "explorer.js must define renderExplorer()"


def test_replay_js_not_in_html() -> None:
    """index.html must not contain a <script> tag loading replay.js."""
    assert _INDEX.exists(), f"Expected {_INDEX} to exist"
    html = _INDEX.read_text(encoding="utf-8")
    # Check for any script src that includes replay.js
    srcs = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)
    replay_srcs = [s for s in srcs if "replay.js" in s]
    assert not replay_srcs, (
        f"index.html must not load replay.js; found: {replay_srcs}"
    )


# ===========================================================================
# Donuts chart — static tests
# ===========================================================================

def test_chart_donuts_id_in_html() -> None:
    """index.html must contain id="chart-donuts"."""
    assert _INDEX.exists(), f"Expected {_INDEX} to exist"
    html = _INDEX.read_text(encoding="utf-8")
    assert 'id="chart-donuts"' in html, 'index.html must contain id="chart-donuts"'


def test_charts_js_references_chart_donuts() -> None:
    """charts.js must reference the ID chart-donuts."""
    src = (_STATIC_DIR / "charts.js").read_text(encoding="utf-8")
    assert "chart-donuts" in src, "charts.js must reference the ID 'chart-donuts'"


# ===========================================================================
# L-3 — live panel tests
# ===========================================================================

def test_live_panel_ids_in_html() -> None:
    """index.html must contain all L-3 live panel element IDs."""
    assert _INDEX.exists(), f"Expected {_INDEX} to exist"
    html = _INDEX.read_text(encoding="utf-8")
    required = [
        "f-live",
        "live-panel",
        "live-key",
        "live-prompt",
        "live-send",
        "live-allow",
        "live-decline",
    ]
    missing = [id_ for id_ in required if f'id="{id_}"' not in html]
    assert not missing, f"index.html is missing L-3 live panel IDs: {missing}"


def test_live_js_exists() -> None:
    """static/live.js must exist."""
    assert (_STATIC_DIR / "live.js").exists(), "static/live.js not found"


def test_live_js_no_local_storage() -> None:
    """static/live.js must not reference localStorage."""
    src = (_STATIC_DIR / "live.js").read_text(encoding="utf-8")
    assert "localStorage" not in src, "live.js must not use localStorage"
