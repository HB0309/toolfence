"""Findings loader and markdown renderer (PG-9).

``load_findings(path)`` reads and validates a findings JSON file against
``findings.schema.json``, returning a list of finding dicts.

``render_findings(findings)`` converts that list into a markdown string: a
``## Findings`` header, a table with one row per finding, and a totals line.

Import boundary
---------------
This module belongs to ``toolfence/engine/`` and may import from
``toolfence/contracts/`` only.  It must NOT import from ``toolfence/guard/``,
``toolfence/integration/``, or any nanobot internals.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Union

import jsonschema

log = logging.getLogger(__name__)

# Path to the findings JSON Schema, co-located with the other contract schemas.
_SCHEMA_PATH = (
    Path(__file__).parent.parent
    / "contracts"
    / "schemas"
    / "findings.schema.json"
)


def load_findings(path: Union[Path, str]) -> list[dict]:
    """Read, parse, and schema-validate a findings JSON file.

    Parameters
    ----------
    path:
        Path to a ``findings.json`` file (absolute or relative to the caller).

    Returns
    -------
    list[dict]
        A list of finding dicts, each matching the ``Finding`` definition in
        ``findings.schema.json``.

    Raises
    ------
    ValueError
        If the file content does not validate against the findings schema.
    FileNotFoundError
        If ``path`` does not exist.
    """
    log.debug("load_findings: reading %s", path)
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))

    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as exc:
        log.error("load_findings: schema validation failed for %s — %s", path, exc.message)
        raise ValueError(
            f"findings file {path!r} failed schema validation: {exc.message}"
        ) from exc
    log.info("load_findings: loaded %d finding(s) from %s", len(data), path)

    return data  # type: ignore[return-value]


def render_findings(findings: list[dict]) -> str:
    """Render a list of finding dicts as a markdown string.

    Parameters
    ----------
    findings:
        A list of finding dicts as returned by :func:`load_findings`.

    Returns
    -------
    str
        Multi-line markdown.  Structure:

        1. ``## Findings`` header
        2. Markdown table: ID | Title | Mitigation | Ref
        3. One row per finding
        4. Summary totals line
    """
    lines: list[str] = []

    lines.append("## Findings")
    lines.append("")
    lines.append("| ID | Title | Mitigation | Ref |")
    lines.append("|----|-------|------------|-----|")

    for finding in findings:
        fid = finding["id"]
        title = finding["title"]
        status = finding["mitigation_status"]
        ref = finding["mitigation_ref"]["req_id"]
        lines.append(f"| {fid} | {title} | {status} | {ref} |")

    lines.append("")

    # Totals line
    total = len(findings)
    mitigated = sum(1 for f in findings if f["mitigation_status"] == "mitigated")
    partial = sum(
        1 for f in findings if f["mitigation_status"] == "partially_mitigated"
    )
    reported = sum(
        1 for f in findings if f["mitigation_status"] == "reported_only"
    )
    lines.append(
        f"**Total findings: {total}** "
        f"({mitigated} mitigated, {partial} partially_mitigated, {reported} reported_only)"
    )
    lines.append("")

    return "\n".join(lines)
