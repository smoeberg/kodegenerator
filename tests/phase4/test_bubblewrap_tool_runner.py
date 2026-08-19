from pathlib import Path

from phase4.implementation_agent.patch_models import ToolKind, TrustedToolSpec
from phase4.implementation_agent.sandbox_tool_runner import BubblewrapToolRunner
from phase6.execution.sandbox import ExecutionOutcome


def _tool(executable: str) -> TrustedToolSpec:
    return TrustedToolSpec(
        "test.tool",
        ToolKind.TEST,
        (executable, "-V"),
        timeout_seconds=10,
        max_output_bytes=4096,
    )


def test_runner_builds_unshared_execution_spec(monkeypatch, tmp_path):
    executable = str(Path("/bin/true").resolve())
    tool = _tool(executable)
    captured = {}

    class FakeResult:
        outcome = ExecutionOutcome.SUCCEEDED
        output = "ok"
        error = None
        exit_code = 0

    class FakeAdapter:
        adapter_id = "bubblewrap-process"

        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

        def execute(self, spec):
            captured["spec"] = spec
            return FakeResult()

    monkeypatch.setattr(
        "phase4.implementation_agent.sandbox_tool_runner.BubblewrapProcessAdapter",
        FakeAdapter,
    )
    runner = BubblewrapToolRunner(bubblewrap_path="/usr/bin/bwrap")
    result = runner.run(tool, cwd=tmp_path)

    assert result.status is ToolStatus.PASSED
    spec = captured["spec"]
    assert spec.network_allowlist == ()
    assert spec.writable_paths == (str(tmp_path.resolve()),)
    assert spec.limits.memory_bytes == 256 * 1024 * 1024
    assert spec.limits.process_count == 1
    assert spec.security.organization_id == "generated-code-sandbox"
