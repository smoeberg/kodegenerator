"""CLI entry for the swarm Worker Agent Daemon.

Usage::

    # In-process empty queue (legacy demo)
    python -m cli.worker --id worker-01 --caps code,test

    # Claim tasks published by the pipeline orchestrator (shared registry)
    python -m cli.worker --id worker-01 --caps code,test,domain,arch --pipeline
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
        "--pipeline",
        action="store_true",
        help=(
            "Claim from the process-shared pipeline task queue "
            "(requires API/worker in the same process or a prior registry init)."
        ),
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


def _resolve_queue(args: argparse.Namespace) -> SwarmTaskQueue:
    if not args.pipeline:
        return SwarmTaskQueue(lease_seconds=args.lease_seconds)
    try:
        from api.dependencies import get_dor
        from runtime.pipeline_registry import get_pipeline_registry
    except ImportError:
        logging.getLogger(__name__).warning(
            "pipeline registry unavailable; falling back to empty local queue"
        )
        return SwarmTaskQueue(lease_seconds=args.lease_seconds)

    # Initialise registry with the same runtime the API uses when possible.
    try:
        runtime = get_dor()
    except Exception:
        runtime = None
    if runtime is not None:
        registry = get_pipeline_registry(runtime, lease_seconds=args.lease_seconds)
    else:
        # Registry must already exist (e.g. API started first in-process).
        registry = get_pipeline_registry(lease_seconds=args.lease_seconds)
    return registry.queue


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    queue = _resolve_queue(args)
    synthesizer = None
    if args.pipeline:
        from contextlib import contextmanager

        from execution.pipeline_executors import build_pipeline_executor_registry
        from execution.pipeline_task_synthesizer import PipelineTaskSynthesizer
        from infrastructure.persistence.uow import UnitOfWork
        from runtime.pipeline_registry import get_pipeline_registry
        from services.task_execution_service import (
            DictTaskExecutorFactory,
            TaskExecutionService,
        )

        registry = get_pipeline_registry()

        @contextmanager
        def execution_service_factory():
            with registry.runtime.database.session() as session:
                yield TaskExecutionService(
                    UnitOfWork(session),
                    DictTaskExecutorFactory(build_pipeline_executor_registry()),
                    runtime_ready=registry.runtime.ready,
                )

        synthesizer = PipelineTaskSynthesizer(
            context_provider=lambda workflow_id: dict(
                registry.orchestrator.get_pipeline_status(workflow_id)["context"]
            ),
            execution_service_factory=execution_service_factory,
        )
    agent = WorkerAgent(
        worker_id=args.worker_id,
        capabilities=args.capabilities,
        queue=queue,
        poll_interval=args.poll_interval,
        heartbeat_interval=args.heartbeat_interval,
        synthesizer=synthesizer,
    )
    agent.run(install_signal_handlers=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
