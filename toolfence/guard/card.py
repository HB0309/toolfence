"""Card message builder for Guard hold notifications (GRD-11).

``build_card_message`` converts a ``HeldCallEvent`` into a human-readable
hold-reason string and the standard ``[["Allow", "Decline"]]`` button list.

Three reason templates
-----------------------
- ``"irreversible"``       → ``"This action is irreversible. Allow or Decline?"``
- ``"tainted_session"``    → ``"This came after reading {N} untrusted result(s). Allow or Decline?"``
- ``"untrusted_argument"`` → ``"The value of '{arg}' came from an untrusted source. Allow or Decline?"``

This module has zero nanobot imports and zero ``toolfence.engine`` imports.
"""

from __future__ import annotations

import logging

from toolfence.contracts.guard import HeldCallEvent

log = logging.getLogger(__name__)

# Standard confirm buttons — always the same regardless of reason.
_BUTTONS: list[list[str]] = [["Allow", "Decline"]]


def build_card_message(event: HeldCallEvent) -> tuple[str, list[list[str]]]:
    """Build the hold-card text and button layout for *event*.

    Parameters
    ----------
    event:
        The ``HeldCallEvent`` emitted by ``GuardedProxy`` when a tool call is
        held for user confirmation.

    Returns
    -------
    tuple[str, list[list[str]]]
        A ``(text, buttons)`` pair where *text* is the human-readable hold
        reason and *buttons* is always ``[["Allow", "Decline"]]``.

    Raises
    ------
    ValueError
        If ``event.reason`` is not one of the three known reason strings.
    """
    reason = event.reason
    log.info("build_card_message: tool=%r reason=%r", event.tool_name, reason)

    if reason == "irreversible":
        text = "This action is irreversible. Allow or Decline?"

    elif reason == "tainted_session":
        n = event.untrusted_read_count
        text = f"This came after reading {n} untrusted result(s). Allow or Decline?"

    elif reason == "untrusted_argument":
        arg = event.untrusted_arg_name or ""
        text = f"The value of '{arg}' came from an untrusted source. Allow or Decline?"

    else:
        log.error("build_card_message: unknown reason %r for tool %r", reason, event.tool_name)
        raise ValueError(f"Unknown HeldCallEvent reason: {reason!r}")

    log.debug("build_card_message: card text=%r", text)
    return text, _BUTTONS
