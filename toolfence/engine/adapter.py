"""Adapter protocol and scripted (fixture-replay) implementation.

AgentAdapter
    Protocol that every agent backend must satisfy.  run_turn() accepts the
    user prompt and a defence label and returns a full Trace.

ScriptedAdapter
    Reads a fixture JSON file at construction time and replays it on every
    run_turn() call.  No LLM, no network.  If the fixture has status != "ok"
    or any tool call has a non-null error field those values are replayed
    exactly as stored — nothing is normalised away.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from toolfence.contracts.trace import Trace


class AgentAdapter(Protocol):
    """Protocol satisfied by every agent backend (scripted or live)."""

    def run_turn(self, prompt: str, defense: str) -> Trace:
        """Run one agent turn and return the full Trace including status,
        final_reply, tool_calls, and usage.  The *defense* label is kept for
        bookkeeping; ScriptedAdapter ignores it (the fixture already encodes
        the outcome).
        """
        ...


class ScriptedAdapter:
    """Deterministic adapter that replays a pre-recorded fixture file.

    Parameters
    ----------
    fixture_path:
        Path to a JSON file whose top-level object is a valid ``Trace``
        document (i.e. it matches the ``Trace`` Pydantic model).  The file
        is read and validated once at construction time.

    Raises
    ------
    FileNotFoundError
        If *fixture_path* does not exist.
    pydantic.ValidationError
        If the fixture JSON does not match the ``Trace`` schema.
    """

    def __init__(self, fixture_path: str | Path) -> None:
        path = Path(fixture_path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        # Validate once; store the model so every replay returns a fresh copy.
        self._trace = Trace.model_validate(raw)

    # ------------------------------------------------------------------
    # AgentAdapter implementation
    # ------------------------------------------------------------------

    def run_turn(self, prompt: str, defense: str) -> Trace:  # noqa: ARG002
        """Return a fresh copy of the pre-loaded trace.

        *prompt* and *defense* are accepted (satisfying the Protocol) but
        ignored — the fixture already encodes the full outcome, including any
        errors or non-ok status values.
        """
        # model_copy() gives a new object with the same field values;
        # deep=True ensures nested models are not shared between calls.
        return self._trace.model_copy(deep=True)
