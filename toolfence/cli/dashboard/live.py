"""Live-mode helpers for the ToolFence dashboard (L-2).

Exposes ``check_key``, ``WebGate``, and ``LiveSession``.  Only active when the
server is started with ``--live``; plain ``serve`` never imports or creates any
of these objects.

stdlib + toolfence imports only — no nanobot at module level.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

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
        self.held_count: int = 0

    def on_held(self, event: Any) -> None:
        """Called by Guard when a tool call is held."""
        with self._lock:
            self._event = event
            self._ready.clear()
            self._answer = None
            self.held_count += 1

    def reset(self) -> None:
        """Reset held_count to 0 before a new run."""
        with self._lock:
            self.held_count = 0

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

    def __init__(self, results_dir: Path) -> None:
        self.gate = WebGate()
        self.results_dir = results_dir
        self.progress: list[dict] = []
        self._busy = threading.Lock()

    def run(
        self,
        key: str,
        prompt: str,
        guard_on: bool,
        defense: str,
        probe: str = "",
    ) -> dict:
        """Run one live turn and return a dict with trace and record.

        Parameters
        ----------
        key:
            OpenRouter API key.
        prompt:
            Free-form user prompt (used only when probe == "").
        guard_on:
            Whether Guard is active.
        defense:
            Defense label ("none", "datamarking", "instructional").
        probe:
            "" for free-form, or "0"/"1"/"2" to run an attack probe.

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
            from toolfence.contracts.profile import TargetProfile
            from toolfence.contracts.surface import SurfaceFile
            from toolfence.contracts.trial import TrialRecord
            from toolfence.engine.runner import DefenseConfig, EvaluationRunner
            from toolfence.integration.live_factory import (
                check_target_health,
                make_live_factory_from_profile,
            )

            check_target_health("http://localhost:8001/")

            self.gate.reset()
            self.progress.clear()

            profile = TargetProfile.model_validate(
                json.loads((REPO / "profiles/galaxium.json").read_text(encoding="utf-8"))
            )
            profile = profile.model_copy(
                update={
                    "nanobot_config": str(REPO / "config/nanobot.live.json"),
                    "surface": str(REPO / "results/surface.json"),
                }
            )

            factory = make_live_factory_from_profile(
                profile,
                "live",
                api_key=key,
                on_held=self.gate.on_held,
                await_decision=self.gate.await_decision,
                on_tool_event=self.progress.append,
            )

            dc = DefenseConfig(name=defense, guard_on=guard_on, datamark_on=(defense == "datamarking"))

            if probe != "":
                # Attack probe path
                from toolfence.cli.main import _apply_task_prompt

                probe_entry = profile.attack_probes[int(probe)]
                if isinstance(probe_entry, str):
                    probe_path = REPO / probe_entry
                    task_prompt_override = None
                else:
                    probe_path = REPO / probe_entry.path
                    task_prompt_override = probe_entry.task_prompt

                probe_dict = json.loads(probe_path.read_text(encoding="utf-8"))
                probe_dict = _apply_task_prompt(probe_dict, profile, task_prompt_override)

                surface = SurfaceFile.model_validate(
                    json.loads((REPO / "results/surface.json").read_text(encoding="utf-8"))
                )

                rec = EvaluationRunner(
                    [(probe_dict, None)],
                    [],
                    [dc],
                    surface_map=surface,
                    adapter_factory=factory,
                ).run_attack("live")[0]
            else:
                # Free-form path
                trace = factory(dc, "normal", prompt).run_turn(prompt, defense)
                rec = TrialRecord(
                    trial_id="x",
                    run_id="live",
                    kind="normal",
                    channel=None,
                    defense=defense,
                    guard_on=guard_on,
                    probe_id=None,
                    canary=None,
                    verdict=None,
                    task_success=None,
                    trace=trace,
                    canary_in_args=False,
                    cards_shown=0,
                    task_label="live",
                )

            utcnow = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
            trial_id = "live-" + utcnow + "-" + uuid4().hex[:4]
            rec = rec.model_copy(update={"trial_id": trial_id, "cards_shown": self.gate.held_count})

            live_dir = self.results_dir / "live"
            live_dir.mkdir(parents=True, exist_ok=True)
            (live_dir / f"{trial_id}.json").write_text(
                rec.model_dump_json(indent=2), encoding="utf-8"
            )

            return {"trace": rec.trace.model_dump(), "record": rec.model_dump()}
        finally:
            self._busy.release()
