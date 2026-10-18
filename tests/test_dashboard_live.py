"""Tests for L-2: live-mode server endpoints.

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
7. LiveSession.run monkeypatched to {"status": "ok"} → /api/live/run 200 with "trace";
   key string never appears in caplog.
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

    # Patch LiveSession.run on the class so the instance created inside
    # make_server picks it up.
    original_run = LiveSession.run

    def _fake_run(self, key, prompt, guard_on, defense):
        return fake_trace

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
        # The key must never appear in captured log output.
        assert secret_key not in caplog.text
    finally:
        server.shutdown()
        monkeypatch.setattr(LiveSession, "run", original_run)
