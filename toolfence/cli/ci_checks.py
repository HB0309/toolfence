"""CI safety checks for ToolFence (C-5).

Two callable functions used by the GitHub Action and the ``toolfence ci-check``
subcommand.  Both return ``(exit_code: int, message: str)`` so the Action can
post a PR comment on failure.

No network, no nanobot, no environment-variable reads at CI time.

Import boundary
---------------
May import from ``toolfence.engine``, ``toolfence.contracts``,
``toolfence.integration``.  Must NOT import nanobot directly.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

from toolfence.contracts.surface import SurfaceFile
from toolfence.engine.surface import (
    check_description_drift,
    get_action_class,
    suggest_action_class,
)
from toolfence.integration.installer import verify_guard_invariant

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# surface_diff_check
# ---------------------------------------------------------------------------

_RISK: dict[str, int] = {"read": 0, "state-changing": 1, "irreversible": 2}


def surface_diff_check(
    surface_path: "str | Path",
    live_tool_list: "list[dict]",
) -> "tuple[int, str]":
    """Compare committed *surface_path* against *live_tool_list*.

    Returns ``(0, "ok")`` when the surface is clean, or ``(1, message)`` for
    any of three failure types (CLI-5):

    1. **Unknown tool** — a tool in *live_tool_list* is absent from
       *surface_path*.  Message contains the tool name.
    2. **Action-class mismatch** — a tool's stored ``action_class`` in
       *surface_path* differs from what the live heuristic would suggest.
       Message contains the tool name.
    3. **Changed description hash** — ``description_sha256`` in the surface
       does not match the current description.  Detected via
       ``check_description_drift``.  Message contains the tool name.

    Parameters
    ----------
    surface_path:
        Path to the committed ``surface.json`` (or fixture equivalent).
    live_tool_list:
        Current tool definitions.  Each dict must contain ``"name"`` (str)
        and optionally ``"description"`` (str), ``"method"`` (str),
        ``"route"`` (str).
    """
    log.info("surface_diff_check: comparing %s against %d live tool(s)", surface_path, len(live_tool_list))
    surface_path = Path(surface_path)
    try:
        surface = SurfaceFile.model_validate(
            json.loads(surface_path.read_text(encoding="utf-8"))
        )
    except Exception as exc:  # noqa: BLE001
        log.error("surface_diff_check: failed to load surface file %s — %s", surface_path, exc)
        return 1, f"Failed to load surface file {surface_path}: {exc}"

    stored_names = {entry.name for entry in surface.tools}
    findings: list[str] = []

    # --- Failure type 1: unknown tool ---
    for tool in live_tool_list:
        name = tool.get("name", "")
        if name and name not in stored_names:
            findings.append(
                f"Unknown tool not in surface.json: '{name}'"
            )

    # --- Failure type 2: action-class mismatch ---
    for tool in live_tool_list:
        name = tool.get("name", "")
        if not name or name not in stored_names:
            continue  # unknown tools already reported above
        route = tool.get("route", "")
        method = tool.get("method") or (route.split()[0].upper() if route else "POST")
        suggested = suggest_action_class(method, name)
        stored = get_action_class(surface, name)
        if _RISK.get(suggested, 1) > _RISK.get(stored, 1):
            findings.append(
                f"Action-class mismatch for '{name}': "
                f"surface has '{stored}', live heuristic suggests '{suggested}'"
            )
        elif suggested != stored:
            log.debug(
                "surface_diff_check: '%s' stored as '%s', heuristic suggests '%s' (reviewed override — ok)",
                name, stored, suggested,
            )
            print(
                f"Warning: '{name}' stored as '{stored}', "
                f"heuristic suggests '{suggested}' (reviewed override — ok)",
                file=sys.stderr,
            )

    # --- Failure type 3: changed description hash ---
    drifted = check_description_drift(surface, live_tool_list)
    for name in drifted:
        findings.append(
            f"Description hash changed for '{name}' — re-review required"
        )

    if findings:
        log.warning("surface_diff_check: %d finding(s):\n%s", len(findings), "\n".join(findings))
        return 1, "\n".join(findings)
    log.info("surface_diff_check: no findings — surface is clean")
    return 0, "ok"


# ---------------------------------------------------------------------------
# guard_wiring_check
# ---------------------------------------------------------------------------

def guard_wiring_check(registry: Any) -> "tuple[int, str]":
    """Verify all tools in *registry._tools* are ``GuardedProxy`` instances.

    Wraps ``verify_guard_invariant``; returns ``(0, "ok")`` on success or
    ``(1, error message)`` if any bare tool is found.

    Parameters
    ----------
    registry:
        Any object that exposes ``._tools`` (dict) and ``.tool_names``
        (list[str]) — the same interface used by nanobot's ``ToolRegistry``
        and the stub registry in tests.
    """
    try:
        verify_guard_invariant(registry)
    except RuntimeError as exc:
        return 1, str(exc)
    return 0, "ok"
