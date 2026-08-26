import pytest
from cli.main import main, build_parser

def test_build_parser_has_subcommands():
    parser = build_parser()
    assert parser.prog == "kodegen"

def test_cli_run_help(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["run", "--help"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "Natural language requirement" in captured.out

def test_cli_status_execution(capsys):
    ret = main(["status", "--project-id", "test-proj-123"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "test-proj-123" in out
    assert "Pending:" in out

def test_cli_run_execution(capsys):
    ret = main(["run", "Add security validation middleware", "--project-id", "test-run-1", "--concurrency", "1"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "Routed to capability" in out
    assert "Swarm run complete" in out
