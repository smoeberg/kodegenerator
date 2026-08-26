"""Subcommand: kodegen status --project-id <id>."""
from __future__ import annotations

import argparse
from typing import Any

from services.swarm_persistence import SQLiteTaskQueue
from services.cost_optimizer import CostOptimizer


def register_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("status", help="Get live status and metrics for a swarm project")
    parser.add_argument("--project-id", type=str, required=True, help="Project identifier")
    parser.add_argument("--db-path", type=str, default=":memory:", help="SQLite DB path for swarm queue")
    parser.set_defaults(handler="status")


def execute(args: argparse.Namespace) -> int:
    queue = SQLiteTaskQueue(db_path=args.db_path)
    stats = queue.get_queue_stats()
    optimizer = CostOptimizer()
    breakdown = optimizer.project_cost(args.project_id)

    print(f"📊 Project Status: {args.project_id}")
    print(f"  • Pending:   {stats.get('pending', 0)}")
    print(f"  • Claimed:   {stats.get('claimed', 0)}")
    print(f"  • Completed: {stats.get('completed', 0)}")
    print(f"  • Failed:    {stats.get('failed', 0)}")
    print(f"  • Spend:     ${breakdown.total_cost:.4f}")
    return 0
