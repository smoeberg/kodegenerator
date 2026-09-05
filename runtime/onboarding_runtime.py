"""Governed Core command runtime for durable onboarding-intent declarations."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import sleep
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import IntegrityError, OperationalError

from domain.authority import AuthorizationDecision
from domain.authorization_audit import create_authorization_audit_event
from domain.event import Event, EventType
from infrastructure.persistence.onboarding_intent_repository import (
    OnboardingIntentPersistenceError,
)
from infrastructure.persistence.uow import UnitOfWork
from phase4.onboarding import (
    OnboardingContractError,
    OnboardingIntent,
    OnboardingIntentDraft,
)
from runtime.commands import CommandConflictError
from services.authorization_service import AuthorizationService

if TYPE_CHECKING:
    from runtime.context import OrganizationContext
    from runtime.core import DORRuntime


ONBOARDING_INTENT_DECLARE_ACTION = "onboarding.intent.declare"
_COMMAND_RETRY_LIMIT = 3
_COMMAND_RETRY_DELAY_SECONDS = 0.02


class OnboardingIntentRuntimeError(RuntimeError):
    """Base error for the governed onboarding declaration boundary."""


class OnboardingIntentNotFoundError(OnboardingIntentRuntimeError):
    """A referenced prior intent is unavailable in the active organization."""


class OnboardingIntentConflictError(OnboardingIntentRuntimeError):
    """The requested declaration conflicts with immutable onboarding history."""


@dataclass(frozen=True)
class DeclareOnboardingIntentCommand:
    """Client command containing semantic intent, never trusted actor metadata."""

    command_id: str
    organization_id: str
    draft: OnboardingIntentDraft

    def __post_init__(self) -> None:
        _command_text("command_id", self.command_id)
        _command_text("organization_id", self.organization_id)
        if not isinstance(self.draft, OnboardingIntentDraft):
            raise OnboardingContractError("draft must be an OnboardingIntentDraft")
        _command_text("source_repository", self.draft.source_repository)

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "contract_version": "1.0",
            "command_type": type(self).__name__,
            "organization_id": self.organization_id,
            "draft": self.draft.semantic_payload(),
            "supersedes_intent_id": self.draft.supersedes_intent_id,
            "content_fingerprint": self.draft.content_fingerprint,
        }


@dataclass(frozen=True)
class OnboardingIntentCommandResult:
    command_id: str
    intent: OnboardingIntent
    replayed: bool


class OnboardingRuntime:
    """Authorize and atomically persist one human-declared onboarding intent."""

    def __init__(self, runtime: "DORRuntime") -> None:
        self.runtime = runtime

    def _record_denial(
        self,
        decision: AuthorizationDecision,
        *,
        command: DeclareOnboardingIntentCommand,
    ) -> None:
        from runtime.core import CommandAuthorizationError

        event = create_authorization_audit_event(
            decision,
            command_id=command.command_id,
            command_type=type(command).__name__,
            allowed=False,
            aggregate_type="onboarding_intent",
        )
        with self.runtime.database.session(decision.organization_id) as session:
            with UnitOfWork(session) as uow:
                uow.events.append(event)
        raise CommandAuthorizationError(decision)

    @staticmethod
    def _assert_existing_command(
        existing: Any,
        *,
        context: "OrganizationContext",
        command: DeclareOnboardingIntentCommand,
    ) -> None:
        if (
            existing.organization_id != context.organization_id
            or existing.actor_id != context.actor_id
            or existing.command_type != type(command).__name__
            or existing.payload != command.payload
        ):
            raise CommandConflictError(
                f"Command ID already used with different command data: {command.command_id}"
            )

    def _organization_mismatch(
        self,
        context: "OrganizationContext",
        command: DeclareOnboardingIntentCommand,
    ) -> None:
        decision = AuthorizationDecision(
            allowed=False,
            reason="Command organization does not match runtime context",
            reason_code="command_organization_mismatch",
            actor_id=context.actor_id,
            principal_id=context.principal.id,
            organization_id=context.organization_id,
            capability_id=ONBOARDING_INTENT_DECLARE_ACTION,
            resource_id=command.draft.source_repository,
            resource_organization_id=context.organization_id,
        )
        self._record_denial(decision, command=command)

    def declare_intent(
        self,
        context: "OrganizationContext",
        command: DeclareOnboardingIntentCommand,
    ) -> OnboardingIntentCommandResult:
        """Run the canonical authorize -> persist -> audit -> receipt write path."""

        for attempt in range(_COMMAND_RETRY_LIMIT):
            try:
                return self._declare_intent_once(context, command)
            except IntegrityError as exc:
                if attempt == _COMMAND_RETRY_LIMIT - 1:
                    raise CommandConflictError(
                        "durable onboarding command or intent history conflicts with existing state"
                    ) from exc
            except OperationalError as exc:
                if (
                    "database is locked" not in str(exc).lower()
                    or attempt == _COMMAND_RETRY_LIMIT - 1
                ):
                    raise
            sleep(_COMMAND_RETRY_DELAY_SECONDS * (attempt + 1))
        raise RuntimeError("unreachable onboarding declaration retry state")

    def _declare_intent_once(
        self,
        context: "OrganizationContext",
        command: DeclareOnboardingIntentCommand,
    ) -> OnboardingIntentCommandResult:
        self.runtime._require_ready()
        if command.organization_id != context.organization_id:
            self._organization_mismatch(context, command)

        denied: AuthorizationDecision | None = None
        result: OnboardingIntentCommandResult | None = None
        with self.runtime.database.session(context.organization_id) as session:
            with UnitOfWork(session) as uow:
                decision = AuthorizationService(uow).authorize(
                    principal=context.principal,
                    actor_id=context.actor_id,
                    organization_id=context.organization_id,
                    capability_id=ONBOARDING_INTENT_DECLARE_ACTION,
                    resource_id=command.draft.source_repository,
                    resource_organization_id=context.organization_id,
                )
                if not decision.allowed:
                    denied = decision
                else:
                    existing = uow.commands.get(command.command_id)
                    if existing is not None:
                        self._assert_existing_command(
                            existing,
                            context=context,
                            command=command,
                        )
                        intent = uow.onboarding_intents.get_for_organization(
                            existing.aggregate_id or "",
                            context.organization_id,
                        )
                        if intent is None:
                            raise OnboardingIntentPersistenceError(
                                "completed onboarding command has no persisted intent"
                            )
                        result = OnboardingIntentCommandResult(
                            command_id=command.command_id,
                            intent=intent,
                            replayed=True,
                        )
                    else:
                        self._validate_history(uow, context, command)
                        declared_at = datetime.now(timezone.utc)
                        intent = OnboardingIntent.from_draft(
                            command.draft,
                            declared_by=context.actor_id,
                            organization_id=context.organization_id,
                            declared_at=declared_at,
                        )
                        equivalent = uow.onboarding_intents.get_for_organization(
                            intent.intent_id,
                            context.organization_id,
                        )
                        if equivalent is not None:
                            raise OnboardingIntentConflictError(
                                "equivalent onboarding intent is already recorded under another command"
                            )

                        uow.onboarding_intents.add(intent)
                        uow.events.append(
                            create_authorization_audit_event(
                                decision,
                                command_id=command.command_id,
                                command_type=type(command).__name__,
                                allowed=True,
                                aggregate_type="onboarding_intent",
                            )
                        )
                        uow.events.append(
                            Event(
                                event_type=EventType.INTENT_CREATED,
                                aggregate_id=intent.intent_id,
                                aggregate_type="onboarding_intent",
                                organization_id=context.organization_id,
                                actor_id=context.actor_id,
                                correlation_id=command.command_id,
                                metadata={
                                    "contract_version": "1.0",
                                    "intent_id": intent.intent_id,
                                    "content_fingerprint": intent.content_fingerprint,
                                    "source_repository": intent.source_repository,
                                    "purpose": intent.purpose.value,
                                    "supersedes_intent_id": intent.supersedes_intent_id,
                                },
                            )
                        )
                        uow.commands.add(
                            command_id=command.command_id,
                            organization_id=context.organization_id,
                            actor_id=context.actor_id,
                            command_type=type(command).__name__,
                            payload=command.payload,
                            aggregate_id=intent.intent_id,
                            created_at=declared_at,
                        )
                        result = OnboardingIntentCommandResult(
                            command_id=command.command_id,
                            intent=intent,
                            replayed=False,
                        )

        if denied is not None:
            self._record_denial(denied, command=command)
        if result is None:
            raise RuntimeError("onboarding declaration completed without a result")
        return result

    @staticmethod
    def _validate_history(
        uow: UnitOfWork,
        context: "OrganizationContext",
        command: DeclareOnboardingIntentCommand,
    ) -> None:
        previous_id = command.draft.supersedes_intent_id
        if previous_id is None:
            existing_root = uow.onboarding_intents.get_root_for_repository(
                command.draft.source_repository,
                context.organization_id,
            )
            if existing_root is not None:
                raise OnboardingIntentConflictError(
                    "repository already has an onboarding root intent; corrections must supersede it"
                )
            return

        previous = uow.onboarding_intents.get_for_organization(
            previous_id,
            context.organization_id,
        )
        if previous is None:
            raise OnboardingIntentNotFoundError(
                "superseded onboarding intent is not available in this organization"
            )
        if previous.source_repository != command.draft.source_repository:
            raise OnboardingIntentConflictError(
                "successor intent must target the same source repository"
            )
        if previous.content_fingerprint == command.draft.content_fingerprint:
            raise OnboardingIntentConflictError(
                "supersession must change the semantic onboarding intent"
            )
        successor = uow.onboarding_intents.get_successor(
            previous_id,
            context.organization_id,
        )
        if successor is not None:
            raise OnboardingIntentConflictError(
                "onboarding intent already has a successor; history cannot branch"
            )


def _command_text(name: str, value: str, *, max_length: int = 128) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise OnboardingContractError(f"{name} must be a non-empty trimmed string")
    if len(value) > max_length:
        raise OnboardingContractError(f"{name} exceeds {max_length} characters")
