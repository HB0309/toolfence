"""Live adapter factory for P-1 evaluation runs (P1-5).

Provides public callables used by both the CLI (``toolfence run --live``)
and ``scripts/run_pg8_gate.py``:

``check_galaxium_health(url)``
    Raises ``RuntimeError`` if the Galaxium HTTP backend is not reachable or
    returns a non-2xx status.  Call this before starting any live trials.

``make_live_factory(config_path, surface_path, run_id, db_path)``
    Returns an ``adapter_factory`` callable that the runner invokes once per
    trial.  The factory:
    1. Reads ``guard_on`` and ``datamark_on`` from the ``DefenseConfig``.
    2. Constructs a ``NanobotAdapter`` with those settings plus
       ``channel``/``review_body`` derived from the channel string.
    3. Wraps it in ``_DbBackupAdapter`` so ``booking.db`` is backed up before
       each trial and restored afterwards via ``sqlite3.backup()``.

``make_live_factory_from_profile(profile, run_id)``
    Target-agnostic variant that reads all settings from a ``TargetProfile``.
    Supports all state_reset and injection strategies defined in
    ``contracts/profile.py``.

Import boundary
---------------
This module lives in ``toolfence/integration/`` and may import nanobot at
runtime (inside closures / methods), but must not import it at module level.
"""

from __future__ import annotations

import shutil
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from toolfence.contracts.profile import TargetProfile
    from toolfence.contracts.trace import Trace
    from toolfence.engine.adapter import AgentAdapter
    from toolfence.engine.runner import DefenseConfig


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


def check_galaxium_health(url: str = "http://localhost:8001/") -> None:
    """Raise ``RuntimeError`` if the Galaxium backend is not reachable.

    Parameters
    ----------
    url:
        Base URL to ping (plain HTTP GET).  Defaults to ``http://localhost:8001/``.

    Raises
    ------
    RuntimeError
        If the request fails (connection error, timeout) or returns a non-2xx
        HTTP status code.
    """
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            status: int = resp.status
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Galaxium backend not reachable at {url} — "
            f"start the backend before running live eval ({exc.reason})"
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"Galaxium backend not reachable at {url} — "
            f"start the backend before running live eval ({exc})"
        ) from exc

    if not (200 <= status < 300):
        raise RuntimeError(
            f"Galaxium backend returned HTTP {status} at {url} — "
            "expected 2xx"
        )


# ---------------------------------------------------------------------------
# DB backup/restore adapter
# ---------------------------------------------------------------------------


class _DbBackupAdapter:
    """Wraps an ``AgentAdapter`` with sqlite3 backup/restore around each trial.

    Before ``run_turn`` the source DB is backed up to ``<db_path>.bak`` using
    ``sqlite3.Connection.backup()``.  After ``run_turn`` (whether it succeeds
    or raises) the backup is restored into the source path.  Both connections
    are closed explicitly in every branch.

    Using ``sqlite3.backup()`` instead of a file copy is required because
    Galaxium keeps ``booking.db`` open via its own connection.
    """

    def __init__(self, inner: "AgentAdapter", db_path: str) -> None:
        self._inner = inner
        self._db_path = db_path
        self._bak_path = db_path + ".bak"

    # ------------------------------------------------------------------
    # AgentAdapter Protocol
    # ------------------------------------------------------------------

    def run_turn(self, prompt: str, defense: str) -> "Trace":
        """Back up DB, run the inner adapter, then restore DB regardless of outcome."""
        # --- Backup ---
        src = sqlite3.connect(self._db_path)
        dst = sqlite3.connect(self._bak_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

        # --- Run trial, restore DB even on exception ---
        try:
            return self._inner.run_turn(prompt, defense)
        finally:
            src2 = sqlite3.connect(self._bak_path)
            dst2 = sqlite3.connect(self._db_path)
            try:
                src2.backup(dst2)
            finally:
                dst2.close()
                src2.close()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_live_factory(
    config_path: str,
    surface_path: str,
    run_id: str,
    db_path: str = "targets/galaxium/booking_system_backend/booking.db",
) -> "Callable[[DefenseConfig, str, str], AgentAdapter]":
    """Return a per-trial adapter factory for live evaluation runs.

    The returned callable matches the ``adapter_factory`` signature expected by
    ``EvaluationRunner``:

        factory(defense: DefenseConfig, channel: str, probe_text: str) -> AgentAdapter

    It:
    1. Reads ``guard_on`` and ``datamark_on`` from *defense*.
    2. Builds a ``NanobotAdapter`` for the trial's channel/probe_text.
    3. Wraps it in ``_DbBackupAdapter`` so ``booking.db`` is always restored.

    Parameters
    ----------
    config_path:
        Path to the nanobot JSON config (e.g. ``config/nanobot.eval.json``).
    surface_path:
        Path to ``surface.json`` — passed to ``NanobotAdapter`` for Guard wiring.
    run_id:
        Run identifier embedded in every ``Trace``.
    db_path:
        Filesystem path to ``booking.db``.
    """

    def _factory(
        defense: "DefenseConfig",
        channel: str,
        probe_text: str,
    ) -> "AgentAdapter":
        from toolfence.integration.nanobot_adapter import NanobotAdapter

        # Map channel to review_body (tool-result probes seed the review row).
        review_body: str | None = probe_text if channel == "tool-result" else None

        adapter = NanobotAdapter(
            config_path=config_path,
            surface_path=surface_path,
            run_id=run_id,
            guard_on=defense.guard_on,
            datamark_on=defense.datamark_on,
            channel=channel if channel != "normal" else None,
            canary=None,
            review_body=review_body,
            galaxium_db_path=db_path,
        )
        return _DbBackupAdapter(adapter, db_path)

    return _factory


# ---------------------------------------------------------------------------
# Target-agnostic state-reset adapters
# ---------------------------------------------------------------------------


class _FsRestoreAdapter:
    """Wraps an ``AgentAdapter`` with folder delete-then-restore around each trial.

    Before ``run_turn``:
      1. ``shutil.rmtree(working_path)`` — removes everything the previous trial wrote.
      2. ``shutil.copytree(snapshot_path, working_path)`` — fresh copy from snapshot.

    After ``run_turn`` (success or error) no extra cleanup is needed; the next
    trial's pre-restore handles it.

    The inject step (writing a canary file) happens outside this class, in the
    factory closure, because it must run *after* the restore so the canary file
    is not overwritten.
    """

    def __init__(self, inner: "AgentAdapter", snapshot_path: str, working_path: str) -> None:
        self._inner = inner
        self._snapshot = Path(snapshot_path)
        self._working = Path(working_path)

    # ------------------------------------------------------------------
    # AgentAdapter Protocol
    # ------------------------------------------------------------------

    def run_turn(self, prompt: str, defense: str) -> "Trace":
        """Restore working folder, then run the inner adapter."""
        # Delete any residue from the previous trial.
        if self._working.exists():
            shutil.rmtree(self._working)
        # Copy snapshot into a fresh working folder.
        shutil.copytree(self._snapshot, self._working)
        return self._inner.run_turn(prompt, defense)


# ---------------------------------------------------------------------------
# Generic health check
# ---------------------------------------------------------------------------


def check_target_health(url: str) -> None:
    """Raise ``RuntimeError`` if the target HTTP backend is not reachable.

    Parameters
    ----------
    url:
        Base URL to ping (plain HTTP GET).

    Raises
    ------
    RuntimeError
        If the request fails or returns a non-2xx HTTP status code.
    """
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            status: int = resp.status
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Target backend not reachable at {url} — "
            f"start the backend before running live eval ({exc.reason})"
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"Target backend not reachable at {url} — "
            f"start the backend before running live eval ({exc})"
        ) from exc

    if not (200 <= status < 300):
        raise RuntimeError(
            f"Target backend returned HTTP {status} at {url} — "
            "expected 2xx"
        )


# ---------------------------------------------------------------------------
# Profile-driven factory
# ---------------------------------------------------------------------------


def make_live_factory_from_profile(
    profile: "TargetProfile",
    run_id: str,
) -> "Callable[[DefenseConfig, str, str], AgentAdapter]":
    """Return a per-trial adapter factory driven by *profile*.

    The returned callable matches the ``adapter_factory`` signature expected by
    ``EvaluationRunner``:

        factory(defense: DefenseConfig, channel: str, probe_text: str) -> AgentAdapter

    Behaviour per strategy
    ----------------------
    state_reset.strategy == "sqlite_backup":
        Wraps the adapter in ``_DbBackupAdapter`` (existing Galaxium logic).
    state_reset.strategy == "fs_restore":
        Wraps the adapter in ``_FsRestoreAdapter``.
    state_reset.strategy == "none":
        Returns the adapter unwrapped.

    injection.strategy == "sqlite_review":
        Sets ``review_body`` and ``injection_db_path`` on the NanobotAdapter so
        it seeds the review table before the turn.
    injection.strategy == "fs_canary_file":
        Writes the canary file into ``working_path`` after the state reset and
        before ``run_turn`` is called.
    injection.strategy == "none":
        No injection.

    Parameters
    ----------
    profile:
        Loaded and validated ``TargetProfile``.
    run_id:
        Evaluation run identifier embedded in every ``Trace``.
    """
    config_path = profile.nanobot_config
    surface_path = profile.surface

    def _factory(
        defense: "DefenseConfig",
        channel: str,
        probe_text: str,
    ) -> "AgentAdapter":
        from toolfence.integration.nanobot_adapter import NanobotAdapter

        # --- Injection config ---
        review_body: str | None = None
        injection_db_path: str | None = None
        injection_table: str | None = None
        injection_columns: dict | None = None
        injection_id_column: str | None = None

        if channel == "tool-result":
            inj = profile.injection
            if inj.strategy == "sqlite_review":
                review_body = probe_text
                injection_db_path = inj.db_path
                injection_table = inj.table
                injection_columns = dict(inj.columns)
                injection_id_column = inj.id_column
            # fs_canary_file is handled by the reset wrapper below

        # --- Build NanobotAdapter ---
        adapter: "AgentAdapter" = NanobotAdapter(
            config_path=config_path,
            surface_path=surface_path,
            run_id=run_id,
            guard_on=defense.guard_on,
            datamark_on=defense.datamark_on,
            channel=channel if channel != "normal" else None,
            canary=None,
            review_body=review_body,
            injection_db_path=injection_db_path,
            injection_table=injection_table,
            injection_columns=injection_columns,
            injection_id_column=injection_id_column,
            required_tool_prefix=profile.required_tool_prefix,
            agent_persona=profile.agent_persona,
        )

        # --- Wrap with state-reset adapter ---
        rst = profile.state_reset
        if rst.strategy == "sqlite_backup":
            adapter = _DbBackupAdapter(adapter, rst.db_path)
        elif rst.strategy == "fs_restore":
            if channel == "tool-result" and profile.injection.strategy == "fs_canary_file":
                # Inject canary file after restore; wrap both operations.
                inj = profile.injection  # type: ignore[assignment]
                adapter = _FsCanaryAndRestoreAdapter(
                    adapter,
                    snapshot_path=rst.snapshot_path,
                    working_path=rst.working_path,
                    canary_filename=inj.filename,
                    canary_content=probe_text,
                )
            else:
                adapter = _FsRestoreAdapter(adapter, rst.snapshot_path, rst.working_path)
        # strategy == "none": no wrapping

        return adapter

    return _factory


class _FsCanaryAndRestoreAdapter:
    """Combines fs_restore + fs_canary_file injection in the correct order.

    Order per trial:
    1. rmtree + copytree (restore snapshot)
    2. Write canary file
    3. run_turn
    """

    def __init__(
        self,
        inner: "AgentAdapter",
        snapshot_path: str,
        working_path: str,
        canary_filename: str,
        canary_content: str,
    ) -> None:
        self._inner = inner
        self._snapshot = Path(snapshot_path)
        self._working = Path(working_path)
        self._canary_filename = canary_filename
        self._canary_content = canary_content

    def run_turn(self, prompt: str, defense: str) -> "Trace":
        # Restore
        if self._working.exists():
            shutil.rmtree(self._working)
        shutil.copytree(self._snapshot, self._working)
        # Inject canary file
        canary_path = self._working / self._canary_filename
        canary_path.write_text(self._canary_content, encoding="utf-8")
        return self._inner.run_turn(prompt, defense)
