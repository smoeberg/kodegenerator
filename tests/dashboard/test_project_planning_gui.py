"""Pure trust-boundary tests for the post-audit planning GUI adapter."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from dashboard.project_planning import (
    ProjectPlanningGUIError,
    ProjectPlanningInput,
    generate_project_plan,
    planning_fingerprint,
    restore_planning_provenance,
)
from phase4.onboarding import OnboardingIntent, OnboardingIntentDraft, OnboardingPurpose


def _intent(purpose: OnboardingPurpose = OnboardingPurpose.EXTEND) -> OnboardingIntent:
    return OnboardingIntent.from_draft(
        OnboardingIntentDraft(
            source_repository="repository:smoeberg/kodegenerator",
            purpose=purpose,
            rationale="Use the exact audited repository as the next planning baseline.",
        ),
        declared_by="alice",
        organization_id="org-a",
        declared_at=datetime(2026, 9, 6, 8, 30, tzinfo=timezone.utc),
    )


def _onboarding(intent: OnboardingIntent) -> dict[str, object]:
    return {"intent": intent.canonical()}


def _audit(intent: OnboardingIntent) -> dict[str, object]:
    return {
        "report_id": "report-123",
        "authoritative": False,
        "recommendation": "CONTINUE_WITH_GAPS",
        "repository": intent.source_repository,
        "commit_sha": "a" * 40,
        "manifest_id": "manifest-123",
        "evidence_bundle_id": "bundle-123",
        "request_fingerprint": "audit-request-123",
        "intent_id": intent.intent_id,
        "purpose": intent.purpose.value,
        "delivery_allowed": intent.purpose is not OnboardingPurpose.AUDIT_ONLY,
        "findings": [
            {
                "finding_id": "finding-1",
                "title": "Add end-to-end verification",
                "severity": "medium",
            }
        ],
        "maturity": [],
    }


def _requirements(objective: str = "Add the next governed feature") -> ProjectPlanningInput:
    return ProjectPlanningInput(
        objective=objective,
        acceptance_criteria="The new behavior is covered by deterministic tests.",
        constraints="Preserve the existing authority boundary.",
    )


def test_restore_planning_provenance_binds_exact_audit_to_intent() -> None:
    intent = _intent()

    restored, provenance = restore_planning_provenance(
        _onboarding(intent),
        _audit(intent),
    )

    assert restored == intent
    assert provenance["intent_id"] == intent.intent_id
    assert provenance["report_id"] == "report-123"
    assert provenance["repository"] == intent.source_repository
    assert provenance["audit_request_fingerprint"] == "audit-request-123"


def test_audit_only_cannot_continue_to_planning() -> None:
    intent = _intent(OnboardingPurpose.AUDIT_ONLY)

    with pytest.raises(ProjectPlanningGUIError, match="Audit-only"):
        restore_planning_provenance(_onboarding(intent), _audit(intent))


def test_planning_rejects_mismatched_intent() -> None:
    intent = _intent()
    audit = _audit(intent)
    audit["intent_id"] = "different-intent"

    with pytest.raises(ProjectPlanningGUIError, match="matcher ikke"):
        restore_planning_provenance(_onboarding(intent), audit)


def test_planning_rejects_mismatched_repository() -> None:
    intent = _intent()
    audit = _audit(intent)
    audit["repository"] = "repository:other/project"

    with pytest.raises(ProjectPlanningGUIError, match="repository"):
        restore_planning_provenance(_onboarding(intent), audit)


def test_planning_rejects_authoritative_audit_claim() -> None:
    intent = _intent()
    audit = _audit(intent)
    audit["authoritative"] = True

    with pytest.raises(ProjectPlanningGUIError, match="non-authoritative"):
        restore_planning_provenance(_onboarding(intent), audit)


def test_planning_fingerprint_binds_human_requirements() -> None:
    intent = _intent()
    _, provenance = restore_planning_provenance(_onboarding(intent), _audit(intent))

    first = planning_fingerprint(provenance, _requirements("Implement A"))
    second = planning_fingerprint(provenance, _requirements("Implement B"))

    assert first != second
    assert len(first) == 64


def test_generated_plan_is_proposed_non_executable_and_keeps_provenance() -> None:
    intent = _intent()
    onboarding = _onboarding(intent)
    audit = _audit(intent)
    requirements = _requirements()
    _, provenance = restore_planning_provenance(onboarding, audit)
    expected_fingerprint = planning_fingerprint(provenance, requirements)

    result = generate_project_plan(onboarding, audit, requirements)

    assert result["status"] == "proposed"
    assert result["authoritative"] is False
    assert result["executable"] is False
    assert result["request_fingerprint"] == expected_fingerprint
    assert result["resource"] == intent.source_repository
    assert result["provenance"]["report_id"] == "report-123"
    assert result["steps"]


def test_required_planning_text_is_bounded_and_canonical() -> None:
    with pytest.raises(ValueError, match="objective"):
        ProjectPlanningInput(objective="", acceptance_criteria="works")
    with pytest.raises(ValueError, match="canonical"):
        ProjectPlanningInput(objective="  scope  ", acceptance_criteria="works")
    with pytest.raises(ValueError, match="4000"):
        ProjectPlanningInput(objective="x" * 4001, acceptance_criteria="works")
