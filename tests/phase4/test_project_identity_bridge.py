"""SC-101A cross-layer project identity provenance tests."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from phase4.implementation_agent.models import ImplementationRequest
from phase4.onboarding import OnboardingIntent, OnboardingIntentDraft, OnboardingPurpose
from phase4.planner import PlannerService
from phase4.project_audit.baseline import DORBaselineProjectAuditProvider
from phase4.project_audit.runtime import ProjectAuditRuntime
from phase4.project_identity_bridge import (
    PROJECT_IDENTITY_CONTEXT_KEY,
    ProjectIdentityBridgeError,
    assert_implementation_binding,
    bind_plan,
    build_implementation_request,
)
from tests.phase4.test_project_audit_runtime import _dor_files, _init_repository


REPOSITORY = "repository:smoeberg/kodegenerator"


def _intent(*, organization_id: str = "org-a", project_id: str = "project-a") -> OnboardingIntent:
    return OnboardingIntent.from_draft(
        OnboardingIntentDraft(
            source_repository=REPOSITORY,
            purpose=OnboardingPurpose.EXTEND,
            rationale="Carry exact project identity through governed delivery provenance.",
        ),
        declared_by="owner-a",
        organization_id=organization_id,
        project_id=project_id,
        declared_at=datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc),
    )


def _audit(tmp_path, intent: OnboardingIntent):
    _init_repository(tmp_path, _dor_files())
    return ProjectAuditRuntime(tmp_path).run(
        intent=intent,
        provider=DORBaselineProjectAuditProvider(),
    ).report


def _plan():
    return PlannerService().plan_from_spec(
        {
            "title": "SC-101A",
            "resource": REPOSITORY,
            "action": "implementation.propose_patch",
            "steps": ["carry project identity into implementation provenance"],
        },
        fingerprint="a" * 64,
        created_at="2026-09-08T10:05:00+00:00",
    )


def test_exact_project_identity_flows_audit_plan_and_implementation(tmp_path) -> None:
    intent = _intent()
    report = _audit(tmp_path, intent)
    bound_plan = bind_plan(intent=intent, report=report, plan=_plan())

    request = build_implementation_request(
        bound_plan=bound_plan,
        organization_id="org-a",
        project_id="project-a",
        agent_identity="implementation-agent:sc101a",
        agent_role="implementer",
        resource=REPOSITORY,
        instruction="Implement the approved SC-101A change.",
        allowed_paths=("phase4/example.py",),
    )

    assert bound_plan.provenance.organization_id == "org-a"
    assert bound_plan.provenance.project_id == "project-a"
    assert bound_plan.provenance.onboarding_intent_id == intent.intent_id
    assert bound_plan.provenance.audit_report_id == report.report_id
    assert len(bound_plan.plan_request_fingerprint) == 64

    matches = [
        item
        for item in request.context_packet.items
        if item.key == PROJECT_IDENTITY_CONTEXT_KEY
    ]
    assert len(matches) == 1
    value = matches[0].canonical()["value"]
    assert value["project_id"] == "project-a"
    assert value["organization_id"] == "org-a"
    assert value["plan_request_fingerprint"] == bound_plan.plan_request_fingerprint
    assert request.context_packet_id == request.context_packet.packet_id
    assert request.context_packet_id in request.request_fingerprint or len(request.request_fingerprint) == 64
    assert_implementation_binding(bound_plan=bound_plan, request=request)


def test_cross_project_and_cross_tenant_drift_fail_closed(tmp_path) -> None:
    intent = _intent()
    report = _audit(tmp_path, intent)
    bound_plan = bind_plan(intent=intent, report=report, plan=_plan())

    with pytest.raises(ProjectIdentityBridgeError, match="organization"):
        build_implementation_request(
            bound_plan=bound_plan,
            organization_id="org-b",
            project_id="project-a",
            agent_identity="implementation-agent:sc101a",
            agent_role="implementer",
            resource=REPOSITORY,
            instruction="wrong tenant",
            allowed_paths=("phase4/example.py",),
        )

    with pytest.raises(ProjectIdentityBridgeError, match="project_id"):
        build_implementation_request(
            bound_plan=bound_plan,
            organization_id="org-a",
            project_id="project-b",
            agent_identity="implementation-agent:sc101a",
            agent_role="implementer",
            resource=REPOSITORY,
            instruction="wrong project",
            allowed_paths=("phase4/example.py",),
        )


def test_audit_from_other_project_cannot_be_rebound(tmp_path) -> None:
    audited = _intent(project_id="project-a")
    report = _audit(tmp_path, audited)
    supplied = _intent(project_id="project-b")

    with pytest.raises(ProjectIdentityBridgeError, match="exact onboarding intent"):
        bind_plan(intent=supplied, report=report, plan=_plan())


def test_implementation_tenant_mutation_is_detected_even_with_same_context(tmp_path) -> None:
    intent = _intent()
    report = _audit(tmp_path, intent)
    bound_plan = bind_plan(intent=intent, report=report, plan=_plan())
    original = build_implementation_request(
        bound_plan=bound_plan,
        organization_id="org-a",
        project_id="project-a",
        agent_identity="implementation-agent:sc101a",
        agent_role="implementer",
        resource=REPOSITORY,
        instruction="Implement the approved SC-101A change.",
        allowed_paths=("phase4/example.py",),
    )
    mutated = ImplementationRequest(
        organization_id="org-b",
        agent_identity=original.agent_identity,
        agent_role=original.agent_role,
        resource=original.resource,
        context_packet=original.context_packet,
        instruction=original.instruction,
        allowed_paths=original.allowed_paths,
        budget=original.budget,
    )

    assert mutated.request_fingerprint != original.request_fingerprint
    with pytest.raises(ProjectIdentityBridgeError, match="tenant"):
        assert_implementation_binding(bound_plan=bound_plan, request=mutated)
