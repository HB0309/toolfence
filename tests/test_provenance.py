"""Tests for ProvenanceStore.record_user_message punctuation stripping.

Test inventory
--------------
  test_email_in_brackets_with_trailing_period
  test_filename_at_end_of_sentence
"""

from __future__ import annotations

from toolfence.guard.provenance import ProvenanceStore


def test_email_in_brackets_with_trailing_period() -> None:
    """Email in parentheses with trailing period should resolve as 'user'.

    Message: "I'm Alice (alice@example.com)."
    The token "(alice@example.com)." must be stored with punctuation stripped
    so that resolve_argument("alice@example.com") returns "user".
    """
    store = ProvenanceStore()
    store.record_user_message("I'm Alice (alice@example.com).")
    assert store.resolve_argument("alice@example.com") == "user"


def test_filename_at_end_of_sentence() -> None:
    """Filename at the end of a sentence (with trailing period) resolves as 'user'.

    Message: "Please summarise report.txt."
    The token "report.txt." must be stored with the trailing period stripped
    so that resolve_argument("report.txt") returns "user".
    """
    store = ProvenanceStore()
    store.record_user_message("Please summarise report.txt.")
    assert store.resolve_argument("report.txt") == "user"
