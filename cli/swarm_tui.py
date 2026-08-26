"""DOR Swarm Production TUI & CLI monitor.

Live terminal view of workers, queue, leases, events, and DLQ.
Supports interactive refresh loop and headless snapshot modes
(text table or JSON).

Usage:
  python -m cli.swarm_tui --project-id proj-demo --refresh-rate 1.0
  python -m cli.swarm_tui --snapshot --format text
  python -m cli.swarm_tui --snapshot --format json --project-id proj-oauth2
  python -m cli.swarm_tui --pause --project-id proj-demo
  python -m cli.swarm_tui --resume --project-id proj-demo
  python -m cli.swarm_tui --inspect-task T-03 --project-id proj-demo
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Snapshot data model
# ---------------------------------------------------------------------------


@dataclass
class WorkerRow:
    worker_id: str
    state: str
    task_id: str | None
    lease_until: str | None
    caps: list[str]


@dataclass
class QueueRow:
    message_id: str
    topic: str
    task_id: str
    status: str
    attempts: int


@dataclass
class LeaseRow:
    lease_id: str
    worker_id: str
    task_id: str
    expires_at: str
    remaining_sec: int


@dataclass
class EventRow:
    timestamp: str
    level: str
    source: str
    message: str


@dataclass
class SwarmSnapshot:
    project_id: str
    captured_at: str
    paused: bool
    workers: list[WorkerRow] = field(default_factory=list)
    queue: list[QueueRow] = field(default_factory=list)
    leases: list[LeaseRow] = field(default_factory=list)
    events: list[EventRow] = field(default_factory=list)
    dlq_count: int = 0
    tasks_pending: int = 0
    tasks_running: int = 0
    tasks_done: int = 0
    tasks_failed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "captured_at": self.captured_at,
            "paused": self.paused,
            "counts": {
                "workers_active": sum(
                    1 for w in self.workers if w.state in ("busy", "running")
                ),
                "workers_total": len(self.workers),
                "queue_depth": len(self.queue),
                "leases": len(self.leases),
                "dlq": self.dlq_count,
                "tasks_pending": self.tasks_pending,
                "tasks_running": self.tasks_running,
                "tasks_done": self.tasks_done,
                "tasks_failed": self.tasks_failed,
            },
            "workers": [asdict(w) for w in self.workers],
            "queue": [asdict(q) for q in self.queue],
            "leases": [asdict(x) for x in self.leases],
            "events": [asdict(e) for e in self.events],
        }


# ---------------------------------------------------------------------------
# In-memory / fixture swarm view (no DB required for local ops)
# ---------------------------------------------------------------------------

_PROJECT_PAUSE: dict[str, bool] = {}
_TASK_DETAILS: dict[str, dict[str, Any]] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).strftime("%Y-%m-%dT%H:%M:%SZ")


def collect_snapshot(project_id: str) -> SwarmSnapshot:
    """Build a SwarmSnapshot for the given project.

    Uses deterministic demo fixtures so TUI/CLI works offline. Production
    can replace this with queue/DB adapters without changing renderers.
    """
    now = _now()
    paused = _PROJECT_PAUSE.get(project_id, False)

    workers = [
        WorkerRow("worker-01", "busy" if not paused else "paused", "T-03", _iso(now + timedelta(seconds=180)), ["domain", "code"]),
        WorkerRow("worker-02", "busy" if not paused else "paused", "T-04", _iso(now + timedelta(seconds=95)), ["code"]),
        WorkerRow("worker-03", "idle", None, None, ["test", "security"]),
        WorkerRow("worker-04", "busy" if not paused else "paused", "T-06", _iso(now + timedelta(seconds=240)), ["test", "code"]),
        WorkerRow("worker-05", "idle", None, None, ["arch", "domain"]),
        WorkerRow("worker-06", "busy" if not paused else "paused", "T-08", _iso(now + timedelta(seconds=60)), ["test"]),
    ]

    queue = [
        QueueRow("msg-a1", "task.execute", "T-05", "pending", 0),
        QueueRow("msg-a2", "task.execute", "T-07", "pending", 1),
        QueueRow("msg-a3", "task.verify", "T-09", "pending", 0),
        QueueRow("msg-a4", "task.execute", "T-10", "pending", 0),
    ]

    leases = [
        LeaseRow("lease-01", "worker-01", "T-03", _iso(now + timedelta(seconds=180)), 180),
        LeaseRow("lease-02", "worker-02", "T-04", _iso(now + timedelta(seconds=95)), 95),
        LeaseRow("lease-03", "worker-04", "T-06", _iso(now + timedelta(seconds=240)), 240),
        LeaseRow("lease-04", "worker-06", "T-08", _iso(now + timedelta(seconds=60)), 60),
    ]

    events = [
        EventRow(_iso(now - timedelta(seconds=45)), "INFO", "orchestrator", f"project {project_id} tick"),
        EventRow(_iso(now - timedelta(seconds=30)), "PASS", "gatekeeper", "T-02 AST + policy OK"),
        EventRow(_iso(now - timedelta(seconds=22)), "INFO", "worker-01", "CLAIM T-03 Domain model & ports"),
        EventRow(_iso(now - timedelta(seconds=15)), "WARN", "sentinel", "lease lease-04 expires in 60s"),
        EventRow(_iso(now - timedelta(seconds=8)), "FAIL", "gatekeeper", "T-05 REJECT policy evidence incomplete"),
        EventRow(_iso(now - timedelta(seconds=3)), "INFO", "healer", "REQUEUE T-05"),
    ]

    # Seed inspectable task details
    for tid, name, status in [
        ("T-03", "Domain model & ports", "running"),
        ("T-04", "API adapters", "running"),
        ("T-05", "Auth OAuth2/PKCE", "pending"),
        ("T-06", "Unit tests", "running"),
        ("T-07", "Security review evidence", "pending"),
        ("T-08", "Integration tests", "running"),
        ("T-09", "AST architecture gate", "pending"),
        ("T-10", "P3-20 verification pack", "pending"),
    ]:
        _TASK_DETAILS.setdefault(
            tid,
            {
                "task_id": tid,
                "project_id": project_id,
                "name": name,
                "status": status,
                "assignee": next((w.worker_id for w in workers if w.task_id == tid), None),
                "attempts": 1 if tid == "T-05" else 0,
                "required_caps": ["code"] if "API" in name or "Domain" in name else ["test"],
            },
        )

    return SwarmSnapshot(
        project_id=project_id,
        captured_at=_iso(now),
        paused=paused,
        workers=workers,
        queue=queue,
        leases=leases,
        events=events,
        dlq_count=2,
        tasks_pending=4,
        tasks_running=4 if not paused else 0,
        tasks_done=2,
        tasks_failed=1,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_text_table(snapshot: SwarmSnapshot) -> str:
    """Plain-text multi-section report (no external TUI deps)."""
    lines: list[str] = []
    pause_flag = " PAUSED" if snapshot.paused else ""
    lines.append("=" * 72)
    lines.append(
        f" DOR Swarm TUI  project={snapshot.project_id}  "
        f"at={snapshot.captured_at}{pause_flag}"
    )
    lines.append("=" * 72)

    # Counts
    lines.append("")
    lines.append("--- COUNTS ---")
    lines.append(
        f"  workers_active={sum(1 for w in snapshot.workers if w.state in ('busy', 'running', 'paused'))}/"
        f"{len(snapshot.workers)}  queue={len(snapshot.queue)}  "
        f"leases={len(snapshot.leases)}  dlq={snapshot.dlq_count}"
    )
    lines.append(
        f"  tasks  pending={snapshot.tasks_pending}  running={snapshot.tasks_running}  "
        f"done={snapshot.tasks_done}  failed={snapshot.tasks_failed}"
    )

    # Workers
    lines.append("")
    lines.append("--- WORKERS ---")
    lines.append(f"  {'ID':<12} {'STATE':<10} {'TASK':<8} {'LEASE_UNTIL':<22} CAPS")
    for w in snapshot.workers:
        lines.append(
            f"  {w.worker_id:<12} {w.state:<10} {w.task_id or '—':<8} "
            f"{w.lease_until or '—':<22} {','.join(w.caps)}"
        )

    # Queue
    lines.append("")
    lines.append("--- QUEUE ---")
    lines.append(f"  {'MSG':<10} {'TOPIC':<14} {'TASK':<8} {'STATUS':<10} ATTEMPTS")
    for q in snapshot.queue:
        lines.append(
            f"  {q.message_id:<10} {q.topic:<14} {q.task_id:<8} {q.status:<10} {q.attempts}"
        )

    # Leases
    lines.append("")
    lines.append("--- LEASES ---")
    lines.append(f"  {'LEASE':<12} {'WORKER':<12} {'TASK':<8} {'EXPIRES':<22} REM_S")
    for x in snapshot.leases:
        lines.append(
            f"  {x.lease_id:<12} {x.worker_id:<12} {x.task_id:<8} "
            f"{x.expires_at:<22} {x.remaining_sec}"
        )

    # Events
    lines.append("")
    lines.append("--- EVENTS ---")
    for e in snapshot.events[:12]:
        lines.append(f"  {e.timestamp}  {e.level:<5}  [{e.source}] {e.message}")

    # DLQ
    lines.append("")
    lines.append("--- DLQ ---")
    lines.append(f"  dead_letter_count={snapshot.dlq_count}")

    lines.append("")
    lines.append("=" * 72)
    return "\n".join(lines) + "\n"


def render_json(snapshot: SwarmSnapshot) -> str:
    return json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False) + "\n"


def render_snapshot(
    snapshot: SwarmSnapshot,
    fmt: Literal["text", "json"] = "text",
) -> str:
    if fmt == "json":
        return render_json(snapshot)
    return render_text_table(snapshot)


# ---------------------------------------------------------------------------
# Control commands
# ---------------------------------------------------------------------------


def pause_project(project_id: str) -> str:
    _PROJECT_PAUSE[project_id] = True
    return f"project {project_id} paused"


def resume_project(project_id: str) -> str:
    _PROJECT_PAUSE[project_id] = False
    return f"project {project_id} resumed"


def inspect_task(task_id: str, project_id: str) -> dict[str, Any]:
    # Ensure snapshot seeded details for project
    collect_snapshot(project_id)
    detail = _TASK_DETAILS.get(task_id)
    if detail is None:
        return {
            "task_id": task_id,
            "project_id": project_id,
            "error": "task_not_found",
        }
    return dict(detail)


# ---------------------------------------------------------------------------
# Interactive loop (curses optional, plain refresh fallback)
# ---------------------------------------------------------------------------


def run_interactive(project_id: str, refresh_rate: float) -> int:
    """Refresh text table until Ctrl+C. Tries curses; falls back to clear+print."""
    stop = False

    def _handle(signum: int, frame: Any) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)

    use_curses = False
    try:
        import curses  # noqa: F401

        use_curses = sys.stdout.isatty()
    except ImportError:
        use_curses = False

    if use_curses:
        return _run_curses(project_id, refresh_rate)
    return _run_plain_loop(project_id, refresh_rate, lambda: stop)


def _run_plain_loop(
    project_id: str,
    refresh_rate: float,
    should_stop: Any,
) -> int:
    while not should_stop():
        snap = collect_snapshot(project_id)
        # ANSI clear for TTYs
        if sys.stdout.isatty():
            sys.stdout.write("\033[2J\033[H")
        sys.stdout.write(render_text_table(snap))
        sys.stdout.write(
            f"\n  refresh={refresh_rate}s  Ctrl+C to exit  "
            f"(pause via: python -m cli.swarm_tui --pause --project-id {project_id})\n"
        )
        sys.stdout.flush()
        time.sleep(max(0.2, refresh_rate))
    return 0


def _run_curses(project_id: str, refresh_rate: float) -> int:
    import curses

    def _draw(stdscr: Any) -> None:
        curses.curs_set(0)
        stdscr.nodelay(True)
        while True:
            ch = stdscr.getch()
            if ch in (ord("q"), ord("Q"), 27):
                break
            snap = collect_snapshot(project_id)
            text = render_text_table(snap)
            stdscr.erase()
            max_y, max_x = stdscr.getmaxyx()
            for i, line in enumerate(text.splitlines()):
                if i >= max_y - 1:
                    break
                stdscr.addstr(i, 0, line[: max_x - 1])
            hint = " q=quit  p=pause  r=resume "
            try:
                stdscr.addstr(max_y - 1, 0, hint[: max_x - 1])
            except curses.error:
                pass
            if ch in (ord("p"), ord("P")):
                pause_project(project_id)
            if ch in (ord("r"), ord("R")):
                resume_project(project_id)
            stdscr.refresh()
            time.sleep(max(0.2, refresh_rate))

    curses.wrapper(_draw)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m cli.swarm_tui",
        description="DOR Swarm Production TUI — live monitor, snapshot, pause/resume, task inspect",
    )
    p.add_argument(
        "--project-id",
        default="proj-demo",
        help="Project identifier to monitor (default: proj-demo)",
    )
    p.add_argument(
        "--refresh-rate",
        type=float,
        default=1.0,
        help="Seconds between interactive refreshes (default: 1.0)",
    )
    p.add_argument(
        "--headless",
        action="store_true",
        help="Single snapshot then exit (no interactive loop)",
    )
    p.add_argument(
        "--snapshot",
        action="store_true",
        help="Alias for --headless: print one snapshot and exit",
    )
    p.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Snapshot output format (default: text)",
    )
    p.add_argument(
        "--pause",
        action="store_true",
        help="Pause project swarm processing and exit",
    )
    p.add_argument(
        "--resume",
        action="store_true",
        help="Resume project swarm processing and exit",
    )
    p.add_argument(
        "--inspect-task",
        metavar="TASK_ID",
        default=None,
        help="Print details for a single task id and exit",
    )
    return p


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.refresh_rate <= 0:
        parser.error("--refresh-rate must be > 0")
    if args.snapshot:
        args.headless = True
    if args.pause and args.resume:
        parser.error("use only one of --pause / --resume")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.pause:
        print(pause_project(args.project_id), flush=True)
        return 0
    if args.resume:
        print(resume_project(args.project_id), flush=True)
        return 0
    if args.inspect_task:
        detail = inspect_task(args.inspect_task, args.project_id)
        if args.format == "json" or True:
            # inspect always JSON for machine use; also print pretty
            print(json.dumps(detail, indent=2, ensure_ascii=False), flush=True)
        return 0 if "error" not in detail else 1

    if args.headless or args.snapshot:
        snap = collect_snapshot(args.project_id)
        sys.stdout.write(render_snapshot(snap, fmt=args.format))  # type: ignore[arg-type]
        return 0

    return run_interactive(args.project_id, args.refresh_rate)


if __name__ == "__main__":
    sys.exit(main())
