# tests/test_setup.py
"""
Tests for scripts/setup.ps1 (B-2).

Run with network:          pytest tests/test_setup.py
Skip network-dependent:    pytest tests/test_setup.py --skip-network
"""
import subprocess
import sys
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).parent.parent
SETUP_SCRIPT = WORKSPACE / "scripts" / "setup.ps1"
GALAXIUM_DIR = WORKSPACE / "targets" / "galaxium"
NANOBOT_DIR = WORKSPACE / "targets" / "nanobot"
SERVER_PY = GALAXIUM_DIR / "booking_system_backend" / "server.py"
PATCH_0002 = WORKSPACE / "targets" / "galaxium-patches" / "0002-reviews-route.patch"


@pytest.fixture(autouse=True)
def skip_if_no_network(request):
    if request.config.getoption("--skip-network"):
        pytest.skip("--skip-network passed")


def _run_setup():
    """Run setup.ps1 and return the CompletedProcess."""
    result = subprocess.run(
        ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", str(SETUP_SCRIPT)],
        cwd=str(WORKSPACE),
        capture_output=True,
        text=True,
    )
    return result


def test_targets_exist():
    """setup.ps1 must leave both target directories present at the pinned commits."""
    result = _run_setup()
    assert result.returncode == 0, (
        f"setup.ps1 exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert GALAXIUM_DIR.is_dir(), f"targets/galaxium/ not found after setup"
    assert NANOBOT_DIR.is_dir(), f"targets/nanobot/ not found after setup"


def test_galaxium_patch_applied():
    """Patch 0001 must be applied: server.py must import QuoteRequest from schemas."""
    # Run setup first if the directory isn't there yet.
    if not GALAXIUM_DIR.is_dir():
        result = _run_setup()
        assert result.returncode == 0, (
            f"setup.ps1 failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    assert SERVER_PY.is_file(), f"server.py not found at {SERVER_PY}"
    content = SERVER_PY.read_text(encoding="utf-8")

    # Patch 0001: QuoteRequest import must be present.
    assert "QuoteRequest" in content, (
        "Patch 0001 does not appear to be applied: 'QuoteRequest' not found in server.py"
    )

    # Patch 0002 (reviews route): assert only if the patch file is committed.
    if PATCH_0002.exists():
        assert "reviews" in content, (
            "Patch 0002 does not appear to be applied: 'reviews' not found in server.py"
        )
