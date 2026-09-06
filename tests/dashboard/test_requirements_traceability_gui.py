from __future__ import annotations

from dashboard.project_planning import ProjectPlanningInput, planning_fingerprint
from dashboard.requirements_traceability import traceability_draft_fingerprint
from phase4.requirements_traceability import (
    CoverageClaim,
    PlanningRequirements,
    RequirementKind,
    canonical_planning_fingerprint,
)


def _provenance() -> dict[str, str]:
    return {
        "intent_id": "intent-1",
        "content_fingerprint": "a" * 64,
        "report_id": "b" * 64,
        "audit_request_fingerprint": "c" * 64,
        "manifest_id": "d" * 64,
        "evidence_bundle_id": "e" * 64,
        "commit_sha": "abc123",
        "repository": "owner/repo",
        "purpose": "extend",
        "recommendation": "CONTINUE_WITH_GAPS",
    }


def test_phase4_traceability_reproduces_existing_dashboard_planning_fingerprint() -> None:
    provenance = _provenance()
    dashboard_requirements = ProjectPlanningInput(
        objective="Add traceability",
        acceptance_criteria="Every requirement links to the certified artifact.",
        constraints="Do not grant release authority.",
    )
    phase4_requirements = PlanningRequirements(
        objective=dashboard_requirements.objective,
        acceptance_criteria=dashboard_requirements.acceptance_criteria,
        constraints=dashboard_requirements.constraints,
    )

    assert canonical_planning_fingerprint(
        provenance,
        phase4_requirements,
    ) == planning_fingerprint(provenance, dashboard_requirements)


def test_traceability_draft_fingerprint_changes_with_human_links() -> None:
    provenance = _provenance()
    requirements = PlanningRequirements(
        objective="Add traceability",
        acceptance_criteria="Link requirements to artifacts.",
    )
    first = traceability_draft_fingerprint(
        certificate_id="f" * 64,
        plan_id="plan-1",
        provenance=provenance,
        requirements=requirements,
        claims=(
            CoverageClaim(
                kind=RequirementKind.OBJECTIVE,
                artifact_paths=("a.py",),
            ),
            CoverageClaim(kind=RequirementKind.ACCEPTANCE_CRITERIA),
        ),
    )
    changed = traceability_draft_fingerprint(
        certificate_id="f" * 64,
        plan_id="plan-1",
        provenance=provenance,
        requirements=requirements,
        claims=(
            CoverageClaim(
                kind=RequirementKind.OBJECTIVE,
                artifact_paths=("b.py",),
            ),
            CoverageClaim(kind=RequirementKind.ACCEPTANCE_CRITERIA),
        ),
    )

    assert len(first) == 64
    assert first != changed
