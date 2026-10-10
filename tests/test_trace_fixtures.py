"""S-3 — Spike-trace fixture validation tests.

Validates all 10 converted TrialRecord fixtures in fixtures/spike_converted/
against trial.schema.json and the Pydantic TrialRecord model.

Assertions per fixture:
  - JSON is valid against trial.schema.json
  - kind == "normal"
  - verdict is null / None

Spot-check:
  - run-05.json has exactly 4 tool calls

Also confirms the 10 original spike files in docs/notes/spike-traces/ still
load as valid JSON (content not validated against the new schema).
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from toolfence.contracts.trial import TrialRecord

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent
FIXTURES_DIR = REPO_ROOT / "fixtures" / "spike_converted"
SPIKE_DIR = REPO_ROOT / "docs" / "notes" / "spike-traces"
SCHEMA_PATH = REPO_ROOT / "toolfence" / "contracts" / "schemas" / "trial.schema.json"

TRIAL_SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate_schema(instance: object) -> None:
    validator_cls = jsonschema.validators.validator_for(TRIAL_SCHEMA)
    validator_cls.check_schema(TRIAL_SCHEMA)
    validator_cls(TRIAL_SCHEMA).validate(instance)


# Parametrize over all 10 converted fixtures.
_FIXTURE_IDS = [f"run-{n:02d}" for n in range(1, 11)]


@pytest.mark.parametrize("run_id", _FIXTURE_IDS)
def test_fixture_validates_against_schema(run_id: str) -> None:
    """Each converted fixture passes trial.schema.json validation."""
    path = FIXTURES_DIR / f"{run_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    _validate_schema(data)


@pytest.mark.parametrize("run_id", _FIXTURE_IDS)
def test_fixture_validates_against_pydantic(run_id: str) -> None:
    """Each converted fixture round-trips through the TrialRecord Pydantic model."""
    path = FIXTURES_DIR / f"{run_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    trial = TrialRecord.model_validate(data)
    assert trial.kind == "normal"
    assert trial.verdict is None


def test_run05_has_four_tool_calls() -> None:
    """Spot-check: run-05.json must have exactly 4 tool calls."""
    path = FIXTURES_DIR / "run-05.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["trace"] is not None
    assert len(data["trace"]["tool_calls"]) == 4


# ---------------------------------------------------------------------------
# Original spike files — load check only (no schema validation)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("run_id", _FIXTURE_IDS)
def test_original_spike_loads_as_json(run_id: str) -> None:
    """Original spike files in docs/notes/spike-traces/ still load as JSON."""
    path = SPIKE_DIR / f"{run_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    # Minimal sanity: the spike format has these top-level keys.
    assert "tool_calls" in data
    assert "run_id" in data
