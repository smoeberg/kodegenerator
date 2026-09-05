"""Contract tests for governed repository onboarding intent v1."""
from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone

import pytest

from generation.project_spec import ProjectDefinition
from phase4.onboarding import (
    AUDIT_ONLY_OBJECTIVES,
    EXTEND_OBJECTIVES,
    MODERNIZE_REWRITE_OBJECTIVES,
    OnboardingContractError,
    OnboardingIntent,
    OnboardingIntentDraft,
    OnboardingPurpose,
    objectives_for,
)


REPOSITORY = "repository:smoeberg/kodegenerator"
ACTOR = "user:alice"
ORGANIZATION = "org:acme"


def rewrite_target(*, name: str = "modernized-dor") -> ProjectDefinition:
    return ProjectDefinition(
        name=name,
        architecture="hexagonal",
        language="rust",
        api="axum",
        database="postgresql",
    )


def make_draft(
    *,
    purpose: OnboardingPurpose = OnboardingPurpose.EXTEND,
    rationale: str = "Extend the existing governed runtime.",
    target_stack: ProjectDefinition | None = None,
    supersedes_intent_id: str | None = None,
) -> OnboardingIntentDraft:
    if purpose is OnboardingPurpose.MODERNIZE_REWRITE and target_stack is None:
        target_stack = rewrite_target()
    return OnboardingIntentDraft(
        source_repository=REPOSITORY,
        purpose=purpose,
        rationale=rationale,
        target_stack=target_stack,
        supersedes_intent_id=supersedes_intent_id,
    )


class TestOnboardingIntentDraft:
    def test_purpose_is_closed_and_client_draft_has_no_trusted_identity_fields(
        self,
    ):
        assert {purpose.value for purpose in OnboardingPurpose} == {
            "extend",
            "modernize_rewrite",
            "audit_only",
        }
        draft = make_draft()
        assert not hasattr(draft, "declared_by")
        assert not hasattr(draft, "organization_id")
        assert not hasattr(draft, "declared_at")
        assert not hasattr(draft, "intent_id")

        with pytest.raises(
            OnboardingContractError,
            match="declared OnboardingPurpose",
        ):
            OnboardingIntentDraft(
                source_repository=REPOSITORY,
                purpose="extend",  # type: ignore[arg-type]
                rationale="Free-text purpose coercion is forbidden.",
            )

    def test_rewrite_requires_target_stack_and_other_purposes_forbid_it(self):
        with pytest.raises(
            OnboardingContractError,
            match="requires an explicit target_stack",
        ):
            OnboardingIntentDraft(
                source_repository=REPOSITORY,
                purpose=OnboardingPurpose.MODERNIZE_REWRITE,
                rationale="Rewrite onto a new stack.",
            )

        for purpose in (
            OnboardingPurpose.EXTEND,
            OnboardingPurpose.AUDIT_ONLY,
        ):
            with pytest.raises(OnboardingContractError, match="only allowed"):
                OnboardingIntentDraft(
                    source_repository=REPOSITORY,
                    purpose=purpose,
                    rationale="Do not reinterpret this as a rewrite.",
                    target_stack=rewrite_target(),
                )

    @pytest.mark.parametrize(
        ("source_repository", "rationale", "message"),
        (
            (" repository:repo ", "valid", "outer whitespace"),
            ("repository:*", "valid", "authority glob"),
            (REPOSITORY, " rationale ", "outer whitespace"),
            (REPOSITORY, "", "non-empty"),
        ),
    )
    def test_semantic_text_is_canonical_and_authority_resource_is_exact(
        self,
        source_repository,
        rationale,
        message,
    ):
        with pytest.raises(OnboardingContractError, match=message):
            OnboardingIntentDraft(
                source_repository=source_repository,
                purpose=OnboardingPurpose.EXTEND,
                rationale=rationale,
            )

    def test_supersession_requires_a_canonical_sha256_identity(self):
        with pytest.raises(OnboardingContractError, match="lowercase SHA-256"):
            make_draft(supersedes_intent_id="ABC")

        previous = "a" * 64
        draft = make_draft(supersedes_intent_id=previous)
        assert draft.supersedes_intent_id == previous

    def test_content_fingerprint_is_deterministic_and_semantic(self):
        first = make_draft()
        second = make_draft()
        changed = make_draft(rationale="A materially different reason.")
        correction = make_draft(supersedes_intent_id="a" * 64)

        assert len(first.content_fingerprint) == 64
        assert first.content_fingerprint == second.content_fingerprint
        assert first.content_fingerprint == correction.content_fingerprint
        assert first.content_fingerprint != changed.content_fingerprint

        rewrite = make_draft(purpose=OnboardingPurpose.MODERNIZE_REWRITE)
        other_stack = make_draft(
            purpose=OnboardingPurpose.MODERNIZE_REWRITE,
            target_stack=rewrite_target(name="other-target"),
        )
        assert rewrite.content_fingerprint != other_stack.content_fingerprint


class TestRecordedOnboardingIntent:
    def test_trusted_metadata_is_attached_by_record_boundary(self):
        declared_at = datetime(
            2026,
            9,
            5,
            18,
            30,
            tzinfo=timezone(timedelta(hours=2)),
        )
        intent = OnboardingIntent.from_draft(
            make_draft(),
            declared_by=ACTOR,
            organization_id=ORGANIZATION,
            declared_at=declared_at,
        )

        assert intent.declared_by == ACTOR
        assert intent.organization_id == ORGANIZATION
        assert intent.declared_at == datetime(
            2026,
            9,
            5,
            16,
            30,
            tzinfo=timezone.utc,
        )
        assert intent.canonical()["declared_at"] == "2026-09-05T16:30:00+00:00"
        assert intent.content_fingerprint == make_draft().content_fingerprint
        assert len(intent.intent_id) == 64

    def test_intent_identity_is_idempotent_across_retry_time(self):
        draft = make_draft()
        first = OnboardingIntent.from_draft(
            draft,
            declared_by=ACTOR,
            organization_id=ORGANIZATION,
            declared_at=datetime(2026, 9, 5, 10, tzinfo=timezone.utc),
        )
        retried = OnboardingIntent.from_draft(
            draft,
            declared_by=ACTOR,
            organization_id=ORGANIZATION,
            declared_at=datetime(2026, 9, 5, 11, tzinfo=timezone.utc),
        )

        assert first.intent_id == retried.intent_id
        assert first.canonical()["declared_at"] != retried.canonical()["declared_at"]

    def test_actor_organization_and_supersession_are_bound_into_record_identity(
        self,
    ):
        draft = make_draft()
        baseline = OnboardingIntent.from_draft(
            draft,
            declared_by=ACTOR,
            organization_id=ORGANIZATION,
        )
        other_actor = OnboardingIntent.from_draft(
            draft,
            declared_by="user:bob",
            organization_id=ORGANIZATION,
        )
        other_org = OnboardingIntent.from_draft(
            draft,
            declared_by=ACTOR,
            organization_id="org:other",
        )
        successor = OnboardingIntent.from_draft(
            make_draft(supersedes_intent_id=baseline.intent_id),
            declared_by=ACTOR,
            organization_id=ORGANIZATION,
        )

        assert baseline.content_fingerprint == other_actor.content_fingerprint
        assert baseline.content_fingerprint == other_org.content_fingerprint
        assert baseline.content_fingerprint == successor.content_fingerprint
        assert baseline.intent_id != other_actor.intent_id
        assert baseline.intent_id != other_org.intent_id
        assert baseline.intent_id != successor.intent_id
        assert successor.supersedes_intent_id == baseline.intent_id
        assert successor.canonical()["supersedes_intent_id"] == baseline.intent_id

    def test_record_is_immutable_and_rejects_untrusted_timestamp_shape(self):
        intent = OnboardingIntent.from_draft(
            make_draft(),
            declared_by=ACTOR,
            organization_id=ORGANIZATION,
        )
        with pytest.raises(FrozenInstanceError):
            intent.purpose = OnboardingPurpose.AUDIT_ONLY

        with pytest.raises(OnboardingContractError, match="timezone-aware"):
            replace(intent, declared_at=datetime(2026, 9, 5, 12, 0))

    def test_record_factory_rejects_non_draft_input(self):
        with pytest.raises(TypeError, match="OnboardingIntentDraft"):
            OnboardingIntent.from_draft(  # type: ignore[arg-type]
                object(),
                declared_by=ACTOR,
                organization_id=ORGANIZATION,
            )


class TestOnboardingObjectives:
    def test_each_purpose_has_an_explicit_non_overlapping_objective_contract(
        self,
    ):
        assert objectives_for(OnboardingPurpose.EXTEND) is EXTEND_OBJECTIVES
        assert (
            objectives_for(OnboardingPurpose.MODERNIZE_REWRITE)
            is MODERNIZE_REWRITE_OBJECTIVES
        )
        assert (
            objectives_for(OnboardingPurpose.AUDIT_ONLY)
            is AUDIT_ONLY_OBJECTIVES
        )
        assert len(EXTEND_OBJECTIVES) == 3
        assert len(MODERNIZE_REWRITE_OBJECTIVES) == 4
        assert len(AUDIT_ONLY_OBJECTIVES) == 2
        assert set(EXTEND_OBJECTIVES).isdisjoint(MODERNIZE_REWRITE_OBJECTIVES)
        assert set(EXTEND_OBJECTIVES).isdisjoint(AUDIT_ONLY_OBJECTIVES)
        assert set(MODERNIZE_REWRITE_OBJECTIVES).isdisjoint(
            AUDIT_ONLY_OBJECTIVES
        )

    def test_objective_mapping_rejects_free_text_even_when_value_matches_enum(
        self,
    ):
        with pytest.raises(
            OnboardingContractError,
            match="declared OnboardingPurpose",
        ):
            objectives_for("extend")  # type: ignore[arg-type]
