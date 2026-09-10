"""Pure trust-boundary tests for the Project Audit Streamlit adapter."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from dashboard.project_audit import (
    ProjectAuditCheckoutBinding,
    ProjectAuditGUIError,
    restore_onboarding_intent,
)
from dashboard.repository_checkout_catalog import RepositoryCheckoutCatalogError
from phase4.onboarding import OnboardingIntent, OnboardingIntentDraft, OnboardingPurpose


def _intent(*, project_id: str | None = None) -> OnboardingIntent:
    return OnboardingIntent.from_draft(
        OnboardingIntentDraft(
            source_repository="repository:smoeberg/kodegenerator",
            purpose=OnboardingPurpose.EXTEND,
            rationale="Audit this exact repository before continuing development.",
        ),
        declared_by="alice",
        organization_id="org-a",
        project_id=project_id,
        declared_at=datetime(2026, 9, 6, 8, 0, tzinfo=timezone.utc),
    )


def test_restore_onboarding_intent_revalidates_canonical_identity() -> None:
    intent = _intent()

    restored = restore_onboarding_intent({"intent": intent.canonical()})

    assert restored == intent
    assert restored.intent_id == intent.intent_id
    assert restored.content_fingerprint == intent.content_fingerprint


def test_restore_onboarding_intent_preserves_project_bound_identity() -> None:
    intent = _intent(project_id="project-a")

    restored = restore_onboarding_intent({"intent": intent.canonical()})

    assert restored == intent
    assert restored.project_id == "project-a"
    assert restored.intent_id == intent.intent_id


def test_restore_onboarding_intent_rejects_tampered_identity() -> None:
    payload = _intent().canonical()
    payload["intent_id"] = "0" * 64

    with pytest.raises(ProjectAuditGUIError, match="intent ID"):
        restore_onboarding_intent({"intent": payload})


def test_checkout_binding_is_server_owned_and_exact(tmp_path) -> None:
    intent = _intent()
    binding = ProjectAuditCheckoutBinding.from_environment(
        {
            "DOR_PROJECT_AUDIT_ORGANIZATION_ID": "org-a",
            "DOR_PROJECT_AUDIT_REPOSITORY": intent.source_repository,
            "DOR_PROJECT_AUDIT_CHECKOUT_ROOT": str(tmp_path),
        }
    )

    assert binding.root_for(intent) == tmp_path.resolve()


def test_checkout_binding_rejects_other_repository(tmp_path) -> None:
    intent = _intent()
    binding = ProjectAuditCheckoutBinding(
        organization_id="org-a",
        repository="repository:other/project",
        root=tmp_path,
    )

    with pytest.raises(
        RepositoryCheckoutCatalogError,
        match="ingen konfigureret audit-checkout",
    ):
        binding.root_for(intent)


def test_checkout_binding_rejects_other_organization(tmp_path) -> None:
    intent = _intent()
    binding = ProjectAuditCheckoutBinding(
        organization_id="org-b",
        repository=intent.source_repository,
        root=tmp_path,
    )

    with pytest.raises(RepositoryCheckoutCatalogError, match="organisation"):
        binding.root_for(intent)


def test_checkout_binding_requires_absolute_existing_path(tmp_path) -> None:
    with pytest.raises(RepositoryCheckoutCatalogError, match="absolut"):
        ProjectAuditCheckoutBinding.from_environment(
            {
                "DOR_PROJECT_AUDIT_ORGANIZATION_ID": "org-a",
                "DOR_PROJECT_AUDIT_REPOSITORY": "repository:smoeberg/kodegenerator",
                "DOR_PROJECT_AUDIT_CHECKOUT_ROOT": "relative/repository",
            }
        )

    with pytest.raises(RepositoryCheckoutCatalogError, match="findes ikke"):
        ProjectAuditCheckoutBinding.from_environment(
            {
                "DOR_PROJECT_AUDIT_ORGANIZATION_ID": "org-a",
                "DOR_PROJECT_AUDIT_REPOSITORY": "repository:smoeberg/kodegenerator",
                "DOR_PROJECT_AUDIT_CHECKOUT_ROOT": str(tmp_path / "missing"),
            }
        )


def test_checkout_binding_rejects_authority_glob(tmp_path) -> None:
    with pytest.raises(
        RepositoryCheckoutCatalogError,
        match="eksakt repository identity",
    ):
        ProjectAuditCheckoutBinding.from_environment(
            {
                "DOR_PROJECT_AUDIT_ORGANIZATION_ID": "org-a",
                "DOR_PROJECT_AUDIT_REPOSITORY": "repository:external/*",
                "DOR_PROJECT_AUDIT_CHECKOUT_ROOT": str(tmp_path),
            }
        )