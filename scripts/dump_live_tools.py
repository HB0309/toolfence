"""Dump every tool name and description that nanobot registers for an eval run.

Connects to a live Galaxium server via the real AgentLoop + MCPProvider path
(identical to launch_nanobot.py — no hand-rolled MCP, no naming-rule copy).
Runs install_guard so spawn is removed and all tools are wrapped, giving the
exact same registry shape as a live eval turn, minus the model call.

Prints one block per tool:
    name:   <tool_name>
    sha256: <description_sha256 via toolfence/engine/surface.py>
    desc:
    <full description text>
    ---

Usage (Galaxium must be running at http://localhost:8001):
    python scripts/dump_live_tools.py
    python scripts/dump_live_tools.py --all-tools          # bypass enabledTools filter
    python scripts/dump_live_tools.py --config config/nanobot.eval.json
    python scripts/dump_live_tools.py --output results/tool_dump.txt
"""
from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

# Ensure toolfence is importable when running from the repo root with the
# nanobot venv (targets/nanobot/.venv) which does not have toolfence installed.
sys.path.insert(0, str(Path(__file__).parent.parent))

# Toolfence imports (no nanobot boundary crossing)
from toolfence.engine.surface import description_sha256
from toolfence.contracts.surface import SurfaceFile
from toolfence.guard.confirm import ConfirmGrant
from toolfence.guard.decision import GuardDecision
from toolfence.guard.provenance import ProvenanceStore
from toolfence.guard.taint import SessionTaint
from toolfence.integration.installer import install_guard

_DEFAULT_CONFIG = "config/nanobot.eval.json"


def _noop_on_held(event):  # type: ignore[no-untyped-def]
    pass


async def _dump(config_path: str, *, all_tools: bool = False) -> list[tuple[str, str, str]]:
    """Return list of (name, description, sha256) for every tool in the registry.

    Parameters
    ----------
    all_tools:
        When True, override every MCP server's ``enabledTools`` list to ``["*"]``
        in memory so every tool the server exposes is registered, regardless of
        what the config file restricts.  The config file is never modified.
    """
    import os

    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.tools.mcp import MCPProvider
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.bus.queue import MessageBus
    from nanobot.cli.runtime_config import _load_runtime_config
    from nanobot.providers.factory import make_provider

    # _load_runtime_config validates env vars; set a dummy key so config
    # parsing succeeds.  No model call is made, so the key is never used.
    os.environ.setdefault("OPENROUTER_API_KEY", "dummy-for-tool-dump")

    workspace = tempfile.mkdtemp(prefix="toolfence-dump-")
    try:
        runtime_config = _load_runtime_config(config_path, workspace)

        if all_tools:
            # Patch the in-memory config only — do not touch the file.
            for server_cfg in runtime_config.tools.mcp_servers.values():
                server_cfg.enabled_tools = ["*"]

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
        except Exception as exc:
            print(
                f"ERROR: Could not connect to MCP server — is Galaxium running?\n  {exc}",
                file=sys.stderr,
            )
            await agent_loop.aclose()
            sys.exit(1)

        try:
            # Install Guard (removes spawn, wraps everything else).
            # Pass an empty surface — we only need the side-effect of spawn removal.
            empty_surface = SurfaceFile(version=1, tools=[])
            install_guard(
                tools,
                empty_surface,
                ProvenanceStore(),
                SessionTaint(),
                GuardDecision(),
                _noop_on_held,
                ConfirmGrant(),
                guard_on=False,   # transparent — we only want spawn removed
                datamark_on=False,
            )

            results: list[tuple[str, str, str]] = []
            for name in sorted(tools.tool_names):
                tool = tools.get(name)
                desc = tool.description if tool is not None else ""
                sha = description_sha256(desc)
                results.append((name, desc, sha))
            return results
        finally:
            await agent_loop.aclose()
            await mcp_provider.aclose()
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dump tool names + descriptions from a live nanobot+Galaxium session."
    )
    parser.add_argument(
        "--config", default=_DEFAULT_CONFIG,
        help=f"nanobot config JSON (default: {_DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--all-tools", action="store_true",
        help=(
            "Override every MCP server's enabledTools to ['*'] in memory so every "
            "tool the server exposes is registered (used to generate surface.json hashes)."
        ),
    )
    parser.add_argument(
        "--output", default=None,
        help="Write output to file instead of stdout",
    )
    args = parser.parse_args()

    entries = asyncio.run(_dump(args.config, all_tools=args.all_tools))

    lines: list[str] = []
    mcp_entries = [(n, d, s) for n, d, s in entries if n.startswith("mcp_")]
    builtin_entries = [(n, d, s) for n, d, s in entries if not n.startswith("mcp_")]

    lines.append(f"# {len(entries)} tools total  "
                 f"({len(mcp_entries)} MCP, {len(builtin_entries)} built-in)\n")

    lines.append("## MCP tools\n")
    for name, desc, sha in mcp_entries:
        lines.append(f"name:   {name}")
        lines.append(f"sha256: {sha}")
        lines.append(f"desc:\n{desc}")
        lines.append("---")

    lines.append("\n## Built-in tools\n")
    for name, desc, sha in builtin_entries:
        lines.append(f"name:   {name}")
        lines.append(f"sha256: {sha}")
        lines.append(f"desc:\n{desc}")
        lines.append("---")

    output = "\n".join(lines) + "\n"

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
