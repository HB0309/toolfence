"""GuardedProxy — wraps any tool behind the Guard decision layer (GRD-1, GRD-2, GRD-8).

Two boolean switches control behaviour:

- ``guard_on``    — enables the four-branch card rule; holds block ``tool.execute``.
- ``datamark_on`` — wraps untrusted tool results in the datamark envelope before
                    they are returned to the caller.

When both switches are ``False`` the proxy is fully transparent: the result is
returned from ``tool.execute`` unchanged and provenance is still recorded
(GRD-2 requires every tool to be wrapped so provenance tracking captures reads).

Logic order inside ``execute``
-------------------------------
0. Pop ``__source__`` from ``params`` (key ``"__source__"``; default
   ``"first-party"``).  This must happen before anything else so the key never
   reaches ``tool.execute``.  Track B's launcher passes ``__source__="user"``
   when the trigger is a button-click callback.
1. Compute the arguments hash and call
   ``confirm_grant.consume_grant(tool_name, args_hash, source)``.  If ``True``,
   skip Guard entirely and call ``tool.execute(**params)`` directly.
2. If ``guard_on``:
   a. Resolve provenance label for each param via ``provenance.resolve_argument``.
   b. Determine ``action_class`` from ``surface_map`` (default ``"state-changing"``
      if the tool is absent — BASE-2 fail-closed rule).
   c. Call ``decision.decide``; on ``"hold"``:
      - Re-use the already-computed ``arguments_hash``.
      - Determine hold reason and ``untrusted_arg_name``.
      - Emit ``HeldCallEvent`` via ``on_held``.
      - Return the hold sentinel without calling ``tool.execute``.
3. Call ``tool.execute(**params)``; capture the string result.
4. Determine the tool's ``trust_label`` from ``surface_map``
   (default ``"first-party"`` if absent).
5. Record the result in ``provenance`` via ``record_tool_result``.
6. If the ``trust_label`` is ``"untrusted"``, mark the session tainted.
7. If ``datamark_on`` and ``trust_label == "untrusted"``, apply ``datamark_result``
   to the result before returning.
8. Return the (possibly datamarked) result.

This module has zero nanobot imports and zero ``toolfence.engine`` imports.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from toolfence.contracts.guard import HeldCallEvent
from toolfence.contracts.surface import SurfaceFile
from toolfence.guard.confirm import ConfirmGrant
from toolfence.guard.datamark import datamark_result
from toolfence.guard.decision import GuardDecision
from toolfence.guard.provenance import ProvenanceStore
from toolfence.guard.taint import SessionTaint

# Sentinel returned to the caller when a tool call is held for confirmation.
_HOLD_SENTINEL = "paused — needs your confirmation"


def _get_action_class(surface_map: SurfaceFile, tool_name: str) -> str:
    """Return the ``action_class`` for *tool_name* from *surface_map*.

    Defaults to ``"state-changing"`` if the tool is not listed (BASE-2 fail-closed).
    """
    for entry in surface_map.tools:
        if entry.name == tool_name:
            return entry.action_class
    return "state-changing"


def _get_trust_label(surface_map: SurfaceFile, tool_name: str) -> str:
    """Return the ``trust_label`` for *tool_name* from *surface_map*.

    Defaults to ``"first-party"`` if the tool is not listed.
    """
    for entry in surface_map.tools:
        if entry.name == tool_name:
            return entry.trust_label
    return "first-party"


def _compute_hash(params: dict[str, Any]) -> str:
    """Return a SHA-256 hex digest of the canonical sorted JSON of *params*."""
    canonical = json.dumps(params, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


class GuardedProxy:
    """Wraps a single tool object behind the Guard decision layer.

    Parameters
    ----------
    tool:
        Any object exposing ``.name`` (str), ``async .execute(**params)`` (callable),
        and optionally ``.schema`` and ``.description``.  This matches the shape of
        every tool in nanobot's registry.
    surface_map:
        The reviewed surface map (``SurfaceFile``) used to look up ``action_class``
        and ``trust_label`` per tool.
    provenance:
        Session-scoped ``ProvenanceStore``; shared across all proxies in one session.
    taint:
        Session-scoped ``SessionTaint``; shared across all proxies in one session.
    decision:
        ``GuardDecision`` instance (stateless; shared is fine).
    on_held:
        Callable invoked with a ``HeldCallEvent`` whenever a call is held.
        The caller (e.g. ``integration/channel_adapter.py``) uses this to send the
        hold card to the user.
    guard_on:
        When ``True`` (default), the four-branch card rule is enforced.
        When ``False``, every call passes through without being held.
    datamark_on:
        When ``True``, results from tools whose ``trust_label`` is ``"untrusted"``
        are wrapped in the datamark envelope before being returned.
    """

    def __init__(
        self,
        tool: Any,
        surface_map: SurfaceFile,
        provenance: ProvenanceStore,
        taint: SessionTaint,
        decision: GuardDecision,
        on_held: Callable[[HeldCallEvent], None],
        confirm_grant: ConfirmGrant,
        *,
        guard_on: bool = True,
        datamark_on: bool = False,
    ) -> None:
        # Store under names that don't collide with forwarded attributes.
        object.__setattr__(self, "_tool", tool)
        object.__setattr__(self, "_surface_map", surface_map)
        object.__setattr__(self, "_provenance", provenance)
        object.__setattr__(self, "_taint", taint)
        object.__setattr__(self, "_decision", decision)
        object.__setattr__(self, "_on_held", on_held)
        object.__setattr__(self, "_confirm_grant", confirm_grant)
        object.__setattr__(self, "_guard_on", guard_on)
        object.__setattr__(self, "_datamark_on", datamark_on)
        # Per-session counter: how many untrusted results have been read.
        object.__setattr__(self, "_untrusted_read_count", 0)

    # ------------------------------------------------------------------
    # Explicit forwarding — same three properties as ProxyStub
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return self._tool.name  # type: ignore[attr-defined]

    @property
    def schema(self) -> Any:
        return getattr(self._tool, "schema", None)

    @property
    def description(self) -> str | None:
        return getattr(self._tool, "description", None)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def execute(self, **params: Any) -> Any:
        """Execute the wrapped tool, applying Guard and datamark logic.

        See module docstring for the full logic order.
        """
        tool_name: str = self.name

        # ----------------------------------------------------------------
        # Step 0 — Extract __source__ kwarg (must happen before anything
        # else so it never leaks into tool.execute's real parameters).
        # Track B passes __source__="user" for button-click callbacks.
        # ----------------------------------------------------------------
        source: str = params.pop("__source__", "first-party")

        # ----------------------------------------------------------------
        # Step 1 — Check for a pending user-approved confirm grant.
        # If consumed, skip Guard entirely and jump straight to execution.
        # ----------------------------------------------------------------
        args_hash_for_grant = _compute_hash(params)
        if self._confirm_grant.consume_grant(tool_name, args_hash_for_grant, source):
            result: Any = await self._tool.execute(**params)  # type: ignore[attr-defined]
            result_str: str = str(result)
            trust_label_grant = _get_trust_label(self._surface_map, tool_name)
            self._provenance.record_tool_result(tool_name, result_str, trust_label_grant)  # type: ignore[arg-type]
            if trust_label_grant == "untrusted":
                self._taint.mark_tainted()
                object.__setattr__(
                    self,
                    "_untrusted_read_count",
                    self._untrusted_read_count + 1,
                )
            if self._datamark_on and trust_label_grant == "untrusted":
                result_str = datamark_result(result_str, tool_name)
            return result_str

        # ----------------------------------------------------------------
        # Step 2 — Guard decision (only when guard_on=True)
        # ----------------------------------------------------------------
        if self._guard_on:
            action_class = _get_action_class(self._surface_map, tool_name)

            # Resolve provenance label for each argument.
            prov_map: dict[str, str] = {
                k: self._provenance.resolve_argument(v)
                for k, v in params.items()
            }

            verdict = self._decision.decide(
                tool_name=tool_name,
                action_class=action_class,
                arguments=params,
                session_tainted=self._taint.is_tainted(),
                provenance=prov_map,
            )

            if verdict == "hold":
                args_hash = args_hash_for_grant  # already computed above

                # Determine reason and untrusted_arg_name.
                if action_class == "irreversible":
                    reason = "irreversible"
                    untrusted_arg_name: str | None = None
                elif self._taint.is_tainted():
                    reason = "tainted_session"
                    untrusted_arg_name = None
                else:
                    reason = "untrusted_argument"
                    # Find the first untrusted argument name.
                    untrusted_arg_name = next(
                        (k for k, v in prov_map.items() if v == "untrusted"),
                        None,
                    )

                event = HeldCallEvent(
                    tool_name=tool_name,
                    arguments=dict(params),
                    arguments_hash=args_hash,
                    reason=reason,  # type: ignore[arg-type]
                    untrusted_read_count=self._untrusted_read_count,
                    untrusted_arg_name=untrusted_arg_name,
                )
                self._on_held(event)
                return _HOLD_SENTINEL

        # ----------------------------------------------------------------
        # Step 3 — Call the real tool
        # ----------------------------------------------------------------
        result = await self._tool.execute(**params)  # type: ignore[attr-defined]
        result_str = str(result)

        # ----------------------------------------------------------------
        # Steps 4–7 — Provenance recording, taint, datamark
        # ----------------------------------------------------------------
        trust_label = _get_trust_label(self._surface_map, tool_name)

        # Record result for provenance tracking (always, regardless of guard_on).
        self._provenance.record_tool_result(tool_name, result_str, trust_label)  # type: ignore[arg-type]

        # Update taint and untrusted read counter.
        if trust_label == "untrusted":
            self._taint.mark_tainted()
            object.__setattr__(
                self,
                "_untrusted_read_count",
                self._untrusted_read_count + 1,
            )

        # Apply datamarking if requested and the tool is untrusted.
        if self._datamark_on and trust_label == "untrusted":
            result_str = datamark_result(result_str, tool_name)

        return result_str

    # ------------------------------------------------------------------
    # Generic attribute forwarding — lets registry inspection work
    # ------------------------------------------------------------------

    def __getattr__(self, item: str) -> Any:
        return getattr(object.__getattribute__(self, "_tool"), item)
