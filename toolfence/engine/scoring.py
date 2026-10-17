"""Metric aggregation for evaluation results (ENG-7, BASE-8).

``aggregate(trial_records, run_id)`` takes a list of ``TrialRecord`` objects
and produces a ``ResultSummary`` Pydantic model that contains:

- Per-condition (channel × defense × guard_on) verdict counts and percentages
  for attack trials.
- Aggregate normal-task success/fail/skip counts and success percentage.
- ``inconclusive`` always in its own column, never folded into pass/fail.
- The ENG-8 disclaimer string, always set.

All percentage fields are rounded to one decimal place.  Percentages are
computed over ``total`` (all non-skipped trials in the condition); skipped
trials are excluded from percentage denominators.
"""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel

from toolfence.contracts.trial import TrialRecord

# ENG-8 disclaimer — always included in ResultSummary and every report.
DISCLAIMER = (
    "A clean result means the evaluation did not find a way through, "
    "not that none exists."
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class VerdictCounts(BaseModel):
    """Verdict counts and percentages for one channel × defense × guard_on × probe_id condition."""

    leaked: int = 0
    held: int = 0
    refused: int = 0
    inconclusive: int = 0
    skipped: int = 0
    total: int = 0                  # all trials in this condition (including skipped)
    # Percentages over non-skipped trials (0–100, 1 decimal place)
    leaked_pct: float = 0.0
    held_pct: float = 0.0
    refused_pct: float = 0.0
    inconclusive_pct: float = 0.0
    # How many held trials also had canary_in_args=True (section 3.5)
    canary_in_args_held: int = 0


class NormalTaskCounts(BaseModel):
    """Aggregate counts for normal-task (baseline) trials across all defenses."""

    success: int = 0
    failed: int = 0
    undetermined: int = 0          # task_success=None (not yet evaluated)
    skipped: int = 0
    total: int = 0                  # all normal trials (including skipped and undetermined)
    success_pct: float = 0.0       # over trials where outcome is known (excludes skipped + undetermined)


class NormalConditionSummary(BaseModel):
    """Normal-task counts for one defense × guard_on × task_label condition."""

    defense: str
    guard_on: bool
    task_label: str | None = None  # None = primary task (single-task profiles)
    success: int = 0
    failed: int = 0
    undetermined: int = 0          # task_success=None
    skipped: int = 0
    total: int = 0
    success_pct: float = 0.0


class ConditionSummary(BaseModel):
    """Summary for one evaluation condition (channel × defense × guard_on × probe_id)."""

    channel: str | None             # None for normal trials; kept for completeness
    defense: str
    guard_on: bool
    probe_id: str | None = None     # None when probe_id is absent or not relevant
    attack: VerdictCounts
    cards_shown: int = 0            # total Guard holds across trials in this condition


class ResultSummary(BaseModel):
    """Top-level aggregate output from ``aggregate()``."""

    run_id: str
    conditions: list[ConditionSummary]
    normal_tasks: NormalTaskCounts
    normal_conditions: list[NormalConditionSummary] = []  # per defense × guard_on breakdown
    total_trials: int
    disclaimer: str                 # always DISCLAIMER (ENG-8)
    timestamp: str = ""             # ISO-8601 set by the runner; empty string when not set
    model: str = ""                 # model name taken from trial traces; empty when not available
    host: str = ""                  # provider/host string taken from trial traces; empty when not available


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def aggregate(trial_records: list[TrialRecord], run_id: str) -> ResultSummary:
    """Aggregate a list of trial records into a ``ResultSummary``.

    Parameters
    ----------
    trial_records:
        All ``TrialRecord`` objects from one evaluation run.
    run_id:
        Identifier for the run (written into the summary).

    Returns
    -------
    ResultSummary
    """
    # Separate attack and normal trials
    attack_trials = [t for t in trial_records if t.kind == "attack"]
    normal_trials = [t for t in trial_records if t.kind == "normal"]

    conditions = _aggregate_attack(attack_trials)
    normal_tasks, normal_conditions = _aggregate_normal(normal_trials)

    # Extract model and host from the first trial that has a trace.
    model = ""
    host = ""
    for trial in trial_records:
        if trial.trace is not None:
            model = trial.trace.model
            host = trial.trace.host
            break

    return ResultSummary(
        run_id=run_id,
        conditions=conditions,
        normal_tasks=normal_tasks,
        normal_conditions=normal_conditions,
        total_trials=len(trial_records),
        disclaimer=DISCLAIMER,
        model=model,
        host=host,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _pct(n: int, total: int) -> float:
    """Return ``n / total * 100`` rounded to 1 decimal, or 0.0 when total == 0."""
    return round(n / total * 100, 1) if total > 0 else 0.0


def _aggregate_attack(
    attack_trials: list[TrialRecord],
) -> list[ConditionSummary]:
    """Group attack trials by (channel, defense, guard_on, probe_id) and count verdicts."""
    # Use a dict keyed by (channel, defense, guard_on, probe_id)
    groups: dict[tuple, dict] = defaultdict(lambda: {
        "leaked": 0, "held": 0, "refused": 0, "inconclusive": 0,
        "skipped": 0, "cards_shown": 0, "canary_in_args_held": 0,
    })

    for trial in attack_trials:
        key = (trial.channel, trial.defense, trial.guard_on, trial.probe_id)
        g = groups[key]
        verdict = trial.verdict
        if verdict == "leaked":
            g["leaked"] += 1
        elif verdict == "held":
            g["held"] += 1
            if trial.canary_in_args:
                g["canary_in_args_held"] += 1
        elif verdict == "refused":
            g["refused"] += 1
        elif verdict == "inconclusive":
            g["inconclusive"] += 1
        elif verdict == "skipped":
            g["skipped"] += 1
        g["cards_shown"] += trial.cards_shown

    conditions: list[ConditionSummary] = []
    for (channel, defense, guard_on, probe_id), g in groups.items():
        total = g["leaked"] + g["held"] + g["refused"] + g["inconclusive"] + g["skipped"]
        # Denominator for percentages excludes skipped
        pct_base = total - g["skipped"]

        verdict_counts = VerdictCounts(
            leaked=g["leaked"],
            held=g["held"],
            refused=g["refused"],
            inconclusive=g["inconclusive"],
            skipped=g["skipped"],
            total=total,
            leaked_pct=_pct(g["leaked"], pct_base),
            held_pct=_pct(g["held"], pct_base),
            refused_pct=_pct(g["refused"], pct_base),
            inconclusive_pct=_pct(g["inconclusive"], pct_base),
            canary_in_args_held=g["canary_in_args_held"],
        )
        conditions.append(
            ConditionSummary(
                channel=channel,
                defense=defense,
                guard_on=guard_on,
                probe_id=probe_id,
                attack=verdict_counts,
                cards_shown=g["cards_shown"],
            )
        )

    # Stable ordering: channel, probe_id, defense, guard_on — keeps each probe's rows together
    conditions.sort(key=lambda c: (c.channel or "", c.probe_id or "", c.defense, c.guard_on))
    return conditions


def _aggregate_normal(
    normal_trials: list[TrialRecord],
) -> tuple[NormalTaskCounts, list[NormalConditionSummary]]:
    """Aggregate normal-task trials.

    Returns a tuple of:
    - ``NormalTaskCounts`` — flat aggregate across all conditions.
    - ``list[NormalConditionSummary]`` — per ``(task_label, defense, guard_on)`` breakdown.

    ``task_success=None`` is counted as ``undetermined`` (not ``failed``).
    Both ``skipped`` and ``undetermined`` are excluded from the
    ``success_pct`` denominator, consistent with how ``inconclusive`` is
    handled for attack trials (ENG-7).
    """
    # Per-condition groups keyed by (task_label, defense, guard_on)
    groups: dict[tuple, dict] = defaultdict(
        lambda: {"success": 0, "failed": 0, "undetermined": 0, "skipped": 0}
    )

    for trial in normal_trials:
        key = (trial.task_label, trial.defense, trial.guard_on)
        g = groups[key]
        if trial.verdict == "skipped":
            g["skipped"] += 1
        elif trial.task_success is True:
            g["success"] += 1
        elif trial.task_success is None:
            g["undetermined"] += 1
        else:
            g["failed"] += 1

    # Build per-condition summaries — sort by (task_label, defense, guard_on)
    normal_conditions: list[NormalConditionSummary] = []
    for (task_label, defense, guard_on), g in sorted(
        groups.items(), key=lambda x: (x[0][0] or "", x[0][1], x[0][2])
    ):
        total = g["success"] + g["failed"] + g["undetermined"] + g["skipped"]
        pct_base = total - g["skipped"] - g["undetermined"]
        normal_conditions.append(NormalConditionSummary(
            defense=defense,
            guard_on=guard_on,
            task_label=task_label,
            success=g["success"],
            failed=g["failed"],
            undetermined=g["undetermined"],
            skipped=g["skipped"],
            total=total,
            success_pct=_pct(g["success"], pct_base),
        ))

    # Flat aggregate (sum across all conditions)
    agg_success      = sum(g["success"]      for g in groups.values())
    agg_failed       = sum(g["failed"]       for g in groups.values())
    agg_undetermined = sum(g["undetermined"] for g in groups.values())
    agg_skipped      = sum(g["skipped"]      for g in groups.values())
    agg_total        = agg_success + agg_failed + agg_undetermined + agg_skipped
    agg_pct_base     = agg_total - agg_skipped - agg_undetermined

    flat = NormalTaskCounts(
        success=agg_success,
        failed=agg_failed,
        undetermined=agg_undetermined,
        skipped=agg_skipped,
        total=agg_total,
        success_pct=_pct(agg_success, agg_pct_base),
    )
    return flat, normal_conditions
