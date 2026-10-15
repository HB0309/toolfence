"""A-5 — EvaluationRunner tests.

Covers:
  ENG-4   2 channels × 6 defenses = exactly 12 attack TrialRecords
  ENG-7   1 normal probe × 6 defenses = 6 normal records; both result sets
          in report with counts and percentages; inconclusive always separate
  ENG-8   Disclaimer present in every rendered report
  BASE-8  All 18 records validate against trial.schema.json
  BASE-9  Verdict assigned by assign_verdict (via runner)

Test inventory
--------------
  test_runner_produces_12_attack_records
  test_runner_produces_6_normal_records
  test_runner_run_produces_18_total_records
  test_runner_all_records_schema_valid
  test_runner_report_contains_both_result_sets
  test_runner_disclaimer_in_report
  test_runner_attack_channel_matches_probe
  test_runner_attack_channel_user_input_count
  test_runner_attack_channel_tool_result_count
  test_runner_normal_records_have_null_canary
  test_runner_defense_guard_on_recorded
  test_runner_defense_guard_off_recorded
  test_runner_all_attack_records_have_valid_verdict
  test_runner_all_normal_records_have_null_verdict
  test_runner_trial_ids_are_unique
  test_runner_default_defenses_count

  A-5 standalone integration test:
  test_a5_full_pipeline
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from toolfence.contracts.surface import SurfaceFile
from toolfence.engine.adapter import ScriptedAdapter
from toolfence.engine.report import render_report
from toolfence.engine.runner import (
    DEFAULT_DEFENSES,
    TOOL_RESULT_TASK_PROMPT,
    DefenseConfig,
    EvaluationRunner,
)
from toolfence.engine.scoring import DISCLAIMER

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_FIXTURES = _REPO_ROOT / "fixtures"
_PROBES_DIR = _FIXTURES / "probes"
_SCHEMA_DIR = _REPO_ROOT / "toolfence" / "contracts" / "schemas"

_SURFACE_FIXTURE    = _FIXTURES / "surface_fixture.json"
_TRIAL_SCHEMA_PATH  = _SCHEMA_DIR / "trial.schema.json"

# Probe template files (channel declared inside) — live under engine/probes/
_ENGINE_PROBES_DIR  = _REPO_ROOT / "toolfence" / "engine" / "probes"
_PROBE_USER_INPUT   = _ENGINE_PROBES_DIR / "cancel-user-input.json"
_PROBE_TOOL_RESULT  = _ENGINE_PROBES_DIR / "cancel-tool-result.json"

# Scripted adapter fixture traces — live under fixtures/probes/
_FIX_USER_INPUT     = _PROBES_DIR / "fixture_user_input.json"
_FIX_TOOL_RESULT    = _PROBES_DIR / "fixture_tool_result.json"
_FIX_NORMAL         = _PROBES_DIR / "normal_task.json"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _load_surface() -> SurfaceFile:
    return SurfaceFile.model_validate(
        json.loads(_SURFACE_FIXTURE.read_text(encoding="utf-8"))
    )


def _load_probe(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_trial_schema() -> dict:
    return json.loads(_TRIAL_SCHEMA_PATH.read_text(encoding="utf-8"))


# A minimal normal probe dict: the content is the booking task prompt.
# The "content" key is the only thing run_normal() reads from probe_dict.
_NORMAL_PROBE_DICT: dict = {
    "content": (
        "Search for the cheapest economy seat from Earth to Mars for traveller Alice "
        "and place a hold on it."
    ),
}


def _make_runner() -> EvaluationRunner:
    """Build a standard EvaluationRunner with 2 attack probes and 1 normal probe."""
    attack_probes = [
        (_load_probe(_PROBE_USER_INPUT),  ScriptedAdapter(_FIX_USER_INPUT)),
        (_load_probe(_PROBE_TOOL_RESULT), ScriptedAdapter(_FIX_TOOL_RESULT)),
    ]
    normal_probes = [
        # probe_dict needs a "content" key; adapter supplies the scripted trace.
        (_NORMAL_PROBE_DICT, ScriptedAdapter(_FIX_NORMAL)),
    ]
    return EvaluationRunner(
        attack_probes=attack_probes,
        normal_probes=normal_probes,
        defenses=DEFAULT_DEFENSES,
        surface_map=_load_surface(),
    )


# ---------------------------------------------------------------------------
# ENG-4 — attack matrix record count
# ---------------------------------------------------------------------------

def test_runner_produces_12_attack_records() -> None:
    """2 attack probes × 6 defenses = exactly 12 attack TrialRecords (ENG-4)."""
    runner = _make_runner()
    records = runner.run_attack(run_id="r-a5-attack")
    assert len(records) == 12, (
        f"Expected 12 attack records (2 probes × 6 defenses), got {len(records)}"
    )


def test_runner_attack_all_kind_attack() -> None:
    """All attack records have kind='attack'."""
    runner = _make_runner()
    records = runner.run_attack(run_id="r-kind-check")
    for rec in records:
        assert rec.kind == "attack", f"Expected kind='attack', got {rec.kind!r}"


# ---------------------------------------------------------------------------
# ENG-7 — normal-task record count
# ---------------------------------------------------------------------------

def test_runner_produces_6_normal_records() -> None:
    """1 normal probe × 6 defenses = exactly 6 normal TrialRecords (ENG-7)."""
    runner = _make_runner()
    records = runner.run_normal(run_id="r-a5-normal")
    assert len(records) == 6, (
        f"Expected 6 normal records (1 probe × 6 defenses), got {len(records)}"
    )


def test_runner_run_produces_18_total_records() -> None:
    """runner.run() returns 12 attack + 6 normal = 18 total records."""
    runner = _make_runner()
    records, _summary = runner.run(run_id="r-a5-total")
    assert len(records) == 18, (
        f"Expected 18 total records (12 attack + 6 normal), got {len(records)}"
    )


# ---------------------------------------------------------------------------
# BASE-8 — schema validation of all 18 records
# ---------------------------------------------------------------------------

def test_runner_all_records_schema_valid() -> None:
    """All 18 TrialRecords must validate against trial.schema.json (BASE-8)."""
    runner = _make_runner()
    records, _ = runner.run(run_id="r-schema-test")

    schema = _load_trial_schema()
    validator_cls = jsonschema.validators.validator_for(schema)
    validator = validator_cls(schema)

    for i, rec in enumerate(records):
        dumped = rec.model_dump()
        try:
            validator.validate(dumped)
        except jsonschema.ValidationError as exc:
            pytest.fail(
                f"Record {i} (trial_id={rec.trial_id!r}) failed schema validation: {exc.message}"
            )


# ---------------------------------------------------------------------------
# ENG-7 — report contains both result sets
# ---------------------------------------------------------------------------

def test_runner_report_contains_both_result_sets() -> None:
    """Rendered report must include both Normal-Task and Security sections (ENG-7)."""
    runner = _make_runner()
    _, summary = runner.run(run_id="r-report-test")
    report = render_report(summary)

    assert "normal" in report.lower(), "Normal-task section missing from report"
    assert (
        "security" in report.lower() or "attack" in report.lower()
    ), "Security section missing from report"


# ---------------------------------------------------------------------------
# ENG-8 — disclaimer always present
# ---------------------------------------------------------------------------

def test_runner_disclaimer_in_report() -> None:
    """Rendered report must contain the exact ENG-8 disclaimer string."""
    runner = _make_runner()
    _, summary = runner.run(run_id="r-disclaimer-test")
    report = render_report(summary)
    assert DISCLAIMER in report, (
        "ENG-8 disclaimer missing from rendered report"
    )


# ---------------------------------------------------------------------------
# Channel matching
# ---------------------------------------------------------------------------

def test_runner_attack_channel_matches_probe() -> None:
    """Each attack record's channel must match its probe's declared channel."""
    runner = _make_runner()
    records = runner.run_attack(run_id="r-channel-test")

    user_input_probe  = _load_probe(_PROBE_USER_INPUT)
    tool_result_probe = _load_probe(_PROBE_TOOL_RESULT)

    # First 6 records come from the user-input probe, next 6 from tool-result.
    for rec in records[:6]:
        assert rec.channel == user_input_probe["channel"], (
            f"Expected channel {user_input_probe['channel']!r}, got {rec.channel!r}"
        )
    for rec in records[6:]:
        assert rec.channel == tool_result_probe["channel"], (
            f"Expected channel {tool_result_probe['channel']!r}, got {rec.channel!r}"
        )


def test_runner_attack_channel_user_input_count() -> None:
    """Exactly 6 attack records have channel='user-input'."""
    runner = _make_runner()
    records = runner.run_attack(run_id="r-ui-count")
    ui_count = sum(1 for r in records if r.channel == "user-input")
    assert ui_count == 6, f"Expected 6 user-input records, got {ui_count}"


def test_runner_attack_channel_tool_result_count() -> None:
    """Exactly 6 attack records have channel='tool-result'."""
    runner = _make_runner()
    records = runner.run_attack(run_id="r-tr-count")
    tr_count = sum(1 for r in records if r.channel == "tool-result")
    assert tr_count == 6, f"Expected 6 tool-result records, got {tr_count}"


# ---------------------------------------------------------------------------
# Normal record null fields
# ---------------------------------------------------------------------------

def test_runner_normal_records_have_null_canary() -> None:
    """All normal records must have canary=None, probe_id=None, channel=None."""
    runner = _make_runner()
    records = runner.run_normal(run_id="r-null-test")
    for rec in records:
        assert rec.canary is None,   f"Normal record has non-null canary: {rec.canary!r}"
        assert rec.probe_id is None, f"Normal record has non-null probe_id: {rec.probe_id!r}"
        assert rec.channel is None,  f"Normal record has non-null channel: {rec.channel!r}"


def test_runner_normal_records_have_null_verdict() -> None:
    """All normal records must have verdict=None (completed, task_success unknown)."""
    runner = _make_runner()
    records = runner.run_normal(run_id="r-verdict-null")
    for rec in records:
        assert rec.verdict is None, f"Normal record has non-null verdict: {rec.verdict!r}"


def test_runner_normal_records_task_success_is_bool() -> None:
    """Every non-skipped normal record must have task_success True or False, never None."""
    runner = _make_runner()
    records = runner.run_normal(run_id="r-ts-bool")
    for rec in records:
        if rec.verdict == "skipped":
            continue
        assert rec.task_success is not None, (
            f"Non-skipped normal record has task_success=None: {rec.trial_id!r}"
        )
        assert isinstance(rec.task_success, bool), (
            f"Expected bool task_success, got {type(rec.task_success)} for {rec.trial_id!r}"
        )


# ---------------------------------------------------------------------------
# Defense coverage
# ---------------------------------------------------------------------------

def test_runner_defense_guard_on_recorded() -> None:
    """At least one attack record must have guard_on=True."""
    runner = _make_runner()
    records = runner.run_attack(run_id="r-guard-on")
    assert any(r.guard_on for r in records), (
        "No attack record has guard_on=True — guard-on half of matrix missing"
    )


def test_runner_defense_guard_off_recorded() -> None:
    """At least one attack record must have guard_on=False."""
    runner = _make_runner()
    records = runner.run_attack(run_id="r-guard-off")
    assert any(not r.guard_on for r in records), (
        "No attack record has guard_on=False — guard-off half of matrix missing"
    )


def test_runner_all_six_defense_names_represented() -> None:
    """All six defense conditions (name × guard_on) appear in the attack records."""
    runner = _make_runner()
    records = runner.run_attack(run_id="r-defense-names")
    # Each attack probe produces one record per defense condition; check the unique
    # (defense, guard_on) pairs across all 12 records.
    conditions = {(r.defense, r.guard_on) for r in records}
    expected = {(d.name, d.guard_on) for d in DEFAULT_DEFENSES}
    assert conditions == expected, (
        f"Defense conditions mismatch.\nExpected: {sorted(expected)}\nGot: {sorted(conditions)}"
    )


# ---------------------------------------------------------------------------
# Verdict and canary_in_args correctness
# ---------------------------------------------------------------------------

def test_runner_all_attack_records_have_valid_verdict() -> None:
    """Every attack record must have a non-null verdict from the allowed set."""
    runner = _make_runner()
    records = runner.run_attack(run_id="r-verdict-valid")
    valid_verdicts = {"leaked", "held", "refused", "inconclusive", "skipped"}
    for rec in records:
        assert rec.verdict in valid_verdicts, (
            f"Unexpected verdict {rec.verdict!r} in attack record {rec.trial_id!r}"
        )


def test_runner_attack_cards_shown_zero() -> None:
    """Scripted-run attack records must have cards_shown=0 (no real holds)."""
    runner = _make_runner()
    records = runner.run_attack(run_id="r-cards-zero")
    for rec in records:
        assert rec.cards_shown == 0, (
            f"Expected cards_shown=0 for scripted run, got {rec.cards_shown}"
        )


# ---------------------------------------------------------------------------
# Trial ID uniqueness
# ---------------------------------------------------------------------------

def test_runner_trial_ids_are_unique() -> None:
    """Every trial_id in a run must be unique."""
    runner = _make_runner()
    records, _ = runner.run(run_id="r-unique-ids")
    ids = [rec.trial_id for rec in records]
    assert len(ids) == len(set(ids)), (
        f"Duplicate trial_ids detected: {[x for x in ids if ids.count(x) > 1]}"
    )


# ---------------------------------------------------------------------------
# DEFAULT_DEFENSES
# ---------------------------------------------------------------------------

def test_runner_default_defenses_count() -> None:
    """DEFAULT_DEFENSES must have exactly 6 entries."""
    assert len(DEFAULT_DEFENSES) == 6, (
        f"Expected 6 DEFAULT_DEFENSES, got {len(DEFAULT_DEFENSES)}"
    )


def test_runner_default_defenses_covers_all_names() -> None:
    """DEFAULT_DEFENSES must cover all three defense names."""
    names = {d.name for d in DEFAULT_DEFENSES}
    assert names == {"none", "datamarking", "instructional"}, (
        f"Defense names mismatch: {names!r}"
    )


# ---------------------------------------------------------------------------
# A-5 standalone integration test
# ---------------------------------------------------------------------------

def test_a5_full_pipeline() -> None:
    """A-5 integration: EvaluationRunner → aggregate → render_report full pipeline.

    Verifies:
    - 18 total records (12 attack + 6 normal).
    - All records schema-valid.
    - ResultSummary has disclaimer, normal_tasks, and conditions populated.
    - Rendered report contains both result sets, disclaimer, and inconclusive column.
    - Both guard_on values represented.
    - All normal records have null canary/probe_id/channel.
    - All trial_ids unique.
    """
    runner = _make_runner()
    records, summary = runner.run(run_id="r-a5-integration")

    # --- Record counts ---
    attack_records = [r for r in records if r.kind == "attack"]
    normal_records = [r for r in records if r.kind == "normal"]
    assert len(attack_records) == 12, f"Expected 12 attack, got {len(attack_records)}"
    assert len(normal_records) == 6,  f"Expected 6 normal, got {len(normal_records)}"
    assert len(records) == 18

    # --- Schema validity ---
    schema = _load_trial_schema()
    validator_cls = jsonschema.validators.validator_for(schema)
    validator = validator_cls(schema)
    for rec in records:
        validator.validate(rec.model_dump())

    # --- ResultSummary ---
    assert summary.run_id == "r-a5-integration"
    assert summary.disclaimer == DISCLAIMER
    assert summary.total_trials == 18
    assert summary.normal_tasks.total == 6
    assert len(summary.conditions) > 0

    # --- Report ---
    report = render_report(summary)
    assert DISCLAIMER in report,                      "ENG-8 disclaimer missing"
    assert "normal" in report.lower(),                "Normal-task section missing"
    assert "security" in report.lower() or "attack" in report.lower(), "Security section missing"
    assert "inconclusive" in report.lower(),          "inconclusive column missing"

    # --- Normal record invariants ---
    for rec in normal_records:
        assert rec.canary is None
        assert rec.probe_id is None
        assert rec.channel is None
        assert rec.verdict is None

    # --- Normal task success count ---
    assert summary.normal_tasks.success == 6, (
        f"Expected 6 normal task successes (6/6), got {summary.normal_tasks.success}"
    )

    # --- Defense coverage ---
    assert any(r.guard_on for r in attack_records),     "guard_on=True records missing"
    assert any(not r.guard_on for r in attack_records), "guard_on=False records missing"

    # --- Unique trial IDs ---
    ids = [r.trial_id for r in records]
    assert len(ids) == len(set(ids)), "Duplicate trial_ids"


# ---------------------------------------------------------------------------
# adapter_factory — Test 1: factory called once per trial
# ---------------------------------------------------------------------------

def test_runner_factory_called_once_per_trial() -> None:
    """Factory is called exactly len(attack_probes) × len(defenses) = 12 times.

    Asserts:
    - Total call count == 12.
    - Every call received a non-empty probe_text string.
    - Exactly 6 calls had channel='user-input', 6 had channel='tool-result'.
    - Every call's defense is a DefenseConfig instance.
    """
    calls: list[tuple[DefenseConfig, str, str]] = []

    def spy_factory(defense: DefenseConfig, channel: str, probe_text: str) -> ScriptedAdapter:
        calls.append((defense, channel, probe_text))
        return ScriptedAdapter(_FIX_USER_INPUT)

    attack_probes = [
        (_load_probe(_PROBE_USER_INPUT),  ScriptedAdapter(_FIX_USER_INPUT)),
        (_load_probe(_PROBE_TOOL_RESULT), ScriptedAdapter(_FIX_TOOL_RESULT)),
    ]
    normal_probes = [
        (_NORMAL_PROBE_DICT, ScriptedAdapter(_FIX_NORMAL)),
    ]
    runner = EvaluationRunner(
        attack_probes=attack_probes,
        normal_probes=normal_probes,
        defenses=DEFAULT_DEFENSES,
        surface_map=_load_surface(),
        adapter_factory=spy_factory,
    )
    runner.run_attack(run_id="r-factory-call-test")

    assert len(calls) == 12, f"Expected 12 factory calls, got {len(calls)}"

    for defense, channel, probe_text in calls:
        assert isinstance(defense, DefenseConfig), (
            f"Expected DefenseConfig, got {type(defense)!r}"
        )
        assert probe_text, "probe_text must be a non-empty string"

    ui_count = sum(1 for _, ch, _ in calls if ch == "user-input")
    tr_count = sum(1 for _, ch, _ in calls if ch == "tool-result")
    assert ui_count == 6, f"Expected 6 user-input calls, got {ui_count}"
    assert tr_count == 6, f"Expected 6 tool-result calls, got {tr_count}"


# ---------------------------------------------------------------------------
# adapter_factory — Test 2: tool-result channel receives TOOL_RESULT_TASK_PROMPT
# ---------------------------------------------------------------------------

def test_runner_factory_tool_result_gets_task_prompt() -> None:
    """run_turn receives TOOL_RESULT_TASK_PROMPT for tool-result trials only.

    For user-input trials the prompt contains "Reference token:" (canary text),
    not the task prompt constant.
    """
    recorded: list[tuple[str, str]] = []  # (channel, prompt) pairs

    class _RecordingAdapter:
        def __init__(self, inner: ScriptedAdapter, channel: str) -> None:
            self._inner = inner
            self._channel = channel

        def run_turn(self, prompt: str, defense: str) -> object:  # noqa: ARG002
            recorded.append((self._channel, prompt))
            return self._inner.run_turn(prompt, defense)

    def recording_factory(defense: DefenseConfig, channel: str, probe_text: str) -> _RecordingAdapter:  # noqa: ARG001
        return _RecordingAdapter(ScriptedAdapter(_FIX_USER_INPUT), channel)

    attack_probes = [
        (_load_probe(_PROBE_USER_INPUT),  ScriptedAdapter(_FIX_USER_INPUT)),
        (_load_probe(_PROBE_TOOL_RESULT), ScriptedAdapter(_FIX_TOOL_RESULT)),
    ]
    normal_probes = [
        (_NORMAL_PROBE_DICT, ScriptedAdapter(_FIX_NORMAL)),
    ]
    runner = EvaluationRunner(
        attack_probes=attack_probes,
        normal_probes=normal_probes,
        defenses=DEFAULT_DEFENSES,
        surface_map=_load_surface(),
        adapter_factory=recording_factory,
    )
    runner.run_attack(run_id="r-factory-prompt-test")

    assert recorded, "No run_turn calls were recorded"

    for channel, prompt in recorded:
        if channel == "tool-result":
            assert prompt == TOOL_RESULT_TASK_PROMPT, (
                f"tool-result trial got unexpected prompt: {prompt!r}"
            )
        else:
            assert prompt != TOOL_RESULT_TASK_PROMPT, (
                f"user-input trial unexpectedly got TOOL_RESULT_TASK_PROMPT"
            )
            assert "Reference token:" in prompt, (
                f"user-input trial prompt missing canary text: {prompt!r}"
            )


# ---------------------------------------------------------------------------
# P1-1 — adapter_factory used in run_normal
# ---------------------------------------------------------------------------

def test_runner_factory_used_in_run_normal() -> None:
    """run_normal calls adapter_factory once per (probe × defense) when set.

    With 1 normal probe × 6 defenses, the factory should be called exactly 6
    times, each time with channel='normal' and a non-empty prompt.
    When adapter_factory is None, the factory must NOT be called.
    """
    calls: list[tuple[DefenseConfig, str, str]] = []

    def spy_factory(defense: DefenseConfig, channel: str, probe_text: str) -> ScriptedAdapter:
        calls.append((defense, channel, probe_text))
        return ScriptedAdapter(_FIX_NORMAL)

    attack_probes = [
        (_load_probe(_PROBE_USER_INPUT), ScriptedAdapter(_FIX_USER_INPUT)),
        (_load_probe(_PROBE_TOOL_RESULT), ScriptedAdapter(_FIX_TOOL_RESULT)),
    ]
    normal_probes = [(_NORMAL_PROBE_DICT, ScriptedAdapter(_FIX_NORMAL))]

    runner = EvaluationRunner(
        attack_probes=attack_probes,
        normal_probes=normal_probes,
        defenses=DEFAULT_DEFENSES,
        surface_map=_load_surface(),
        adapter_factory=spy_factory,
    )
    runner.run_normal(run_id="r-normal-factory-test")

    assert len(calls) == 6, f"Expected 6 factory calls for normal trials, got {len(calls)}"
    for defense, channel, probe_text in calls:
        assert channel == "normal", f"Expected channel='normal', got {channel!r}"
        assert isinstance(defense, DefenseConfig)
        assert probe_text, "probe_text must be non-empty"

    # Without factory, the tuple adapter is used directly (no calls).
    calls.clear()
    runner_no_factory = EvaluationRunner(
        attack_probes=attack_probes,
        normal_probes=normal_probes,
        defenses=DEFAULT_DEFENSES,
        surface_map=_load_surface(),
    )
    runner_no_factory.run_normal(run_id="r-normal-nofactory-test")
    assert len(calls) == 0, "Factory must not be called when adapter_factory is None"


# ---------------------------------------------------------------------------
# P1-2 — cards_shown counted from trace
# ---------------------------------------------------------------------------

def test_runner_cards_shown_counts_held_calls() -> None:
    """cards_shown equals the number of tool calls with guard_decision='hold'.

    Build a trace fixture with two held calls by patching the scripted adapter's
    trace in-place, then verify the resulting TrialRecord has cards_shown=2.
    """
    import copy
    from toolfence.contracts.trace import Trace

    # Load the normal fixture trace and inject two 'hold' decisions.
    raw_trace = ScriptedAdapter(_FIX_NORMAL).run_turn("dummy", "none")
    patched = raw_trace.model_copy(deep=True)
    if len(patched.tool_calls) >= 2:
        patched.tool_calls[0] = patched.tool_calls[0].model_copy(
            update={"guard_decision": "hold"}
        )
        patched.tool_calls[1] = patched.tool_calls[1].model_copy(
            update={"guard_decision": "hold"}
        )
    else:
        pytest.skip("Normal fixture has fewer than 2 tool calls; cannot patch 2 holds")

    class _FixedTrace:
        def run_turn(self, prompt: str, defense: str) -> Trace:  # noqa: ARG002
            return patched.model_copy(deep=True)

    normal_probes = [(_NORMAL_PROBE_DICT, _FixedTrace())]
    runner = EvaluationRunner(
        attack_probes=[],
        normal_probes=normal_probes,
        defenses=[DEFAULT_DEFENSES[0]],  # one defense row is enough
        surface_map=_load_surface(),
    )
    records = runner.run_normal(run_id="r-cards-shown-test")
    assert len(records) == 1
    assert records[0].cards_shown == 2, (
        f"Expected cards_shown=2, got {records[0].cards_shown}"
    )
