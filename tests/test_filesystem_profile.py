"""Tests for the filesystem target profile (Phase C).

Test inventory (17 tests)
-------------------------
  test_filesystem_profile_loads
  test_filesystem_profile_has_two_normal_tasks
  test_extra_task_label_is_read_then_write
  test_fs_user_input_probe_loads
  test_fs_tool_result_probe_loads
  test_fs_snapshot_hello_txt_exists
  test_fs_restore_delete_then_copy
  test_fs_restore_does_not_use_dirs_exist_ok
  test_canary_file_written_after_restore
  test_canary_file_not_in_snapshot
  test_task_label_in_normal_probe_dict
  test_scoring_separate_rows_for_each_label
  test_write_only_prompt_contains_workdir_placeholder
  test_expand_workdir_replaces_placeholder
  test_workdir_expanded_in_run_turn
  test_nanobot_config_filesystem_loads
  test_report_normal_conditions_has_task_column
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: str) -> dict:
    return json.loads((REPO_ROOT / path).read_text(encoding="utf-8"))


def _make_trace() -> Any:
    """Return a minimal Trace suitable for TrialRecord."""
    from toolfence.engine.adapter import ScriptedAdapter
    return ScriptedAdapter(REPO_ROOT / "fixtures/probes/normal_task.json").run_turn("x", "none")


# ---------------------------------------------------------------------------
# Profile and probe loading
# ---------------------------------------------------------------------------

def test_filesystem_profile_loads():
    """profiles/filesystem.json parses as a TargetProfile without error."""
    from toolfence.contracts.profile import TargetProfile
    data = _load_json("profiles/filesystem.json")
    profile = TargetProfile.model_validate(data)
    assert profile.profile_id == "filesystem"
    assert profile.surface == "profiles/filesystem-surface.json"
    assert profile.state_reset.strategy == "fs_restore"
    assert profile.injection.strategy == "fs_canary_file"


def test_filesystem_profile_has_two_normal_tasks():
    """Primary normal_task plus one extra_normal_tasks entry = 2 tasks."""
    from toolfence.contracts.profile import TargetProfile
    data = _load_json("profiles/filesystem.json")
    profile = TargetProfile.model_validate(data)
    assert len(profile.extra_normal_tasks) == 1


def test_extra_task_label_is_read_then_write():
    """extra_normal_tasks[0].label == 'read_then_write'."""
    from toolfence.contracts.profile import TargetProfile
    data = _load_json("profiles/filesystem.json")
    profile = TargetProfile.model_validate(data)
    assert profile.extra_normal_tasks[0].label == "read_then_write"


def test_fs_user_input_probe_loads():
    """fs-user-input.json is a valid probe with the correct channel and probe_id."""
    probe = _load_json("toolfence/engine/probes/fs-user-input.json")
    assert probe["channel"] == "user-input"
    assert "probe_id" in probe and probe["probe_id"]
    assert "{{CANARY}}" in probe["content"]
    assert "{{WORKDIR}}" in probe["content"]


def test_fs_tool_result_probe_loads():
    """fs-tool-result.json is a valid probe with the correct channel and probe_id."""
    probe = _load_json("toolfence/engine/probes/fs-tool-result.json")
    assert probe["channel"] == "tool-result"
    assert "probe_id" in probe and probe["probe_id"]
    assert "{{CANARY}}" in probe["content"]


def test_fs_snapshot_hello_txt_exists():
    """profiles/fs-snapshot/hello.txt exists and is non-empty."""
    p = REPO_ROOT / "profiles" / "fs-snapshot" / "hello.txt"
    assert p.exists(), "profiles/fs-snapshot/hello.txt not found"
    assert p.read_text(encoding="utf-8").strip(), "hello.txt is empty"


# ---------------------------------------------------------------------------
# _FsRestoreAdapter
# ---------------------------------------------------------------------------

def test_fs_restore_delete_then_copy(tmp_path):
    """_FsRestoreAdapter.run_turn deletes the working dir then copies from snapshot."""
    from toolfence.integration.live_factory import _FsRestoreAdapter

    snapshot = tmp_path / "snap"
    snapshot.mkdir()
    (snapshot / "seed.txt").write_text("seed", encoding="utf-8")

    working = tmp_path / "work"
    working.mkdir()
    (working / "old.txt").write_text("old", encoding="utf-8")

    inner = MagicMock()
    inner.run_turn.return_value = _make_trace()

    adapter = _FsRestoreAdapter(inner, str(snapshot), str(working))
    adapter.run_turn("prompt", "none")

    # old.txt must be gone; seed.txt must be present
    assert not (working / "old.txt").exists()
    assert (working / "seed.txt").exists()
    inner.run_turn.assert_called_once()


def test_fs_restore_does_not_use_dirs_exist_ok(tmp_path):
    """copytree is never called with dirs_exist_ok=True (delete-then-copy invariant)."""
    from toolfence.integration.live_factory import _FsRestoreAdapter

    snapshot = tmp_path / "snap"
    snapshot.mkdir()
    working = tmp_path / "work"

    inner = MagicMock()
    inner.run_turn.return_value = _make_trace()

    with patch("toolfence.integration.live_factory.shutil.copytree") as mock_copytree:
        mock_copytree.side_effect = lambda src, dst, **kw: dst.mkdir(exist_ok=True)  # type: ignore[attr-defined]
        adapter = _FsRestoreAdapter(inner, str(snapshot), str(working))
        adapter.run_turn("prompt", "none")
        _, kwargs = mock_copytree.call_args
        assert not kwargs.get("dirs_exist_ok", False), "copytree must not use dirs_exist_ok=True"


# ---------------------------------------------------------------------------
# _FsCanaryAndRestoreAdapter
# ---------------------------------------------------------------------------

def test_canary_file_written_after_restore(tmp_path):
    """_FsCanaryAndRestoreAdapter writes the canary file into the working dir after restore."""
    from toolfence.integration.live_factory import _FsCanaryAndRestoreAdapter

    snapshot = tmp_path / "snap"
    snapshot.mkdir()
    (snapshot / "seed.txt").write_text("seed", encoding="utf-8")

    working = tmp_path / "work"

    inner = MagicMock()
    inner.run_turn.return_value = _make_trace()

    adapter = _FsCanaryAndRestoreAdapter(
        inner,
        snapshot_path=str(snapshot),
        working_path=str(working),
        canary_filename="canary.txt",
        canary_content="CANARY_CONTENT",
    )
    adapter.run_turn("prompt", "none")

    assert (working / "canary.txt").read_text(encoding="utf-8") == "CANARY_CONTENT"
    assert (working / "seed.txt").exists()


def test_canary_file_not_in_snapshot():
    """profiles/fs-snapshot/ does not contain canary.txt."""
    canary = REPO_ROOT / "profiles" / "fs-snapshot" / "canary.txt"
    assert not canary.exists(), "canary.txt must not be in the committed snapshot"


# ---------------------------------------------------------------------------
# task_label in scoring
# ---------------------------------------------------------------------------

def test_task_label_in_normal_probe_dict():
    """CLI wires primary normal_task with a 'label' key taken from profile.normal_task.label."""
    from toolfence.contracts.profile import TargetProfile

    data = _load_json("profiles/filesystem.json")
    profile = TargetProfile.model_validate(data)

    # Primary task gets label from profile.normal_task.label; extra gets extra.label
    primary_dict = {
        "content": profile.normal_task.prompt,
        "goal_tool": profile.normal_task.goal_tool,
        "label": profile.normal_task.label,
    }
    extra_dicts = [
        {
            "content": e.prompt,
            "goal_tool": e.goal_tool,
            "label": e.label,
        }
        for e in profile.extra_normal_tasks
    ]

    assert primary_dict["label"] == "write_only"
    assert extra_dicts[0]["label"] == "read_then_write"


def test_scoring_separate_rows_for_each_label():
    """_aggregate_normal produces a separate NormalConditionSummary per task_label."""
    from toolfence.contracts.trial import TrialRecord
    from toolfence.engine.scoring import _aggregate_normal

    trace = _make_trace()

    def _make_normal(label: str | None, success: bool) -> TrialRecord:
        return TrialRecord(
            trial_id="t-1",
            run_id="r-1",
            kind="normal",
            channel=None,
            defense="none",
            guard_on=False,
            probe_id=None,
            canary=None,
            verdict=None,
            task_success=success,
            trace=trace,
            canary_in_args=False,
            cards_shown=0,
            task_label=label,
        )

    trials = [
        _make_normal("write_only", True),
        _make_normal("read_then_write", False),
    ]
    _, conditions = _aggregate_normal(trials)
    labels = {nc.task_label for nc in conditions}
    assert "write_only" in labels
    assert "read_then_write" in labels
    assert len(conditions) == 2


# ---------------------------------------------------------------------------
# {{WORKDIR}} placeholder
# ---------------------------------------------------------------------------

def test_write_only_prompt_contains_workdir_placeholder():
    """Primary normal_task.prompt contains {{WORKDIR}} and no literal path."""
    data = _load_json("profiles/filesystem.json")
    prompt = data["normal_task"]["prompt"]
    assert "{{WORKDIR}}" in prompt, "prompt must contain {{WORKDIR}} placeholder"
    assert "profiles/fs-workdir" not in prompt, "prompt must not contain literal relative path"
    assert "\\" not in prompt, "prompt must not contain backslashes"


def test_expand_workdir_replaces_placeholder():
    """_expand_workdir substitutes {{WORKDIR}} with the given absolute path."""
    from toolfence.integration.live_factory import _expand_workdir

    result = _expand_workdir("{{WORKDIR}}/foo.txt", "/abs/path")
    assert result == "/abs/path/foo.txt"


def test_workdir_expanded_in_run_turn(tmp_path):
    """_FsRestoreAdapter expands {{WORKDIR}} in the prompt before calling the inner adapter."""
    from toolfence.integration.live_factory import _FsRestoreAdapter

    snapshot = tmp_path / "snap"
    snapshot.mkdir()

    inner = MagicMock()
    inner.run_turn.return_value = _make_trace()

    workdir_abs = str(tmp_path / "work").replace("\\", "/")
    adapter = _FsRestoreAdapter(
        inner,
        str(snapshot),
        str(tmp_path / "work"),
        workdir_abs=workdir_abs,
    )
    adapter.run_turn("Create {{WORKDIR}}/summary.txt", "none")

    called_prompt = inner.run_turn.call_args[0][0]
    assert "{{WORKDIR}}" not in called_prompt
    assert workdir_abs in called_prompt


# ---------------------------------------------------------------------------
# nanobot config
# ---------------------------------------------------------------------------

def test_nanobot_config_filesystem_loads():
    """config/nanobot.filesystem.json is valid JSON with mcpServers.filesystem."""
    data = _load_json("config/nanobot.filesystem.json")
    assert "mcpServers" in data.get("tools", {})
    assert "filesystem" in data["tools"]["mcpServers"]
    cfg = data["tools"]["mcpServers"]["filesystem"]
    assert cfg.get("type") == "stdio"
    assert "WORKDIR_PLACEHOLDER" in cfg.get("args", [])


# ---------------------------------------------------------------------------
# report.py Task column
# ---------------------------------------------------------------------------

def test_report_normal_conditions_has_task_column():
    """render_report includes a Task column in the normal-task conditions table."""
    from toolfence.contracts.trial import TrialRecord
    from toolfence.engine.report import render_report
    from toolfence.engine.scoring import aggregate

    trace = _make_trace()
    record = TrialRecord(
        trial_id="t-1",
        run_id="r-1",
        kind="normal",
        channel=None,
        defense="none",
        guard_on=False,
        probe_id=None,
        canary=None,
        verdict=None,
        task_success=True,
        trace=trace,
        canary_in_args=False,
        cards_shown=0,
        task_label="write_only",
    )
    summary = aggregate([record], "r-1")
    report = render_report(summary)
    assert "Task" in report, "render_report must include a 'Task' column header"
    assert "write_only" in report
