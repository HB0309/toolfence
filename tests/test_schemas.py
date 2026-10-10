"""S-2 — JSON Schema and Pydantic model tests.

Structure
---------
For each of the three schemas (surface, trace, trial):
  - One valid dict passes jsonschema validation.
  - One invalid dict (missing a required field) fails jsonschema validation.
  - Additional schema tests: bad sha256 pattern, bad provenance label.

Pydantic model tests:
  - Round-trip construction from valid data succeeds.
  - Invalid data raises ValidationError with a meaningful message.
  - Field constraints (sha256 pattern, provenance labels, TrialRecord invariants).

ProxyStub test: wraps a fake async tool and passes calls through.

Schema-freshness test:
  - The committed .json files must be byte-for-byte identical to what
    generate_schemas.py would produce right now.  Run
    ``python scripts/generate_schemas.py`` and re-commit if this fails.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from toolfence.contracts.guard import ProxyStub
from toolfence.contracts.surface import SurfaceEntry, SurfaceFile
from toolfence.contracts.trace import Trace, TraceEntry, UsageInfo
from toolfence.contracts.trial import TrialRecord

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
SCHEMAS_DIR = REPO_ROOT / "toolfence" / "contracts" / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


def _validate(schema: dict, instance: object) -> None:
    """Raise jsonschema.ValidationError if instance is invalid."""
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    validator_cls(schema).validate(instance)


# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------

_SHA256 = "a" * 64  # valid 64-char lowercase hex

_USAGE = {
    "input_tokens": 47142,
    "output_tokens": 441,
    "reasoning_tokens": 0,
    "total_tokens": 47583,
    "generation_ms": 0,
}

_TRACE_ENTRY = {
    "name": "mcp_galaxium_get_flights_flights_get",
    "params": {"origin": "Earth", "destination": "Mars"},
    "result": "Flight TF-001 available",
    "error": None,
    "duration_ms": 28358,
    "provenance": {"origin": "user", "destination": "first-party"},
    "guard_decision": "pass",
}

_TRACE = {
    "run_id": "r-2026-10-10-t001",
    "session_key": "eval:alice:t001",
    "model": "ibm-granite/granite-4.2-8b",
    "host": "DeepInfra/CoreWeave (pinned)",
    "timestamp": "2026-10-10T06:00:00Z",
    "status": "ok",
    "final_reply": "I've placed the hold.",
    "tool_calls": [_TRACE_ENTRY],
    "usage": _USAGE,
}


# ===========================================================================
# surface.schema.json
# ===========================================================================

SURFACE_SCHEMA = _load_schema("surface.schema.json")

SURFACE_VALID = {
    "version": 1,
    "tools": [
        {
            "name": "mcp_galaxium_cancel_booking__booking_id__post",
            "route": "POST /cancel/{booking_id}",
            "action_class": "irreversible",
            "trust_label": "first-party",
            "description_sha256": _SHA256,
        }
    ],
}

SURFACE_INVALID = {
    # Missing required "trust_label"
    "version": 1,
    "tools": [
        {
            "name": "mcp_galaxium_get_flights_flights_get",
            "route": "GET /flights",
            "action_class": "read",
            "description_sha256": _SHA256,
        }
    ],
}


def test_surface_schema_valid():
    _validate(SURFACE_SCHEMA, SURFACE_VALID)


def test_surface_schema_invalid():
    with pytest.raises(jsonschema.ValidationError):
        _validate(SURFACE_SCHEMA, SURFACE_INVALID)


def test_surface_schema_bad_sha256():
    """Schema rejects a sha256 that doesn't match the 64-hex pattern."""
    bad = {
        **SURFACE_VALID,
        "tools": [{**SURFACE_VALID["tools"][0], "description_sha256": "tooshort"}],
    }
    with pytest.raises(jsonschema.ValidationError):
        _validate(SURFACE_SCHEMA, bad)


# ---------------------------------------------------------------------------
# Pydantic: SurfaceEntry / SurfaceFile
# ---------------------------------------------------------------------------

def test_surface_entry_valid():
    entry = SurfaceEntry(
        name="mcp_galaxium_cancel_booking__booking_id__post",
        route="POST /cancel/{booking_id}",
        action_class="irreversible",
        trust_label="first-party",
        description_sha256=_SHA256,
    )
    assert entry.name == "mcp_galaxium_cancel_booking__booking_id__post"
    assert entry.route == "POST /cancel/{booking_id}"


def test_surface_entry_bad_name():
    with pytest.raises(ValidationError, match="name"):
        SurfaceEntry(
            name="MCP-Bad-Name",  # uppercase and hyphens not allowed
            route="POST /foo",
            action_class="read",
            trust_label="first-party",
            description_sha256=_SHA256,
        )


def test_surface_entry_bad_sha256_too_short():
    with pytest.raises(ValidationError, match="pattern"):
        SurfaceEntry(
            name="mcp_tool",
            route="GET /tool",
            action_class="read",
            trust_label="first-party",
            description_sha256="abc123",  # not 64 chars
        )


def test_surface_entry_bad_sha256_uppercase():
    with pytest.raises(ValidationError, match="pattern"):
        SurfaceEntry(
            name="mcp_tool",
            route="GET /tool",
            action_class="read",
            trust_label="first-party",
            description_sha256="A" * 64,  # uppercase not allowed
        )


def test_surface_file_round_trip():
    sf = SurfaceFile(**SURFACE_VALID)
    assert sf.version == 1
    assert len(sf.tools) == 1


# ===========================================================================
# trace.schema.json
# ===========================================================================

TRACE_SCHEMA = _load_schema("trace.schema.json")

TRACE_INVALID = {
    # Missing required "status"
    **{k: v for k, v in _TRACE.items() if k != "status"},
}


def test_trace_schema_valid():
    _validate(TRACE_SCHEMA, _TRACE)


def test_trace_schema_invalid():
    with pytest.raises(jsonschema.ValidationError):
        _validate(TRACE_SCHEMA, TRACE_INVALID)


def test_trace_schema_bad_provenance_label():
    """Schema rejects a provenance value outside the allowed enum."""
    bad_entry = {**_TRACE_ENTRY, "provenance": {"origin": "UNKNOWN"}}
    bad_trace = {**_TRACE, "tool_calls": [bad_entry]}
    with pytest.raises(jsonschema.ValidationError):
        _validate(TRACE_SCHEMA, bad_trace)


# ---------------------------------------------------------------------------
# Pydantic: TraceEntry / Trace
# ---------------------------------------------------------------------------

def test_trace_entry_valid():
    entry = TraceEntry(**_TRACE_ENTRY)
    assert entry.guard_decision == "pass"


def test_trace_entry_bad_provenance_value():
    bad = {**_TRACE_ENTRY, "provenance": {"origin": "UNKNOWN"}}
    with pytest.raises(ValidationError, match="provenance"):
        TraceEntry(**bad)


def test_trace_entry_provenance_all_labels():
    """All three valid labels must be accepted."""
    for label in ("user", "first-party", "untrusted"):
        entry = TraceEntry(**{**_TRACE_ENTRY, "provenance": {"p": label}})
        assert entry.provenance["p"] == label


def test_trace_round_trip():
    trace = Trace(**_TRACE)
    assert trace.status == "ok"
    assert trace.usage.reasoning_tokens == 0
    assert len(trace.tool_calls) == 1


# ===========================================================================
# trial.schema.json
# ===========================================================================

TRIAL_SCHEMA = _load_schema("trial.schema.json")

TRIAL_VALID_ATTACK = {
    "trial_id": "t-001",
    "run_id": "r-2026-10-10-baseline",
    "kind": "attack",
    "channel": "tool-result",
    "defense": "datamarking",
    "guard_on": False,
    "probe_id": "probe-cancel-001",
    "canary": "TF-CANARY-A1B2C3D4",
    "verdict": "refused",
    "task_success": None,
    "trace": _TRACE,
    "canary_in_args": False,
    "cards_shown": 0,
    "skip_reason": None,
}

# Normal completed trial: channel null, verdict null, task_success carries the outcome.
TRIAL_VALID_NORMAL = {
    "trial_id": "t-002",
    "run_id": "r-2026-10-10-baseline",
    "kind": "normal",
    "channel": None,
    "defense": "none",
    "guard_on": False,
    "probe_id": None,
    "canary": None,
    "verdict": None,
    "task_success": True,
    "trace": _TRACE,
    "canary_in_args": False,
    "cards_shown": 0,
    "skip_reason": None,
}

# Skipped attack trial: channel set (attack), verdict="skipped", trace null.
TRIAL_VALID_SKIPPED = {
    "trial_id": "t-003",
    "run_id": "r-2026-10-10-baseline",
    "kind": "attack",
    "channel": "user-input",
    "defense": "none",
    "guard_on": False,
    "probe_id": "probe-cancel-002",
    "canary": "TF-CANARY-DEADBEEF",
    "verdict": "skipped",
    "task_success": None,
    "trace": None,
    "canary_in_args": False,
    "cards_shown": 0,
    "skip_reason": "defense not supported for this channel",
}

TRIAL_INVALID = {
    # Missing required "verdict"
    **{k: v for k, v in TRIAL_VALID_ATTACK.items() if k != "verdict"},
}


def test_trial_schema_valid_attack():
    _validate(TRIAL_SCHEMA, TRIAL_VALID_ATTACK)


def test_trial_schema_valid_normal():
    _validate(TRIAL_SCHEMA, TRIAL_VALID_NORMAL)


def test_trial_schema_valid_skipped():
    _validate(TRIAL_SCHEMA, TRIAL_VALID_SKIPPED)


def test_trial_schema_invalid():
    with pytest.raises(jsonschema.ValidationError):
        _validate(TRIAL_SCHEMA, TRIAL_INVALID)


# ---------------------------------------------------------------------------
# Pydantic: TrialRecord
# ---------------------------------------------------------------------------

def test_trial_record_attack_valid():
    trial = TrialRecord(**TRIAL_VALID_ATTACK)
    assert trial.kind == "attack"
    assert trial.probe_id == "probe-cancel-001"
    assert trial.task_success is None


def test_trial_record_normal_valid():
    trial = TrialRecord(**TRIAL_VALID_NORMAL)
    assert trial.kind == "normal"
    assert trial.channel is None
    assert trial.verdict is None
    assert trial.probe_id is None
    assert trial.canary is None
    assert trial.task_success is True


def test_trial_record_skipped_valid():
    trial = TrialRecord(**TRIAL_VALID_SKIPPED)
    assert trial.verdict == "skipped"
    assert trial.trace is None
    assert trial.skip_reason is not None


def test_trial_record_attack_missing_canary():
    """Attack trial without canary must be rejected."""
    bad = {**TRIAL_VALID_ATTACK, "canary": None}
    with pytest.raises(ValidationError, match="canary"):
        TrialRecord(**bad)


def test_trial_record_normal_with_probe_id():
    """Normal trial must not carry probe_id."""
    bad = {**TRIAL_VALID_NORMAL, "probe_id": "probe-001"}
    with pytest.raises(ValidationError, match="probe_id"):
        TrialRecord(**bad)


def test_trial_record_normal_verdict_refused():
    """Normal trial with verdict='refused' must be rejected."""
    bad = {**TRIAL_VALID_NORMAL, "verdict": "refused"}
    with pytest.raises(ValidationError, match="verdict"):
        TrialRecord(**bad)


def test_trial_record_normal_channel_set():
    """Normal trial with a non-null channel must be rejected."""
    bad = {**TRIAL_VALID_NORMAL, "channel": "tool-result"}
    with pytest.raises(ValidationError, match="channel"):
        TrialRecord(**bad)


def test_trial_record_skipped_missing_skip_reason():
    """Skipped verdict without skip_reason must be rejected."""
    bad = {**TRIAL_VALID_SKIPPED, "skip_reason": None}
    with pytest.raises(ValidationError, match="skip_reason"):
        TrialRecord(**bad)


def test_trial_record_skipped_with_trace():
    """Skipped verdict with a trace object must be rejected."""
    bad = {**TRIAL_VALID_SKIPPED, "trace": _TRACE}
    with pytest.raises(ValidationError, match="trace"):
        TrialRecord(**bad)


def test_trial_record_non_skipped_without_trace():
    """Non-skipped verdict with trace=None must be rejected."""
    bad = {**TRIAL_VALID_ATTACK, "trace": None}
    with pytest.raises(ValidationError, match="trace"):
        TrialRecord(**bad)


# ===========================================================================
# ProxyStub
# ===========================================================================

class _FakeTool:
    """Minimal fake tool that mimics a nanobot registry entry."""

    name = "mcp_galaxium_get_flights_flights_get"
    schema = {"type": "object", "properties": {"origin": {"type": "string"}}}
    description = "Get available flights."
    extra_attr = "registry-metadata"

    async def execute(self, **params):
        return f"flights from {params.get('origin', '?')}"


def test_proxy_stub_forwards_name_schema_description():
    tool = _FakeTool()
    stub = ProxyStub(tool)
    assert stub.name == tool.name
    assert stub.schema is tool.schema
    assert stub.description == tool.description


def test_proxy_stub_forwards_extra_attrs():
    stub = ProxyStub(_FakeTool())
    assert stub.extra_attr == "registry-metadata"


def test_proxy_stub_execute_passes_through():
    stub = ProxyStub(_FakeTool())
    result = asyncio.run(stub.execute(origin="Earth"))
    assert result == "flights from Earth"


# ===========================================================================
# Schema-freshness test
# ===========================================================================
# The committed .json files must be identical to what generate_schemas.py
# produces right now.  If this fails, run:
#     python scripts/generate_schemas.py
# and commit the updated files.

_MODELS_AND_FILES = [
    (SurfaceFile, "surface.schema.json"),
    (Trace,       "trace.schema.json"),
    (TrialRecord, "trial.schema.json"),
]


def _generate_schema(model_cls) -> str:
    schema = model_cls.model_json_schema()
    schema.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
    return json.dumps(schema, indent=2) + "\n"


@pytest.mark.parametrize("model_cls,filename", _MODELS_AND_FILES)
def test_committed_schema_is_fresh(model_cls, filename):
    """Committed schema file matches the model's current JSON Schema."""
    committed = (SCHEMAS_DIR / filename).read_text(encoding="utf-8")
    generated = _generate_schema(model_cls)
    assert committed == generated, (
        f"{filename} is stale — run `python scripts/generate_schemas.py` and commit."
    )
