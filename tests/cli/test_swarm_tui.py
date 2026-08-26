"""Tests for cli.swarm_tui — snapshot render, formats, argument parsing."""

from __future__ import annotations

import json

import pytest

from cli.swarm_tui import (
    build_parser,
    collect_snapshot,
    inspect_task,
    main,
    parse_args,
    pause_project,
    render_json,
    render_snapshot,
    render_text_table,
    resume_project,
)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def test_parse_project_id_and_refresh_rate():
    args = parse_args(
        ["--project-id", "proj-oauth2", "--refresh-rate", "2.5"]
    )
    assert args.project_id == "proj-oauth2"
    assert args.refresh_rate == 2.5


def test_parse_headless_and_snapshot():
    args = parse_args(["--snapshot", "--format", "json"])
    assert args.headless is True
    assert args.snapshot is True
    assert args.format == "json"


def test_parse_headless_flag():
    args = parse_args(["--headless", "--format", "text"])
    assert args.headless is True
    assert args.format == "text"


def test_parse_rejects_non_positive_refresh():
    with pytest.raises(SystemExit):
        parse_args(["--refresh-rate", "0"])


def test_parse_rejects_pause_and_resume_together():
    with pytest.raises(SystemExit):
        parse_args(["--pause", "--resume"])


def test_build_parser_mentions_options():
    help_text = build_parser().format_help()
    assert "--project-id" in help_text
    assert "--refresh-rate" in help_text
    assert "--headless" in help_text or "--snapshot" in help_text


# ---------------------------------------------------------------------------
# Snapshot content
# ---------------------------------------------------------------------------


def test_collect_snapshot_has_required_sections():
    snap = collect_snapshot("proj-test")
    assert snap.project_id == "proj-test"
    assert snap.captured_at
    assert len(snap.workers) >= 1
    assert len(snap.queue) >= 1
    assert len(snap.leases) >= 1
    assert len(snap.events) >= 1
    assert snap.dlq_count >= 0
    assert snap.tasks_pending >= 0


def test_text_render_contains_all_section_headers():
    snap = collect_snapshot("proj-demo")
    text = render_text_table(snap)
    for section in (
        "COUNTS",
        "WORKERS",
        "QUEUE",
        "LEASES",
        "EVENTS",
        "DLQ",
    ):
        assert section in text, f"missing section {section}"
    assert "proj-demo" in text
    assert "worker-" in text
    assert "dead_letter_count=" in text


def test_json_render_structure():
    snap = collect_snapshot("proj-json")
    payload = json.loads(render_json(snap))
    assert payload["project_id"] == "proj-json"
    assert "counts" in payload
    assert "workers" in payload
    assert "queue" in payload
    assert "leases" in payload
    assert "events" in payload
    assert payload["counts"]["dlq"] == snap.dlq_count
    assert isinstance(payload["workers"], list)
    assert len(payload["workers"]) == len(snap.workers)


def test_render_snapshot_format_dispatch():
    snap = collect_snapshot("proj-x")
    assert "WORKERS" in render_snapshot(snap, "text")
    assert json.loads(render_snapshot(snap, "json"))["project_id"] == "proj-x"


# ---------------------------------------------------------------------------
# Headless CLI
# ---------------------------------------------------------------------------


def test_main_snapshot_text(capsys):
    code = main(["--snapshot", "--project-id", "proj-cli", "--format", "text"])
    assert code == 0
    out = capsys.readouterr().out
    assert "COUNTS" in out
    assert "WORKERS" in out
    assert "QUEUE" in out
    assert "LEASES" in out
    assert "EVENTS" in out
    assert "DLQ" in out
    assert "proj-cli" in out


def test_main_snapshot_json(capsys):
    code = main(["--headless", "--project-id", "proj-j", "--format", "json"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["project_id"] == "proj-j"
    assert "dlq" in data["counts"]


def test_main_pause_resume(capsys):
    assert main(["--pause", "--project-id", "proj-pr"]) == 0
    assert "paused" in capsys.readouterr().out
    snap = collect_snapshot("proj-pr")
    assert snap.paused is True
    assert main(["--resume", "--project-id", "proj-pr"]) == 0
    assert "resumed" in capsys.readouterr().out
    assert collect_snapshot("proj-pr").paused is False


def test_main_inspect_task(capsys):
    code = main(["--inspect-task", "T-03", "--project-id", "proj-demo"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["task_id"] == "T-03"
    assert data.get("error") is None


def test_inspect_unknown_task():
    detail = inspect_task("T-MISSING", "proj-demo")
    assert detail.get("error") == "task_not_found"


def test_pause_resume_helpers():
    pause_project("proj-z")
    assert collect_snapshot("proj-z").paused is True
    resume_project("proj-z")
    assert collect_snapshot("proj-z").paused is False
