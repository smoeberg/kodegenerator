"""Contract tests proving every pipeline executor delegates to a real backend."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from execution.pipeline_executors import (
    CodeExecutor,
    DeployExecutor,
    ReleaseExecutor,
    RunTestsExecutor,
)
from execution.pipeline_executors import (
    TestGeneratorExecutor as PipelineTestGeneratorExecutor,
)
from phase4.verification.selector import VerifierSelection
from phase6.execution.sandbox import ExecutionOutcome, ExecutionResult
from services.github_pr_contracts import PRResult, PRStatus


class FakeImplementationRuntime:
    def run(self, **kwargs):
        assert kwargs["organization_id"] == "org-1"
        return SimpleNamespace(
            proposal=SimpleNamespace(proposal_id="proposal-1", unified_diff="diff")
        )


class FakeSelector:
    def select(self, **kwargs):
        assert kwargs["quorum_size"] == 1
        return VerifierSelection(
            claim_id=kwargs["claim_id"],
            policy_id=kwargs["policy_id"],
            candidate_ids=("agent-1",),
            selected_ids=("agent-1",),
            seed="seed",
            reason="selected",
        )


class FakeSandbox:
    def execute(self, spec):
        return ExecutionResult(
            spec.execution_id,
            spec.adapter_id,
            ExecutionOutcome.SUCCEEDED,
            output="1 passed",
            exit_code=0,
        )


class FakeDeployBackend:
    def deploy(self, repository, project_name, environment, target, release, workspace):
        assert repository == "https://github.test/demo.git" and project_name == "demo"
        return {"image_tag": "demo:test", "url": target, "deployed_at": "now"}


class FakePublisher:
    def publish_patch_as_pr(self, **kwargs):
        assert kwargs["patch"].patch_id == "task-1"
        return PRResult(
            status=PRStatus.CREATED,
            pr_number=42,
            pr_url="https://github.test/pull/42",
            commit_hash="abc",
        )


def test_code_executor_uses_implementation_agent_runtime():
    result = CodeExecutor(FakeImplementationRuntime()).execute(
        {
            "task_id": "task-1",
            "organization_id": "org-1",
            "resource": "repository:test/demo",
            "allowed_paths": ["app.py"],
            "context": {"requirements": "build app"},
        }
    )
    assert result["code"]["proposal_id"] == "proposal-1"


def test_test_generator_uses_verifier_selector():
    result = PipelineTestGeneratorExecutor(FakeSelector()).execute(
        {"task_id": "task-1"}
    )
    assert result["tests"]["selected_ids"] == ("agent-1",)


def test_default_test_generator_selects_registered_verifier():
    result = PipelineTestGeneratorExecutor().execute({"task_id": "task-default"})
    assert len(result["tests"]["selected_ids"]) == 1


def test_run_tests_uses_sandbox_registry(tmp_path):
    result = RunTestsExecutor(FakeSandbox()).execute(
        {
            "task_id": "task-1",
            "organization_id": "org-1",
            "actor_id": "worker-1",
            "workspace": str(tmp_path),
            "sandbox_adapter_id": "fake",
        }
    )
    assert result["test_run"]["output"] == "1 passed"


def test_deploy_executor_uses_git_docker_backend():
    grant = MagicMock()
    grant.verified = True
    grant.action = "pipeline.deploy"
    grant.resource = "https://github.test/demo.git"
    grant.parameters = (
        ("environment", "test"),
        ("target", "https://demo"),
        ("release", ""),
    )
    result = DeployExecutor(FakeDeployBackend()).execute(
        {
            "repository": "https://github.test/demo.git",
            "project_name": "demo",
            "environment": "test",
            "target": "https://demo",
            "authority_grant": grant,
        }
    )
    assert result["deployment"]["image_tag"] == "demo:test"


def test_release_executor_uses_git_pr_publisher():
    grant = MagicMock()
    grant.verified = True
    grant.is_expired.return_value = False
    result = ReleaseExecutor(FakePublisher()).execute(
        {
            "workflow_id": "workflow-1",
            "patch": {"patch_id": "task-1", "patch_content": "diff", "author": "bot"},
            "pr_metadata": {
                "title": "feat: demo",
                "description": "",
                "branch": "feat/demo",
            },
            "push_remote": False,
            "authority_grant": grant,
        }
    )
    assert result["release"]["pr_number"] == 42


def test_release_executor_requires_authority_grant():
    with pytest.raises(ValueError, match="authority_grant"):
        ReleaseExecutor(FakePublisher()).execute(
            {
                "patch": {
                    "patch_id": "task-1",
                    "patch_content": "diff",
                    "author": "bot",
                },
                "pr_metadata": {
                    "title": "feat: demo",
                    "description": "",
                    "branch": "feat/demo",
                },
            }
        )
