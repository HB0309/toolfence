"""Phase B — Taint-flow probe file tests.

Covers:
  - validate_probe_file passes for taint-flow-tool-result.json
  - ProbeBuilder substitutes the canary placeholder correctly
  - channel and probe_id values match spec

Test inventory
--------------
  test_taint_flow_probe_file_validates
  test_taint_flow_probe_builder_substitutes_canary
  test_taint_flow_probe_no_canary_placeholder_after_build
  test_taint_flow_probe_channel_is_tool_result
  test_taint_flow_probe_id
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_PROBE_PATH = _REPO_ROOT / "toolfence" / "engine" / "probes" / "taint-flow-tool-result.json"

_CANARY = "TF-CANARY-DEADBEEF"


def test_taint_flow_probe_file_validates() -> None:
    """validate_probe_file returns True for taint-flow-tool-result.json."""
    from toolfence.engine.probe import validate_probe_file

    assert _PROBE_PATH.exists(), f"Probe file not found: {_PROBE_PATH}"
    assert validate_probe_file(_PROBE_PATH), "validate_probe_file returned False"


def test_taint_flow_probe_builder_substitutes_canary() -> None:
    """ProbeBuilder.build replaces {{CANARY}} with the canary string."""
    import json

    from toolfence.engine.probe import ProbeBuilder

    probe_dict = json.loads(_PROBE_PATH.read_text(encoding="utf-8"))
    built = ProbeBuilder(probe_dict).build(_CANARY)
    assert _CANARY in built["content"], "Canary not present in built content"


def test_taint_flow_probe_no_canary_placeholder_after_build() -> None:
    """After build, {{CANARY}} placeholder is gone from content."""
    import json

    from toolfence.engine.probe import ProbeBuilder

    probe_dict = json.loads(_PROBE_PATH.read_text(encoding="utf-8"))
    built = ProbeBuilder(probe_dict).build(_CANARY)
    assert "{{CANARY}}" not in built["content"], "Placeholder still present after build"


def test_taint_flow_probe_channel_is_tool_result() -> None:
    """Probe channel must be 'tool-result'."""
    import json

    probe_dict = json.loads(_PROBE_PATH.read_text(encoding="utf-8"))
    assert probe_dict["channel"] == "tool-result"


def test_taint_flow_probe_id() -> None:
    """Probe ID must be 'taint-flow-tool-result-001'."""
    import json

    probe_dict = json.loads(_PROBE_PATH.read_text(encoding="utf-8"))
    assert probe_dict["probe_id"] == "taint-flow-tool-result-001"
