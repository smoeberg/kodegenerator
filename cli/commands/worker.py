"""Subcommand: kodegen worker --concurrency 4."""
from __future__ import annotations

import argparse
from typing import Any

from services.swarm_persistence import SQLiteTaskQueue
from services.worker_agent_daemon import WorkerAgent
from services.swarm_supervisor import SwarmSupervisor


def register_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("worker", help="Start dedicated worker daemon pool")
    parser.add_argument("--concurrency", type=int, default=4, help="Worker concurrency (default: 4)")
    parser.add_argument("--project-id", type=str, default="default", help="Project identifier to pull from")
    parser.add_argument("--db-path", type=str, default=":memory:", help="SQLite DB path")
    parser.set_defaults(handler="worker")


def execute(args: argparse.Namespace) -> int:
    print(f"👷 Starting worker pool (concurrency={args.concurrency}) for project={args.project_id}")
    queue = SQLiteTaskQueue(db_path=args.db_path)
    
    def worker_factory(agent_id: str, capabilities: Any) -> WorkerAgent:
        return WorkerAgent(worker_id=agent_id, capabilities=list(capabilities), queue=queue)

    caps = [["service", "code"] for _ in range(args.concurrency)]
    supervisor = SwarmSupervisor(worker_factory, caps, health_interval=0.1)
    supervisor.start()
    try:
        print(f"👷 {supervisor.active_workers} workers active. Press Ctrl+C to stop.")
    finally:
        supervisor.stop()
        supervisor.join(1.0)
    print("👷 Worker pool exited gracefully.")
    return 0
