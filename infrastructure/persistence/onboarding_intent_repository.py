"""Repository for immutable tenant-scoped onboarding intent records."""
from __future__ import annotations

from datetime import timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from generation.project_spec import ProjectDefinition
from phase4.onboarding import OnboardingIntent, OnboardingPurpose

from .onboarding_intent_models import OnboardingIntentModel


class OnboardingIntentPersistenceError(RuntimeError):
    """Raised when durable onboarding state violates its canonical contract."""


class OnboardingIntentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, intent: OnboardingIntent) -> None:
        if not isinstance(intent, OnboardingIntent):
            raise TypeError("intent must be an OnboardingIntent")
        self.session.add(
            OnboardingIntentModel(
                intent_id=intent.intent_id,
                organization_id=intent.organization_id,
                source_repository=intent.source_repository,
                purpose=intent.purpose.value,
                rationale=intent.rationale,
                target_stack=(
                    intent.target_stack.model_dump(mode="json")
                    if intent.target_stack is not None
                    else None
                ),
                supersedes_intent_id=intent.supersedes_intent_id,
                content_fingerprint=intent.content_fingerprint,
                declared_by=intent.declared_by,
                declared_at=intent.declared_at,
            )
        )
        self.session.flush()

    def get_for_organization(
        self,
        intent_id: str,
        organization_id: str,
    ) -> OnboardingIntent | None:
        row = self.session.execute(
            select(OnboardingIntentModel).where(
                OnboardingIntentModel.intent_id == intent_id,
                OnboardingIntentModel.organization_id == organization_id,
            )
        ).scalar_one_or_none()
        return self._restore(row) if row is not None else None

    def get_successor(
        self,
        intent_id: str,
        organization_id: str,
    ) -> OnboardingIntent | None:
        row = self.session.execute(
            select(OnboardingIntentModel).where(
                OnboardingIntentModel.organization_id == organization_id,
                OnboardingIntentModel.supersedes_intent_id == intent_id,
            )
        ).scalar_one_or_none()
        return self._restore(row) if row is not None else None

    @staticmethod
    def _restore(row: OnboardingIntentModel) -> OnboardingIntent:
        declared_at = row.declared_at
        if declared_at.tzinfo is None or declared_at.utcoffset() is None:
            # SQLite drops timezone offsets from DateTime values. Database writes
            # are canonical UTC, so restore that transport detail explicitly.
            declared_at = declared_at.replace(tzinfo=timezone.utc)
        else:
            declared_at = declared_at.astimezone(timezone.utc)

        try:
            target_stack = (
                ProjectDefinition.model_validate(row.target_stack)
                if row.target_stack is not None
                else None
            )
            intent = OnboardingIntent(
                source_repository=row.source_repository,
                purpose=OnboardingPurpose(row.purpose),
                rationale=row.rationale,
                declared_by=row.declared_by,
                organization_id=row.organization_id,
                target_stack=target_stack,
                supersedes_intent_id=row.supersedes_intent_id,
                declared_at=declared_at,
            )
        except Exception as exc:
            raise OnboardingIntentPersistenceError(
                "persisted onboarding intent cannot be reconstructed canonically"
            ) from exc

        if intent.intent_id != row.intent_id:
            raise OnboardingIntentPersistenceError(
                "persisted onboarding intent identity does not match canonical content"
            )
        if intent.content_fingerprint != row.content_fingerprint:
            raise OnboardingIntentPersistenceError(
                "persisted onboarding content fingerprint does not match canonical content"
            )
        return intent
