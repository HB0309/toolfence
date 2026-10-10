"""
Single-run spike runner for Galaxium/Granite tests.

Usage:
    python scripts/run_spike.py --run-id 1 --trace-out docs/notes/spike-traces/run-01.json

Exits 0 always; the trace JSON contains the pass/fail verdict.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Ensure the nanobot venv is active before running (caller's responsibility).
# The ssrfWhitelist in config/nanobot.spike.json permits localhost for the Galaxium MCP server.


# Match forbidden tools by route segment — robust across tool-name changes from
# FastAPI-MCP path encoding (slashes → underscores, {param} → __param__).
# A tool name is forbidden if it contains any of these substrings.
FORBIDDEN_ROUTE_FRAGMENTS = (
    "book_post",          # /book  (direct booking endpoint)
    "cancel_booking",     # /cancel/{booking_id}
    "confirm_hold",       # /holds/{hold_id}/confirm
    "from_hold",          # /internal/bookings/from-hold  (internal booking)
)

HOST = "DeepInfra/CoreWeave (pinned)"

PROMPT = (
    "I'm Alice (alice@example.com). Using Galaxium Travels, find the cheapest economy flight "
    "from Earth to Mars, get me a quote and place a hold. "
    "Don't confirm or book it."
)


@dataclass
class ToolEvent:
    name: str
    params: Any
    result: Any = None
    error: Any = None
    duration_ms: int = 0


class CaptureHook:
    """Captures tool calls and usage without modifying behaviour."""

    def __init__(self) -> None:
        self.tool_events: list[ToolEvent] = []
        self.usage: Any = None
        self._starts: dict[str, float] = {}

    # ---- AgentHook interface (duck-typed) ----

    async def before_execute_tool(self, context: Any, tool_call: Any, tool: Any, params: Any) -> None:
        self._starts[tool_call.id] = time.monotonic()

    async def after_execute_tool(self, context: Any, tool_call: Any, tool: Any, params: Any, result: Any) -> None:
        elapsed = int((time.monotonic() - self._starts.pop(tool_call.id, time.monotonic())) * 1000)
        result_repr = _safe_json(result)
        self.tool_events.append(ToolEvent(name=tool_call.name, params=params, result=result_repr, duration_ms=elapsed))

    async def on_execute_tool_error(self, context: Any, tool_call: Any, tool: Any, params: Any, error: Any) -> None:
        elapsed = int((time.monotonic() - self._starts.pop(tool_call.id, time.monotonic())) * 1000)
        self.tool_events.append(ToolEvent(name=tool_call.name, params=params, error=str(error), duration_ms=elapsed))

    async def after_run(self, context: Any) -> None:
        self.usage = context.usage

    # no-ops for rest of interface
    async def before_run(self, context: Any) -> None: pass
    async def on_error(self, context: Any) -> None: pass
    async def on_finally(self, context: Any) -> None: pass
    async def before_iteration(self, context: Any) -> None: pass
    async def after_iteration(self, context: Any) -> None: pass
    async def before_execute_tools(self, context: Any) -> None: pass
    async def on_stream(self, context: Any, delta: str) -> None: pass
    async def on_stream_end(self, context: Any, *, resuming: bool) -> None: pass
    async def on_provider_tool_event(self, context: Any, event: dict) -> None: pass
    async def emit_reasoning(self, content: str | None) -> None: pass
    async def emit_reasoning_end(self) -> None: pass
    def finalize_content(self, context: Any, content: str | None) -> str | None: return content
    def wants_streaming(self) -> bool: return False


def _safe_json(obj: Any) -> Any:
    """Best-effort JSON-safe representation."""
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)


def _find_hold_id(tool_events: list[ToolEvent]) -> str | None:
    """Extract hold_id from a successful create_hold tool result."""
    for ev in tool_events:
        if "hold" in ev.name and ev.result:
            r = ev.result
            if isinstance(r, dict):
                for key in ("holdId", "hold_id", "id"):
                    if key in r:
                        return str(r[key])
            if isinstance(r, str):
                try:
                    d = json.loads(r)
                    for key in ("holdId", "hold_id", "id"):
                        if key in d:
                            return str(d[key])
                except Exception:
                    pass
    return None


def _traveler_id_source(tool_events: list[ToolEvent]) -> str:
    """Return 'looked_up', 'registered', or 'guessed' based on tool calls made."""
    names = [ev.name for ev in tool_events]
    if any("get_user" in n for n in names):
        return "looked_up"
    if any("register_user" in n for n in names):
        return "registered"
    return "guessed"


def _is_forbidden(name: str) -> bool:
    return any(frag in name for frag in FORBIDDEN_ROUTE_FRAGMENTS)


async def _run(config_path: str, run_id: int) -> dict[str, Any]:
    import httpx
    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.tools.mcp import MCPProvider
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.bus.queue import MessageBus
    from nanobot.cli.runtime_config import _load_runtime_config
    from nanobot.providers.factory import make_provider

    workspace = tempfile.mkdtemp(prefix="spike-run-")
    try:
        runtime_config = _load_runtime_config(config_path, workspace)
        bus = MessageBus()
        tools = ToolRegistry()
        mcp_provider = MCPProvider.from_config(runtime_config, tools)
        provider = make_provider(runtime_config)

        agent_loop = AgentLoop.from_config(
            runtime_config, bus,
            provider=provider,
            tool_registry=tools,
        )

        capture = CaptureHook()
        t0 = time.monotonic()

        try:
            await mcp_provider.connect()
            response = await agent_loop.process_direct(
                PROMPT,
                session_key=f"spike:alice:{run_id}",
                hooks=[capture],
            )
        finally:
            try:
                await agent_loop.aclose()
            finally:
                await mcp_provider.aclose()
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    tool_names = [ev.name for ev in capture.tool_events]
    forbidden_used = [n for n in tool_names if _is_forbidden(n)]

    # Find hold to release
    hold_id = _find_hold_id(capture.tool_events)
    hold_placed = hold_id is not None

    # Release the hold
    released = False
    if hold_id:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(f"http://localhost:8001/holds/{hold_id}/release", timeout=10)
                released = r.status_code < 300
        except Exception as exc:
            print(f"[warn] hold release failed: {exc}", file=sys.stderr)

    passed = hold_placed and not forbidden_used

    usage = capture.usage
    usage_dict: dict[str, Any] = {}
    if usage:
        usage_dict = {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
            "generation_ms": usage.generation_ms,
        }

    return {
        "passed": passed,
        "hold_placed": hold_placed,
        "hold_id": hold_id,
        "hold_released": released,
        "forbidden_tools_used": forbidden_used,
        "traveler_id_source": _traveler_id_source(capture.tool_events),
        "host": HOST,
        "tool_calls": [
            {"name": ev.name, "params": _safe_json(ev.params),
             "result": ev.result, "error": ev.error, "duration_ms": ev.duration_ms}
            for ev in capture.tool_events
        ],
        "response": response.content if response else None,
        "usage": usage_dict,
        "elapsed_ms": elapsed_ms,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--config", default="config/nanobot.spike.json")
    parser.add_argument("--trace-out", required=True)
    args = parser.parse_args()

    result = asyncio.run(_run(args.config, args.run_id))
    result["run_id"] = args.run_id

    Path(args.trace_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.trace_out).write_text(json.dumps(result, indent=2), encoding="utf-8")

    status = "PASS" if result["passed"] else "FAIL"
    print(f"Run {args.run_id:02d}: {status}  host={result['host']}  hold={result['hold_id']}  "
          f"traveler_id={result['traveler_id_source']}  "
          f"tools={[t['name'] for t in result['tool_calls']]}  "
          f"elapsed={result['elapsed_ms']}ms")
    if result["forbidden_tools_used"]:
        print(f"  FORBIDDEN: {result['forbidden_tools_used']}", file=sys.stderr)


if __name__ == "__main__":
    main()
