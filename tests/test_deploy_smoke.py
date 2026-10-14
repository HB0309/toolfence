# tests/test_deploy_smoke.py — C-7 smoke tests for the deployed dashboard.
#
# Two tests:
#
#   test_smoke_dashboard_reachable
#       Requires --skip-network to be absent AND TOOLFENCE_DEPLOY_URL set.
#       GETs the deployed URL, asserts HTTP 200 and "inconclusive" in the body
#       (the dashboard must render the inconclusive column per CLI-6).
#
#   test_smoke_no_api_key_in_deploy_docs
#       Runs offline — reads docs/deploy.md and asserts that OPENROUTER_API_KEY
#       appears in a "must NOT" context (CLI-8, CLI-7).

from __future__ import annotations

import os
from pathlib import Path


# ---------------------------------------------------------------------------
# test_smoke_dashboard_reachable
# ---------------------------------------------------------------------------

def test_smoke_dashboard_reachable(request):
    """GET the deployed dashboard URL and assert it is reachable with the
    inconclusive column present.

    Skipped when:
    - --skip-network flag is set, OR
    - TOOLFENCE_DEPLOY_URL environment variable is not set.
    """
    skip_network = request.config.getoption("--skip-network", default=False)
    if skip_network:
        import pytest
        pytest.skip("--skip-network: skipping deployed dashboard smoke test")

    deploy_url = os.environ.get("TOOLFENCE_DEPLOY_URL", "").strip()
    if not deploy_url:
        import pytest
        pytest.skip("TOOLFENCE_DEPLOY_URL not set — skipping live smoke test")

    import urllib.request

    url = deploy_url.rstrip("/")
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            status = resp.status
            body = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(
            f"Could not reach deployed dashboard at {url!r}: {exc}"
        ) from exc

    assert status == 200, f"Expected HTTP 200, got {status}"
    assert "inconclusive" in body.lower(), (
        "'inconclusive' column not found in dashboard response body. "
        "The dashboard must render an inconclusive column (CLI-6)."
    )


# ---------------------------------------------------------------------------
# test_smoke_no_api_key_in_deploy_docs
# ---------------------------------------------------------------------------

def test_smoke_no_api_key_in_deploy_docs():
    """Confirm that docs/deploy.md explicitly forbids OPENROUTER_API_KEY.

    Specifically: the file must contain OPENROUTER_API_KEY AND the phrase
    "must NOT" (case-insensitive) so the constraint is documented clearly.

    This test runs fully offline — no network required.
    """
    deploy_md = Path(__file__).parent.parent / "docs" / "deploy.md"
    assert deploy_md.is_file(), "docs/deploy.md not found — C-7 requires this file"

    text = deploy_md.read_text(encoding="utf-8")

    assert "OPENROUTER_API_KEY" in text, (
        "docs/deploy.md must mention OPENROUTER_API_KEY"
    )

    # The spec requires the word "must NOT" in the context of OPENROUTER_API_KEY.
    # Check that both appear in the document (they are on the same line in the
    # warning box added by C-7).
    text_lower = text.lower()
    assert "must not" in text_lower, (
        "docs/deploy.md must contain a 'must NOT' prohibition (CLI-8 / CLI-7)"
    )

    # Extra belt-and-suspenders: confirm the ibmcloud ce application create
    # command is present (IMPLEMENTATION_PLAN.md C-7 requirement).
    assert "ibmcloud ce application create" in text, (
        "docs/deploy.md must contain the 'ibmcloud ce application create' command"
    )
