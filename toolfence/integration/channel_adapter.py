"""Telegram confirm-card adapter for GuardedProxy hold events (GRD-11).

Two public functions:

``send_hold_card(event, send_message, chat_id, channel_name)``
    Build and send a Telegram confirm card for a held tool call.
    Button labels carry a short hash suffix so a stale card's buttons
    cannot approve a different held call.

``wrap_callback_query(original_handler, confirm_grant, channel, get_pending, clear_pending)``
    Return a replacement ``_on_callback_query`` coroutine that calls
    ``confirm_grant.store_pending`` only when:
    - the tap is from an allowed sender (``channel.is_allowed``),
    - there is a currently-held event (``get_pending()`` is not None), and
    - the button label's ``#hash8`` suffix matches the held event's
      ``arguments_hash[:8]``.

    For a matching Decline tap the held call is cleared without storing a grant.
    The original handler is always called last so nanobot can ACK the callback.

Import boundary
---------------
This module belongs to ``toolfence/integration/`` and may import from
``toolfence/contracts/`` and ``toolfence/guard/``.  All ``nanobot`` imports are
deferred inside function bodies so the module is importable without nanobot on
``sys.path``.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from toolfence.contracts.guard import HeldCallEvent
from toolfence.guard.card import build_card_message
from toolfence.guard.confirm import ConfirmGrant


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


def wrap_callback_query(
    original_handler: Callable[..., Any],
    confirm_grant: ConfirmGrant,
    channel: Any,
    get_pending: Callable[[], HeldCallEvent | None],
    clear_pending: Callable[[], None],
) -> Callable[..., Any]:
    """Return a replacement ``_on_callback_query`` coroutine.

    The replacement guards ``confirm_grant.store_pending`` behind three checks:
    1. The sender is allowed (``channel.is_allowed``).
    2. There is a currently-held event (``get_pending()`` returns a
       ``HeldCallEvent``).
    3. The tapped button label matches ``f"Allow #{pending.arguments_hash[:8]}"``.

    A matching ``Decline #<hash8>`` tap clears the held call without storing a
    grant.  The original handler is called unconditionally last so nanobot can
    ACK the callback and clear the inline keyboard.

    Parameters
    ----------
    original_handler:
        The ``TelegramChannel._on_callback_query`` method being replaced.
    confirm_grant:
        The session's ``ConfirmGrant`` instance.
    channel:
        The ``TelegramChannel`` instance (used for ``is_allowed``).
    get_pending:
        Zero-argument callable; returns the current ``HeldCallEvent`` or None.
    clear_pending:
        Zero-argument callable; clears the pending-event cell.
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
            confirm_grant.store_pending(pending.tool_name, pending.arguments_hash)
            clear_pending()
        elif button_label == f"Decline #{hash8}":
            clear_pending()

        await original_handler(update, context)

    return _wrapped
