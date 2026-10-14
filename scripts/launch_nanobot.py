"""Guard-wired async launcher for direct / eval nanobot runs (B-3).

Usage
-----
    python scripts/launch_nanobot.py \\
        --prompt "Find the cheapest flight from Earth to Mars." \\
        --session-key "eval:alice:1"

    # Override config and surface map:
    python scripts/launch_nanobot.py \\
        --config config/nanobot.spike.json \\
        --surface fixtures/surface_fixture.json \\
        --prompt "..."

The launcher:
1. Loads nanobot config and creates a fresh temp workspace.
2. Loads surface.json so Guard knows action_class / trust_label per tool
   (without this every tool defaults to state-changing + untrusted).
3. Instantiates the full Guard stack (ProvenanceStore, SessionTaint,
   GuardDecision, ConfirmGrant).
4. Connects MCP servers via MCPProvider.
5. Calls install_guard to wrap every registry tool with GuardedProxy.
6. Calls provenance.record_user_message(prompt) so user-supplied values
   are resolved as "user" provenance (not untrusted) on the first turn.
7. Calls verify_guard_invariant to assert all tools are wrapped.
8. Runs agent_loop.process_direct and returns the response.
9. Tears down cleanly in a finally block.

This script is the basis for NanobotAdapter (B-4).  It intentionally has no
MessageBus subscriber — process_direct builds InboundMessage internally and
never goes through the bus inbound queue.

Default config is config/nanobot.eval.json (not the spike config — the spike
config omits X-Traveler-Id, which causes 403s on cancel and booking routes).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from toolfence.contracts.surface import SurfaceFile
from toolfence.guard.confirm import ConfirmGrant
from toolfence.guard.decision import GuardDecision
from toolfence.guard.provenance import ProvenanceStore
from toolfence.guard.taint import SessionTaint
from toolfence.integration.installer import install_guard, verify_guard_invariant

_DEFAULT_CONFIG = "config/nanobot.eval.json"
_DEFAULT_SURFACE = "results/surface.json"


def _load_surface(surface_path: str) -> SurfaceFile:
    """Load surface.json; exit with a clear message if the file is missing."""
    p = Path(surface_path)
    if not p.exists():
        sys.exit(
            f"Error: surface file not found: {surface_path}\n"
            "Run 'toolfence scan' (A-1) or copy fixtures/surface_fixture.json to get started."
        )
    return SurfaceFile.model_validate(json.loads(p.read_text(encoding="utf-8")))


def _noop_on_held(event: Any) -> None:
    """Placeholder held-call handler — prints a warning; B-4b wires the real one."""
    print(
        f"[warn] tool '{event.tool_name}' held (reason={event.reason}); "
        "no channel adapter installed — call will not be retried.",
        file=sys.stderr,
    )


async def _run(
    config_path: str,
    surface_path: str,
    prompt: str,
    session_key: str,
    *,
    guard_on: bool = True,
    datamark_on: bool = False,
) -> dict[str, Any]:
    """Run one agent turn with Guard wiring and return a result dict."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.tools.mcp import MCPProvider
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.bus.queue import MessageBus
    from nanobot.cli.runtime_config import _load_runtime_config
    from nanobot.providers.factory import make_provider

    surface_map = _load_surface(surface_path)

    workspace = tempfile.mkdtemp(prefix="toolfence-launch-")
    try:
        runtime_config = _load_runtime_config(config_path, workspace)

        # Guard stack — one instance per session.
        provenance = ProvenanceStore()
        taint = SessionTaint()
        decision = GuardDecision()
        confirm_grant = ConfirmGrant()

        bus = MessageBus()
        tools = ToolRegistry()
        mcp_provider = MCPProvider.from_config(runtime_config, tools)
        provider = make_provider(runtime_config)

        agent_loop = AgentLoop.from_config(
            runtime_config,
            bus,
            provider=provider,
            tool_registry=tools,
        )

        try:
            await mcp_provider.connect()

            # Install Guard over every tool now in the registry.
            install_guard(
                tools,
                surface_map,
                provenance,
                taint,
                decision,
                _noop_on_held,
                confirm_grant,
                guard_on=guard_on,
                datamark_on=datamark_on,
            )

            # Record the user's prompt so values the user typed are resolved as
            # "user" provenance (not untrusted) inside GuardedProxy.
            provenance.record_user_message(prompt)

            # Per-turn invariant check — every tool must be wrapped.
            verify_guard_invariant(tools)

            response = await agent_loop.process_direct(
                prompt,
                session_key=session_key,
            )
        finally:
            try:
                await agent_loop.aclose()
            finally:
                await mcp_provider.aclose()
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    return {
        "response": response.content if response else None,
        "session_key": session_key,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Guard-wired nanobot launcher (B-3).")
    parser.add_argument("--config", default=_DEFAULT_CONFIG,
                        help=f"nanobot config JSON (default: {_DEFAULT_CONFIG})")
    parser.add_argument("--surface", default=_DEFAULT_SURFACE,
                        help=f"surface.json path (default: {_DEFAULT_SURFACE})")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--session-key", default="eval:direct:1")
    parser.add_argument("--no-guard", action="store_true",
                        help="Disable Guard (transparent proxy).")
    parser.add_argument("--datamark", action="store_true",
                        help="Enable datamarking of untrusted results.")
    args = parser.parse_args()

    result = asyncio.run(_run(
        args.config,
        args.surface,
        args.prompt,
        args.session_key,
        guard_on=not args.no_guard,
        datamark_on=args.datamark,
    ))
    print(result.get("response") or "(no response)")


if __name__ == "__main__":
    main()
