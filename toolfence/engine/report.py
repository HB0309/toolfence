"""Markdown report renderer (ENG-7, ENG-8).

``render_report(summary)`` converts a ``ResultSummary`` into a human-readable
markdown string.  The report always ends with the ENG-8 disclaimer.

Report structure
----------------
1. Header + run ID
2. Defense Legend
3. Normal-task results table
4. Security (attack) results table — one row per condition, with
   ``inconclusive`` always in its own column (ENG-7)
5. Cards shown per condition
6. Disclaimer blockquote (ENG-8) — last content line
"""

from __future__ import annotations

from toolfence.engine.scoring import DISCLAIMER, ConditionSummary, ResultSummary


def render_report(summary: ResultSummary) -> str:
    """Render *summary* as a markdown string.

    Parameters
    ----------
    summary:
        A ``ResultSummary`` produced by ``scoring.aggregate()``.

    Returns
    -------
    str
        Multi-line markdown.  The last non-empty line is the ENG-8 disclaimer
        as a blockquote.
    """
    lines: list[str] = []

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------
    lines.append("# ToolFence Evaluation Report")
    lines.append("")
    lines.append(f"**Run ID:** `{summary.run_id}`")
    lines.append(f"**Total trials:** {summary.total_trials}")
    if summary.model:
        lines.append(f"**Model:** `{summary.model}`")
    if summary.host:
        lines.append(f"**Host:** {summary.host}")
    lines.append("")

    # ------------------------------------------------------------------
    # Defense Legend
    # ------------------------------------------------------------------
    lines.append("## Defense Legend")
    lines.append("")
    lines.append("| Defense | Description |")
    lines.append("|---------|-------------|")
    lines.append("| `none` | No prompt defense applied; baseline. |")
    lines.append("| `datamarking` | Untrusted tool results wrapped in declared-untrusted markers before the model sees them. |")
    lines.append("| `instructional` | `AGENTS.md` written to the agent's workspace instructing it to treat tool results as data only. |")
    lines.append("")

    # ------------------------------------------------------------------
    # Normal-task results — aggregate
    # ------------------------------------------------------------------
    lines.append("## Normal-Task Results")
    lines.append("")
    nt = summary.normal_tasks
    lines.append("| Metric | Count | % |")
    lines.append("|--------|------:|--:|")
    lines.append(f"| Success      | {nt.success} | {nt.success_pct}% |")
    lines.append(f"| Failed       | {nt.failed} | — |")
    lines.append(f"| Undetermined | {nt.undetermined} | — |")
    lines.append(f"| Skipped      | {nt.skipped} | — |")
    lines.append(f"| **Total**    | **{nt.total}** | — |")
    lines.append("")

    # ------------------------------------------------------------------
    # Normal-task results — per defense × guard_on condition
    # ------------------------------------------------------------------
    if summary.normal_conditions:
        lines.append("### Normal-Task Results by Condition")
        lines.append("")
        lines.append("| Task | Defense | Guard | Success | Failed | Undetermined | Skipped | Total | Success% |")
        lines.append("|------|---------|-------|--------:|-------:|-------------:|--------:|------:|---------:|")
        for nc in summary.normal_conditions:
            guard_label = "✓" if nc.guard_on else "✗"
            task_label = nc.task_label or "—"
            lines.append(
                f"| {task_label} | {nc.defense} | {guard_label} | "
                f"{nc.success} | {nc.failed} | {nc.undetermined} | {nc.skipped} | {nc.total} | {nc.success_pct}% |"
            )
        lines.append("")

    # ------------------------------------------------------------------
    # Security (attack) results
    # ------------------------------------------------------------------
    lines.append("## Security Results")
    lines.append("")

    if not summary.conditions:
        lines.append("*No attack trials recorded.*")
    else:
        lines.append(
            "| Channel | Probe | Defense | Guard | "
            "Leaked | Held | Refused | Inconclusive | Skipped | Total | "
            "Leaked% | Held% | Refused% | Inconclusive% | Cards Shown | Canary-in-args held |"
        )
        lines.append(
            "|---------|-------|---------|-------|"
            "-------:|-----:|--------:|-------------:|--------:|------:|"
            "--------:|------:|---------:|-------------:|------------:|--------------------:|"
        )
        for cond in summary.conditions:
            a = cond.attack
            guard_label = "✓" if cond.guard_on else "✗"
            channel_label = cond.channel or "—"
            probe_label = cond.probe_id or "—"
            lines.append(
                f"| {channel_label} | {probe_label} | {cond.defense} | {guard_label} | "
                f"{a.leaked} | {a.held} | {a.refused} | {a.inconclusive} | "
                f"{a.skipped} | {a.total} | "
                f"{a.leaked_pct}% | {a.held_pct}% | {a.refused_pct}% | "
                f"{a.inconclusive_pct}% | {cond.cards_shown} | {a.canary_in_args_held} |"
            )

    lines.append("")

    # Note for user-input probes — Guard-on "leaked" is the expected control
    # result for this channel because the canary is in the user's own message.
    if any(c.channel == "user-input" for c in summary.conditions):
        lines.append(
            "> **Note (user-input probes):** here the canary is in the user's own message. "
            "Guard passes values the user typed, by design, so *leaked* with Guard on is "
            "the expected control result: Guard doesn't block what the user asked for. "
            "The tool-result rows are where Guard is tested."
        )
        lines.append("")

    # ------------------------------------------------------------------
    # Cards shown summary (separate section for quick scan)
    # ------------------------------------------------------------------
    if summary.conditions:
        lines.append("## Cards Shown")
        lines.append("")
        total_cards = sum(c.cards_shown for c in summary.conditions)
        lines.append(f"**Total Guard confirm cards shown across all conditions:** {total_cards}")
        lines.append("")
        for cond in summary.conditions:
            channel_label = cond.channel or "—"
            probe_label = cond.probe_id or "—"
            guard_label = "on" if cond.guard_on else "off"
            lines.append(
                f"- {channel_label} / {probe_label} / {cond.defense} / guard {guard_label}: "
                f"{cond.cards_shown} card(s)"
            )
        lines.append("")

    # ------------------------------------------------------------------
    # Disclaimer (ENG-8) — always last
    # ------------------------------------------------------------------
    lines.append(f"> {DISCLAIMER}")
    lines.append("")

    return "\n".join(lines)
