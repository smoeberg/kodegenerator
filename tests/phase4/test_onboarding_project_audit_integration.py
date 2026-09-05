"""Cross-layer tests for governed onboarding intent propagation."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from generation.project_spec import ProjectDefinition
from phase4.onboarding import (
    OnboardingIntent,
    OnboardingIntentDraft,
    OnboardingPurpose,
    objectives_for,
)
from phase4.project_audit.baseline import DORBaselineProjectAuditProvider
from phase4.project_audit.runtime import (
    ONBOARDING_INTENT_CONTEXT_KEY,
    ProjectAuditRuntime,
    ProjectAuditRuntimeError,
)
from services.onboarding_delivery_service import (
    OnboardingDeliveryError,
    plan_modernize_rewrite,
)
from services.requirements_contract_service import (
    RequirementsIntentBindingError,
    approve,
    bind_onboarding_intent,
)
from tests.phase3.test_requirements_contract import make_spec
from tests.phase4.test_project_audit_runtime import _dor_files, _init_repository


REPOSITORY = "repository:smoeberg/kodegenerator"


def _intent(
    purpose: OnboardingPurpose = OnboardingPurpose.EXTEND,
) -> OnboardingIntent:
    target_stack = None
    if purpose is OnboardingPurpose.MODERNIZE_REWRITE:
        target_stack = ProjectDefinition(
            name="modernized-dor",
            architecture="hexagonal",
            language="rust",
            api="axum",
            database="postgresql",
        )
    draft = OnboardingIntentDraft(
        source_repository=REPOSITORY,
        purpose=purpose,
        rationale="Human-declared purpose for the governed integration test.",
        target_stack=target_stack,
    )
    return OnboardingIntent.from_draft(
        draft,
        declared_by="actor-a",
        organization_id="org-a",
        declared_at=datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc),
    )


def _audit(tmp_path, intent: OnboardingIntent):
    _init_repository(tmp_path, _dor_files())
    return ProjectAuditRuntime(tmp_path).run(
        intent=intent,
        provider=DORBaselineProjectAuditProvider(),
    )


def test_project_audit_derives_resource_objectives_and_provenance_from_intent(
    tmp_path,
) -> None:
    intent = _intent(OnboardingPurpose.AUDIT_ONLY)

    run = _audit(tmp_path, intent)

    assert run.report.request.resource == intent.source_repository
    assert run.report.request.objectives == tuple(
        sorted(objectives_for(intent.purpose))
    )
    matches = [
        item
        for item in run.report.request.context_packet.items
        if item.key == ONBOARDING_INTENT_CONTEXT_KEY
    ]
    assert len(matches) == 1
    assert matches[0].source == "onboarding-intent"
    assert matches[0].canonical()["value"] == intent.canonical()
    assert matches[0].provenance == f"onboarding-intent:{intent.intent_id}"


def test_project_audit_rejects_repository_and_objective_override(tmp_path) -> None:
    intent = _intent(OnboardingPurpose.EXTEND)
    runtime = ProjectAuditRuntime(tmp_path)
    provider = DORBaselineProjectAuditProvider()

    with pytest.raises(ProjectAuditRuntimeError, match="repository"):
        runtime.run(
            repository="repository:other/project",
            intent=intent,
            provider=provider,
        )
    with pytest.raises(ProjectAuditRuntimeError, match="objectives"):
        runtime.run(
            intent=intent,
            objectives=("reinterpret the human purpose",),
            provider=provider,
        )


def test_requirements_binding_is_audited_and_covered_by_approval_fingerprint(
    tmp_path,
) -> None:
    intent = _intent(OnboardingPurpose.EXTEND)
    run = _audit(tmp_path, intent)
    original = make_spec()

    bound = bind_onboarding_intent(
        original,
        report=run.report,
        intent=intent,
    )
    metadata = bound.intent["onboarding"]

    assert original.intent.get("onboarding") is None
    assert metadata["intent_id"] == intent.intent_id
    assert metadata["purpose"] == "extend"
    assert metadata["declared_by"] == "actor-a"
    assert metadata["audit_report_id"] == run.report.report_id
    assert bound.fingerprint != original.fingerprint

    approved = approve(bound, "requirements-owner")
    assert approved.status == "approved"
    assert approved.approval.content_fingerprint == approved.fingerprint
    assert approved.intent["onboarding"] == metadata


def test_requirements_binding_rejects_audit_from_different_intent(tmp_path) -> None:
    audited_intent = _intent(OnboardingPurpose.AUDIT_ONLY)
    run = _audit(tmp_path, audited_intent)
    supplied_intent = _intent(OnboardingPurpose.EXTEND)

    with pytest.raises(RequirementsIntentBindingError):
        bind_onboarding_intent(
            make_spec(),
            report=run.report,
            intent=supplied_intent,
        )


def test_modernize_rewrite_scaffold_is_bound_to_approved_parity_contract(
    tmp_path,
) -> None:
    intent = _intent(OnboardingPurpose.MODERNIZE_REWRITE)
    run = _audit(tmp_path, intent)
    bound = bind_onboarding_intent(
        make_spec(),
        report=run.report,
        intent=intent,
    )
    approved = approve(bound, "requirements-owner")

    delivery = plan_modernize_rewrite(
        intent=intent,
        approved_spec=approved,
    )

    assert delivery.scaffold.project == intent.target_stack
    assert delivery.requirements_fingerprint == approved.fingerprint
    assert delivery.parity_requirement_ids == ("FR-001",)
    assert delivery.scaffold.validate() == ()
    assert len(delivery.fingerprint) == 64


def test_rewrite_scaffold_fails_closed_before_approval_or_for_non_rewrite(
    tmp_path,
) -> None:
    rewrite = _intent(OnboardingPurpose.MODERNIZE_REWRITE)
    run = _audit(tmp_path, rewrite)
    bound = bind_onboarding_intent(
        make_spec(),
        report=run.report,
        intent=rewrite,
    )

    with pytest.raises(OnboardingDeliveryError, match="approved"):
        plan_modernize_rewrite(intent=rewrite, approved_spec=bound)

    extend = _intent(OnboardingPurpose.EXTEND)
    with pytest.raises(OnboardingDeliveryError, match="MODERNIZE_REWRITE"):
        plan_modernize_rewrite(
            intent=extend,
            approved_spec=approve(bound, "requirements-owner"),
        )
