"""B-4b integration tests — channel_adapter.py (no nanobot required).

Test inventory
--------------
  test_send_hold_card_correct_buttons             -- buttons carry #hash8 suffix
  test_wrap_callback_allow_matching_hash_stores_grant
                                                  -- correct hash + allowed → store_pending
  test_wrap_callback_wrong_hash_stores_nothing    -- stale card hash → no grant
  test_wrap_callback_decline_clears_pending       -- Decline clears pending; no grant
  test_wrap_callback_no_pending_event_stores_nothing
                                                  -- nothing held → no grant
  test_wrap_callback_disallowed_sender_stores_nothing
                                                  -- disallowed sender → no grant
  test_store_pending_called_from_only_one_place   -- single call site in integration/
  test_import_check_channel_adapter               -- no module-level nanobot import

  test_on_held_first_call_sends_card              -- first event → card sent, hash added to set
  test_on_held_duplicate_hash_skips_card          -- same hash again → no card, returns early
  test_on_held_different_hash_sends_card          -- different hash → card sent even if set non-empty
  test_on_held_clear_removes_hash_from_set        -- _clear_pending removes hash; same hash fires again
"""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from toolfence.contracts.guard import HeldCallEvent
from toolfence.guard.confirm import ConfirmGrant
from toolfence.integration.channel_adapter import send_hold_card, wrap_callback_query

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _make_event(
    tool_name: str = "mcp_book_flight",
    args_hash: str = "a3f9c112deadbeef",
) -> HeldCallEvent:
    """Return a minimal HeldCallEvent with known tool_name and arguments_hash."""
    return HeldCallEvent(
        tool_name=tool_name,
        arguments={"dest": "Paris"},
        arguments_hash=args_hash,
        reason="irreversible",
        untrusted_read_count=0,
        untrusted_arg_name=None,
    )


def _make_update(label: str, user_id: int = 42, username: str = "alice") -> SimpleNamespace:
    """Return a minimal fake Telegram Update with callback_query.data = label."""
    return SimpleNamespace(
        callback_query=SimpleNamespace(data=label),
        effective_user=SimpleNamespace(id=user_id, username=username),
    )


# ---------------------------------------------------------------------------
# Fake nanobot.bus.events module so send_hold_card runs without nanobot
# ---------------------------------------------------------------------------


class _FakeOutboundMessage:
    """Minimal stand-in for nanobot.bus.events.OutboundMessage."""

    def __init__(
        self,
        *,
        channel: str,
        chat_id: str,
        content: str,
        buttons: list[list[str]] | None = None,
        **_kw: object,
    ) -> None:
        self.channel = channel
        self.chat_id = chat_id
        self.content = content
        self.buttons = buttons or []


@pytest.fixture(autouse=True)
def _fake_nanobot_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject a minimal fake nanobot.bus.events into sys.modules."""
    if "nanobot.bus.events" not in sys.modules:
        fake_events = types.ModuleType("nanobot.bus.events")
        fake_events.OutboundMessage = _FakeOutboundMessage  # type: ignore[attr-defined]

        for mod_name in ("nanobot", "nanobot.bus"):
            if mod_name not in sys.modules:
                monkeypatch.setitem(sys.modules, mod_name, types.ModuleType(mod_name))

        monkeypatch.setitem(sys.modules, "nanobot.bus.events", fake_events)


# ---------------------------------------------------------------------------
# send_hold_card
# ---------------------------------------------------------------------------


def test_send_hold_card_correct_buttons() -> None:
    """send_hold_card must produce buttons [['Allow #<hash8>', 'Decline #<hash8>']]."""
    event = _make_event(args_hash="a3f9c112deadbeef")
    hash8 = "a3f9c112"

    send_message = AsyncMock()

    _run(send_hold_card(event, send_message, chat_id="123", channel_name="telegram"))

    send_message.assert_awaited_once()
    msg = send_message.call_args[0][0]
    assert msg.buttons == [[f"Allow #{hash8}", f"Decline #{hash8}"]], (
        f"Expected hashed buttons, got: {msg.buttons}"
    )
    assert msg.channel == "telegram"
    assert msg.chat_id == "123"
    assert msg.content  # non-empty card text


# ---------------------------------------------------------------------------
# wrap_callback_query helpers
# ---------------------------------------------------------------------------


def _make_wrapper_parts(
    event: HeldCallEvent | None = None,
) -> tuple[AsyncMock, ConfirmGrant, MagicMock, list[HeldCallEvent | None]]:
    original_handler = AsyncMock()
    cg = ConfirmGrant()
    channel = MagicMock()
    channel.is_allowed.return_value = True
    pending: list[HeldCallEvent | None] = [event]
    return original_handler, cg, channel, pending


# ---------------------------------------------------------------------------
# wrap_callback_query tests
# ---------------------------------------------------------------------------


def test_wrap_callback_allow_matching_hash_stores_grant() -> None:
    """Allow tap with correct #hash8 → store_pending called, pending cleared, original called."""
    event = _make_event(args_hash="a3f9c112deadbeef")
    original, cg, channel, pending = _make_wrapper_parts(event=event)
    wrapper = wrap_callback_query(
        original, cg, channel,
        get_pending=lambda: pending[0],
        clear_pending=lambda: pending.__setitem__(0, None),
    )

    _run(wrapper(_make_update("Allow #a3f9c112"), None))

    assert cg._pending_tool == event.tool_name
    assert cg._pending_hash == event.arguments_hash
    assert pending[0] is None, "pending cell must be cleared after Allow"
    original.assert_awaited_once()


def test_wrap_callback_wrong_hash_stores_nothing() -> None:
    """Allow tap with wrong #hash8 (stale card) → store_pending not called, pending unchanged."""
    event = _make_event(args_hash="a3f9c112deadbeef")
    original, cg, channel, pending = _make_wrapper_parts(event=event)
    wrapper = wrap_callback_query(
        original, cg, channel,
        get_pending=lambda: pending[0],
        clear_pending=lambda: pending.__setitem__(0, None),
    )

    _run(wrapper(_make_update("Allow #00000000"), None))  # different hash

    assert cg._pending_tool is None, "store_pending must not be called for wrong hash"
    assert pending[0] is event, "pending cell must not be cleared for wrong hash"
    original.assert_awaited_once()


def test_wrap_callback_decline_clears_pending() -> None:
    """Decline tap with matching #hash8 → pending cleared, store_pending not called, original called."""
    event = _make_event(args_hash="a3f9c112deadbeef")
    original, cg, channel, pending = _make_wrapper_parts(event=event)
    wrapper = wrap_callback_query(
        original, cg, channel,
        get_pending=lambda: pending[0],
        clear_pending=lambda: pending.__setitem__(0, None),
    )

    _run(wrapper(_make_update("Decline #a3f9c112"), None))

    assert cg._pending_tool is None, "store_pending must not be called on Decline"
    assert pending[0] is None, "pending cell must be cleared on Decline"
    original.assert_awaited_once()


def test_wrap_callback_no_pending_event_stores_nothing() -> None:
    """Allow tap but nothing held → store_pending not called, original called."""
    original, cg, channel, pending = _make_wrapper_parts(event=None)
    wrapper = wrap_callback_query(
        original, cg, channel,
        get_pending=lambda: pending[0],
        clear_pending=lambda: pending.__setitem__(0, None),
    )

    _run(wrapper(_make_update("Allow #a3f9c112"), None))

    assert cg._pending_tool is None
    original.assert_awaited_once()


def test_wrap_callback_disallowed_sender_stores_nothing() -> None:
    """Disallowed sender → store_pending not called, original called."""
    event = _make_event(args_hash="a3f9c112deadbeef")
    original, cg, channel, pending = _make_wrapper_parts(event=event)
    channel.is_allowed.return_value = False
    wrapper = wrap_callback_query(
        original, cg, channel,
        get_pending=lambda: pending[0],
        clear_pending=lambda: pending.__setitem__(0, None),
    )

    _run(wrapper(_make_update("Allow #a3f9c112"), None))

    assert cg._pending_tool is None, "store_pending must not be called for disallowed sender"
    original.assert_awaited_once()


# ---------------------------------------------------------------------------
# Source-level checks
# ---------------------------------------------------------------------------


def test_store_pending_called_from_only_one_place() -> None:
    """Exactly one call site of .store_pending( must exist in toolfence/integration/."""
    integration_dir = Path(__file__).parent.parent / "toolfence" / "integration"
    call_sites: list[tuple[str, int, str]] = []
    for py_file in sorted(integration_dir.glob("*.py")):
        for lineno, line in enumerate(
            py_file.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if ".store_pending(" in line:
                call_sites.append((py_file.name, lineno, line.strip()))

    assert len(call_sites) == 1, (
        f"Expected exactly 1 call site of .store_pending( in toolfence/integration/, "
        f"found {len(call_sites)}: {call_sites}"
    )
    assert call_sites[0][0] == "channel_adapter.py", (
        f"The single store_pending call must be in channel_adapter.py, "
        f"found it in {call_sites[0][0]}"
    )


def test_import_check_channel_adapter() -> None:
    """channel_adapter.py must have no module-level nanobot import."""
    src_path = (
        Path(__file__).parent.parent / "toolfence" / "integration" / "channel_adapter.py"
    )
    for lineno, line in enumerate(src_path.read_text(encoding="utf-8").splitlines(), start=1):
        assert not line.startswith("import nanobot"), (
            f"channel_adapter.py line {lineno}: module-level 'import nanobot' is forbidden "
            f"(nanobot imports must be deferred inside function bodies)"
        )
        assert not line.startswith("from nanobot"), (
            f"channel_adapter.py line {lineno}: module-level 'from nanobot' is forbidden "
            f"(nanobot imports must be deferred inside function bodies)"
        )


# ---------------------------------------------------------------------------
# on_held duplicate-skip logic (launch_gateway.py pattern)
#
# We test the duplicate-skip state machine in isolation — no nanobot required.
# The helper below replicates the exact state and logic from launch_gateway.py
# so we can unit-test it without importing that module (which has side effects
# and requires nanobot + env-vars at import time).
# ---------------------------------------------------------------------------


def _make_on_held_parts() -> tuple[
    "list[HeldCallEvent | None]",
    "set[str]",
    "list[int]",
    "Any",
    "Any",
]:
    """Return (pending_cell, pending_hashes, card_send_count, on_held, clear_pending).

    ``on_held`` mirrors the Telegram branch of launch_gateway.py exactly.
    ``card_send_count[0]`` increments instead of scheduling a real asyncio task.
    """
    pending: list[HeldCallEvent | None] = [None]
    pending_hashes: set[str] = set()
    card_send_count: list[int] = [0]

    def on_held(event: HeldCallEvent) -> None:
        if event.arguments_hash in pending_hashes:
            return  # duplicate — skip card
        pending[0] = event
        pending_hashes.add(event.arguments_hash)
        card_send_count[0] += 1  # stand-in for asyncio task

    def clear_pending() -> None:
        ev = pending[0]
        if ev is not None:
            pending_hashes.discard(ev.arguments_hash)
        pending[0] = None

    return pending, pending_hashes, card_send_count, on_held, clear_pending


def test_on_held_first_call_sends_card() -> None:
    """First on_held call with a new hash → card sent, hash tracked in set."""
    _, hashes, count, on_held, _ = _make_on_held_parts()
    event = _make_event(args_hash="a3f9c112deadbeef")

    on_held(event)

    assert count[0] == 1, "card must be sent on first call"
    assert "a3f9c112deadbeef" in hashes


def test_on_held_duplicate_hash_skips_card() -> None:
    """Second on_held with the same hash → no additional card sent."""
    _, _, count, on_held, _ = _make_on_held_parts()
    event = _make_event(args_hash="a3f9c112deadbeef")

    on_held(event)
    on_held(event)  # duplicate

    assert count[0] == 1, "card must be sent exactly once for a duplicate hash"


def test_on_held_different_hash_sends_card() -> None:
    """Two on_held calls with different hashes → two cards sent."""
    _, _, count, on_held, _ = _make_on_held_parts()
    event_a = _make_event(tool_name="tool_a", args_hash="aaaaaaaabbbbbbbb")
    event_b = _make_event(tool_name="tool_b", args_hash="ccccccccdddddddd")

    on_held(event_a)
    on_held(event_b)

    assert count[0] == 2, "each distinct hash must produce one card"


def test_on_held_clear_removes_hash_from_set() -> None:
    """After clear_pending, the same hash fires a card again (not a duplicate)."""
    pending, hashes, count, on_held, clear_pending = _make_on_held_parts()
    event = _make_event(args_hash="a3f9c112deadbeef")

    on_held(event)          # card 1 sent
    clear_pending()         # user tapped — slot freed
    on_held(event)          # same hash, but cleared → card 2 sent

    assert count[0] == 2, "after clear, the same hash must be allowed to send another card"
    assert "a3f9c112deadbeef" in hashes, "hash must be back in set after second on_held"
    assert pending[0] is event
