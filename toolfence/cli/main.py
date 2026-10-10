"""toolfence CLI entry point."""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="toolfence",
        description=(
            "ToolFence — tool-surface auditing and injection-resilience evaluation "
            "for MCP agents."
        ),
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    sub.add_parser("scan", help="Scan a target and produce a surface.json draft.")
    sub.add_parser("run", help="Run a safety evaluation against a target.")
    sub.add_parser("report", help="Render a markdown report from the latest results.")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    # Subcommand dispatch (implementations added in later tasks).
    print(f"Command '{args.command}' is not yet implemented.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
