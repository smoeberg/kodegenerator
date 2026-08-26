"""Unified ``kodegen`` CLI entrypoint.

Commands
--------
- ``kodegen run "<requirement>"`` — TaskRouter + WBS + local worker pool
- ``kodegen worker --concurrency 4`` — dedicated worker daemon pool
- ``kodegen status --project-id <id>`` — completion, DLQ, CostOptimizer spend

Usage::

    python -m cli.main run "Build a secure order API"
    python -m cli.main status --project-id proj-abc123
    python -m cli.main worker --concurrency 4 --max-idle-cycles 3
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Optional, Sequence

from cli.commands import run as run_cmd
from cli.commands import status as status_cmd
from cli.commands import worker as worker_cmd


def build_parser() -> argparse.ArgumentParser:
    """Construct the root argparse parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="kodegen",
        description=(
            "DOR kodegen — start, orchestrate and monitor a complete swarm run "
            "from the terminal."
        ),
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: WARNING)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run_cmd.register_parser(sub)
    worker_cmd.register_parser(sub)
    status_cmd.register_parser(sub)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point used by ``python -m cli.main`` and console scripts."""
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    handler = getattr(args, "handler", None)
    if handler == "run":
        return run_cmd.execute(args)
    if handler == "worker":
        return worker_cmd.execute(args)
    if handler == "status":
        return status_cmd.execute(args)

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
