"""B-3 — installer tests.

Covers:
  GRD-2   Every tool is wrapped (even reads like read_file)
  GRD-3a  Reconnect re-wrap: registry.register patch wraps new raw tools
  GRD-3b  verify_guard_invariant raises when a bare tool is present
  GRD-6   read_file result recorded in provenance store via proxy execute
  GRD-13  spawn and exec are absent after install_guard

All tests use a hand-built stub registry — no nanobot runtime required.

Test inventory
--------------
  test_all_tools_wrapped                  -- all 4 tools become GuardedProxy (GRD-2)
  test_reconnect_rewraps                  -- register patch auto-wraps new raw tool (GRD-3a)
  test_invariant_raises_on_bare_tool      -- bare tool in registry → RuntimeError (GRD-3b)
  test_spawn_exec_removed                 -- spawn and exec absent after install (GRD-13)
  test_read_file_provenance_recorded      -- proxy.execute records result in provenance (GRD-6)
  test_double_install_does_not_double_wrap -- second install_guard call is idempotent
  test_register_patch_blocks_forbidden    -- register after install ignores spawn/exec
"""
from __future__ import annotations

import asyncio
import json
import hashlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from toolfence.contracts.surface import SurfaceFile
from toolfence.guard.confirm import ConfirmGrant
from toolfence.guard.decision import GuardDecision
from toolfence.guard.provenance import ProvenanceStore
from toolfence.guard.proxy import GuardedProxy
from toolfence.guard.taint import SessionTaint
from toolfence.integration.installer import install_guard, verify_guard_invariant


# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------

class _StubTool:
    """Minimal tool stub that satisfies the GuardedProxy interface."""

    def __init__(self, name: str, result: str = "ok") -> None:
        self.name = name
        self.schema: Any = None
        self.description: str | None = None
        self._result = result

    async def execute(self, **params: Any) -> Any:
        return self._result


class _StubRegistry:
    """Minimal ToolRegistry stub (no nanobot dependency)."""

    def __init__(self, tools: dict[str, Any] | None = None) -> None:
        self._tools: dict[str, Any] = tools or {}

    def register(self, tool: Any) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Any:
        return self._tools.get(name)

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())


def _make_surface() -> SurfaceFile:
    """Minimal surface map — all tools absent so defaults apply."""
    return SurfaceFile(version=1, tools=[])


def _install(registry: _StubRegistry, **kwargs: Any) -> None:
    """Call install_guard with minimal defaults."""
    install_guard(
        registry,
        _make_surface(),
        ProvenanceStore(),
        SessionTaint(),
        GuardDecision(),
        lambda event: None,   # on_held no-op
        ConfirmGrant(),
        guard_on=kwargs.get("guard_on", True),
        datamark_on=kwargs.get("datamark_on", False),
    )


# ---------------------------------------------------------------------------
# GRD-2  Every tool is wrapped (even built-ins like read_file)
# ---------------------------------------------------------------------------

def test_all_tools_wrapped() -> None:
    """3 MCP tools + 1 read_file → all 4 replaced by GuardedProxy."""
    registry = _StubRegistry({
        "mcp_galaxium_get_flights": _StubTool("mcp_galaxium_get_flights"),
        "mcp_galaxium_create_hold": _StubTool("mcp_galaxium_create_hold"),
        "mcp_galaxium_cancel_booking": _StubTool("mcp_galaxium_cancel_booking"),
        "read_file": _StubTool("read_file"),
    })

    _install(registry)

    assert len(registry._tools) == 4
    for name, tool in registry._tools.items():
        assert isinstance(tool, GuardedProxy), (
            f"Expected GuardedProxy for '{name}', got {type(tool).__name__}"
        )


# ---------------------------------------------------------------------------
# GRD-3a  Reconnect re-wrap: register patch auto-wraps new raw tools
# ---------------------------------------------------------------------------

def test_reconnect_rewraps() -> None:
    """After install_guard, calling registry.register(raw_tool) stores a GuardedProxy."""
    registry = _StubRegistry({
        "mcp_existing": _StubTool("mcp_existing"),
    })

    _install(registry)

    # Simulate a reconnect re-registration with a fresh raw tool.
    new_raw = _StubTool("mcp_reconnected")
    registry.register(new_raw)

    stored = registry._tools["mcp_reconnected"]
    assert isinstance(stored, GuardedProxy), (
        f"Expected GuardedProxy after reconnect register, got {type(stored).__name__}"
    )


# ---------------------------------------------------------------------------
# GRD-3b  verify_guard_invariant raises on bare tool
# ---------------------------------------------------------------------------

def test_invariant_raises_on_bare_tool() -> None:
    """Injecting a bare StubTool after install → verify_guard_invariant raises RuntimeError."""
    registry = _StubRegistry({
        "mcp_tool_a": _StubTool("mcp_tool_a"),
    })

    _install(registry)

    # Bypass the patched register to inject a bare tool directly.
    registry._tools["mcp_tool_a"] = _StubTool("mcp_tool_a")

    with pytest.raises(RuntimeError, match="Guard invariant violated"):
        verify_guard_invariant(registry)


def test_invariant_passes_when_all_wrapped() -> None:
    """verify_guard_invariant does not raise when all tools are GuardedProxy."""
    registry = _StubRegistry({
        "mcp_tool_b": _StubTool("mcp_tool_b"),
    })
    _install(registry)
    # Should not raise.
    verify_guard_invariant(registry)


# ---------------------------------------------------------------------------
# GRD-13  spawn and exec removed
# ---------------------------------------------------------------------------

def test_spawn_exec_removed() -> None:
    """spawn and exec are absent from _tools after install_guard."""
    registry = _StubRegistry({
        "mcp_good_tool": _StubTool("mcp_good_tool"),
        "spawn": _StubTool("spawn"),
        "exec": _StubTool("exec"),
    })

    _install(registry)

    assert "spawn" not in registry._tools, "'spawn' should have been removed"
    assert "exec" not in registry._tools, "'exec' should have been removed"
    # The legitimate tool must remain (and be wrapped).
    assert "mcp_good_tool" in registry._tools
    assert isinstance(registry._tools["mcp_good_tool"], GuardedProxy)


# ---------------------------------------------------------------------------
# GRD-6  read_file result recorded in provenance via proxy execute
# ---------------------------------------------------------------------------

def test_read_file_provenance_recorded() -> None:
    """Executing the wrapped read_file proxy records the result in provenance."""
    provenance = ProvenanceStore()
    taint = SessionTaint()

    registry = _StubRegistry({
        "read_file": _StubTool("read_file", result="secret_content_42"),
    })

    install_guard(
        registry,
        _make_surface(),
        provenance,
        taint,
        GuardDecision(),
        lambda event: None,
        ConfirmGrant(),
        guard_on=False,   # transparent; we only care about provenance recording
        datamark_on=False,
    )

    proxy = registry._tools["read_file"]
    assert isinstance(proxy, GuardedProxy)

    # Execute the proxy — this should call the real tool and record the result.
    result = asyncio.run(proxy.execute(path="some/file.txt"))

    # The result string should appear in the provenance store as "untrusted"
    # (read_file not in surface_map → defaults to untrusted trust_label).
    resolved = provenance.resolve_argument("secret_content_42")
    assert resolved == "untrusted", (
        f"Expected 'untrusted' provenance for read_file result, got {resolved!r}"
    )


# ---------------------------------------------------------------------------
# Idempotence — double install must not double-wrap
# ---------------------------------------------------------------------------

def test_double_install_does_not_double_wrap() -> None:
    """Calling install_guard twice on the same registry leaves each tool wrapped once."""
    registry = _StubRegistry({
        "mcp_tool_x": _StubTool("mcp_tool_x"),
    })

    _install(registry)
    first_proxy = registry._tools["mcp_tool_x"]
    assert isinstance(first_proxy, GuardedProxy)

    # Second call — should be a no-op on the already-wrapped tool.
    _install(registry)
    second_proxy = registry._tools["mcp_tool_x"]

    # Same object: the proxy was not re-wrapped.
    assert second_proxy is first_proxy, (
        "install_guard called twice must not create a proxy-of-proxy"
    )
    # Still a single-layer GuardedProxy (not a GuardedProxy wrapping a GuardedProxy).
    assert isinstance(second_proxy, GuardedProxy)
    assert not isinstance(second_proxy._tool, GuardedProxy), (
        "inner _tool must be the original raw tool, not another GuardedProxy"
    )


# ---------------------------------------------------------------------------
# GRD-13 continued — register patch must block forbidden names added later
# ---------------------------------------------------------------------------

def test_register_patch_blocks_forbidden() -> None:
    """After install_guard, registering 'spawn' or 'exec' is silently ignored."""
    registry = _StubRegistry({
        "mcp_tool_y": _StubTool("mcp_tool_y"),
    })

    _install(registry)

    # Try to re-register forbidden tools via the patched register.
    registry.register(_StubTool("spawn"))
    registry.register(_StubTool("exec"))

    assert "spawn" not in registry._tools, "'spawn' must not be re-registered after install"
    assert "exec" not in registry._tools, "'exec' must not be re-registered after install"
    # Legitimate tool unaffected.
    assert "mcp_tool_y" in registry._tools


# ---------------------------------------------------------------------------
# Import boundary check — installer.py must not import nanobot or engine
# ---------------------------------------------------------------------------

def test_installer_no_nanobot_import() -> None:
    """installer.py source must not contain a nanobot import."""
    from pathlib import Path
    src = (Path(__file__).parent.parent / "toolfence" / "integration" / "installer.py").read_text()
    forbidden = ["from nanobot", "import nanobot"]
    for pat in forbidden:
        assert pat not in src, (
            f"installer.py must not import nanobot at module level (found {pat!r})"
        )


def test_installer_no_engine_import() -> None:
    """installer.py source must not import toolfence.engine."""
    from pathlib import Path
    src = (Path(__file__).parent.parent / "toolfence" / "integration" / "installer.py").read_text()
    assert "toolfence.engine" not in src, (
        "installer.py must not import toolfence.engine"
    )
