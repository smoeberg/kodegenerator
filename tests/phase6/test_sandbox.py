from pathlib import Path

import pytest

from phase6.sandbox import BubblewrapSandbox, SandboxLimits, SandboxUnavailableError


def test_sandbox_fails_closed_without_bwrap(monkeypatch, tmp_path):
    monkeypatch.setattr("phase6.sandbox.shutil.which", lambda _: None)
    with pytest.raises(SandboxUnavailableError):
        BubblewrapSandbox(tmp_path)


def test_sandbox_uses_unshared_namespace_and_read_only_project(monkeypatch, tmp_path):
    monkeypatch.setattr("phase6.sandbox.shutil.which", lambda _: "/usr/bin/bwrap")
    project = tmp_path / "project"
    workspace = tmp_path / "workspace"
    project.mkdir()
    sandbox = BubblewrapSandbox(project, limits=SandboxLimits(memory_bytes=64 * 1024 * 1024))
    command = sandbox.command(("python", "-c", "print('ok')"), workspace)
    assert "--unshare-all" in command
    assert "--new-session" in command
    assert "--ro-bind" in command
    assert str(project.resolve()) in command
    assert "--bind" in command
    assert str(workspace.resolve()) in command
    assert "--proc" in command
    assert "--tmpfs" in command


def test_sandbox_rejects_workspace_inside_project(monkeypatch, tmp_path):
    monkeypatch.setattr("phase6.sandbox.shutil.which", lambda _: "/usr/bin/bwrap")
    project = tmp_path / "project"
    project.mkdir()
    sandbox = BubblewrapSandbox(project)
    with pytest.raises(Exception):
        sandbox.command(("python", "-V"), project / "workspace")
