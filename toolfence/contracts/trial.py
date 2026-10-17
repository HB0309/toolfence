"""Pydantic model for one evaluation trial record."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, model_validator

from toolfence.contracts.trace import Trace


class TrialRecord(BaseModel):
    """One JSON object per trial stored in results/.

    Invariants enforced by model_validator:

    Attack trials (kind == "attack"):
    - channel, probe_id, canary must all be non-null.
    - verdict is one of: "leaked" | "held" | "refused" | "inconclusive" | "skipped".

    Normal trials (kind == "normal"):
    - channel, probe_id, canary must all be null.
    - verdict must be null (completed — outcome in task_success) or "skipped" (not run).

    Skipped trials (verdict == "skipped", either kind):
    - skip_reason must be a non-null string.
    - trace must be null.

    Non-skipped trials:
    - trace must be non-null.
    """

    model_config = {"extra": "forbid"}

    trial_id: str
    run_id: str
    kind: Literal["attack", "normal"]
    channel: Literal["user-input", "tool-result"] | None  # null for normal trials
    defense: Literal["none", "datamarking", "instructional"]
    guard_on: bool
    probe_id: str | None                    # None for normal trials
    canary: str | None                      # None for normal trials
    verdict: Literal[
        "leaked", "held", "refused", "inconclusive", "skipped"
    ] | None                                # None = completed normal trial; "skipped" allowed for both
    task_success: bool | None               # None when not yet determined
    trace: Trace | None                     # None only when verdict == "skipped"
    canary_in_args: bool
    cards_shown: int
    skip_reason: str | None = None          # present when verdict == "skipped"
    task_label: str | None = None           # label for normal trials (e.g. "write_only", "read_then_write")

    @model_validator(mode="after")
    def _check_invariants(self) -> "TrialRecord":
        if self.kind == "attack":
            if self.channel is None:
                raise ValueError("attack trials must have channel")
            if self.probe_id is None or self.canary is None:
                raise ValueError("attack trials must have probe_id and canary")
        else:  # normal
            if self.channel is not None:
                raise ValueError("normal trials must have channel == None")
            if self.probe_id is not None or self.canary is not None:
                raise ValueError("normal trials must not have probe_id or canary")
            if self.verdict not in (None, "skipped"):
                raise ValueError(
                    "normal trials must have verdict == None (completed) or 'skipped'"
                )

        if self.verdict == "skipped":
            if self.skip_reason is None:
                raise ValueError("skipped trials must have skip_reason")
            if self.trace is not None:
                raise ValueError("skipped trials must have trace == None")
        else:
            if self.trace is None:
                raise ValueError("non-skipped trials must have trace")

        return self
