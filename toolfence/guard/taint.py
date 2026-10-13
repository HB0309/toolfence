"""Session taint tracker for Guard (GRD-5).

``SessionTaint`` tracks whether the current session has read any untrusted tool
result.  Once tainted, a session remains tainted until it ends — taint is never
cleared within a session (GRD-5).

It also maintains a session-wide count of untrusted reads so that
``HeldCallEvent.untrusted_read_count`` reflects the true number of untrusted
reads across *all* proxies sharing this ``SessionTaint`` instance.

A new ``SessionTaint`` instance always starts untainted with a count of zero.
"""

from __future__ import annotations


class SessionTaint:
    """Session-level taint flag and untrusted-read counter.

    Create one instance per evaluation session (or per nanobot turn session).
    Share it across all ``GuardedProxy`` instances for that session so the
    counter is accurate regardless of which proxy reads untrusted data.

    Call ``mark_tainted()`` the first time an untrusted result is observed.
    Call ``increment_untrusted_reads()`` every time an untrusted result is read.
    Call ``is_tainted()`` before every state-changing call to check current state.
    """

    def __init__(self) -> None:
        self._tainted: bool = False
        self._untrusted_read_count: int = 0

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

    def increment_untrusted_reads(self) -> None:
        """Increment the session-wide count of untrusted tool results read."""
        self._untrusted_read_count += 1

    @property
    def untrusted_read_count(self) -> int:
        """Number of untrusted tool results read in this session."""
        return self._untrusted_read_count
