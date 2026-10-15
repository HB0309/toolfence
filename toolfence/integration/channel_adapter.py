"""Telegram confirm-card adapter for GuardedProxy hold events (GRD-11).

Public API
----------
``send_hold_card(event, send_message, chat_id, channel_name)``
    Build and send a Telegram confirm card for a held tool call.
    Button labels carry a short hash suffix so a stale card's buttons
    cannot approve a different held call.

``wrap_callback_query(original_handler, confirm_grant, channel, get_pending,
                      clear_pending, *, resolve_decision=None)``
    Return a replacement ``_on_callback_query`` coroutine that calls
    ``resolve_decision(True/False)`` when a matching Allow/Decline button is
    tapped. The original handler is always called last so nanobot can ACK
    the callback.

``DecisionGate``
    Owns all hold-decision state for one gateway session:
    - sends the confirm card exactly once per held hash
    - creates and awaits an ``asyncio.Future`` (120 s timeout)
    - intercepts typed Allow/Decline/nudge replies via ``handle_inbound``
    - handles button taps via ``resolve``
    - calls ``confirm_grant.store_pending`` (the only call site in
      ``toolfence/integration/``) before returning ``True`` from
      ``await_decision``

    ``launch_gateway.py`` constructs one ``DecisionGate`` and wires it into
    ``install_guard``; it contains no decision logic itself.

Import boundary
---------------
This module belongs to ``toolfence/integration/`` and may import from
``toolfence/contracts/`` and ``toolfence/guard/``.  All ``nanobot`` imports are
deferred inside function bodies so the module is importable without nanobot on
``sys.path``.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, Awaitable

from toolfence.contracts.guard import HeldCallEvent
from toolfence.guard.card import build_card_message
from toolfence.guard.confirm import ConfirmGrant

_NUDGE_TEXT = "Waiting for your answer: tap Allow or Decline on the card above."
_TIMEOUT_TEXT = "No answer in time, so I didn't do it."


# ---------------------------------------------------------------------------
# send_hold_card
# ---------------------------------------------------------------------------


async def send_hold_card(
    event: HeldCallEvent,
    send_message: Callable[..., Any],
    chat_id: str,
    channel_name: str,
) -> None:
    """Send a confirm card for *event* via *send_message*.

    Builds button labels of the form ``"Allow #<hash8>"`` /
    ``"Decline #<hash8>"`` where ``hash8`` is the first 8 characters of
    ``event.arguments_hash``.  This lets the callback wrapper reject button
    taps from cards that belong to an earlier held call.

    Parameters
    ----------
    event:
        The ``HeldCallEvent`` emitted by ``GuardedProxy``.
    send_message:
        Async callable that accepts a nanobot ``OutboundMessage``.
    chat_id:
        Telegram chat identifier to deliver the card to.
    channel_name:
        Nanobot channel name (``"telegram"``).
    """
    from nanobot.bus.events import OutboundMessage  # deferred — nanobot optional

    card_text, _ = build_card_message(event)
    hash8 = event.arguments_hash[:8]
    buttons = [[f"Allow #{hash8}", f"Decline #{hash8}"]]
    msg = OutboundMessage(
        channel=channel_name,
        chat_id=chat_id,
        content=card_text,
        buttons=buttons,
    )
    await send_message(msg)


# ---------------------------------------------------------------------------
# DecisionGate
# ---------------------------------------------------------------------------


class DecisionGate:
    """Owns all hold-decision state for one gateway session.

    Parameters
    ----------
    confirm_grant:
        The session's ``ConfirmGrant`` instance.  ``store_pending`` is called
        here — this is the only call site in ``toolfence/integration/``.
    send_card:
        Async callable ``(HeldCallEvent) -> None`` that sends the confirm card.
        Typically ``functools.partial(send_hold_card, send_message=...,
        chat_id=..., channel_name=...)``.
    channel:
        Channel object exposing ``is_allowed(sender_id: str) -> bool``.
    send_message:
        Async callable used for nudge and timeout messages.
    chat_id:
        Telegram chat ID for nudge/timeout messages.
    channel_name:
        Channel name for outbound messages (default ``"telegram"``).
    """

    def __init__(
        self,
        confirm_grant: ConfirmGrant,
        send_card: Callable[[HeldCallEvent], Awaitable[None]],
        channel: Any,
        send_message: Callable[..., Awaitable[None]],
        chat_id: str,
        channel_name: str = "telegram",
    ) -> None:
        self._confirm_grant = confirm_grant
        self._send_card = send_card
        self._channel = channel
        self._send_message = send_message
        self._chat_id = chat_id
        self._channel_name = channel_name

        self._event: HeldCallEvent | None = None
        self._future: asyncio.Future[bool] | None = None
        self._waiting: bool = False
        self._sent_hashes: set[str] = set()

    # ------------------------------------------------------------------
    # on_held — called synchronously by GuardedProxy
    # ------------------------------------------------------------------

    def on_held(self, event: HeldCallEvent) -> None:
        """Store the held event and schedule the confirm card.

        If a decision is already pending, returns immediately without
        creating a new future or sending a card.  The proxy's subsequent
        ``await_decision`` call will detect the hash mismatch and return
        ``False`` at once.
        """
        if self._event is not None:
            # A decision is already in flight — decline the new one via
            # hash-mismatch in await_decision.
            return

        self._event = event
        self._future = asyncio.get_running_loop().create_future()
        self._waiting = False
        self._sent_hashes.add(event.arguments_hash)
        asyncio.get_running_loop().create_task(
            self._send_card(event),
            name="toolfence-hold-card",
        )

    # ------------------------------------------------------------------
    # await_decision — awaited by GuardedProxy
    # ------------------------------------------------------------------

    async def await_decision(self, event: HeldCallEvent) -> bool:
        """Await the user's decision for *event*.

        Returns ``True`` if the user approved (and stores the grant),
        ``False`` if the user declined, timed out, or a guard condition
        was not met.

        Only one waiter per decision is allowed.  A second concurrent call
        for the same hash returns ``False`` immediately.
        """
        # Hash mismatch — either idle or a different call is pending.
        if self._event is None or event.arguments_hash != self._event.arguments_hash:
            return False

        # Duplicate waiter guard.
        if self._waiting:
            return False

        self._waiting = True
        try:
            result: bool = await asyncio.wait_for(
                asyncio.shield(self._future),  # type: ignore[arg-type]
                timeout=120,
            )
        except asyncio.TimeoutError:
            self.clear()
            asyncio.get_running_loop().create_task(
                self._send_timeout_message(),
                name="toolfence-timeout-msg",
            )
            return False
        except asyncio.CancelledError:
            self.clear()
            raise
        finally:
            self._waiting = False

        if result:
            self._confirm_grant.store_pending(
                event.tool_name, event.arguments_hash
            )
        return result

    async def _send_timeout_message(self) -> None:
        from nanobot.bus.events import OutboundMessage  # deferred

        msg = OutboundMessage(
            channel=self._channel_name,
            chat_id=self._chat_id,
            content=_TIMEOUT_TEXT,
        )
        await self._send_message(msg)

    # ------------------------------------------------------------------
    # handle_inbound — called by launch_gateway's publish_inbound wrapper
    # ------------------------------------------------------------------

    async def handle_inbound(self, sender_id: str, text: str) -> bool:
        """Attempt to consume an inbound message as a decision reply.

        While a decision is pending, any text from the allowed user is
        consumed and answered with a nudge — decisions must come via the
        inline keyboard buttons on the card.

        Returns ``True`` if the message was consumed (caller must not
        publish it to the agent or record it as provenance).  Returns
        ``False`` if there is no pending decision or the sender is not
        allowed.
        """
        if self._event is None:
            return False
        if not self._channel.is_allowed(sender_id):
            return False

        # Any text while a decision is pending — send nudge; never resolve.
        asyncio.get_running_loop().create_task(
            self._send_nudge(),
            name="toolfence-nudge",
        )
        return True

    async def _send_nudge(self) -> None:
        from nanobot.bus.events import OutboundMessage  # deferred

        msg = OutboundMessage(
            channel=self._channel_name,
            chat_id=self._chat_id,
            content=_NUDGE_TEXT,
        )
        await self._send_message(msg)

    # ------------------------------------------------------------------
    # resolve / clear
    # ------------------------------------------------------------------

    def resolve(self, approved: bool) -> None:
        """Resolve the pending future with *approved* and clear state."""
        if self._future is not None and not self._future.done():
            self._future.set_result(approved)
        self.clear()

    def clear(self) -> None:
        """Cancel the pending future (if unresolved) and reset all state."""
        if self._future is not None and not self._future.done():
            self._future.cancel()
        if self._event is not None:
            self._sent_hashes.discard(self._event.arguments_hash)
        self._event = None
        self._future = None
        self._waiting = False


# ---------------------------------------------------------------------------
# wrap_callback_query
# ---------------------------------------------------------------------------


def wrap_callback_query(
    original_handler: Callable[..., Any],
    confirm_grant: ConfirmGrant,
    channel: Any,
    get_pending: Callable[[], HeldCallEvent | None],
    clear_pending: Callable[[], None],
    *,
    resolve_decision: Callable[[bool], None] | None = None,
) -> Callable[..., Any]:
    """Return a replacement ``_on_callback_query`` coroutine.

    The replacement handles Allow/Decline button taps:
    - Checks sender is allowed (``channel.is_allowed``).
    - Checks there is a currently-held event (``get_pending()``).
    - Checks the button label's ``#hash8`` suffix matches the held event.

    On a matching Allow tap: calls ``resolve_decision(True)`` if provided,
    then ``clear_pending()``.
    On a matching Decline tap: calls ``resolve_decision(False)`` if provided,
    then ``clear_pending()``.

    The original handler is called unconditionally last so nanobot can ACK
    the callback and clear the inline keyboard.

    Parameters
    ----------
    original_handler:
        The ``TelegramChannel._on_callback_query`` method being replaced.
    confirm_grant:
        The session's ``ConfirmGrant`` instance (kept for API compatibility;
        ``store_pending`` is now called by ``DecisionGate.await_decision``).
    channel:
        The ``TelegramChannel`` instance (used for ``is_allowed``).
    get_pending:
        Zero-argument callable; returns the current ``HeldCallEvent`` or None.
        When wired to a ``DecisionGate``, pass ``lambda: gate._event``.
    clear_pending:
        Zero-argument callable; clears the pending-event cell.
        When wired to a ``DecisionGate``, pass ``gate.clear``.
    resolve_decision:
        Optional zero-argument callable ``(bool) -> None``; called with
        ``True`` on Allow and ``False`` on Decline before ``clear_pending``.
        When wired to a ``DecisionGate``, pass ``gate.resolve``.
    """

    async def _wrapped(update: Any, context: Any) -> None:
        user = getattr(update, "effective_user", None)
        if user is None:
            await original_handler(update, context)
            return

        # Build sender_id the same way TelegramChannel._sender_id does:
        # "id|username" when username is present, else "id".
        username = getattr(user, "username", None)
        sender_id = f"{user.id}|{username}" if username else str(user.id)

        button_label = getattr(
            getattr(update, "callback_query", None), "data", ""
        ) or ""

        if not channel.is_allowed(sender_id):
            await original_handler(update, context)
            return

        pending = get_pending()
        if pending is None:
            await original_handler(update, context)
            return

        hash8 = pending.arguments_hash[:8]

        if button_label == f"Allow #{hash8}":
            if resolve_decision is not None:
                resolve_decision(True)
            clear_pending()
        elif button_label == f"Decline #{hash8}":
            if resolve_decision is not None:
                resolve_decision(False)
            clear_pending()

        await original_handler(update, context)

    return _wrapped
