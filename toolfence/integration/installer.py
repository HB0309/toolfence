"""Post-load Guard installer for nanobot's ToolRegistry (B-3).

Public API
----------
``install_guard(registry, ...)``
    Wrap every tool currently in ``registry._tools`` with a ``GuardedProxy``,
    remove ``spawn`` and ``exec``, and monkey-patch ``registry.register`` so
    that any tool registered afterward (e.g. on MCP reconnect) is also wrapped
    automatically.

``verify_guard_invariant(registry)``
    Raise ``RuntimeError`` if any tool currently in ``registry._tools`` is not
    a ``GuardedProxy``.  Call this before every ``process_direct`` turn to
    catch any unwrapped tool that slipped past the installer.

Import boundary
---------------
This module imports nanobot lazily (inside function bodies) so that the module
can be imported without nanobot on ``sys.path``.  The ``registry`` parameter is
typed ``Any`` for the same reason — the actual ``ToolRegistry`` type check is
duck-typed at runtime.

Known limits (GRD-3)
--------------------
The ``register`` patch handles the common re-registration path on reconnect.
However, two nanobot internals limit full reconnect transparency:

1. ``_refresh_terminated_server`` (mcp.py:1646) returns early when
   ``current_tool is not stale_tool`` — the ``GuardedProxy`` wrapping the stale
   ``_MCPWrapperBase`` is a different object, so nanobot skips reconnect.
2. ``_attach_reconnect_handlers`` (mcp.py:1625) only calls
   ``set_reconnect_handler`` on ``_MCPWrapperBase`` instances; ``GuardedProxy``
   is not a subclass, so it never receives a reconnect handler.

These issues are tracked for a later task.  Do not attempt to fix them here.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from toolfence.contracts.guard import HeldCallEvent
from toolfence.contracts.surface import SurfaceFile
from toolfence.guard.confirm import ConfirmGrant
from toolfence.guard.decision import GuardDecision
from toolfence.guard.provenance import ProvenanceStore
from toolfence.guard.proxy import GuardedProxy
from toolfence.guard.taint import SessionTaint

log = logging.getLogger(__name__)

# Tools that must be removed unconditionally (GRD-13).
_FORBIDDEN_TOOL_NAMES = frozenset(("spawn", "exec"))

# Sentinel attribute placed on the registry after the first install_guard call.
# Prevents double-wrapping and double-patching when install_guard is called again
# on the same registry (e.g. if a caller accidentally calls it twice).
_GUARD_INSTALLED_ATTR = "_toolfence_guard_installed"


def install_guard(
    registry: Any,
    surface_map: SurfaceFile,
    provenance: ProvenanceStore,
    taint: SessionTaint,
    decision: GuardDecision,
    on_held: Callable[[HeldCallEvent], None],
    confirm_grant: ConfirmGrant,
    *,
    guard_on: bool,
    datamark_on: bool,
    await_decision: Callable[[HeldCallEvent], Awaitable[bool]] | None = None,
) -> None:
    """Wrap every tool in ``registry._tools`` with ``GuardedProxy``.

    Steps performed:
    1. Remove ``spawn`` and ``exec`` from the registry (GRD-13).
    2. Wrap every remaining *unwrapped* tool with ``GuardedProxy`` (skips tools
       that are already a ``GuardedProxy`` so a second call is idempotent).
    3. Monkey-patch ``registry.register`` once so that any tool registered
       afterward (e.g. on MCP reconnect) is also wrapped automatically (GRD-3).
       The patch also silently drops re-registration of ``spawn``/``exec``.
    """
    log.info("install_guard: installing Guard on registry (guard_on=%s, datamark_on=%s)", guard_on, datamark_on)
    # Step 1 — remove forbidden tools.
    for name in list(_FORBIDDEN_TOOL_NAMES):
        try:
            registry.unregister(name)
            log.info("install_guard: removed forbidden tool %r", name)
        except Exception:  # noqa: BLE001
            log.debug("install_guard: tool %r not present, nothing to remove", name)

    # Step 2 — wrap every current unwrapped tool in-place.
    def _make_proxy(tool: Any) -> GuardedProxy:
        return GuardedProxy(
            tool,
            surface_map,
            provenance,
            taint,
            decision,
            on_held,
            confirm_grant,
            guard_on=guard_on,
            datamark_on=datamark_on,
            await_decision=await_decision,
        )

    wrapped_count = 0
    for name, tool in list(registry._tools.items()):
        if not isinstance(tool, GuardedProxy):
            registry._tools[name] = _make_proxy(tool)
            wrapped_count += 1
            log.debug("install_guard: wrapped tool %r in GuardedProxy", name)
    log.info("install_guard: wrapped %d tool(s)", wrapped_count)

    # Step 3 — patch register once; skip if already patched.
    if not getattr(registry, _GUARD_INSTALLED_ATTR, False):
        _original_register = registry.register

        def _guarded_register(tool: Any) -> None:
            # Silently drop forbidden tools even if nanobot re-registers them.
            if getattr(tool, "name", None) in _FORBIDDEN_TOOL_NAMES:
                return
            if not isinstance(tool, GuardedProxy):
                tool = _make_proxy(tool)
            _original_register(tool)

        registry.register = _guarded_register
        # Mark the registry so a second install_guard call skips re-patching.
        try:
            object.__setattr__(registry, _GUARD_INSTALLED_ATTR, True)
        except (AttributeError, TypeError):
            # Plain objects and MagicMocks may not support object.__setattr__;
            # fall back to a normal attribute set.
            setattr(registry, _GUARD_INSTALLED_ATTR, True)


def verify_guard_invariant(registry: Any) -> None:
    """Raise ``RuntimeError`` if any tool in ``registry._tools`` is not a ``GuardedProxy``.

    Call this before every ``process_direct`` turn to enforce that no raw tool
    has been re-inserted into the registry since ``install_guard`` ran.
    """
    log.debug("verify_guard_invariant: checking %d tool(s)", len(registry.tool_names))
    for name in registry.tool_names:
        tool = registry._tools.get(name)
        if not isinstance(tool, GuardedProxy):
            msg = (
                f"Guard invariant violated: tool '{name}' is not a GuardedProxy "
                f"(got {type(tool).__name__!r}).  "
                "Call install_guard before process_direct."
            )
            log.error("verify_guard_invariant: %s", msg)
            raise RuntimeError(msg)
    log.debug("verify_guard_invariant: all tools are GuardedProxy instances")
