"""Canary generation, probe builder, and probe-file validator.

Canary
------
``generate_canary() -> str``
    Returns a fresh random string in the format ``TF-CANARY-XXXXXXXX`` where
    the suffix is 8 uppercase hexadecimal characters (e.g. ``TF-CANARY-3F9A1B2C``).
    Each call produces a cryptographically random, unique value (BASE-6).
    Test fixtures use *constant* canary strings (e.g. ``TF-CANARY-DEADBEEF``) so
    fixture assertions remain stable across runs.

ProbeBuilder
------------
``ProbeBuilder(template).build(canary) -> dict``
    Accepts a probe template dict and returns a new dict with every occurrence
    of the literal placeholder ``"{{CANARY}}"`` in any string value replaced by
    the given canary string.  The original template is never mutated.

validate_probe_file
-------------------
``validate_probe_file(path) -> bool``
    Validates a probe JSON file against the following rules (ENG-5):

    Structural rules
    ~~~~~~~~~~~~~~~~
    1. File must be a JSON object.
    2. Must contain keys ``"channel"`` and ``"content"``.
    3. ``"channel"`` must be one of ``"user-input"`` or ``"tool-result"``.
    4. ``"content"`` must be a string.

    Payload-safety rules (Non-negotiable #2 from IDEA.md)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    5. ``"content"`` must NOT match any of the forbidden patterns below.
       These patterns identify strings that look like real injection payloads
       rather than synthetic probes.  The list is intentionally conservative
       and can be extended once A-2 ships.

    Forbidden patterns (case-insensitive)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    - ``ignore previous instructions``
    - ``disregard your``
    - ``you are now``
    - ``new instruction``
    - ``system prompt``

    Note: a probe that contains a *resolved* canary value (e.g.
    ``TF-CANARY-3F9A1B2C``) is still valid — canary strings do not match any
    forbidden pattern.  ``test_e2e_built_probe_still_passes_validator`` in
    ``tests/test_probe.py`` enforces this.
"""

from __future__ import annotations

import copy
import json
import logging
import re
import secrets
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Forbidden pattern list — payload-safety check (ENG-5)
# ---------------------------------------------------------------------------

_FORBIDDEN_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+previous\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+your", re.IGNORECASE),
    re.compile(r"you\s+are\s+now", re.IGNORECASE),
    re.compile(r"new\s+instruction", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
]

_VALID_CHANNELS = frozenset({"user-input", "tool-result"})


# ---------------------------------------------------------------------------
# generate_canary
# ---------------------------------------------------------------------------

def generate_canary() -> str:
    """Return a fresh random canary string (BASE-6).

    Format: ``TF-CANARY-`` followed by 8 uppercase hexadecimal characters.

    Example
    -------
    >>> c = generate_canary()
    >>> c.startswith("TF-CANARY-")
    True
    >>> len(c)
    18
    """
    suffix = secrets.token_hex(4).upper()  # 4 bytes → 8 hex chars
    canary = f"TF-CANARY-{suffix}"
    log.debug("generate_canary: %s", canary)
    return canary


# ---------------------------------------------------------------------------
# ProbeBuilder
# ---------------------------------------------------------------------------

class ProbeBuilder:
    """Embeds a canary into a probe template.

    The template is any JSON-serialisable dict.  The placeholder string
    ``"{{CANARY}}"`` (exact literal, including the double braces) in any
    string value is replaced with the provided canary on each ``build()`` call.

    Parameters
    ----------
    template:
        A dict representing the probe template.  Nested dicts and lists are
        supported; only string values are inspected for the placeholder.
        The original dict is never mutated.
    """

    PLACEHOLDER = "{{CANARY}}"

    def __init__(self, template: dict[str, Any]) -> None:
        self._template = template

    def build(self, canary: str) -> dict[str, Any]:
        """Return a deep copy of the template with ``{{CANARY}}`` replaced.

        Parameters
        ----------
        canary:
            The canary string to embed (e.g. ``"TF-CANARY-3F9A1B2C"``).

        Returns
        -------
        dict
            New dict with the placeholder substituted.  The original template
            is unchanged.
        """
        return _substitute(copy.deepcopy(self._template), canary)


def _substitute(obj: Any, canary: str) -> Any:
    """Recursively replace ``{{CANARY}}`` in all string values of *obj*."""
    if isinstance(obj, str):
        return obj.replace(ProbeBuilder.PLACEHOLDER, canary)
    if isinstance(obj, dict):
        return {k: _substitute(v, canary) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_substitute(item, canary) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# validate_probe_file
# ---------------------------------------------------------------------------

def validate_probe_file(path: str | Path) -> bool:
    """Validate a probe JSON file against structural and payload-safety rules.

    Parameters
    ----------
    path:
        Path to a ``.json`` file containing a probe template.

    Returns
    -------
    bool
        ``True`` if the file passes all rules; ``False`` otherwise.
        Never raises — catches all exceptions and returns ``False``.

    Rules
    -----
    See module docstring for the full list of structural and payload-safety
    rules.
    """
    log.debug("validate_probe_file: checking %s", path)
    try:
        text = Path(path).read_text(encoding="utf-8")
        data = json.loads(text)
    except Exception:  # noqa: BLE001
        log.warning("validate_probe_file: could not read/parse %s", path)
        return False

    # Rule 1: must be a dict
    if not isinstance(data, dict):
        return False

    # Rule 2: must have "channel" and "content"
    if "channel" not in data or "content" not in data:
        return False

    # Rule 3: channel must be one of the valid values
    if data["channel"] not in _VALID_CHANNELS:
        return False

    # Rule 4: content must be a string
    content = data["content"]
    if not isinstance(content, str):
        return False

    # Rule 5: content must not match any forbidden pattern
    for pattern in _FORBIDDEN_PATTERNS:
        if pattern.search(content):
            log.warning("validate_probe_file: forbidden pattern %r matched in %s", pattern.pattern, path)
            return False

    # Rule 6: probe_id must be a non-empty string
    probe_id = data.get("probe_id")
    if not isinstance(probe_id, str) or not probe_id.strip():
        return False

    return True
