"""Subcommand: kodegen run "<requirement>"."""
from __future__ import annotations

import argparse
import sys
import uuid
from typing import Any

from services.task_router import TaskRouter
from services.swarm_persistence import SQLiteTaskQueue
from services.swarm_task_queue import QueuedTask
from services.worker_agent_daemon import WorkerAgent
from services.cost_optimizer import CostOptimizer


def register_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("run", help="Run full swarm pipeline on a requirement prompt")
    parser.add_argument("requirement", type=str, help="Natural language requirement or feature request")
    parser.add_argument("--project-id", type=str, default=None, help="Optional project identifier")
    parser.add_argument("--concurrency", type=int, default=2, help="Number of worker daemons (default: 2)")
    parser.add_argument("--db-path", type=str, default=":memory:", help="SQLite DB path for swarm queue")
    parser.set_defaults(handler="run")


def execute(args: argparse.Namespace) -> int:
    project_id = args.project_id or f"proj-{uuid.uuid4().hex[:8]}"
    print(f"🚀 Starting swarm run for project: {project_id}")
    print(f"📋 Requirement: {args.requirement}")

    router = TaskRouter()
    capability = router.route(args.requirement)
    print(f"🎯 Routed to capability: {capability}")

    queue = SQLiteTaskQueue(db_path=args.db_path)
    
    # Submit root task
    task = QueuedTask(
        task_id=f"task-{project_id}-1",
        name=f"Implement requirement: {args.requirement[:40]}",
        capabilities=(capability,),
        priority=1,
        metadata={"project_id": project_id},
    )
    queue.submit_task(task)
    print(f"🧩 Queued swarm tasks for project: {project_id}")

    # Run worker daemon single step / pool
    worker = WorkerAgent(
        worker_id=f"worker-{project_id}-1",
        capabilities=[capability],
        queue=queue,
    )
    processed = worker.run_once()
    if processed:
        print(f"⚡ Worker completed task: {processed.task_id}")

    optimizer = CostOptimizer()
    breakdown = optimizer.project_cost(project_id)
    print(f"✅ Swarm run complete for {project_id} | Spend: ${breakdown.total_cost:.4f}")
    return 0
