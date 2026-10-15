"""Minimal demo gateway launcher with Guard + Telegram confirm card (B-4b).

Usage
-----
Set environment variables then run::

    NANOBOT_CONFIG=config/nanobot.gateway.json \\
    TOOLFENCE_SURFACE=results/surface.json \\
    TELEGRAM_USER_ID=<your-telegram-user-id> \\
    python scripts/launch_gateway.py

Secrets (``BOT_TOKEN``, etc.) stay in the nanobot config file — this script
reads only the Guard-specific variables shown above.

What this script does
---------------------
1. Loads nanobot config and constructs ``bus``, ``tools``, and ``mcp_provider``
   using the same constructors as ``gateway_runtime._run_gateway``.
2. Creates a temporary workspace (``tempfile.mkdtemp()``) for the session, the
   same way ``nanobot_adapter._async_run_turn`` does.
3. Builds a ``DecisionGate`` that owns all hold-decision state.
4. Applies the loopback transport fix (via
   ``nanobot_adapter._mcp_urls_are_all_loopback``) before ``mcp_provider.connect()``
   and restores the original factory after ``mcp_provider.aclose()``.
5. Wraps ``bus.publish_inbound`` to:
   - Drop all Telegram ``is_callback`` inbound messages silently.
   - Pass Telegram text messages through ``gate.handle_inbound`` before
     recording provenance; consumed messages never reach the agent.
   - Record provenance and publish all other messages normally.
6. Builds ``ChannelManager``; gets the ``TelegramChannel``; wraps its
   ``_on_callback_query`` with ``wrap_callback_query`` (passing
   ``resolve_decision=gate.resolve``) before channels start.
7. Runs a minimal async loop: connect MCP → install Guard → start agent and
   channels concurrently → wait for shutdown.

Guard install happens after ``mcp_provider.connect()`` so the MCP tools are
registered before ``install_guard`` wraps them, matching the pattern in
``nanobot_adapter._async_run_turn``.

``on_held`` uses ``asyncio.get_running_loop().create_task(...)`` because it is
called from within the running event loop (inside ``GuardedProxy.execute``).

This is a **demo launcher** scoped to B-4b.  Production features (cron, dream,
heartbeat, health server, WebUI) are out of scope and not wired here.

Import boundary
---------------
This script lives in ``scripts/`` and may import from anywhere including nanobot.
"""
from __future__ import annotations

import asyncio
import functools
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)
_log = logging.getLogger("toolfence.gateway")

# ---------------------------------------------------------------------------
# Env-var config
# ---------------------------------------------------------------------------

_CONFIG_PATH = os.environ.get("NANOBOT_CONFIG", "config/nanobot.gateway.json")
_SURFACE_PATH = os.environ.get("TOOLFENCE_SURFACE", "results/surface.json")
_CHAT_ID = os.environ.get("TELEGRAM_USER_ID", "")

if not _CHAT_ID:
    print(
        "ERROR: TELEGRAM_USER_ID is not set.\n"
        "Export TELEGRAM_USER_ID=<your-telegram-user-id> and re-run.",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Imports (nanobot + toolfence)
# ---------------------------------------------------------------------------

import json as _json

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.mcp import MCPProvider
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.manager import ChannelManager
from nanobot.cli.runtime_config import _load_runtime_config
from nanobot.providers.factory import make_provider
from nanobot.session.manager import SessionManager

from toolfence.contracts.guard import HeldCallEvent
from toolfence.contracts.surface import SurfaceFile
from toolfence.guard.confirm import ConfirmGrant
from toolfence.guard.decision import GuardDecision
from toolfence.guard.provenance import ProvenanceStore
from toolfence.guard.taint import SessionTaint
from toolfence.integration.channel_adapter import (
    DecisionGate,
    send_hold_card,
    wrap_callback_query,
)
from toolfence.integration.installer import install_guard
from toolfence.integration.nanobot_adapter import _mcp_urls_are_all_loopback

# ---------------------------------------------------------------------------
# Load config and surface
# ---------------------------------------------------------------------------

_workspace = tempfile.mkdtemp(prefix="toolfence-gateway-")
config = _load_runtime_config(_CONFIG_PATH, _workspace)

surface_map = SurfaceFile.model_validate(
    _json.loads(Path(_SURFACE_PATH).read_text(encoding="utf-8"))
)

# ---------------------------------------------------------------------------
# Core nanobot objects
# ---------------------------------------------------------------------------

bus = MessageBus()
tools = ToolRegistry()
mcp_provider = MCPProvider.from_config(config, tools)
session_manager = SessionManager(Path(_workspace))

provider = make_provider(config)
agent = AgentLoop.from_config(
    config, bus, provider=provider, tool_registry=tools, session_manager=session_manager,
)

# ---------------------------------------------------------------------------
# Guard components
# ---------------------------------------------------------------------------

provenance = ProvenanceStore()
taint = SessionTaint()
decision = GuardDecision()
confirm_grant = ConfirmGrant()

# ---------------------------------------------------------------------------
# Channel manager — build before event loop starts
# ---------------------------------------------------------------------------

channels = ChannelManager(
    config,
    bus,
    session_manager=session_manager,
)

# ---------------------------------------------------------------------------
# Telegram channel — resolve before building DecisionGate
# ---------------------------------------------------------------------------

telegram_ch = channels.get_channel("telegram")

if telegram_ch is None:
    print(
        "WARNING: Telegram channel not found in config. "
        "The confirm card will not be sent.",
        file=sys.stderr,
    )

# ---------------------------------------------------------------------------
# DecisionGate — owns all decision state
# ---------------------------------------------------------------------------

# When there is no Telegram channel, send_card and send_message are no-ops so
# await_decision times out and declines correctly.
if telegram_ch is not None:
    async def _send_card_to_telegram(event: HeldCallEvent) -> None:
        await send_hold_card(event, telegram_ch.send, _CHAT_ID, "telegram")

    async def _send_message_to_telegram(msg: Any) -> None:
        await telegram_ch.send(msg)

    gate = DecisionGate(
        confirm_grant=confirm_grant,
        send_card=_send_card_to_telegram,
        channel=telegram_ch,
        send_message=_send_message_to_telegram,
        chat_id=_CHAT_ID,
        channel_name="telegram",
    )
else:
    async def _noop_send_card(event: HeldCallEvent) -> None:  # type: ignore[misc]
        pass

    async def _noop_send_message(msg: Any) -> None:  # type: ignore[misc]
        pass

    class _NeverAllowed:
        def is_allowed(self, sender_id: str) -> bool:
            return False

    gate = DecisionGate(  # type: ignore[assignment]
        confirm_grant=confirm_grant,
        send_card=_noop_send_card,
        channel=_NeverAllowed(),
        send_message=_noop_send_message,
        chat_id=_CHAT_ID,
        channel_name="telegram",
    )


def on_held(event: HeldCallEvent) -> None:
    """Delegate to gate; log the hold."""
    hash8 = event.arguments_hash[:8]
    _log.info(
        "held tool=%s reason=%s untrusted_arg=%s hash8=%s",
        event.tool_name,
        event.reason,
        event.untrusted_arg_name,
        hash8,
    )
    gate.on_held(event)


# ---------------------------------------------------------------------------
# Wrap bus.publish_inbound for provenance recording and decision interception
# ---------------------------------------------------------------------------

_orig_publish_inbound = bus.publish_inbound


async def _provenance_publish_inbound(msg: InboundMessage) -> None:
    """Gate all inbound messages before provenance and agent.

    Logic order:
    1. Telegram is_callback messages are dropped silently (button taps must
       never reach the agent as a text turn).
    2. Telegram text messages are passed through gate.handle_inbound; if
       consumed (Allow/Decline/nudge), the message is not published.
    3. All other messages are recorded as provenance and published normally.
    """
    if msg.channel == "telegram":
        if msg.metadata.get("is_callback"):
            return  # drop silently — never reaches agent or provenance
        consumed = await gate.handle_inbound(msg.sender_id, msg.content)
        if consumed:
            return  # decision text / nudge — never reaches provenance or agent

    provenance.record_user_message(msg.content)
    await _orig_publish_inbound(msg)


bus.publish_inbound = _provenance_publish_inbound  # type: ignore[method-assign]

# ---------------------------------------------------------------------------
# Telegram callback wrapping — wrap _on_callback_query before channels start
# ---------------------------------------------------------------------------

if telegram_ch is not None:
    def _log_tap_and_wrap(original_wrapped: Any) -> Any:
        """Add a per-tap log line around the already-wrapped callback handler."""

        async def _outer(update: Any, context: Any) -> None:
            user = getattr(update, "effective_user", None)
            button_label: str = (
                getattr(getattr(update, "callback_query", None), "data", "") or ""
            )
            pending = gate._event

            if user is None:
                _log.info("tap button=%r outcome=no-user", button_label)
                await original_wrapped(update, context)
                return

            username = getattr(user, "username", None)
            sender_id = f"{user.id}|{username}" if username else str(user.id)

            if not telegram_ch.is_allowed(sender_id):
                _log.info("tap button=%r sender=%s outcome=disallowed-sender", button_label, sender_id)
                await original_wrapped(update, context)
                return

            if pending is None:
                _log.info("tap button=%r sender=%s outcome=nothing-pending", button_label, sender_id)
                await original_wrapped(update, context)
                return

            hash8 = pending.arguments_hash[:8]
            if button_label == f"Allow #{hash8}":
                _log.info(
                    "tap button=%r sender=%s hash8=%s outcome=allow-matched",
                    button_label, sender_id, hash8,
                )
            elif button_label == f"Decline #{hash8}":
                _log.info(
                    "tap button=%r sender=%s hash8=%s outcome=decline-matched",
                    button_label, sender_id, hash8,
                )
            else:
                _log.info(
                    "tap button=%r sender=%s hash8=%s outcome=wrong-hash",
                    button_label, sender_id, hash8,
                )
            await original_wrapped(update, context)

        return _outer

    _inner_wrapped = wrap_callback_query(
        telegram_ch._on_callback_query,
        confirm_grant,
        telegram_ch,
        get_pending=lambda: gate._event,
        clear_pending=gate.clear,
        resolve_decision=gate.resolve,
    )
    telegram_ch._on_callback_query = _log_tap_and_wrap(_inner_wrapped)  # type: ignore[method-assign]

# ---------------------------------------------------------------------------
# Async entry point
# ---------------------------------------------------------------------------


async def _run() -> None:
    """Connect MCP (with loopback fix), install Guard, run agent + channels."""
    _mcp_mod: Any = None
    _orig_transport_kwargs: Any = None
    try:
        # Apply the loopback transport fix: PinnedDNSAsyncTransport holds a
        # class-level asyncio.Lock during _receive_response_headers, which blocks
        # every subsequent MCP request for the 30 s httpx read timeout when the
        # server is on loopback.  Swap it out for a plain AsyncHTTPTransport for
        # the duration of the session, then restore it on aclose().
        if _mcp_urls_are_all_loopback(config):
            import httpx
            import nanobot.agent.tools.mcp as _mcp_mod  # type: ignore[import]
            _orig_transport_kwargs = _mcp_mod._pinned_transport_kwargs  # type: ignore[attr-defined]
            _mcp_mod._pinned_transport_kwargs = lambda: {"transport": httpx.AsyncHTTPTransport()}  # type: ignore[attr-defined]

        await mcp_provider.connect()

        install_guard(
            tools,
            surface_map,
            provenance,
            taint,
            decision,
            on_held,
            confirm_grant,
            guard_on=True,
            datamark_on=False,
            await_decision=gate.await_decision,
        )

        async def _run_agent() -> None:
            try:
                await agent.run()
            finally:
                await mcp_provider.aclose()
                if _mcp_mod is not None and _orig_transport_kwargs is not None:
                    _mcp_mod._pinned_transport_kwargs = _orig_transport_kwargs  # type: ignore[attr-defined]

        await asyncio.gather(
            _run_agent(),
            channels.start_all(),
        )
    finally:
        await channels.stop_all()
        agent.stop()
        shutil.rmtree(_workspace, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(_run())
