"""Guard decision logic — deterministic hold/pass rule (BASE-7, GRD-7, GRD-12).

``GuardDecision.decide(...)`` implements the four-branch card rule with no nanobot
imports and no LLM calls.  It is the single authoritative place that decides whether
a tool call should be held for user confirmation or passed through.

Decision branches (priority order)
------------------------------------
1. ``action_class == "irreversible"``                              → ``"hold"``
2. ``action_class == "state-changing"`` and ``session_tainted``   → ``"hold"``
3. ``action_class == "state-changing"`` and any provenance value
   is ``"untrusted"``                                             → ``"hold"``
4. All other cases (including all ``"read"`` class calls)          → ``"pass"``

Rule 4 means reads always pass regardless of session taint or argument provenance
(GRD-12).  This is intentional: read results are captured for provenance tracking by
the proxy layer, not held.
"""

from __future__ import annotations

from typing import Literal

# ProvenanceLabel is the canonical type alias defined in contracts — import and
# reuse; do not redefine here.
from toolfence.contracts.trace import ProvenanceLabel  # noqa: F401 — re-exported for callers


GuardResult = Literal["pass", "hold"]


class GuardDecision:
    """Stateless implementation of the four-branch Guard card rule (GRD-7).

    This class holds no state; every call to ``decide`` is independent.  Session
    state (taint, provenance) is passed in by the caller (``GuardedProxy``).
    """

    def decide(
        self,
        tool_name: str,
        action_class: str,
        arguments: dict,
        session_tainted: bool,
        provenance: dict[str, str],
    ) -> GuardResult:
        """Return ``"hold"`` or ``"pass"`` for the given tool call context.

        Parameters
        ----------
        tool_name:
            The tool's name (e.g. ``"mcp_galaxium_cancel_booking__booking_id__post"``).
            Not used by the current rule but accepted for future extension and logging.
        action_class:
            One of ``"read"``, ``"state-changing"``, or ``"irreversible"``.  Values
            not in this set are treated as ``"state-changing"`` (fail-closed, matching
            the BASE-2 default).
        arguments:
            The tool call's argument dict (parameter name → value).  Only the keys
            matter here; values are resolved to provenance labels by the caller.
        session_tainted:
            ``True`` if the session has read at least one untrusted result (GRD-5).
        provenance:
            Map of parameter name → provenance label (``"user"``, ``"first-party"``,
            or ``"untrusted"``) for each argument.  Missing entries are treated as
            ``"untrusted"`` (fail-closed).

        Returns
        -------
        GuardResult
            ``"hold"`` if any hold condition is met; ``"pass"`` otherwise.
        """
        # Branch 1 — irreversible actions always hold.
        if action_class == "irreversible":
            return "hold"

        # Branch 4 shortcut — reads always pass (GRD-12).
        # Check this before state-changing branches so "read" never accidentally
        # triggers a hold even in a tainted session with untrusted arguments.
        if action_class == "read":
            return "pass"

        # Remaining branches apply only to state-changing (and unknown) classes.
        # Branch 2 — state-changing call in a tainted session.
        if session_tainted:
            return "hold"

        # Branch 3 — any argument provenance is "untrusted".
        # Missing provenance entries default to "untrusted" (fail-closed per GRD-4).
        for param_name in arguments:
            label = provenance.get(param_name, "untrusted")
            if label == "untrusted":
                return "hold"

        # Branch 4 — all other cases pass.
        return "pass"
