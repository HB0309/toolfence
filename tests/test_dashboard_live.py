"""Tests for L-2 / L-6b: live-mode server endpoints.

No network, no nanobot.  The server is started on port 0 (kernel assigns a
free port) and torn down after each test.

Test inventory
--------------
1. WebGate: on_held then decide(True) from a thread → await_decision returns True.
2. WebGate timeout=0.1 with no decide → False.
3. WebGate decide with nothing pending → False.
4. Without live: /api/live/status → {"enabled": false}; POST /api/live/run → 404.
5. With live: POST /api/live/run with empty key → 400.
6. check_key monkeypatched → /api/live/key returns its result.
7. LiveSession.run monkeypatched → /api/live/run 200; key not in logs.
8. (L-6b) Free-form run writes one JSON in tmp/live/ that passes TrialRecord.model_validate.
9. (L-6b) probe "9" → 400.
10. (L-6b) GET /api/live/pending includes "progress" key.
"""
from __future__ import annotations

import asyncio
import json
import threading
import urllib.request
from http.server import HTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from toolfence.contracts.guard import HeldCallEvent
from toolfence.cli.dashboard.live import WebGate, LiveSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event() -> HeldCallEvent:
    return HeldCallEvent(
        tool_name="cancel_booking",
        arguments={"booking_id": 1},
        arguments_hash="abc123",
        reason="irreversible",
        untrusted_read_count=0,
        untrusted_arg_name=None,
    )


def _start_server(live: bool = False) -> tuple[HTTPServer, str]:
    """Start a test server on port 0 and return (server, base_url)."""
    from toolfence.cli.dashboard.server import make_server
    # Patch LiveSession so we don't need real deps when live=True.
    server = make_server("127.0.0.1", 0, Path("results"), live=live)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    port = server.server_address[1]
    return server, f"http://127.0.0.1:{port}"


def _do_get(url: str) -> tuple[int, Any]:
    try:
        with urllib.request.urlopen(url) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, None


def _do_post(url: str, body: dict) -> tuple[int, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Content-Length": str(len(data))},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, None


# ---------------------------------------------------------------------------
# 1. WebGate: approve via decide from a thread → await_decision returns True
# ---------------------------------------------------------------------------

def test_webgate_allow_from_thread():
    gate = WebGate(timeout=5.0)
    event = _make_event()
    gate.on_held(event)

    def _approve():
        import time
        time.sleep(0.05)
        gate.decide(True)

    t = threading.Thread(target=_approve, daemon=True)
    t.start()

    result = asyncio.run(gate.await_decision(event))
    t.join()
    assert result is True


# ---------------------------------------------------------------------------
# 2. WebGate timeout with no decide → False
# ---------------------------------------------------------------------------

def test_webgate_timeout():
    gate = WebGate(timeout=0.1)
    event = _make_event()
    gate.on_held(event)

    result = asyncio.run(gate.await_decision(event))
    assert result is False


# ---------------------------------------------------------------------------
# 3. WebGate decide with nothing pending → False
# ---------------------------------------------------------------------------

def test_webgate_decide_nothing_pending():
    gate = WebGate()
    assert gate.decide(True) is False


# ---------------------------------------------------------------------------
# 4. Without live: /api/live/status → false; POST /api/live/run → 404
# ---------------------------------------------------------------------------

def test_no_live_status_and_run_404():
    server, base = _start_server(live=False)
    try:
        status, body = _do_get(f"{base}/api/live/status")
        assert status == 200
        assert body == {"enabled": False}

        code, _ = _do_post(f"{base}/api/live/run", {"key": "k", "prompt": "hi", "guard": True, "defense": "none"})
        assert code == 404
    finally:
        server.shutdown()


# ---------------------------------------------------------------------------
# 5. With live: POST /api/live/run with empty key → 400
# ---------------------------------------------------------------------------

def test_live_run_empty_key_400():
    server, base = _start_server(live=True)
    try:
        code, _ = _do_post(f"{base}/api/live/run", {"key": "", "prompt": "hi", "guard": True, "defense": "none"})
        assert code == 400
    finally:
        server.shutdown()


# ---------------------------------------------------------------------------
# 6. check_key monkeypatched → /api/live/key returns its result
# ---------------------------------------------------------------------------

def test_live_key_uses_check_key(monkeypatch):
    monkeypatch.setattr(
        "toolfence.cli.dashboard.live.check_key",
        lambda key: (True, "Key OK"),
    )
    server, base = _start_server(live=True)
    try:
        code, body = _do_post(f"{base}/api/live/key", {"key": "sk-or-test"})
        assert code == 200
        assert body["ok"] is True
        assert body["message"] == "Key OK"
    finally:
        server.shutdown()


# ---------------------------------------------------------------------------
# 7. LiveSession.run monkeypatched → /api/live/run 200; key not in logs
# ---------------------------------------------------------------------------

def test_live_run_returns_trace_key_not_logged(monkeypatch, caplog):
    import logging
    import toolfence.cli.dashboard.live as live_mod

    secret_key = "sk-or-super-secret-12345"
    fake_trace = {"status": "ok", "tool_calls": []}
    fake_result = {"trace": fake_trace, "record": {}}

    # Patch LiveSession.run on the class so the instance created inside
    # make_server picks it up.
    original_run = LiveSession.run

    def _fake_run(self, key, prompt, guard_on, defense, probe=""):
        return fake_result

    monkeypatch.setattr(LiveSession, "run", _fake_run)

    server, base = _start_server(live=True)
    try:
        with caplog.at_level(logging.DEBUG):
            code, body = _do_post(
                f"{base}/api/live/run",
                {"key": secret_key, "prompt": "Hello", "guard": True, "defense": "none"},
            )
        assert code == 200
        assert "trace" in body
        assert body["trace"]["status"] == "ok"
        assert "record" in body
        # The key must never appear in captured log output.
        assert secret_key not in caplog.text
    finally:
        server.shutdown()
        monkeypatch.setattr(LiveSession, "run", original_run)


# ---------------------------------------------------------------------------
# 8. Free-form run writes one JSON in tmp/live/ that passes TrialRecord.model_validate
# ---------------------------------------------------------------------------

def test_live_run_freeform_writes_valid_trial_record(tmp_path, monkeypatch):
    """LiveSession.run (free-form) must write a TrialRecord JSON to results_dir/live/."""
    import datetime
    from toolfence.contracts.trace import Trace, UsageInfo
    from toolfence.contracts.trial import TrialRecord
    import toolfence.cli.dashboard.live as live_mod

    # Build a minimal fake REPO tree so profile loading works without real files.
    fake_repo = tmp_path / "repo"
    profiles_dir = fake_repo / "profiles"
    profiles_dir.mkdir(parents=True)
    # Minimal galaxium profile JSON (fields validated by TargetProfile)
    import toolfence.contracts.profile as profile_mod
    real_profile_cls = profile_mod.TargetProfile
    # We don't have a real galaxium.json, so redirect REPO to fake_repo and
    # write a stub profile that make_live_factory_from_profile won't be called with
    # (we monkeypatch the factory instead).
    stub_profile_json = {
        "profile_id": "galaxium-test",
        "description": "Test stub",
        "nanobot_config": "config/nanobot.live.json",
        "surface": "results/surface.json",
        "state_reset": {"strategy": "none"},
        "injection": {"strategy": "none"},
        "agent_persona": "You are a helpful assistant.",
        "normal_task": {"prompt": "book me a trip", "goal_tool": "get_bookings", "label": "normal"},
        "attack_probes": [],
        "tool_result_task_prompt": "Check the reviews.",
    }
    (profiles_dir / "galaxium.json").write_text(
        json.dumps(stub_profile_json), encoding="utf-8"
    )

    monkeypatch.setattr(live_mod, "REPO", fake_repo)

    fake_trace = Trace(
        run_id="live",
        session_key="sess",
        model="test-model",
        host="nanobot",
        timestamp=datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
        status="ok",
        final_reply="done",
        tool_calls=[],
        usage=UsageInfo(
            input_tokens=1,
            output_tokens=1,
            reasoning_tokens=0,
            total_tokens=2,
            generation_ms=10,
        ),
    )

    def _fake_factory(dc, channel, probe_text):
        class _A:
            def run_turn(self, prompt, defense):
                return fake_trace
        return _A()

    monkeypatch.setattr(
        "toolfence.integration.live_factory.make_live_factory_from_profile",
        lambda *a, **kw: _fake_factory,
    )
    monkeypatch.setattr(
        "toolfence.integration.live_factory.check_target_health",
        lambda url: None,
    )

    session = LiveSession(tmp_path)
    result = session.run("sk-or-testkey", "book me a trip", True, "none", "")

    # Result dict has both keys
    assert "trace" in result
    assert "record" in result

    # One file written under tmp_path/live/
    live_dir = tmp_path / "live"
    files = list(live_dir.glob("*.json"))
    assert len(files) == 1

    # File content passes TrialRecord.model_validate
    raw = json.loads(files[0].read_text(encoding="utf-8"))
    rec = TrialRecord.model_validate(raw)
    assert rec.run_id == "live"
    assert rec.trial_id.startswith("live-")
    assert rec.task_label == "live"
    assert rec.kind == "normal"


# ---------------------------------------------------------------------------
# 9. probe "9" → 400
# ---------------------------------------------------------------------------

def test_live_run_bad_probe_returns_400():
    server, base = _start_server(live=True)
    try:
        code, _ = _do_post(
            f"{base}/api/live/run",
            {"key": "sk-or-testkey", "prompt": "hi", "guard": True, "defense": "none", "probe": "9"},
        )
        assert code == 400
    finally:
        server.shutdown()


# ---------------------------------------------------------------------------
# 10. GET /api/live/pending includes "progress" key
# ---------------------------------------------------------------------------

def test_live_pending_includes_progress():
    server, base = _start_server(live=True)
    try:
        status, body = _do_get(f"{base}/api/live/pending")
        assert status == 200
        assert "pending" in body
        assert "progress" in body
        assert isinstance(body["progress"], list)
    finally:
        server.shutdown()
