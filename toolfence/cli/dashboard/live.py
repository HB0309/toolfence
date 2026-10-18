"""Live-mode helpers for the ToolFence dashboard (L-2).

Exposes ``check_key``, ``WebGate``, and ``LiveSession``.  Only active when the
server is started with ``--live``; plain ``serve`` never imports or creates any
of these objects.

stdlib + toolfence imports only — no nanobot at module level.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# Key validation
# ---------------------------------------------------------------------------


def check_key(key: str) -> tuple[bool, str]:
    """Validate *key* against the OpenRouter key-info endpoint.

    Makes a GET to ``https://openrouter.ai/api/v1/key`` with
    ``Authorization: Bearer <key>`` and a 10-second timeout.

    Returns
    -------
    (True, "Key OK")           on HTTP 200
    (False, "Key rejected …")  on HTTP 401
    (False, "<reason>")        on any other error
    """
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/key",
        headers={"Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status: int = resp.status
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return False, "Key rejected by OpenRouter"
        return False, f"HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return False, str(exc.reason)
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)

    if status == 200:
        return True, "Key OK"
    return False, f"HTTP {status}"


# ---------------------------------------------------------------------------
# WebGate — thread-safe decision gate for the dashboard
# ---------------------------------------------------------------------------


class WebGate:
    """Thread-safe gate that bridges HTTP decide calls into async await_decision."""

    def __init__(self, timeout: float = 120.0) -> None:
        self._timeout = timeout
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._event: Any = None   # HeldCallEvent | None
        self._answer: bool | None = None

    def on_held(self, event: Any) -> None:
        """Called by Guard when a tool call is held."""
        with self._lock:
            self._event = event
            self._ready.clear()
            self._answer = None

    async def await_decision(self, event: Any) -> bool:
        """Await the user's Allow/Decline for up to *timeout* seconds."""
        got = await asyncio.to_thread(self._ready.wait, self._timeout)
        with self._lock:
            result = got and self._answer is True
            self._event = None
        return result

    def pending(self) -> dict | None:
        """Return a dict describing the pending held call, or None."""
        from toolfence.guard.card import build_card_message

        with self._lock:
            ev = self._event
        if ev is None:
            return None
        text, _ = build_card_message(ev)
        return {
            "tool": ev.tool_name,
            "arguments": ev.arguments,
            "reason": ev.reason,
            "text": text,
        }

    def decide(self, approved: bool) -> bool:
        """Resolve the pending decision. Returns False if nothing is pending."""
        with self._lock:
            if self._event is None:
                return False
            self._answer = approved
            self._ready.set()
            return True


# ---------------------------------------------------------------------------
# LiveSession — one-at-a-time live run coordinator
# ---------------------------------------------------------------------------


class LiveSession:
    """Coordinates live runs; enforces one-at-a-time via a threading.Lock."""

    class Busy(Exception):
        """Raised when a run is already in progress."""

    def __init__(self) -> None:
        self.gate = WebGate()
        self._busy = threading.Lock()

    def run(
        self,
        key: str,
        prompt: str,
        guard_on: bool,
        defense: str,
    ) -> dict:
        """Run one live turn and return the Trace as a dict.

        Raises
        ------
        LiveSession.Busy
            If a run is already in progress.
        RuntimeError
            If the Galaxium backend is not reachable (caller maps to 503).
        """
        if not self._busy.acquire(blocking=False):
            raise LiveSession.Busy

        try:
            from toolfence.integration.live_factory import check_target_health
            from toolfence.integration.nanobot_adapter import NanobotAdapter

            check_target_health("http://localhost:8001/")

            adapter = NanobotAdapter(
                config_path=str(REPO / "config" / "nanobot.live.json"),
                surface_path=str(REPO / "results" / "surface.json"),
                run_id="live",
                guard_on=guard_on,
                datamark_on=(defense == "datamarking"),
                channel=None,
                api_key=key,
                on_held=self.gate.on_held,
                await_decision=self.gate.await_decision,
            )

            from toolfence.integration.live_factory import _DbBackupAdapter  # type: ignore[attr-defined]

            wrapped = _DbBackupAdapter(
                adapter,
                str(REPO / "targets" / "galaxium" / "booking_system_backend" / "booking.db"),
            )

            return wrapped.run_turn(prompt, defense).model_dump()
        finally:
            self._busy.release()
