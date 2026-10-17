"""toolfence CLI entry point.

Subcommands
-----------
scan <path>                      Scan a surface JSON and print a tool table.
run  --surface <path>            Run the evaluation matrix.
     [--output <dir>]
     [--live]                    Use NanobotAdapter instead of scripted adapter.
     [--config <path>]           Nanobot config (default: config/nanobot.eval.json).
     [--probe <id|normal>]       Run only the named attack probe, or only normal trials.
     [--defense <name>]          Restrict to one defense condition.
     [--guard on|off]            Restrict to guard-on or guard-off rows.
report <results-dir>             Render a markdown report from trial records.
ci-check --surface <path>        Surface-diff CI check (compares surface file
         [--live <path>]          against a live tool list JSON, or itself).

Import boundary
---------------
This module may import from toolfence.engine, toolfence.guard, toolfence.contracts,
toolfence.integration.  It must NOT import nanobot directly.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="toolfence",
        description=(
            "ToolFence — tool-surface auditing and injection-resilience evaluation "
            "for MCP agents."
        ),
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # scan
    scan_p = sub.add_parser("scan", help="Scan a surface JSON and print a tool table.")
    scan_p.add_argument("path", help="Path to a surface JSON file or a plain tool-list JSON.")

    # run
    run_p = sub.add_parser("run", help="Run the evaluation matrix.")
    run_p.add_argument("--surface", required=False, default=None, metavar="PATH",
                       help="Path to the reviewed surface.json. Required unless --target is given.")
    run_p.add_argument("--output", default="results", metavar="DIR",
                       help="Directory to write trial record JSON files (default: results/).")
    run_p.add_argument("--live", action="store_true",
                       help="Use NanobotAdapter (real model) instead of the scripted adapter.")
    run_p.add_argument("--config", default="config/nanobot.eval.json", metavar="PATH",
                       help="Nanobot config path (default: config/nanobot.eval.json).")
    run_p.add_argument("--target", default=None, metavar="PATH",
                       help=(
                           "Path to a target profile JSON (e.g. profiles/galaxium.json). "
                           "Requires --live. Overrides --config, --surface, and the "
                           "default probe list with values from the profile."
                       ))
    run_p.add_argument("--probe", default=None, metavar="ID|normal",
                       help=(
                           "Run only the named attack probe ID (skips normal trials), "
                           "or 'normal' to run only normal trials (skips attack trials)."
                       ))
    run_p.add_argument("--defense", default=None, metavar="NAME",
                       help="Restrict to one defense condition: none, datamarking, instructional.")
    run_p.add_argument("--guard", default=None, choices=["on", "off"], metavar="on|off",
                       help="Restrict to guard-on or guard-off defense rows.")

    # report
    report_p = sub.add_parser("report", help="Render a markdown report from trial records.")
    report_p.add_argument("results_dir", nargs="?", default="results", metavar="DIR",
                          help="Directory containing trial record JSON files (default: results/).")

    # ci-check
    ci_p = sub.add_parser(
        "ci-check",
        help="Surface-diff CI check: compare surface.json against a live tool list.",
    )
    ci_p.add_argument("--surface", required=True, metavar="PATH",
                      help="Path to the committed surface.json.")
    ci_p.add_argument("--live", default=None, metavar="PATH",
                      help="Path to a live tool-list JSON (default: re-read surface itself).")

    # serve (dashboard)
    serve_p = sub.add_parser("serve", help="Start the read-only results dashboard server.")
    serve_p.add_argument("--host", default="localhost", metavar="HOST",
                         help="Host to listen on (default: localhost).")
    serve_p.add_argument("--port", type=int, default=8080, metavar="PORT",
                         help="Port to listen on (default: 8080).")
    serve_p.add_argument("--results-dir", default="results", metavar="DIR",
                         help="Directory of trial record JSON files (default: results/).")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "scan":
        _cmd_scan(args.path)
    elif args.command == "run":
        _cmd_run(
            args.surface,
            args.output,
            live=args.live,
            config_path=args.config,
            target_path=getattr(args, "target", None),
            probe_filter=args.probe,
            defense_filter=args.defense,
            guard_filter=args.guard,
        )
    elif args.command == "report":
        _cmd_report(args.results_dir)
    elif args.command == "ci-check":
        _cmd_ci_check(args.surface, args.live)
    elif args.command == "serve":
        _cmd_serve(args.host, args.port, args.results_dir)
    else:
        print(f"Unknown command: {args.command!r}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------

def _cmd_scan(path: str) -> None:
    """Print a markdown table of the tools in *path*."""
    from toolfence.engine.surface import SurfaceScanner

    log.info("_cmd_scan: scanning %r", path)
    try:
        surface = SurfaceScanner().scan_json(path)
    except Exception as exc:  # noqa: BLE001
        log.error("_cmd_scan: failed to scan %r — %s", path, exc)
        print(f"Error scanning {path!r}: {exc}", file=sys.stderr)
        sys.exit(1)
    log.info("_cmd_scan: found %d tool(s)", len(surface.tools))

    # Header
    print(f"Scanned {len(surface.tools)} tool(s) from {path}")
    print()
    col_w = [50, 40, 16, 12]
    header = (
        f"{'Name':<{col_w[0]}} {'Route':<{col_w[1]}} "
        f"{'Action class':<{col_w[2]}} {'Trust label':<{col_w[3]}}"
    )
    sep = "-" * len(header)
    print(header)
    print(sep)
    for entry in surface.tools:
        print(
            f"{entry.name:<{col_w[0]}} {entry.route:<{col_w[1]}} "
            f"{entry.action_class:<{col_w[2]}} {entry.trust_label:<{col_w[3]}}"
        )

    sys.exit(0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apply_task_prompt(
    probe_dict: dict,
    profile: Any,
    task_prompt_override: str | None,
) -> dict:
    """Return probe_dict with the effective task_prompt stamped in.

    Priority:
    1. Per-probe *task_prompt_override* wins (when not None).
    2. Profile-level *tool_result_task_prompt* for tool-result channel probes.
    3. Non-tool-result probes without an override are returned unchanged.
    """
    if probe_dict.get("channel") == "tool-result":
        effective = (
            task_prompt_override
            if task_prompt_override is not None
            else profile.tool_result_task_prompt
        )
        return {**probe_dict, "task_prompt": effective}
    if task_prompt_override is not None:
        return {**probe_dict, "task_prompt": task_prompt_override}
    return probe_dict


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

def _cmd_run(
    surface_path: str | None,
    output_dir: str,
    *,
    live: bool = False,
    config_path: str = "config/nanobot.eval.json",
    target_path: str | None = None,
    probe_filter: str | None = None,
    defense_filter: str | None = None,
    guard_filter: str | None = None,
) -> None:
    """Run the evaluation matrix (scripted or live adapter).

    When ``target_path`` is set, the profile overrides ``config_path``,
    ``surface_path``, and the default probe list.  ``--target`` requires
    ``--live``; passing ``--target`` without ``--live`` is a usage error.
    """
    import os

    from toolfence.contracts.surface import SurfaceFile
    from toolfence.engine.adapter import ScriptedAdapter
    from toolfence.engine.runner import DEFAULT_DEFENSES, NORMAL_TASK_PROMPT, EvaluationRunner

    _REPO_ROOT = Path(__file__).parent.parent.parent

    # --- Validate surface/target combination ---
    if surface_path is None and target_path is None:
        print(
            "Error: --surface is required when --target is not given.",
            file=sys.stderr,
        )
        sys.exit(1)

    # --- Load target profile (if given) ---
    profile = None
    if target_path is not None:
        from toolfence.contracts.profile import TargetProfile

        try:
            profile = TargetProfile.model_validate(
                json.loads(Path(target_path).read_text(encoding="utf-8"))
            )
        except Exception as exc:  # noqa: BLE001
            print(f"Error loading target profile {target_path!r}: {exc}", file=sys.stderr)
            sys.exit(1)

        # --target requires --live; fail immediately with a usage error.
        if not live:
            print(
                "Error: --target requires --live. Run with --live to use a target profile.",
                file=sys.stderr,
            )
            sys.exit(1)

        # Profile overrides CLI --config and --surface for live runs.
        config_path = profile.nanobot_config
        surface_path = profile.surface

    # --- Live mode pre-flight ---
    adapter_factory = None
    if live:
        if not os.environ.get("OPENROUTER_API_KEY"):
            print(
                "Error: OPENROUTER_API_KEY is not set — "
                "export it before running live eval.",
                file=sys.stderr,
            )
            sys.exit(1)

        if profile is not None:
            # Profile-driven live run.
            from toolfence.integration.live_factory import (
                check_target_health,
                make_live_factory_from_profile,
            )
            if profile.health_url is not None:
                try:
                    check_target_health(profile.health_url)
                except RuntimeError as exc:
                    print(f"Error: {exc}", file=sys.stderr)
                    sys.exit(1)

            run_id_for_factory = datetime.datetime.utcnow().strftime("run-%Y%m%d-%H%M%S")
            adapter_factory = make_live_factory_from_profile(profile, run_id_for_factory)
        else:
            # Legacy Galaxium live run (no --target).
            from toolfence.integration.live_factory import (
                check_galaxium_health,
                make_live_factory,
            )
            try:
                check_galaxium_health()
            except RuntimeError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                sys.exit(1)

            run_id_for_factory = datetime.datetime.utcnow().strftime("run-%Y%m%d-%H%M%S")
            adapter_factory = make_live_factory(config_path, surface_path, run_id_for_factory)
    else:
        run_id_for_factory = None  # will be set below

    # --- Load surface ---
    try:
        surface = SurfaceFile.model_validate(
            json.loads(Path(surface_path).read_text(encoding="utf-8"))
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Error loading surface {surface_path!r}: {exc}", file=sys.stderr)
        sys.exit(1)

    # --- Locate probe templates and their paired fixture traces ---
    engine_probes_dir = _REPO_ROOT / "toolfence" / "engine" / "probes"
    fixtures_probes_dir = _REPO_ROOT / "fixtures" / "probes"

    attack_probes: list[tuple[dict, Any]] = []
    normal_probes: list[tuple[dict, Any]] = []

    if profile is not None:
        # Profile-driven probe list.
        for probe_entry in profile.attack_probes:
            if isinstance(probe_entry, str):
                probe_path = _REPO_ROOT / probe_entry
                task_prompt_override = None
            else:
                # AttackProbeEntry object with an explicit per-probe task_prompt.
                probe_path = _REPO_ROOT / probe_entry.path
                task_prompt_override = probe_entry.task_prompt

            if not probe_path.exists():
                print(f"Probe template not found: {probe_path}", file=sys.stderr)
                sys.exit(1)
            probe_dict = json.loads(probe_path.read_text(encoding="utf-8"))

            probe_dict = _apply_task_prompt(probe_dict, profile, task_prompt_override)

            normal_fix_path = fixtures_probes_dir / "normal_task.json"
            stub_adapter = ScriptedAdapter(normal_fix_path) if normal_fix_path.exists() else None
            attack_probes.append((probe_dict, stub_adapter))  # type: ignore[arg-type]

        # Normal task from profile.
        normal_fix_path = fixtures_probes_dir / "normal_task.json"
        if not normal_fix_path.exists():
            print(f"Normal task fixture not found: {normal_fix_path}", file=sys.stderr)
            sys.exit(1)
        normal_probes.append((
            {
                "content": profile.normal_task.prompt,
                "goal_tool": profile.normal_task.goal_tool,
                "label": "write_only",
            },
            ScriptedAdapter(normal_fix_path),
        ))
        # Extra normal tasks (e.g. read_then_write for filesystem profile).
        for extra in profile.extra_normal_tasks:
            normal_probes.append((
                {
                    "content": extra.prompt,
                    "goal_tool": extra.goal_tool,
                    "label": extra.label,
                },
                ScriptedAdapter(normal_fix_path),
            ))
    else:
        # Legacy fixed probe list (backward-compatible Galaxium path).
        _ATTACK_PAIRS: list[tuple[str, str]] = [
            ("cancel-user-input.json",  "fixture_user_input.json"),
            ("cancel-tool-result.json", "fixture_tool_result.json"),
        ]
        _NORMAL_FIXTURE = "normal_task.json"
        _NORMAL_PROBE_CONTENT = NORMAL_TASK_PROMPT

        for probe_name, fixture_name in _ATTACK_PAIRS:
            probe_path = engine_probes_dir / probe_name
            fix_path = fixtures_probes_dir / fixture_name
            if not probe_path.exists():
                print(f"Probe template not found: {probe_path}", file=sys.stderr)
                sys.exit(1)
            if not fix_path.exists():
                print(f"Fixture trace not found: {fix_path}", file=sys.stderr)
                sys.exit(1)
            probe_dict = json.loads(probe_path.read_text(encoding="utf-8"))
            attack_probes.append((probe_dict, ScriptedAdapter(fix_path)))

        normal_fix_path = fixtures_probes_dir / _NORMAL_FIXTURE
        if not normal_fix_path.exists():
            print(f"Normal task fixture not found: {normal_fix_path}", file=sys.stderr)
            sys.exit(1)
        normal_probes = [
            ({"content": _NORMAL_PROBE_CONTENT}, ScriptedAdapter(normal_fix_path)),
        ]

    # --- Apply filters ---
    # --probe: a probe ID selects attack-only and drops normal;
    #          the literal "normal" selects normal-only and drops attack.
    if probe_filter is not None:
        if probe_filter == "normal":
            attack_probes = []
        else:
            attack_probes = [
                (pd, a) for pd, a in attack_probes
                if pd.get("probe_id") == probe_filter
            ]
            normal_probes = []

    # --defense: filter defense rows by name
    defenses = list(DEFAULT_DEFENSES)
    if defense_filter is not None:
        defenses = [d for d in defenses if d.name == defense_filter]

    # --guard: filter defense rows by guard_on flag
    if guard_filter is not None:
        want_guard_on = guard_filter == "on"
        defenses = [d for d in defenses if d.guard_on == want_guard_on]

    # Guard against empty matrix
    total_trials = len(attack_probes) * len(defenses) + len(normal_probes) * len(defenses)
    log.info(
        "_cmd_run: %d attack probe(s), %d normal probe(s), %d defense(s) → %d trial(s)",
        len(attack_probes), len(normal_probes), len(defenses), total_trials,
    )
    if total_trials == 0:
        print(
            "Warning: the combination of --probe/--defense/--guard filters "
            "produced zero trials. Nothing to run.",
            file=sys.stderr,
        )
        sys.exit(0)

    # --- Compute run_id (re-use the one from live factory if already set) ---
    run_id = run_id_for_factory or datetime.datetime.utcnow().strftime("run-%Y%m%d-%H%M%S")

    # --- Build runner ---
    runner = EvaluationRunner(
        attack_probes=attack_probes,
        normal_probes=normal_probes,
        defenses=defenses,
        surface_map=surface,
        adapter_factory=adapter_factory,
    )

    mode_label = "live" if live else "scripted"
    print(f"Starting evaluation run: {run_id}  [{mode_label}]")
    print(f"Surface: {surface_path}  ({len(surface.tools)} tools)")
    print(f"Defenses: {len(defenses)} condition(s)")
    print(f"Attack probes: {len(attack_probes)}  |  Normal probes: {len(normal_probes)}")
    if live:
        print(f"Config: {config_path}")
    print()

    # --- Run ---
    log.info("_cmd_run: starting evaluation run %r", run_id)
    try:
        records, summary = runner.run(run_id=run_id)
    except Exception as exc:  # noqa: BLE001
        log.error("_cmd_run: evaluation failed — %s", exc)
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        sys.exit(1)
    log.info("_cmd_run: run complete — %d record(s) written", len(records))

    # --- Write records ---
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    for rec in records:
        rec_file = out_path / f"{rec.trial_id}.json"
        rec_file.write_text(
            json.dumps(rec.model_dump(), indent=2, default=str),
            encoding="utf-8",
        )
        verdict_label = rec.verdict or "(normal)"
        print(f"  {rec.trial_id}  {rec.kind:<8}  {verdict_label}")

    print()
    print(f"Wrote {len(records)} trial record(s) to {out_path.resolve()}")

    # Brief aggregate
    attack_recs = [r for r in records if r.kind == "attack"]
    normal_recs = [r for r in records if r.kind == "normal"]
    print(
        f"Attack: {len(attack_recs)} records  |  "
        f"Normal: {len(normal_recs)} records  |  "
        f"Total: {len(records)}"
    )

    sys.exit(0)


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def _cmd_report(results_dir: str) -> None:
    """Print a markdown report from all trial records in *results_dir*."""
    from toolfence.contracts.trial import TrialRecord
    from toolfence.engine.report import render_report
    from toolfence.engine.scoring import aggregate

    log.info("_cmd_report: reading results from %r", results_dir)
    results_path = Path(results_dir)
    if not results_path.is_dir():
        log.error("_cmd_report: directory not found: %s", results_path)
        print(f"Results directory not found: {results_path}", file=sys.stderr)
        sys.exit(1)

    json_files = sorted(results_path.glob("*.json"))
    if not json_files:
        log.warning("_cmd_report: no .json files in %s", results_path)
        print(f"No .json files found in {results_path}", file=sys.stderr)
        sys.exit(1)
    log.debug("_cmd_report: found %d JSON file(s)", len(json_files))

    records: list[TrialRecord] = []
    for jf in json_files:
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
            records.append(TrialRecord.model_validate(data))
        except Exception as exc:  # noqa: BLE001
            log.warning("_cmd_report: skipping %s — %s", jf.name, exc)
            print(f"Warning: could not load {jf.name}: {exc}", file=sys.stderr)

    if not records:
        log.error("_cmd_report: no valid trial records found in %s", results_path)
        print("No valid trial records found.", file=sys.stderr)
        sys.exit(1)
    log.info("_cmd_report: loaded %d valid record(s)", len(records))

    # Use run_id from first record; fall back to dir name
    run_id = records[0].run_id if records else results_dir
    summary = aggregate(records, run_id=run_id)
    report = render_report(summary)
    # Write as UTF-8 bytes directly to avoid Windows cp1252 encode errors
    # (the report contains ✓/✗ characters from render_report).
    sys.stdout.buffer.write(report.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()

    sys.exit(0)


# ---------------------------------------------------------------------------
# serve (dashboard)
# ---------------------------------------------------------------------------

def _cmd_serve(host: str, port: int, results_dir: str) -> None:
    """Start the read-only results dashboard server."""
    from toolfence.cli.dashboard.server import run_server
    run_server(host=host, port=port, results_dir=Path(results_dir))


# ---------------------------------------------------------------------------
# ci-check
# ---------------------------------------------------------------------------

def _cmd_ci_check(surface_path: str, live_path: "str | None") -> None:
    """Run the surface-diff CI check and exit with the result code."""
    from toolfence.cli.ci_checks import surface_diff_check

    log.info("_cmd_ci_check: surface=%r live=%r", surface_path, live_path)
    if live_path is not None:
        try:
            live_data = json.loads(Path(live_path).read_text(encoding="utf-8"))
            live_tool_list = (
                live_data if isinstance(live_data, list)
                else live_data.get("tools", [])
            )
        except Exception as exc:  # noqa: BLE001
            log.error("_cmd_ci_check: failed to load live tool list %r — %s", live_path, exc)
            print(f"Error loading live tool list {live_path!r}: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        try:
            raw = json.loads(Path(surface_path).read_text(encoding="utf-8"))
            live_tool_list = raw.get("tools", []) if isinstance(raw, dict) else raw
        except Exception as exc:  # noqa: BLE001
            log.error("_cmd_ci_check: failed to load surface file %r — %s", surface_path, exc)
            print(f"Error loading surface file {surface_path!r}: {exc}", file=sys.stderr)
            sys.exit(1)

    exit_code, message = surface_diff_check(surface_path, live_tool_list)

    if exit_code == 0:
        log.info("_cmd_ci_check: PASSED — %s", message)
        print(f"CI surface-diff check passed: {message}")
    else:
        log.warning("_cmd_ci_check: FAILED — %s", message)
        print(f"CI surface-diff check FAILED:\n{message}", file=sys.stderr)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
