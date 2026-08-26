"""Tests for cli.run_swarm — argument parsing, headless demo, shutdown."""

from __future__ import annotations

import threading
import time

import pytest

from cli.run_swarm import (
    SwarmState,
    TaskStatus,
    WorkerAgent,
    WorkerState,
    build_parser,
    load_demo_project,
    main,
    parse_args,
    parse_caps,
    project_complete,
    run_swarm,
)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def test_parse_caps_default_and_alias():
    assert "domain" in parse_caps(None)
    assert "domain" in parse_caps("domein,code,test")
    assert parse_caps("code, test") == frozenset({"code", "test"})


def test_parse_args_workers_and_demo():
    args = parse_args(["--workers", "8", "--demo", "--caps", "code,test"])
    assert args.workers == 8
    assert args.demo is True
    assert "code" in parse_caps(args.caps)


def test_parse_args_headless_implies_demo_and_ticks():
    args = parse_args(["--headless", "--workers", "2"])
    assert args.demo is True
    assert args.quiet is True
    assert args.max_ticks == 200


def test_parse_args_rejects_zero_workers():
    with pytest.raises(SystemExit):
        parse_args(["--workers", "0"])


def test_build_parser_help():
    parser = build_parser()
    help_text = parser.format_help()
    assert "--workers" in help_text
    assert "--demo" in help_text
    assert "Gatekeeper" in help_text or "swarm" in help_text.lower()


# ---------------------------------------------------------------------------
# Demo / state helpers
# ---------------------------------------------------------------------------


def test_load_demo_project_populates_tasks():
    state = SwarmState()
    load_demo_project(state)
    assert len(state.tasks) >= 5
    assert all(t.status == TaskStatus.PENDING for t in state.tasks.values())


def test_project_complete_false_until_all_merged():
    state = SwarmState()
    load_demo_project(state)
    assert project_complete(state) is False
    for t in state.tasks.values():
        t.status = TaskStatus.MERGED
    assert project_complete(state) is True


# ---------------------------------------------------------------------------
# Headless demo flow
# ---------------------------------------------------------------------------


def test_run_swarm_headless_completes_or_stops():
    """Headless demo should exit without hanging and merge at least one task."""
    args = parse_args(
        [
            "--headless",
            "--workers",
            "4",
            "--work-seconds",
            "0.02",
            "--max-ticks",
            "80",
        ]
    )
    code = run_swarm(args)
    assert code in (0, 1)
    # run_swarm returns after stop; if demo loaded, prefer success path when merges happened
    # Re-run short to assert exit 0 when max-ticks allows progress
    args2 = parse_args(
        [
            "--demo",
            "--quiet",
            "--workers",
            "6",
            "--work-seconds",
            "0.01",
            "--max-ticks",
            "120",
        ]
    )
    code2 = run_swarm(args2)
    assert code2 == 0


def test_main_headless_exit_code():
    code = main(
        [
            "--demo",
            "--quiet",
            "--workers",
            "3",
            "--work-seconds",
            "0.01",
            "--max-ticks",
            "100",
        ]
    )
    assert code == 0


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------


def test_stop_event_stops_workers_quickly():
    from cli.run_swarm import worker_loop

    state = SwarmState()
    load_demo_project(state)
    worker = WorkerAgent(
        worker_id="worker-test",
        caps=frozenset({"domain", "code", "test", "security", "arch", "pm"}),
    )
    state.workers[worker.worker_id] = worker

    t = threading.Thread(
        target=worker_loop, args=(state, worker, 0.05), daemon=True
    )
    t.start()
    time.sleep(0.15)
    state.stop_event.set()
    with state.lock:
        worker.state = WorkerState.STOPPING
    t.join(timeout=2.0)
    assert not t.is_alive()
    assert worker.state == WorkerState.STOPPED
