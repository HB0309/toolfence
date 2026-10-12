"""Guard-related contracts: HeldCallEvent, GuardResult type alias, and ProxyStub."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


# Type alias used throughout the codebase for a guard decision.
GuardResult = Literal["pass", "hold"]


@dataclass
class HeldCallEvent:
    """Emitted by GuardedProxy when a tool call is held for user confirmation."""

    tool_name: str
    arguments: dict[str, Any]
    arguments_hash: str              # SHA-256 of sorted canonical JSON of arguments
    reason: Literal[
        "irreversible",
        "tainted_session",
        "untrusted_argument",
    ]
    untrusted_read_count: int        # number of untrusted results read this session
    untrusted_arg_name: str | None   # which argument triggered (reason == "untrusted_argument")


class ProxyStub:
    """Minimal pass-through proxy that satisfies the GuardedProxy interface.

    Wraps a real tool object from nanobot's registry and forwards all calls
    unchanged — no Guard logic.  Used by Track B (B-3) before C-2
    (GuardedProxy) is implemented.

    The wrapped tool must be an object that exposes:
      - ``name``        (str) — tool identifier
      - ``schema``      (dict, optional) — JSON Schema of the tool's parameters
      - ``description`` (str, optional) — human-readable description
      - ``execute(**params)`` (async callable) — the actual tool implementation

    Any attribute not explicitly handled is forwarded to the wrapped tool so
    that code inspecting registry entries sees the original values.
    """

    def __init__(self, tool: Any) -> None:
        # Store under a name that won't collide with forwarded attributes.
        object.__setattr__(self, "_tool", tool)

    # -----------------------------------------------------------------
    # Explicit forwarding for the three attributes B-3 / the installer
    # needs to read directly.
    # -----------------------------------------------------------------

    @property
    def name(self) -> str:
        return self._tool.name  # type: ignore[attr-defined]

    @property
    def schema(self) -> Any:
        return getattr(self._tool, "schema", None)

    @property
    def description(self) -> str | None:
        return getattr(self._tool, "description", None)

    # -----------------------------------------------------------------
    # Pass-through execute — identical signature to GuardedProxy.
    # -----------------------------------------------------------------

    async def execute(self, **params: Any) -> Any:
        """Forward the call to the wrapped tool with no Guard logic."""
        return await self._tool.execute(**params)  # type: ignore[attr-defined]

    # -----------------------------------------------------------------
    # Generic attribute forwarding so registry inspection still works.
    # -----------------------------------------------------------------

    def __getattr__(self, item: str) -> Any:
        return getattr(object.__getattribute__(self, "_tool"), item)
