import pytest

from phase6.execution.sandbox import (
    ExecutionLimits,
    ExecutionOutcome,
    ExecutionResult,
    ExecutionSecurityContext,
    ExecutionSpec,
    SandboxRegistry,
    UnknownSandboxAdapter,
)


class FakeAdapter:
    adapter_id = "test-isolated"

    def execute(self, spec: ExecutionSpec) -> ExecutionResult:
        return ExecutionResult(
            execution_id=spec.execution_id,
            adapter_id=self.adapter_id,
            outcome=ExecutionOutcome.SUCCEEDED,
            output="ok",
            exit_code=0,
        )


def make_spec(**overrides) -> ExecutionSpec:
    values = {
        "execution_id": "exec-1",
        "adapter_id": "test-isolated",
        "argv": ("python", "-c", "print('ok')"),
        "security": ExecutionSecurityContext(
            organization_id="org-1",
            principal_id="principal-1",
            actor_id="actor-1",
            capabilities=("repo.read",),
            secret_references=("secret:repo-token",),
        ),
    }
    values.update(overrides)
    return ExecutionSpec(**values)


def test_execution_spec_is_immutable_and_structured():
    spec = make_spec()
    with pytest.raises((AttributeError, TypeError)):
        spec.adapter_id = "other"
    assert spec.argv[0] == "python"
    assert spec.security.capabilities == ("repo.read",)


def test_registry_only_executes_registered_adapter():
    registry = SandboxRegistry({"test-isolated": FakeAdapter()})
    result = registry.execute(make_spec())
    assert result.outcome is ExecutionOutcome.SUCCEEDED
    assert registry.adapter_ids == ("test-isolated",)

    with pytest.raises(UnknownSandboxAdapter):
        registry.execute(make_spec(adapter_id="not-registered"))


def test_registry_rejects_duplicate_registration():
    registry = SandboxRegistry({"test-isolated": FakeAdapter()})
    with pytest.raises(ValueError, match="already registered"):
        registry.register("test-isolated", FakeAdapter())


def test_security_context_cannot_be_mutated_or_self_escalated():
    context = ExecutionSecurityContext(
        organization_id="org-1",
        principal_id="principal-1",
        actor_id="actor-1",
        capabilities=("repo.read",),
    )
    with pytest.raises((AttributeError, TypeError)):
        context.capabilities = ("admin",)


def test_limits_reject_unbounded_or_inconsistent_values():
    with pytest.raises(ValueError):
        ExecutionLimits(wall_time_seconds=0)
    with pytest.raises(ValueError):
        ExecutionLimits(wall_time_seconds=5, cpu_time_seconds=6)
    with pytest.raises(ValueError):
        ExecutionLimits(output_bytes=0)


def test_execution_spec_rejects_shell_style_environment_assignment():
    with pytest.raises(ValueError, match="environment assignments"):
        make_spec(argv=("python", "TOKEN=secret"))


def test_execution_spec_rejects_wildcard_network_access():
    with pytest.raises(ValueError, match="wildcard"):
        make_spec(network_allowlist=("*",))


def test_execution_spec_rejects_overlapping_filesystem_scopes():
    with pytest.raises(ValueError, match="both writable and read-only"):
        make_spec(read_only_paths=("/workspace",), writable_paths=("/workspace",))


def test_registry_rejects_oversized_adapter_output():
    class OversizedAdapter(FakeAdapter):
        adapter_id = "oversized"

        def execute(self, spec: ExecutionSpec) -> ExecutionResult:
            return ExecutionResult(
                execution_id=spec.execution_id,
                adapter_id=self.adapter_id,
                outcome=ExecutionOutcome.SUCCEEDED,
                output="123456",
            )

    registry = SandboxRegistry({"oversized": OversizedAdapter()})
    spec = make_spec(adapter_id="oversized", limits=ExecutionLimits(output_bytes=5))
    with pytest.raises(ValueError, match="output above configured limit"):
        registry.execute(spec)
