from dataclasses import asdict
from types import SimpleNamespace

import pytest

from domain.factory_integration import IntegrationStatus, ReleaseHandoff
from domain.factory_work import fingerprint
from execution.pipeline_executors import DeployExecutor, ReleaseExecutor
from services.delivery_evidence_gate import (
    AttestedDeliveryGate,
    DeliveryEvidenceError,
)
from services.github_pr_contracts import PRResult, PRStatus


def _state():
    patch = "diff --git a/app.py b/app.py\n"
    plan_fingerprint = "1" * 64
    receipt_id = "2" * 64
    base_sha = "a" * 40
    head_sha = "b" * 40
    evidence = (("failures", "0"), ("status", "passed"), ("tests_run", "3"))
    plan = SimpleNamespace(
        plan_id="plan-1",
        content_fingerprint=plan_fingerprint,
        repository="owner/repo",
        base_sha=base_sha,
        integration_branch="factory/integration/demo",
        status=IntegrationStatus.SUCCEEDED,
    )
    receipt = SimpleNamespace(
        receipt_id=receipt_id,
        plan_id="plan-1",
        integration_head_sha=head_sha,
        integration_branch="factory/integration/demo",
        suite_attestation=(*evidence, ("result_fingerprint", "3" * 64)),
        status=IntegrationStatus.SUCCEEDED,
    )
    handoff = ReleaseHandoff(
        organization_id="org-1",
        integration_receipt_id=receipt_id,
        plan_fingerprint=plan_fingerprint,
        repository="owner/repo",
        base_sha=base_sha,
        head_sha=head_sha,
        branch="factory/integration/demo",
        patch_content=patch,
        patch_fingerprint=fingerprint(patch),
        test_attestation=evidence,
    )
    return plan, receipt, handoff


class _Store:
    def __init__(self, plan, receipt):
        self.plan = plan
        self.receipt = receipt

    def get_plan(self, organization_id, plan_id):
        return self.plan if organization_id == "org-1" and plan_id == "plan-1" else None

    def get_receipt_for_plan(self, organization_id, plan_fingerprint):
        if (
            organization_id == "org-1"
            and plan_fingerprint == self.plan.content_fingerprint
        ):
            return self.receipt
        return None


def _grant(handoff: ReleaseHandoff, action: str = "release.publish"):
    parameters = {
        "integration_receipt_id": handoff.integration_receipt_id,
        "plan_fingerprint": handoff.plan_fingerprint,
        "base_sha": handoff.base_sha,
        "head_sha": handoff.head_sha,
        "patch_fingerprint": handoff.patch_fingerprint,
    }
    if action == "release.publish":
        parameters.update(base_branch="main", patch_id=handoff.patch_fingerprint)
    if action == "pipeline.deploy":
        parameters.update(
            environment="demo",
            target="compose.yml",
            release="demo-v1",
        )
    return SimpleNamespace(
        verified=True,
        action=action,
        capability=action,
        organization_id="org-1",
        resource="repository:owner/repo",
        parameters=tuple(sorted(parameters.items())),
    )


def test_release_binding_derives_patch_and_tests_from_durable_receipt() -> None:
    plan, receipt, handoff = _state()
    gate = AttestedDeliveryGate(_Store(plan, receipt))
    payload = {
        "organization_id": "org-1",
        "release_handoff": asdict(handoff),
        "base_branch": "main",
        "patch_content": "forged",
        "test_results": {"status": "passed", "tests_run": 999},
    }

    bound = gate.bind(payload, _grant(handoff), action="release.publish")

    assert bound["patch_content"] == handoff.patch_content
    assert bound["patch_id"] == handoff.patch_fingerprint
    assert bound["test_results"] == {
        "failures": 0,
        "status": "passed",
        "tests_run": 3,
    }
    assert bound["repository"] == "owner/repo"


def test_deploy_binding_requires_pipeline_deploy_authority() -> None:
    plan, receipt, handoff = _state()
    gate = AttestedDeliveryGate(_Store(plan, receipt))

    bound = gate.bind(
        {
            "organization_id": "org-1",
            "release_handoff": handoff,
        },
        _grant(handoff, "pipeline.deploy"),
        action="pipeline.deploy",
    )

    assert bound["patch_id"] == handoff.patch_fingerprint
    assert bound["test_results"]["status"] == "passed"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload, grant, receipt: payload.update(organization_id="org-2"),
        lambda payload, grant, receipt: setattr(
            receipt, "integration_head_sha", "c" * 40
        ),
        lambda payload, grant, receipt: setattr(grant, "organization_id", "org-2"),
        lambda payload, grant, receipt: setattr(
            grant, "resource", "repository:other/repo"
        ),
        lambda payload, grant, receipt: setattr(grant, "verified", False),
    ],
)
def test_delivery_gate_rejects_cross_tenant_stale_or_unbound_evidence(
    mutation,
) -> None:
    plan, receipt, handoff = _state()
    grant = _grant(handoff)
    payload = {
        "organization_id": "org-1",
        "release_handoff": asdict(handoff),
        "base_branch": "main",
    }
    mutation(payload, grant, receipt)

    with pytest.raises(DeliveryEvidenceError):
        AttestedDeliveryGate(_Store(plan, receipt)).bind(
            payload, grant, action="release.publish"
        )


def test_delivery_gate_rejects_missing_handoff_before_side_effect() -> None:
    plan, receipt, handoff = _state()

    with pytest.raises(DeliveryEvidenceError, match="release_handoff"):
        AttestedDeliveryGate(_Store(plan, receipt)).bind(
            {"organization_id": "org-1"},
            _grant(handoff),
            action="release.publish",
        )


def test_deploy_executor_fingerprints_the_verified_handoff() -> None:
    plan, receipt, handoff = _state()
    observed: dict = {}

    class Backend:
        def deploy(
            self, repository, project_name, environment, target, release, workspace
        ):
            return {"repository": repository, "status": "deployed"}

    class SideEffects:
        def execute(self, **kwargs):
            observed.update(kwargs)
            return kwargs["operation"](), False

    result = DeployExecutor(
        backend=Backend(),
        side_effects=SideEffects(),
        delivery_gate=AttestedDeliveryGate(_Store(plan, receipt)),
    ).execute(
        {
            "task_id": "deploy-attested-1",
            "organization_id": "org-1",
            "release_handoff": asdict(handoff),
            "project_name": "demo",
            "environment": "demo",
            "target": "compose.yml",
            "release": "demo-v1",
            "authority_grant": _grant(handoff, "pipeline.deploy"),
        }
    )

    assert result["status"] == "success"
    assert observed["request_data"]["release_handoff"]["integration_receipt_id"] == (
        handoff.integration_receipt_id
    )
    assert observed["request_data"]["repository"] == plan.repository


def test_release_executor_publishes_only_the_attested_patch() -> None:
    plan, receipt, handoff = _state()
    published: dict = {}

    class Publisher:
        def __init__(self, **kwargs):
            pass

        def publish_patch_as_pr(self, **kwargs):
            published.update(kwargs)
            return PRResult(
                status=PRStatus.CREATED,
                pr_number=7,
                pr_url="https://github.com/owner/repo/pull/7",
                commit_hash=handoff.head_sha,
            )

    result = ReleaseExecutor(
        publisher_factory=Publisher,
        delivery_gate=AttestedDeliveryGate(_Store(plan, receipt)),
    ).execute(
        {
            "workflow_id": "release-attested-1",
            "organization_id": "org-1",
            "release_handoff": asdict(handoff),
            "owner": "owner",
            "repo": "repo",
            "token": "test-token",
            "base_branch": "main",
            "patch_content": "forged patch",
            "test_results": {"status": "passed", "failures": 0},
            "authority_grant": _grant(handoff),
        }
    )

    assert result["release"]["pr_number"] == 7
    assert published["patch"].patch_content == handoff.patch_content
    assert published["patch"].patch_id == handoff.patch_fingerprint
    assert published["test_results"] == {
        "failures": 0,
        "status": "passed",
        "tests_run": 3,
    }
