"""Tests for toolfence/integration/live_factory.py (P1-5).

All tests run without a live Galaxium backend or real model.  Network calls and
sqlite3 operations are mocked.

Test inventory
--------------
  test_check_galaxium_health_raises_on_connection_error
  test_check_galaxium_health_raises_on_non_2xx
  test_check_galaxium_health_passes_on_2xx
  test_db_backup_adapter_backup_and_restore_called
  test_db_backup_adapter_restores_even_on_inner_error
  test_make_live_factory_returns_callable
  test_make_live_factory_sets_guard_on_from_defense
  test_make_live_factory_sets_datamark_on_from_defense
  test_make_live_factory_review_body_set_for_tool_result
  test_make_live_factory_no_review_body_for_user_input
  test_make_live_factory_no_review_body_for_normal
"""

from __future__ import annotations

import sqlite3
import urllib.error
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from toolfence.engine.runner import DefenseConfig
from toolfence.integration.live_factory import (
    _DbBackupAdapter,
    check_galaxium_health,
    make_live_factory,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_defense(guard_on: bool = False, datamark_on: bool = False) -> DefenseConfig:
    return DefenseConfig(name="none", guard_on=guard_on, datamark_on=datamark_on)


class _FakeResponse:
    """Minimal file-like object returned by urllib.request.urlopen mock."""

    def __init__(self, status: int = 200) -> None:
        self.status = status

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# check_galaxium_health
# ---------------------------------------------------------------------------

class TestCheckGalaxiumHealth:

    def test_raises_on_connection_error(self) -> None:
        """ConnectionRefusedError wrapped in URLError must raise RuntimeError."""
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            with pytest.raises(RuntimeError, match="not reachable"):
                check_galaxium_health("http://localhost:8001/")

    def test_raises_on_non_2xx(self) -> None:
        """A 503 response must raise RuntimeError."""
        with patch(
            "urllib.request.urlopen",
            return_value=_FakeResponse(status=503),
        ):
            with pytest.raises(RuntimeError, match="HTTP 503"):
                check_galaxium_health("http://localhost:8001/")

    def test_passes_on_200(self) -> None:
        """A 200 response must not raise."""
        with patch(
            "urllib.request.urlopen",
            return_value=_FakeResponse(status=200),
        ):
            check_galaxium_health("http://localhost:8001/")  # should not raise

    def test_passes_on_201(self) -> None:
        """A 201 response (2xx) must not raise."""
        with patch(
            "urllib.request.urlopen",
            return_value=_FakeResponse(status=201),
        ):
            check_galaxium_health("http://localhost:8001/")  # should not raise


# ---------------------------------------------------------------------------
# _DbBackupAdapter
# ---------------------------------------------------------------------------

class TestDbBackupAdapter:

    def _make_trace(self) -> Any:
        """Return a minimal object accepted as a Trace."""
        from toolfence.engine.adapter import ScriptedAdapter
        return ScriptedAdapter("fixtures/probes/normal_task.json").run_turn("x", "none")

    def test_backup_and_restore_called_on_success(self) -> None:
        """On a successful run_turn, backup and restore are both called."""
        trace = self._make_trace()

        inner = MagicMock()
        inner.run_turn.return_value = trace

        src_conn = MagicMock(spec=sqlite3.Connection)
        bak_conn = MagicMock(spec=sqlite3.Connection)
        src2_conn = MagicMock(spec=sqlite3.Connection)
        dst2_conn = MagicMock(spec=sqlite3.Connection)

        # sqlite3.connect returns connections in order:
        # 1st call → src (backup phase)
        # 2nd call → dst (backup phase)
        # 3rd call → src2 (restore phase)
        # 4th call → dst2 (restore phase)
        connect_mock = MagicMock(side_effect=[src_conn, bak_conn, src2_conn, dst2_conn])

        with patch("toolfence.integration.live_factory.sqlite3.connect", connect_mock):
            adapter = _DbBackupAdapter(inner, "/fake/booking.db")
            result = adapter.run_turn("prompt", "none")

        assert result is trace

        # Backup: src.backup(dst)
        src_conn.backup.assert_called_once_with(bak_conn)
        bak_conn.close.assert_called_once()
        src_conn.close.assert_called_once()

        # Restore: src2.backup(dst2)
        src2_conn.backup.assert_called_once_with(dst2_conn)
        dst2_conn.close.assert_called_once()
        src2_conn.close.assert_called_once()

        # Paths
        connect_mock.assert_any_call("/fake/booking.db")
        connect_mock.assert_any_call("/fake/booking.db.bak")

    def test_restore_called_even_when_inner_raises(self) -> None:
        """Restore must happen in `finally` even if inner.run_turn raises."""
        inner = MagicMock()
        inner.run_turn.side_effect = RuntimeError("model timeout")

        src_conn = MagicMock(spec=sqlite3.Connection)
        bak_conn = MagicMock(spec=sqlite3.Connection)
        src2_conn = MagicMock(spec=sqlite3.Connection)
        dst2_conn = MagicMock(spec=sqlite3.Connection)

        connect_mock = MagicMock(side_effect=[src_conn, bak_conn, src2_conn, dst2_conn])

        with patch("toolfence.integration.live_factory.sqlite3.connect", connect_mock):
            adapter = _DbBackupAdapter(inner, "/fake/booking.db")
            with pytest.raises(RuntimeError, match="model timeout"):
                adapter.run_turn("prompt", "none")

        # Backup happened
        src_conn.backup.assert_called_once_with(bak_conn)
        # Restore happened despite the exception
        src2_conn.backup.assert_called_once_with(dst2_conn)
        # All connections closed
        for conn in (src_conn, bak_conn, src2_conn, dst2_conn):
            conn.close.assert_called_once()


# ---------------------------------------------------------------------------
# make_live_factory
# ---------------------------------------------------------------------------

class TestMakeLiveFactory:

    def _call_factory(
        self,
        channel: str = "user-input",
        guard_on: bool = False,
        datamark_on: bool = False,
        probe_text: str = "some probe",
    ) -> Any:
        """Call make_live_factory and invoke the returned factory with given args."""
        defense = _make_defense(guard_on=guard_on, datamark_on=datamark_on)
        factory = make_live_factory(
            config_path="config/nanobot.eval.json",
            surface_path="results/surface.json",
            run_id="test-run-001",
            db_path="/fake/booking.db",
        )

        # Patch NanobotAdapter construction so we don't need nanobot installed.
        mock_adapter = MagicMock()
        with patch(
            "toolfence.integration.live_factory.sqlite3.connect",
            side_effect=lambda _: MagicMock(spec=sqlite3.Connection),
        ), patch(
            "toolfence.integration.nanobot_adapter.NanobotAdapter",
        ) as mock_cls:
            mock_cls.return_value = mock_adapter
            result = factory(defense, channel, probe_text)
            return result, mock_cls

    def test_returns_callable(self) -> None:
        """make_live_factory must return a callable."""
        factory = make_live_factory(
            config_path="config/nanobot.eval.json",
            surface_path="results/surface.json",
            run_id="r-001",
        )
        assert callable(factory)

    def test_result_is_db_backup_adapter(self) -> None:
        """The factory must wrap the NanobotAdapter in _DbBackupAdapter."""
        adapter, _ = self._call_factory()
        assert isinstance(adapter, _DbBackupAdapter)

    def test_guard_on_passed_to_nanobot(self) -> None:
        """guard_on=True on DefenseConfig must flow into NanobotAdapter."""
        defense = _make_defense(guard_on=True)
        factory = make_live_factory("cfg", "surf", "rid", db_path="/fake/db")

        with patch(
            "toolfence.integration.nanobot_adapter.NanobotAdapter",
        ) as mock_cls:
            mock_cls.return_value = MagicMock()
            factory(defense, "user-input", "probe")
            _, kwargs = mock_cls.call_args
            assert kwargs.get("guard_on") is True

    def test_guard_off_passed_to_nanobot(self) -> None:
        """guard_on=False must flow through."""
        defense = _make_defense(guard_on=False)
        factory = make_live_factory("cfg", "surf", "rid", db_path="/fake/db")

        with patch(
            "toolfence.integration.nanobot_adapter.NanobotAdapter",
        ) as mock_cls:
            mock_cls.return_value = MagicMock()
            factory(defense, "user-input", "probe")
            _, kwargs = mock_cls.call_args
            assert kwargs.get("guard_on") is False

    def test_datamark_on_passed_to_nanobot(self) -> None:
        """datamark_on=True must flow through."""
        defense = _make_defense(datamark_on=True)
        factory = make_live_factory("cfg", "surf", "rid", db_path="/fake/db")

        with patch(
            "toolfence.integration.nanobot_adapter.NanobotAdapter",
        ) as mock_cls:
            mock_cls.return_value = MagicMock()
            factory(defense, "user-input", "probe")
            _, kwargs = mock_cls.call_args
            assert kwargs.get("datamark_on") is True

    def test_review_body_set_for_tool_result(self) -> None:
        """review_body == probe_text for channel='tool-result'."""
        defense = _make_defense()
        factory = make_live_factory("cfg", "surf", "rid", db_path="/fake/db")

        with patch(
            "toolfence.integration.nanobot_adapter.NanobotAdapter",
        ) as mock_cls:
            mock_cls.return_value = MagicMock()
            factory(defense, "tool-result", "PROBE_TEXT_HERE")
            _, kwargs = mock_cls.call_args
            assert kwargs.get("review_body") == "PROBE_TEXT_HERE"

    def test_no_review_body_for_user_input(self) -> None:
        """review_body is None for channel='user-input'."""
        defense = _make_defense()
        factory = make_live_factory("cfg", "surf", "rid", db_path="/fake/db")

        with patch(
            "toolfence.integration.nanobot_adapter.NanobotAdapter",
        ) as mock_cls:
            mock_cls.return_value = MagicMock()
            factory(defense, "user-input", "probe")
            _, kwargs = mock_cls.call_args
            assert kwargs.get("review_body") is None

    def test_no_review_body_for_normal(self) -> None:
        """review_body is None for channel='normal'."""
        defense = _make_defense()
        factory = make_live_factory("cfg", "surf", "rid", db_path="/fake/db")

        with patch(
            "toolfence.integration.nanobot_adapter.NanobotAdapter",
        ) as mock_cls:
            mock_cls.return_value = MagicMock()
            factory(defense, "normal", "prompt")
            _, kwargs = mock_cls.call_args
            assert kwargs.get("review_body") is None

    def test_channel_none_for_normal(self) -> None:
        """channel kwarg passed to NanobotAdapter must be None for 'normal'."""
        defense = _make_defense()
        factory = make_live_factory("cfg", "surf", "rid", db_path="/fake/db")

        with patch(
            "toolfence.integration.nanobot_adapter.NanobotAdapter",
        ) as mock_cls:
            mock_cls.return_value = MagicMock()
            factory(defense, "normal", "prompt")
            _, kwargs = mock_cls.call_args
            assert kwargs.get("channel") is None
