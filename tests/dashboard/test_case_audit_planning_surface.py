"""Contracts for Project Audit + Requirements/Plan inside canonical Sag."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from dashboard.case_audit_planning import (
    audit_matches_case,
    plan_matches_case,
    restore_case_intent,
)
from dashboard.project_audit import ProjectAuditGUIError
from phase4.onboarding import OnboardingIntent, OnboardingIntentDraft, OnboardingPurpose

ROOT = Path(__file__).resolve().parents[2]
SURFACE = ROOT / "dashboard" / "case_audit_planning.py"
CLARIFICATION = ROOT / "dashboard" / "case_clarification.py"


def _intent(*, project_id: str = "project-a", purpose: OnboardingPurpose = OnboardingPurpose.EXTEND) -> OnboardingIntent:
    return OnboardingIntent.from_draft(
        OnboardingIntentDraft(
            source_repository="repository:smoeberg/kodegenerator",
            purpose=purpose,
            rationale="Understand the repository before changing it.",
        ),
        declared_by="alice",
        organization_id="org-a",
        project_id=project_id,
        declared_at=datetime(2026, 9, 10, 7, 0, tzinfo=timezone.utc),
    )


def test_restore_case_intent_accepts_only_exact_selected_project() -> None:
    intent = _intent()

    restored = restore_case_intent(intent.canonical(), project_id="project-a")

    assert restored == intent
    with pytest.raises(ProjectAuditGUIError, match="valgte sag"):
        restore_case_intent(intent.canonical(), project_id="project-b")


def test_audit_cache_requires_exact_case_intent_repository_and_non_authority() -> None:
    intent = _intent()
    audit = {
        "project_id": "project-a",
        "intent_id": intent.intent_id,
        "repository": intent.source_repository,
        "report_id": "report-a",
        "authoritative": False,
    }

    assert audit_matches_case(audit, project_id="project-a", intent=intent)
    assert not audit_matches_case({**audit, "project_id": "project-b"}, project_id="project-a", intent=intent)
    assert not audit_matches_case({**audit, "intent_id": "other"}, project_id="project-a", intent=intent)
    assert not audit_matches_case({**audit, "repository": "repository:other/repo"}, project_id="project-a", intent=intent)
    assert not audit_matches_case({**audit, "authoritative": True}, project_id="project-a", intent=intent)


def test_plan_cache_requires_same_audit_and_remains_non_authoritative() -> None:
    intent = _intent()
    audit = {"report_id": "report-a"}
    plan = {
        "project_id": "project-a",
        "authoritative": False,
        "executable": False,
        "resource": intent.source_repository,
        "provenance": {
            "intent_id": intent.intent_id,
            "report_id": "report-a",
        },
    }

    assert plan_matches_case(plan, project_id="project-a", intent=intent, audit=audit)
    assert not plan_matches_case({**plan, "authoritative": True}, project_id="project-a", intent=intent, audit=audit)
    assert not plan_matches_case({**plan, "executable": True}, project_id="project-a", intent=intent, audit=audit)
    assert not plan_matches_case(
        {**plan, "provenance": {**plan["provenance"], "report_id": "report-b"}},
        project_id="project-a",
        intent=intent,
        audit=audit,
    )


def test_case_surface_resolves_checkout_server_side_and_has_no_legacy_page_hop() -> None:
    source = SURFACE.read_text(encoding="utf-8")

    assert "discover_repository_checkout" in source
    assert "/api/v1/control-plane/onboarding-intents/current" in source
    assert "st.page_link" not in source
    assert "DOR_PROJECT_AUDIT_CHECKOUT_ROOT" not in source
    assert "Browseren vælger ingen sti eller checkout" in source
    assert '"Tekniske auditdetaljer"' in source
    assert '"Tekniske plandetaljer"' in source


def test_audit_only_is_an_explicit_stop_before_planning() -> None:
    source = SURFACE.read_text(encoding="utf-8")

    assert "OnboardingPurpose.AUDIT_ONLY" in source
    assert "Flowet stopper efter analysen" in source
    assert "return\n\n    plan = _cached_plan" in source


def test_case_clarification_makes_audit_and_planning_reachable_in_sag() -> None:
    source = CLARIFICATION.read_text(encoding="utf-8")

    assert "from dashboard.case_audit_planning import render_case_audit_planning" in source
    assert "render_case_audit_planning(client, item)" in source
