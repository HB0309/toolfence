"""Session taint tracker for Guard (GRD-5).

``SessionTaint`` tracks whether the current session has read any untrusted tool
result.  Once tainted, a session remains tainted until it ends — taint is never
cleared within a session (GRD-5).

A new ``SessionTaint`` instance always starts untainted.
"""

from __future__ import annotations


class SessionTaint:
    """Session-level taint flag.

    Create one instance per evaluation session (or per nanobot turn session).
    Call ``mark_tainted()`` the first time an untrusted result is observed.
    Call ``is_tainted()`` before every state-changing call to check current state.
    """

    def __init__(self) -> None:
        self._tainted: bool = False

    def mark_tainted(self) -> None:
        """Mark this session as tainted.

        Idempotent — calling multiple times has the same effect as calling once.
        Taint is never cleared once set (GRD-5).
        """
        self._tainted = True

    def is_tainted(self) -> bool:
        """Return ``True`` if this session has been tainted, ``False`` otherwise.

        A fresh session always returns ``False`` until ``mark_tainted()`` is called.
        """
        return self._tainted
