# tests/test_galaxium_patches.py
"""
Integration tests for targets/galaxium-patches/.

Strategy: extract the pinned commit to a temp directory via `git archive`, apply
all patches in lexicographic order, run the Galaxium backend's own pytest via its
pre-installed .venv, then delete the temp directory.

The live targets/galaxium/ working tree is never touched.

Run:
    pytest tests/test_galaxium_patches.py
Skip (target dir / venv absent):
    pytest tests/test_galaxium_patches.py --skip-network
"""
import subprocess
import tempfile
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).parent.parent
GALAXIUM_DIR = WORKSPACE / "targets" / "galaxium"
PATCHES_DIR = WORKSPACE / "targets" / "galaxium-patches"
PINNED_COMMIT = "6163380"

# Python interpreter from the Galaxium backend's pre-installed venv.
_GALAXIUM_PYTHON = GALAXIUM_DIR / "booking_system_backend" / ".venv" / "Scripts" / "python.exe"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def skip_if_no_network(request):
    if request.config.getoption("--skip-network"):
        pytest.skip("--skip-network passed")


@pytest.fixture()
def patched_tmp(tmp_path):
    """
    Extract the pinned Galaxium commit to tmp_path, apply every *.patch in
    PATCHES_DIR in lexicographic order, yield the extracted root, then the
    fixture cleans up automatically via pytest's tmp_path machinery.
    """
    if not GALAXIUM_DIR.is_dir():
        pytest.skip("targets/galaxium/ not present — run scripts/setup.ps1 first")
    if not _GALAXIUM_PYTHON.is_file():
        pytest.skip(
            "Galaxium .venv not found — "
            "cd targets/galaxium/booking_system_backend && python -m venv .venv && "
            ".venv/Scripts/pip install -r requirements.txt"
        )

    # 1. Archive the pinned commit into tmp_path.
    archive_result = subprocess.run(
        ["git", "-C", str(GALAXIUM_DIR), "archive", PINNED_COMMIT],
        capture_output=True,
    )
    assert archive_result.returncode == 0, (
        f"git archive failed:\n{archive_result.stderr.decode()}"
    )
    tar_result = subprocess.run(
        ["tar", "-x", "-C", str(tmp_path)],
        input=archive_result.stdout,
        capture_output=True,
    )
    assert tar_result.returncode == 0, (
        f"tar extract failed:\n{tar_result.stderr.decode()}"
    )

    # 2. Apply all patches in order.
    patches = sorted(PATCHES_DIR.glob("*.patch"))
    assert patches, f"No patches found in {PATCHES_DIR}"
    for patch in patches:
        r = subprocess.run(
            ["git", "apply", "--ignore-whitespace", "--unsafe-paths", "--directory", str(tmp_path), str(patch)],
            cwd=str(GALAXIUM_DIR),
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, (
            f"git apply {patch.name} failed:\n{r.stderr}"
        )

    yield tmp_path
    # tmp_path is deleted automatically by pytest.


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_reviews_route(patched_tmp):
    """
    After all patches are applied to the extracted copy:
    - TestReviewsEndpoint passes in the Galaxium backend test suite.
    """
    backend_dir = patched_tmp / "booking_system_backend"
    result = subprocess.run(
        [
            str(_GALAXIUM_PYTHON), "-m", "pytest",
            "tests/test_rest.py::TestReviewsEndpoint",
            "-v", "--tb=short",
        ],
        cwd=str(backend_dir),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Galaxium TestReviewsEndpoint failed:\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_ownership_checks(patched_tmp):
    """
    After all patches are applied to the extracted copy:
    - TestOwnershipChecks passes in the Galaxium backend test suite.
    """
    backend_dir = patched_tmp / "booking_system_backend"
    result = subprocess.run(
        [
            str(_GALAXIUM_PYTHON), "-m", "pytest",
            "tests/test_rest.py::TestOwnershipChecks",
            "-v", "--tb=short",
        ],
        cwd=str(backend_dir),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Galaxium TestOwnershipChecks failed:\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
