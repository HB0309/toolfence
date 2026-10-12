# Cross-track handoff note (C-3):
# GuardedProxy.execute extracts the source kwarg using the key "__source__"
# (double-underscore prefix) from **params to avoid colliding with any real
# tool parameter that might legitimately be named "source".
#
#   source = params.pop("__source__", "first-party")
#
# Track B's launcher must pass  __source__="user"  in the kwargs dict when
# the call is triggered by a native button-click callback, e.g.:
#
#   await proxy.execute(**tool_args, __source__="user")
#
# Any other invocation (tool-driven retry, programmatic call) must NOT pass
# __source__ at all (or pass __source__="first-party"), so consume_grant
# rejects it.  ConfirmGrant has zero knowledge of button-label strings.

"""ConfirmGrant — stores and validates user-approved retry grants (GRD-9).

A held call can be retried when the user clicks Allow.  ``ConfirmGrant``
stores one pending grant per session (tool_name + arguments_hash) and
validates that the retry originates from a direct button-click user action.

Design principles
-----------------
- No knowledge of button labels — no label-string matching of any kind.
- No nanobot imports.
- ``consume_grant`` rejects any grant whose ``source`` is not ``"user"``.
- One stored grant at a time; ``store_pending`` replaces any prior grant.
"""

from __future__ import annotations


class ConfirmGrant:
    """Stores and validates a pending user-approval grant.

    The grant lifecycle is:
    1. ``store_pending(tool_name, args_hash)`` — called by Track B's launcher
       when the native button-click callback fires (e.g. Telegram
       ``_on_callback_query``).  Only one pending grant is held at a time;
       calling ``store_pending`` again replaces the previous one.
    2. ``consume_grant(tool_name, args_hash, source)`` — called by
       ``GuardedProxy.execute`` at the top of every execute attempt.
       Returns ``True`` (and clears the grant) only when *all* three
       conditions are met:
         - ``source == "user"``
         - stored ``tool_name`` matches the argument
         - stored ``args_hash`` matches the argument
       Returns ``False`` without clearing on any mismatch or wrong source.
    """

    def __init__(self) -> None:
        self._pending_tool: str | None = None
        self._pending_hash: str | None = None

    def store_pending(self, tool_name: str, args_hash: str) -> None:
        """Store a pending grant for *tool_name* / *args_hash*.

        Replaces any previously stored pending grant.
        """
        self._pending_tool = tool_name
        self._pending_hash = args_hash

    def consume_grant(self, tool_name: str, args_hash: str, source: str) -> bool:
        """Attempt to consume a matching grant.

        Returns ``True`` and clears the stored grant if and only if:
        - ``source == "user"``
        - the stored ``tool_name`` matches *tool_name*
        - the stored ``args_hash`` matches *args_hash*

        Returns ``False`` without side-effects on any mismatch or
        non-user source.
        """
        if source != "user":
            return False
        if self._pending_tool != tool_name or self._pending_hash != args_hash:
            return False
        # Successful match — clear the grant and return True.
        self._pending_tool = None
        self._pending_hash = None
        return True
