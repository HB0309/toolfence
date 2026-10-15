"""B-4b integration tests — channel_adapter.py (no nanobot required).

Test inventory
--------------
  test_send_hold_card_correct_buttons             -- buttons carry #hash8 suffix
  test_wrap_callback_allow_matching_hash_stores_grant
                                                  -- correct hash + allowed → resolve_decision(True)
  test_wrap_callback_wrong_hash_stores_nothing    -- stale card hash → no resolution
  test_wrap_callback_decline_clears_pending       -- Decline → resolve_decision(False)
  test_wrap_callback_no_pending_event_stores_nothing
                                                  -- nothing held → no resolution
  test_wrap_callback_disallowed_sender_stores_nothing
                                                  -- disallowed sender → no resolution
  test_store_pending_called_from_only_one_place   -- single call site in integration/
  test_import_check_channel_adapter               -- no module-level nanobot import

  test_gate_on_held_sends_card_once               -- first event → card task scheduled
  test_gate_await_decision_allow                  -- "Allow" → True, store_pending called
  test_gate_await_decision_decline                -- "Decline" → False, store_pending not called
  test_gate_await_decision_numeric                -- "1" → True; "2" → False
  test_gate_await_decision_timeout                -- timeout → False + timeout message sent
  test_gate_nudge_on_unknown_text                 -- unknown text → nudge sent; future still waiting
  test_gate_second_call_declined_immediately      -- second on_held while pending → await_decision False
  test_gate_duplicate_waiter_declined             -- second concurrent await_decision → False immediately
  test_gate_non_allowed_sender_passes_through     -- disallowed sender → handle_inbound False
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
from toolfence.integration.channel_adapter import (
    DecisionGate,
    send_hold_card,
    wrap_callback_query,
)

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
# Fake nanobot.bus.events module so send_hold_card / DecisionGate run without nanobot
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
    """Allow tap with correct #hash8 → resolve_decision(True) called; pending cleared; original called."""
    event = _make_event(args_hash="a3f9c112deadbeef")
    original, cg, channel, pending = _make_wrapper_parts(event=event)
    resolve_spy: list[bool | None] = []
    wrapper = wrap_callback_query(
        original, cg, channel,
        get_pending=lambda: pending[0],
        clear_pending=lambda: pending.__setitem__(0, None),
        resolve_decision=lambda approved: resolve_spy.append(approved),
    )

    _run(wrapper(_make_update("Allow #a3f9c112"), None))

    assert resolve_spy == [True], f"resolve_decision must be called with True, got {resolve_spy}"
    assert cg._pending_tool is None, "store_pending must not be called directly by wrap_callback_query"
    assert pending[0] is None, "pending cell must be cleared after Allow"
    original.assert_awaited_once()


def test_wrap_callback_wrong_hash_stores_nothing() -> None:
    """Allow tap with wrong #hash8 (stale card) → resolve_decision not called; pending unchanged."""
    event = _make_event(args_hash="a3f9c112deadbeef")
    original, cg, channel, pending = _make_wrapper_parts(event=event)
    resolve_spy: list[bool | None] = []
    wrapper = wrap_callback_query(
        original, cg, channel,
        get_pending=lambda: pending[0],
        clear_pending=lambda: pending.__setitem__(0, None),
        resolve_decision=lambda approved: resolve_spy.append(approved),
    )

    _run(wrapper(_make_update("Allow #00000000"), None))  # different hash

    assert resolve_spy == [], "resolve_decision must not be called for wrong hash"
    assert pending[0] is event, "pending cell must not be cleared for wrong hash"
    original.assert_awaited_once()


def test_wrap_callback_decline_clears_pending() -> None:
    """Decline tap with matching #hash8 → resolve_decision(False) called; pending cleared; original called."""
    event = _make_event(args_hash="a3f9c112deadbeef")
    original, cg, channel, pending = _make_wrapper_parts(event=event)
    resolve_spy: list[bool | None] = []
    wrapper = wrap_callback_query(
        original, cg, channel,
        get_pending=lambda: pending[0],
        clear_pending=lambda: pending.__setitem__(0, None),
        resolve_decision=lambda approved: resolve_spy.append(approved),
    )

    _run(wrapper(_make_update("Decline #a3f9c112"), None))

    assert resolve_spy == [False], f"resolve_decision must be called with False, got {resolve_spy}"
    assert pending[0] is None, "pending cell must be cleared on Decline"
    original.assert_awaited_once()


def test_wrap_callback_no_pending_event_stores_nothing() -> None:
    """Allow tap but nothing held → resolve_decision not called; original called."""
    original, cg, channel, pending = _make_wrapper_parts(event=None)
    resolve_spy: list[bool | None] = []
    wrapper = wrap_callback_query(
        original, cg, channel,
        get_pending=lambda: pending[0],
        clear_pending=lambda: pending.__setitem__(0, None),
        resolve_decision=lambda approved: resolve_spy.append(approved),
    )

    _run(wrapper(_make_update("Allow #a3f9c112"), None))

    assert resolve_spy == []
    original.assert_awaited_once()


def test_wrap_callback_disallowed_sender_stores_nothing() -> None:
    """Disallowed sender → resolve_decision not called; original called."""
    event = _make_event(args_hash="a3f9c112deadbeef")
    original, cg, channel, pending = _make_wrapper_parts(event=event)
    channel.is_allowed.return_value = False
    resolve_spy: list[bool | None] = []
    wrapper = wrap_callback_query(
        original, cg, channel,
        get_pending=lambda: pending[0],
        clear_pending=lambda: pending.__setitem__(0, None),
        resolve_decision=lambda approved: resolve_spy.append(approved),
    )

    _run(wrapper(_make_update("Allow #a3f9c112"), None))

    assert resolve_spy == [], "resolve_decision must not be called for disallowed sender"
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
# DecisionGate helper
# ---------------------------------------------------------------------------


def _make_gate(
    allowed: bool = True,
) -> tuple[DecisionGate, list[int], AsyncMock]:
    """Build a DecisionGate with fake send_card / send_message for testing.

    Returns (gate, card_count, send_message_spy).
    ``card_count[0]`` increments each time send_card is called.
    """
    card_count: list[int] = [0]

    async def _fake_send_card(event: HeldCallEvent) -> None:
        card_count[0] += 1

    send_message_spy = AsyncMock()

    channel = MagicMock()
    channel.is_allowed.return_value = allowed

    gate = DecisionGate(
        confirm_grant=ConfirmGrant(),
        send_card=_fake_send_card,
        channel=channel,
        send_message=send_message_spy,
        chat_id="test-chat",
        channel_name="telegram",
    )
    return gate, card_count, send_message_spy


# ---------------------------------------------------------------------------
# DecisionGate tests
# ---------------------------------------------------------------------------


def test_gate_on_held_sends_card_once() -> None:
    """First on_held → card task scheduled; second on_held while pending → not scheduled again."""

    async def _run_test() -> None:
        gate, card_count, _ = _make_gate()
        event = _make_event(args_hash="a3f9c112deadbeef")

        gate.on_held(event)
        await asyncio.sleep(0)  # let the card task run
        assert card_count[0] == 1, "card must be sent on first on_held"

        gate.on_held(event)  # second call while pending
        await asyncio.sleep(0)
        assert card_count[0] == 1, "card must not be sent again while a decision is pending"

    _run(_run_test())


def test_gate_await_decision_allow() -> None:
    """resolve(True) via button tap → await_decision returns True; store_pending called."""

    async def _run_test() -> bool:
        gate, _, _ = _make_gate()
        event = _make_event(args_hash="a3f9c112deadbeef")

        gate.on_held(event)
        await asyncio.sleep(0)

        # Simulate a button tap resolving True (buttons-only path).
        async def _approve() -> None:
            await asyncio.sleep(0)
            gate.resolve(True)

        result, _ = await asyncio.gather(
            gate.await_decision(event),
            _approve(),
        )
        return result

    result = _run(_run_test())
    assert result is True, f"await_decision must return True on resolve(True), got {result!r}"


def test_gate_await_decision_allow_stores_grant() -> None:
    """After approve via button, confirm_grant.store_pending is populated."""

    async def _run_test() -> ConfirmGrant:
        gate, _, _ = _make_gate()
        event = _make_event(args_hash="a3f9c112deadbeef")
        gate.on_held(event)
        await asyncio.sleep(0)

        async def _approve() -> None:
            await asyncio.sleep(0)
            gate.resolve(True)

        await asyncio.gather(gate.await_decision(event), _approve())
        return gate._confirm_grant

    cg = _run(_run_test())
    assert cg._pending_tool == "mcp_book_flight"
    assert cg._pending_hash == "a3f9c112deadbeef"


def test_gate_await_decision_decline() -> None:
    """resolve(False) via button tap → await_decision returns False; store_pending not called."""

    async def _run_test() -> tuple[bool, ConfirmGrant]:
        gate, _, _ = _make_gate()
        event = _make_event(args_hash="a3f9c112deadbeef")
        gate.on_held(event)
        await asyncio.sleep(0)

        async def _decline() -> None:
            await asyncio.sleep(0)
            gate.resolve(False)

        result, _ = await asyncio.gather(gate.await_decision(event), _decline())
        return result, gate._confirm_grant

    result, cg = _run(_run_test())
    assert result is False
    assert cg._pending_tool is None, "store_pending must not be called on decline"


def test_gate_await_decision_numeric() -> None:
    """Typing '1' while a decision is pending sends the nudge (buttons only)."""

    async def _run_test() -> tuple[bool, int]:
        gate, _, send_message_spy = _make_gate()
        event = _make_event(args_hash="aaaa1111bbbb2222")
        gate.on_held(event)
        await asyncio.sleep(0)

        consumed = await gate.handle_inbound("42|alice", "1")
        await asyncio.sleep(0)  # let nudge task run
        return consumed, send_message_spy.call_count

    consumed, nudge_count = _run(_run_test())
    assert consumed is True, "typed '1' must be consumed (not forwarded to agent)"
    assert nudge_count >= 1, "nudge must be sent for typed '1'"


def test_gate_await_decision_timeout() -> None:
    """No reply within timeout → await_decision returns False; timeout message sent."""

    async def _run_test() -> tuple[bool, int]:
        gate, _, send_message_spy = _make_gate()
        event = _make_event(args_hash="a3f9c112deadbeef")
        gate.on_held(event)
        await asyncio.sleep(0)

        # Patch the timeout to near-zero to keep the test fast.
        import toolfence.integration.channel_adapter as _mod
        original_wait_for = asyncio.wait_for

        async def _fast_wait_for(fut: Any, timeout: float) -> Any:  # type: ignore[override]
            return await original_wait_for(fut, timeout=0.01)

        import unittest.mock as _mock
        with _mock.patch("asyncio.wait_for", side_effect=_fast_wait_for):
            result = await gate.await_decision(event)

        await asyncio.sleep(0)  # allow timeout message task to run
        return result, send_message_spy.call_count

    result, msg_count = _run(_run_test())
    assert result is False, "await_decision must return False on timeout"
    assert msg_count >= 1, "timeout message must be sent to user"


def test_gate_nudge_on_unknown_text() -> None:
    """Any text while decision pending → nudge sent; consumed; future still pending."""

    async def _run_test() -> tuple[bool, bool, int]:
        gate, _, send_message_spy = _make_gate()
        event = _make_event(args_hash="a3f9c112deadbeef")
        gate.on_held(event)
        await asyncio.sleep(0)

        consumed = await gate.handle_inbound("42|alice", "what do you mean?")
        await asyncio.sleep(0)  # let nudge task run
        future_still_pending = gate._future is not None and not gate._future.done()
        return consumed, future_still_pending, send_message_spy.call_count

    consumed, still_pending, msg_count = _run(_run_test())
    assert consumed is True, "handle_inbound must return True (consumed)"
    assert still_pending, "future must still be pending after nudge"
    assert msg_count >= 1, "nudge message must be sent"


def test_gate_nudge_on_allow_text() -> None:
    """Typing 'Allow' while decision pending → nudge sent (buttons only); future still pending."""

    async def _run_test() -> tuple[bool, bool, int]:
        gate, _, send_message_spy = _make_gate()
        event = _make_event(args_hash="a3f9c112deadbeef")
        gate.on_held(event)
        await asyncio.sleep(0)

        consumed = await gate.handle_inbound("42|alice", "Allow")
        await asyncio.sleep(0)
        future_still_pending = gate._future is not None and not gate._future.done()
        return consumed, future_still_pending, send_message_spy.call_count

    consumed, still_pending, msg_count = _run(_run_test())
    assert consumed is True, "typed 'Allow' must be consumed (not forwarded)"
    assert still_pending, "future must still be pending — typed Allow must not resolve"
    assert msg_count >= 1, "nudge must be sent for typed 'Allow'"


def test_gate_second_call_declined_immediately() -> None:
    """Second on_held while first is pending → await_decision for second returns False immediately."""

    async def _run_test() -> bool:
        gate, _, _ = _make_gate()
        event_a = _make_event(tool_name="tool_a", args_hash="aaaa1111bbbb2222")
        event_b = _make_event(tool_name="tool_b", args_hash="cccc3333dddd4444")

        gate.on_held(event_a)   # first hold — sets up future
        gate.on_held(event_b)   # second hold while first pending — no-op

        # await_decision for event_b must return False immediately (hash mismatch)
        result = await gate.await_decision(event_b)
        return result

    assert _run(_run_test()) is False


def test_gate_duplicate_waiter_declined() -> None:
    """Two concurrent await_decision calls for same event → second returns False immediately."""

    async def _run_test() -> tuple[bool, bool]:
        gate, _, _ = _make_gate()
        event = _make_event(args_hash="a3f9c112deadbeef")
        gate.on_held(event)
        await asyncio.sleep(0)

        results: list[bool] = []

        async def _first_waiter() -> None:
            results.append(await gate.await_decision(event))

        async def _second_waiter() -> None:
            # Yield once so _first_waiter starts and sets _waiting=True.
            await asyncio.sleep(0)
            results.append(await gate.await_decision(event))

        # Start both; then resolve the future to unblock the first.
        async def _resolver() -> None:
            await asyncio.sleep(0.01)
            gate.resolve(False)

        await asyncio.gather(
            _first_waiter(),
            _second_waiter(),
            _resolver(),
        )
        # results[1] is the second waiter — must be False immediately
        return results[0], results[1]

    first_result, second_result = _run(_run_test())
    assert second_result is False, "duplicate waiter must get False immediately"


def test_gate_non_allowed_sender_passes_through() -> None:
    """handle_inbound from disallowed sender → returns False (message not consumed)."""

    async def _run_test() -> bool:
        gate, _, _ = _make_gate(allowed=False)
        event = _make_event(args_hash="a3f9c112deadbeef")
        gate.on_held(event)
        await asyncio.sleep(0)
        return await gate.handle_inbound("99|mallory", "Allow")

    assert _run(_run_test()) is False
