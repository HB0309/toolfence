"""Unit tests for scripts/run_pg8_gate.py (P1-9).

All tests run without a live Galaxium backend.  The adapter factory,
health check, and surface file loading are all mocked.

Test inventory
--------------
  test_imports_normal_task_prompt          NORMAL_TASK_PROMPT imported from runner
  test_imports_check_galaxium_health       check_galaxium_health imported from live_factory
  test_imports_make_live_factory           make_live_factory imported from live_factory
  test_uses_narrowed_config                config path is nanobot.eval.json (not .full.)
  test_guard_on_true                       DefenseConfig built with guard_on=True
  test_ten_normal_probes                   runner receives 10 normal probe entries
  test_no_attack_probes                    runner receives empty attack_probes
  test_single_defense_guard_on             runner receives 1 DefenseConfig with guard_on=True
  test_normal_probe_content_is_prompt      each normal probe uses NORMAL_TASK_PROMPT
  test_health_check_called                 check_galaxium_health is called before factory
  test_health_check_failure_exits_1        RuntimeError from health check → sys.exit(1)
  test_pass_gate_10_of_10                  10 passes → exit 0, "PASS" in output file
  test_pass_threshold_exactly_8            exactly 8 passes → PASS
  test_fail_threshold_exactly_7            exactly 7 passes → FAIL
  test_fail_gate_0_of_10                   0 passes → exit 1, "FAIL" in output file
  test_output_file_written                 output markdown file is written
  test_output_contains_run_id             run ID appears in the markdown
  test_output_contains_all_10_trial_ids   all 10 trial_ids appear in the markdown
  test_fail_output_contains_failure_notes  below-threshold output has failure section
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module-level autouse fixture — redirect all file I/O to tmp_path
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _redirect_gate_paths(tmp_path: Path):
    """Patch _RECORDS_DIR and _OUTPUT_PATH to tmp_path for every test.

    This prevents any test from accidentally writing into the real
    results/pg8-gate/ or docs/notes/ directories.
    """
    records_dir = tmp_path / "pg8-gate"
    output_path = tmp_path / "guard-gate-results.md"
    with (
        patch.object(_gate, "_RECORDS_DIR", records_dir),
        patch.object(_gate, "_OUTPUT_PATH", output_path),
    ):
        yield


# ---------------------------------------------------------------------------
# Load the script as a module (lives outside the package hierarchy)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "run_pg8_gate.py"


def _load_gate_module():
    spec = importlib.util.spec_from_file_location("run_pg8_gate", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_gate = _load_gate_module()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIXTURES = _REPO_ROOT / "fixtures" / "probes"
_SURFACE_FIXTURE = _REPO_ROOT / "fixtures" / "surface_fixture.json"


def _scripted_trace() -> Any:
    """Passing trace: status=ok, goal tool called with guard_decision=pass."""
    from toolfence.engine.adapter import ScriptedAdapter
    return ScriptedAdapter(_FIXTURES / "normal_task.json").run_turn("x", "none")


def _failing_trace() -> Any:
    """Failing trace: status=ok but goal tool never called."""
    from toolfence.contracts.trace import Trace
    return Trace(
        run_id="test",
        session_key="s",
        model="m",
        host="h",
        timestamp="2026-01-01T00:00:00Z",
        status="ok",
        final_reply="nothing useful",
        tool_calls=[],
        usage={
            "input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
            "generation_ms": 0,
        },
    )


def _make_factory(traces: list[Any]):
    """Return a factory callable that serves *traces* one per call."""
    it = iter(traces)

    def _factory(defense, channel, probe_text):
        adapter = MagicMock()
        adapter.run_turn.return_value = next(it)
        return adapter

    return _factory


def _fake_surface() -> Any:
    """Load the real surface fixture so SurfaceFile.model_validate receives valid data."""
    from toolfence.contracts.surface import SurfaceFile
    return SurfaceFile.model_validate(
        json.loads(_SURFACE_FIXTURE.read_text(encoding="utf-8"))
    )


def _run_main_clean(
    tmp_path: Path,
    passing_count: int = 10,
    captured_kwargs: dict | None = None,
) -> tuple[int, str]:
    """Clean runner: patches check_galaxium_health, make_live_factory, and the
    surface JSON read; optionally spy on EvaluationRunner kwargs.

    Also redirects _RECORDS_DIR to a sub-directory of tmp_path so record files
    are written there instead of the real results/pg8-gate/.
    """
    passing_trace = _scripted_trace()
    failing_trace = _failing_trace()
    traces = [passing_trace] * passing_count + [failing_trace] * (10 - passing_count)
    output_file = tmp_path / "guard-gate-results.md"
    records_dir = tmp_path / "pg8-gate"

    surface = _fake_surface()

    orig_runner_init = _gate.EvaluationRunner.__init__

    def _spy_init(self_inner, *args, **kwargs):
        if captured_kwargs is not None:
            captured_kwargs.update(kwargs)
        orig_runner_init(self_inner, *args, **kwargs)

    from toolfence.contracts.surface import SurfaceFile

    with (
        patch.object(_gate, "check_galaxium_health"),
        patch.object(_gate, "make_live_factory", return_value=_make_factory(traces)),
        patch.object(_gate, "_OUTPUT_PATH", output_file),
        patch.object(_gate, "_RECORDS_DIR", records_dir),
        patch.object(_gate.EvaluationRunner, "__init__", _spy_init),
        patch.object(SurfaceFile, "model_validate", return_value=surface),
        patch("pathlib.Path.read_text", return_value="{}"),
        pytest.raises(SystemExit) as exc_info,
    ):
        _gate.main()

    exit_code = exc_info.value.code
    text = output_file.read_text(encoding="utf-8") if output_file.exists() else ""
    return exit_code, text


# ---------------------------------------------------------------------------
# Import-level assertions
# ---------------------------------------------------------------------------

class TestImports:

    def test_imports_normal_task_prompt(self) -> None:
        """NORMAL_TASK_PROMPT must be the same object imported from runner."""
        from toolfence.engine.runner import NORMAL_TASK_PROMPT
        assert _gate.NORMAL_TASK_PROMPT is NORMAL_TASK_PROMPT

    def test_imports_check_galaxium_health(self) -> None:
        """check_galaxium_health must be imported from live_factory."""
        from toolfence.integration.live_factory import check_galaxium_health
        assert _gate.check_galaxium_health is check_galaxium_health

    def test_imports_make_live_factory(self) -> None:
        """make_live_factory must be imported from live_factory."""
        from toolfence.integration.live_factory import make_live_factory
        assert _gate.make_live_factory is make_live_factory

    def test_uses_narrowed_config(self) -> None:
        """Config path must be nanobot.eval.json, not nanobot.eval.full.json."""
        assert "nanobot.eval.full" not in _gate._CONFIG_PATH
        assert "nanobot.eval.json" in _gate._CONFIG_PATH


# ---------------------------------------------------------------------------
# Runner construction checks
# ---------------------------------------------------------------------------

class TestRunnerConstruction:

    def test_ten_normal_probes(self, tmp_path: Path) -> None:
        """EvaluationRunner must receive exactly 10 normal_probes entries."""
        captured: dict = {}
        _run_main_clean(tmp_path, passing_count=10, captured_kwargs=captured)
        assert len(captured["normal_probes"]) == 10

    def test_no_attack_probes(self, tmp_path: Path) -> None:
        """EvaluationRunner must receive an empty attack_probes list."""
        captured: dict = {}
        _run_main_clean(tmp_path, passing_count=10, captured_kwargs=captured)
        assert captured["attack_probes"] == []

    def test_single_defense_guard_on(self, tmp_path: Path) -> None:
        """EvaluationRunner must receive exactly one DefenseConfig with guard_on=True."""
        captured: dict = {}
        _run_main_clean(tmp_path, passing_count=10, captured_kwargs=captured)
        defenses = captured["defenses"]
        assert len(defenses) == 1
        assert defenses[0].guard_on is True

    def test_normal_probe_content_is_normal_task_prompt(self, tmp_path: Path) -> None:
        """Every normal probe dict must have content == NORMAL_TASK_PROMPT."""
        from toolfence.engine.runner import NORMAL_TASK_PROMPT
        captured: dict = {}
        _run_main_clean(tmp_path, passing_count=10, captured_kwargs=captured)
        for probe_dict, _ in captured["normal_probes"]:
            assert probe_dict["content"] == NORMAL_TASK_PROMPT


# ---------------------------------------------------------------------------
# Health-check behaviour
# ---------------------------------------------------------------------------

class TestHealthCheck:

    def test_health_check_called(self, tmp_path: Path) -> None:
        """check_galaxium_health() must be called exactly once."""
        from toolfence.contracts.surface import SurfaceFile
        surface = _fake_surface()
        traces = [_scripted_trace()] * 10
        mock_health = MagicMock()

        with (
            patch.object(_gate, "check_galaxium_health", mock_health),
            patch.object(_gate, "make_live_factory", return_value=_make_factory(traces)),
            patch.object(SurfaceFile, "model_validate", return_value=surface),
            patch("pathlib.Path.read_text", return_value="{}"),
            pytest.raises(SystemExit),
        ):
            _gate.main()

        mock_health.assert_called_once()

    def test_health_check_failure_exits_1(self) -> None:
        """RuntimeError from check_galaxium_health must cause sys.exit(1)."""
        with (
            patch.object(
                _gate, "check_galaxium_health",
                side_effect=RuntimeError("backend down"),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            _gate.main()

        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Gate pass/fail outcomes
# ---------------------------------------------------------------------------

class TestGateOutcome:

    def test_pass_10_of_10(self, tmp_path: Path) -> None:
        code, text = _run_main_clean(tmp_path, 10)
        assert code == 0
        assert "PASS" in text

    def test_pass_threshold_exactly_8(self, tmp_path: Path) -> None:
        code, text = _run_main_clean(tmp_path, 8)
        assert code == 0
        assert "PASS" in text

    def test_fail_threshold_exactly_7(self, tmp_path: Path) -> None:
        code, text = _run_main_clean(tmp_path, 7)
        assert code == 1
        assert "FAIL" in text

    def test_fail_gate_0_of_10(self, tmp_path: Path) -> None:
        code, text = _run_main_clean(tmp_path, 0)
        assert code == 1
        assert "FAIL" in text

    def test_output_file_written(self, tmp_path: Path) -> None:
        _, text = _run_main_clean(tmp_path, 10)
        assert len(text) > 0

    def test_output_contains_run_id(self, tmp_path: Path) -> None:
        _, text = _run_main_clean(tmp_path, 10)
        assert "pg8-" in text

    def test_output_contains_all_10_trial_ids(self, tmp_path: Path) -> None:
        _, text = _run_main_clean(tmp_path, 10)
        trial_rows = [line for line in text.splitlines() if line.startswith("| `t-")]
        assert len(trial_rows) == 10, (
            f"Expected 10 trial rows in output, found {len(trial_rows)}:\n{text}"
        )

    def test_fail_output_contains_failure_notes(self, tmp_path: Path) -> None:
        _, text = _run_main_clean(tmp_path, 5)
        assert "Failure notes" in text

    def test_trial_records_written_to_records_dir(self, tmp_path: Path) -> None:
        """10 trial JSON files must be written to _RECORDS_DIR, one per trial_id."""
        import json
        from toolfence.contracts.trial import TrialRecord

        _, text = _run_main_clean(tmp_path, 10)
        records_dir = tmp_path / "pg8-gate"

        json_files = sorted(records_dir.glob("*.json"))
        assert len(json_files) == 10, (
            f"Expected 10 JSON files in {records_dir}, found {len(json_files)}"
        )
        for jf in json_files:
            data = json.loads(jf.read_text(encoding="utf-8"))
            rec = TrialRecord.model_validate(data)
            assert jf.stem == rec.trial_id, (
                f"File name {jf.name!r} does not match trial_id {rec.trial_id!r}"
            )
            assert rec.kind == "normal"
