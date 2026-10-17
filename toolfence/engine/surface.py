"""Surface scanner — maps an agent's tool surface to a SurfaceFile draft.

Three source types are supported:

* ``scan_json(path)``      — plain JSON tool list (dict with "tools" key, or list)
* ``scan_openapi(source)`` — OpenAPI spec (URL or file path)
* ``scan_mcp(url)``        — MCP server tool list via HTTP GET /tools

All three methods return a ``SurfaceFile`` whose ``action_class`` and
``trust_label`` fields carry *suggested* values.  A person reviews and commits
the file; nothing is final until that review happens.

Module-level helpers
--------------------
``suggest_action_class(http_method, name)``
    Heuristic per ENG-2:
    - Names containing ``cancel``, ``confirm``, or ``internal`` → ``irreversible``
    - ``GET`` → ``read``
    - ``POST`` / ``PUT`` / ``PATCH`` / ``DELETE`` → ``state-changing``
    Name-based check takes priority over method-based check.

``description_sha256(text)``
    SHA-256 of the description string; returns 64 lowercase hex chars.

``get_action_class(surface, tool_name)``
    Look up a tool's action class; returns ``"state-changing"`` if the tool is
    absent (BASE-2 fail-closed default).

``check_description_drift(surface, live_tools)``
    Compare stored hashes against current tool descriptions; return the list of
    tool names whose hashes have changed (ENG-3).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.request import urlopen
from urllib.error import URLError

from toolfence.contracts.surface import SurfaceEntry, SurfaceFile

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sentinel SHA-256 used when a tool carries no description
# ---------------------------------------------------------------------------
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()  # 64 lowercase hex chars

# ---------------------------------------------------------------------------
# MCP tool name sanitise+truncate rule (copied from nanobot — no import)
# ---------------------------------------------------------------------------
_MAX_MCP_TOOL_NAME = 64
_HASH_LEN = 8
_SANITIZE_RE = re.compile(r"[^a-z0-9_]+")  # replace non-alphanumeric (step 1)
_COLLAPSE_RE = re.compile(r"_+")            # collapse underscore runs (step 2)


def _mcp_tool_name(server_name: str, operation_id: str) -> str:
    """Return the nanobot-style MCP tool name for *server_name* + *operation_id*.

    Mirrors nanobot's ``_sanitize_mcp_tool_name`` + ``_limit_tool_name`` rules
    without importing from nanobot (AGENTS.md hard boundary).

    Two-step sanitisation (issue #5):
    1. Replace anything outside ``[a-z0-9_]`` with ``_`` (after lowercasing).
    2. Collapse every run of ``_`` to a single ``_``.

    FastAPI ``operationId`` values encode path parameters with double underscores
    (e.g. ``cancel__booking_id__post``); step 2 collapses those so the result
    matches what nanobot registers.

    If the result is longer than 64 characters it is truncated to 55 chars and
    an 8-char SHA-1 suffix is appended (``{raw[:55]}_{sha1[:8]}`` = 64 chars).
    """
    raw = _SANITIZE_RE.sub("_", f"mcp_{server_name}_{operation_id}".lower())
    raw = _COLLAPSE_RE.sub("_", raw)
    if len(raw) <= _MAX_MCP_TOOL_NAME:
        return raw
    digest = hashlib.sha1(raw.encode()).hexdigest()[:_HASH_LEN]
    return f"{raw[:_MAX_MCP_TOOL_NAME - _HASH_LEN - 1]}_{digest}"


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def description_sha256(text: str) -> str:
    """Return the SHA-256 hex digest of *text* (UTF-8 encoded).

    Parameters
    ----------
    text:
        The tool description string.  An empty string is accepted and hashed
        to the well-known empty-SHA-256.

    Returns
    -------
    str
        64 lowercase hexadecimal characters.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def suggest_action_class(http_method: str, name: str) -> str:
    """Suggest an action class from the HTTP method and tool name (ENG-2).

    Priority order
    --------------
    1. Name contains ``cancel``, ``confirm``, or ``internal`` → ``irreversible``
    2. HTTP method is ``GET``                                  → ``read``
    3. Any other method (POST / PUT / PATCH / DELETE / …)     → ``state-changing``

    Parameters
    ----------
    http_method:
        HTTP verb (case-insensitive).
    name:
        Tool name or route path fragment (case-insensitive for the keyword
        check so that ``Cancel`` also matches).

    Returns
    -------
    str
        One of ``"read"``, ``"state-changing"``, ``"irreversible"``.
    """
    name_lower = name.lower()
    if any(kw in name_lower for kw in ("cancel", "confirm", "internal")):
        return "irreversible"
    if http_method.upper() == "GET":
        return "read"
    return "state-changing"


def get_action_class(surface: SurfaceFile, tool_name: str) -> str:
    """Return the action class for *tool_name* from *surface*.

    If *tool_name* is not present in *surface*, returns ``"state-changing"``
    (BASE-2 fail-closed default).

    Parameters
    ----------
    surface:
        A validated ``SurfaceFile`` instance.
    tool_name:
        The tool name to look up (exact match).

    Returns
    -------
    str
        One of ``"read"``, ``"state-changing"``, ``"irreversible"``.
    """
    for entry in surface.tools:
        if entry.name == tool_name:
            return entry.action_class
    return "state-changing"


def check_description_drift(
    surface: SurfaceFile,
    live_tools: list[dict[str, Any]],
) -> list[str]:
    """Return tool names whose description hash has changed since review (ENG-3).

    Parameters
    ----------
    surface:
        The committed ``SurfaceFile`` (reviewed hashes).
    live_tools:
        Current tool definitions.  Each dict must contain ``"name"`` (str) and
        optionally ``"description"`` (str).  Tools not in *surface* are ignored.

    Returns
    -------
    list[str]
        Tool names whose current hash differs from the stored hash.  Empty list
        means no drift detected.
    """
    stored: dict[str, str] = {e.name: e.description_sha256 for e in surface.tools}
    drifted: list[str] = []
    for tool in live_tools:
        name = tool.get("name", "")
        if name not in stored:
            continue
        current_hash = description_sha256(tool.get("description") or "")
        if current_hash != stored[name]:
            drifted.append(name)
    return drifted


# ---------------------------------------------------------------------------
# SurfaceScanner
# ---------------------------------------------------------------------------

class SurfaceScanner:
    """Produces a ``SurfaceFile`` draft from three source types.

    All three scan methods apply ``suggest_action_class`` for action class and
    default ``trust_label`` to ``"first-party"``.  The caller is expected to
    review and update both fields before committing the file.

    The ``description_sha256`` for each tool is recorded at scan time so that
    subsequent CI checks can detect description drift.
    """

    # ------------------------------------------------------------------
    # scan_json
    # ------------------------------------------------------------------

    def scan_json(self, path: str | Path) -> SurfaceFile:
        """Produce a ``SurfaceFile`` draft from a plain JSON tool list.

        Parameters
        ----------
        path:
            Path to a JSON file.  Accepted shapes:

            * ``{"tools": [...]}`` — dict with a ``"tools"`` key
            * ``[...]``            — a bare list of tool objects

            Each tool object must contain ``"name"`` (str).  Optional fields:
            ``"description"`` (str), ``"method"`` (str, HTTP verb), and
            ``"route"`` (str).  If ``"method"`` is absent, ``"POST"`` is
            assumed so the heuristic defaults to ``"state-changing"``.

        Returns
        -------
        SurfaceFile
            Draft with suggested ``action_class`` and ``trust_label``.
        """
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        tool_list: list[dict[str, Any]] = raw if isinstance(raw, list) else raw.get("tools", [])
        return self._build_surface(tool_list)

    # ------------------------------------------------------------------
    # scan_openapi
    # ------------------------------------------------------------------

    def scan_openapi(self, source: str | Path, *, server_name: str = "") -> SurfaceFile:
        """Produce a ``SurfaceFile`` draft from an OpenAPI spec.

        Parameters
        ----------
        source:
            Either a URL (``http://…`` or ``https://…``) or a local file path
            to a JSON OpenAPI spec.  The spec must be OpenAPI 3.x JSON.
        server_name:
            MCP server name used as the middle segment of the tool name when an
            ``operationId`` is present (e.g. ``"galaxium"`` →
            ``mcp_galaxium_<operationId>``).  Defaults to ``""`` (empty), which
            produces ``mcp__<operationId>`` — useful for draft scanning where the
            server name is not yet known.

        Returns
        -------
        SurfaceFile
            Draft with suggested ``action_class`` and ``trust_label``.

        Notes
        -----
        **Tool name derivation (two paths):**

        1. If the operation carries an ``operationId``, the tool name is derived
           via ``_mcp_tool_name(server_name, operationId)`` — the same
           sanitise-and-truncate rule that nanobot applies.  This path produces
           names that match nanobot's registry exactly for ``fastapi_mcp``-backed
           servers.

        2. If no ``operationId`` is present, the name falls back to joining the
           HTTP method and path segments with underscores, stripping ``{…}``
           braces from path parameters, and lowercasing:
           ``POST /cancel/{booking_id}`` → ``post_cancel_booking_id``.

        The ``route`` field always stores the original ``"METHOD /path"`` string.

        **Description concatenation:**

        When both ``summary`` and ``description`` fields are present, the tool
        description is assembled as ``"{summary}\\n\\n{description}"``, mirroring
        how ``fastapi_mcp`` builds the MCP tool description.  When only one field
        is present, that field is used alone.

        Limitations
        -----------
        ``fastapi_mcp`` appends a ``### Responses:`` block built from the
        operation's response schemas after the human-readable description.  This
        block cannot be reconstructed from the OpenAPI spec alone, so the
        ``description_sha256`` values produced by ``scan_openapi`` will still
        differ from what nanobot reports for ``fastapi_mcp``-backed servers by
        that suffix.

        For bit-exact hashes (matching nanobot's live descriptions), use
        ``scan_mcp(url)`` against a running server, or ``scan_json`` with a tool
        list captured directly from the MCP endpoint.
        """
        spec = self._load_json_source(str(source))
        tool_list: list[dict[str, Any]] = []
        paths: dict[str, Any] = spec.get("paths", {})
        for path, path_item in paths.items():
            for method, operation in path_item.items():
                if method.lower() not in ("get", "post", "put", "patch", "delete"):
                    continue
                # Mirror fastapi_mcp's description assembly: summary + "\n\n" + description.
                # response_info is not included — see Limitations in the docstring.
                summary = operation.get("summary") or ""
                body = operation.get("description") or ""
                if summary and body:
                    description = f"{summary}\n\n{body}"
                elif summary:
                    description = summary
                else:
                    description = body
                # Derive tool name from operationId when present; fall back to path segments.
                operation_id = operation.get("operationId")
                if operation_id:
                    tool_name = _mcp_tool_name(server_name, operation_id)
                else:
                    clean_path = path.replace("{", "").replace("}", "")
                    segments = [s for s in clean_path.split("/") if s]
                    name_parts = [method.lower()] + segments
                    tool_name = "_".join(name_parts).replace("-", "_")
                tool_list.append({
                    "name": tool_name,
                    "description": description,
                    "method": method.upper(),
                    "route": f"{method.upper()} {path}",
                })
        return self._build_surface(tool_list)

    # ------------------------------------------------------------------
    # scan_mcp
    # ------------------------------------------------------------------

    def scan_mcp(self, url: str) -> SurfaceFile:
        """Produce a ``SurfaceFile`` draft from an MCP server's tool list.

        Parameters
        ----------
        url:
            Base URL of the MCP server.  The scanner fetches ``GET {url}/tools``
            and expects a JSON response with shape ``{"tools": [...]}`` where
            each tool has at least ``"name"`` (str) and optionally
            ``"description"`` (str), ``"inputSchema"`` (dict).

            MCP tools carry no HTTP method, so the heuristic falls back to the
            name-based keywords only; tools without a keyword default to
            ``"state-changing"`` (safe default per BASE-2).

        Returns
        -------
        SurfaceFile
            Draft with suggested ``action_class`` and ``trust_label``.

        Raises
        ------
        URLError
            If the MCP server cannot be reached.
        ValueError
            If the response cannot be parsed as JSON.

        Notes
        -----
        This implementation uses a simple REST ``GET {url}/tools`` request suitable
        for MCP servers that expose a plain JSON tool list.  Galaxium uses the
        ``streamableHttp`` transport (MCP JSON-RPC over HTTP POST to ``/mcp``).
        For live Galaxium scans, use ``scan_openapi`` against Galaxium's ``/openapi.json``
        endpoint instead, or pass the full Galaxium tool list as a JSON file to
        ``scan_json``.  Full streamableHttp support is implemented in B-5.
        """
        endpoint = url.rstrip("/") + "/tools"
        log.debug("SurfaceScanner.scan_mcp: GET %s", endpoint)
        try:
            with urlopen(endpoint, timeout=10) as resp:  # noqa: S310
                body = resp.read().decode("utf-8")
        except URLError as exc:
            log.error("scan_mcp: cannot reach MCP server at %s — %s", endpoint, exc)
            raise URLError(f"Cannot reach MCP server at {endpoint}: {exc}") from exc

        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            log.error("scan_mcp: non-JSON response from %s — %s", endpoint, exc)
            raise ValueError(f"MCP server returned non-JSON response: {exc}") from exc

        raw_tools: list[dict[str, Any]] = (
            data if isinstance(data, list) else data.get("tools", [])
        )
        # MCP tools have no HTTP method — use empty string so heuristic uses name-only path
        tool_list = [
            {
                "name": t.get("name", ""),
                "description": t.get("description") or "",
                "method": "",   # no HTTP method for MCP tools
                "route": t.get("name", ""),  # route = tool name when no HTTP path available
            }
            for t in raw_tools
            if t.get("name")
        ]
        return self._build_surface(tool_list)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_json_source(self, source: str) -> dict:
        """Load JSON from a URL (http/https) or a local file path."""
        if source.startswith("http://") or source.startswith("https://"):
            with urlopen(source, timeout=10) as resp:  # noqa: S310
                return json.loads(resp.read().decode("utf-8"))
        return json.loads(Path(source).read_text(encoding="utf-8"))

    def _build_surface(self, tool_list: list[dict[str, Any]]) -> SurfaceFile:
        """Convert a normalised list of tool dicts to a validated ``SurfaceFile``.

        If a tool dict already carries ``"action_class"`` and ``"trust_label"``
        (e.g. when loading a previously reviewed surface file via ``scan_json``),
        those values are preserved.  Otherwise the heuristic and defaults apply.
        """
        entries: list[SurfaceEntry] = []
        for tool in tool_list:
            name: str = tool.get("name", "")
            if not name:
                log.debug("_build_surface: skipping tool entry with empty name")
                continue
            # Reject names that don't already match ^[a-z0-9_]+$.
            # We never rewrite names — a name that needs rewriting is wrong input.
            if not _is_valid_name(name):
                log.warning("_build_surface: skipping tool %r — name fails ^[a-z0-9_]+$ check", name)
                continue

            description: str = tool.get("description") or ""
            method: str = tool.get("method") or "POST"
            route: str = tool.get("route") or f"{method.upper()} /{name}"

            # Preserve reviewed values when present; apply heuristic/defaults otherwise.
            action_class: str = tool.get("action_class") or suggest_action_class(method, name)
            trust_label: str = tool.get("trust_label") or "first-party"
            sha: str = tool.get("description_sha256") or description_sha256(description)

            entries.append(
                SurfaceEntry(
                    name=name,
                    route=route,
                    action_class=action_class,  # type: ignore[arg-type]
                    trust_label=trust_label,     # type: ignore[arg-type]
                    description_sha256=sha,
                )
            )
        log.info("_build_surface: built SurfaceFile with %d tool entry(ies)", len(entries))
        return SurfaceFile(version=1, tools=entries)


# ---------------------------------------------------------------------------
# Internal utilities
# ---------------------------------------------------------------------------

def _is_valid_name(name: str) -> bool:
    """Return ``True`` if *name* already matches ``^[a-z0-9_]+$``.

    Names that do not conform are **rejected** (skipped silently) — never
    rewritten.  This ensures ``surface.json`` always contains exactly the
    names that nanobot uses, with no silent mangling.
    """
    return bool(re.fullmatch(r"[a-z0-9_]+", name))
