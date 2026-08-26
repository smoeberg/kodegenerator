"""CLI entry for the swarm Worker Agent Daemon.

Usage::

    python -m cli.worker --id worker-01 --caps cap.domain.modeling,cap.code.generation
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import List

from services.swarm_task_queue import SwarmTaskQueue
from services.worker_agent_daemon import WorkerAgent


def parse_capabilities(raw: str) -> List[str]:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise argparse.ArgumentTypeError("at least one capability is required")
    return parts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cli.worker",
        description="Run a DOR swarm Worker Agent Daemon process.",
    )
    parser.add_argument(
        "--id",
        required=True,
        dest="worker_id",
        help="Stable worker / agent identity (e.g. worker-01).",
    )
    parser.add_argument(
        "--caps",
        required=True,
        type=parse_capabilities,
        dest="capabilities",
        help="Comma-separated capability tokens this worker may claim.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Seconds to wait when no eligible task is available (default: 1.0).",
    )
    parser.add_argument(
        "--heartbeat-interval",
        type=float,
        default=30.0,
        help="Seconds between lease heartbeats during task execution (default: 30).",
    )
    parser.add_argument(
        "--lease-seconds",
        type=int,
        default=300,
        help="Queue lease duration in seconds for the in-process queue (default: 300).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO).",
    )
    return parser


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    # In-process queue is suitable for single-process swarm demos and tests.
    # A durable queue adapter can be injected later without changing WorkerAgent.
    queue = SwarmTaskQueue(lease_seconds=args.lease_seconds)
    agent = WorkerAgent(
        worker_id=args.worker_id,
        capabilities=args.capabilities,
        queue=queue,
        poll_interval=args.poll_interval,
        heartbeat_interval=args.heartbeat_interval,
    )
    agent.run(install_signal_handlers=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
