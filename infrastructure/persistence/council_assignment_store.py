"""Tenant-scoped persistence for frozen Council assignment plans.

Assignment plans are immutable once frozen: replaying the same run must
return the identical plan and never a silently substituted provider.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from phase4.council.configuration import ProtocolFunction
from phase4.council.roles import CouncilRole
from phase4.council.routing import AssignmentRoute, CouncilAssignmentPlan
from phase4.verification.allocation_selector import FrozenCouncilAssignment

from .database import apply_tenant_context
from .selection_models import CouncilFrozenAssignmentModel


class CouncilAssignmentStoreError(RuntimeError):
    pass


class CouncilAssignmentConflictError(CouncilAssignmentStoreError):
    pass


def _utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


class CouncilAssignmentStore:
    """Read/write frozen assignment plans against bot_session_assignments."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        role_for_stage: Callable[[str], CouncilRole],
        persona_for_role: Callable[[CouncilRole], Any],
        protocol_for_stage: Callable[[str], ProtocolFunction],
        model_lookup: Callable[[str, int, str], dict[str, Any]],
    ) -> None:
        self._sessions = session_factory
        self._role_for_stage = role_for_stage
        self._persona_for_role = persona_for_role
        self._protocol_for_stage = protocol_for_stage
        self._model_lookup = model_lookup

    def save_plan(self, plan: CouncilAssignmentPlan) -> CouncilAssignmentPlan:
        if not plan.routes:
            raise CouncilAssignmentStoreError("cannot persist an empty assignment plan")
        try:
            with self._sessions() as session, session.begin():
                apply_tenant_context(session, plan.organization_id)
                for index, route in enumerate(plan.routes):
                    session.add(
                        CouncilFrozenAssignmentModel(
                            organization_id=plan.organization_id,
                            assignment_id=route.assignment_id,
                            decision_id=plan.decision_id,
                            assignment_index=index,
                            stage_id=route.protocol_function.value,
                            role_id=route.role.value,
                            role_version=1,
                            allocation_id=route.connection_id,
                            allocation_version=route.connection_version,
                            bot_profile_id=route.agent_identity,
                            bot_profile_version=1,
                            profile_fingerprint=route.route_fingerprint,
                            agent_identity=route.agent_identity,
                            deployment_id=route.deployment_id,
                            deployment_revision=route.deployment_revision,
                            deployment_fingerprint=route.route_fingerprint,
                            connection_id=route.connection_id,
                            connection_version=route.connection_version,
                            connection_fingerprint=route.route_fingerprint,
                            scope_id=plan.run_id,
                            repository="",
                            base_sha="",
                            input_fingerprint=plan.plan_fingerprint,
                        )
                    )
        except IntegrityError as exc:
            raise CouncilAssignmentConflictError(
                "frozen assignment plan already exists"
            ) from exc
        return plan

    def get_plan(self, organization_id: str, run_id: str) -> CouncilAssignmentPlan | None:
        with self._sessions() as session:
            apply_tenant_context(session, organization_id)
            rows = session.scalars(
                select(CouncilFrozenAssignmentModel)
                .where(
                    CouncilFrozenAssignmentModel.organization_id == organization_id,
                    CouncilFrozenAssignmentModel.scope_id == run_id,
                )
                .order_by(CouncilFrozenAssignmentModel.assignment_index)
            ).all()
            if not rows:
                return None
            routes: list[AssignmentRoute] = []
            for row in rows:
                role = CouncilRole(row.role_id)
                persona = self._persona_for_role(role)
                protocol = ProtocolFunction(row.stage_id)
                provider_id = row.connection_id
                model = self._model_lookup(
                    row.deployment_id,
                    row.deployment_revision,
                    row.deployment_fingerprint,
                )
                routes.append(
                    AssignmentRoute(
                        assignment_id=row.assignment_id,
                        role=role,
                        agent_identity=row.agent_identity,
                        capability=persona.capability,
                        provider_id=provider_id,
                        connection_id=row.connection_id,
                        connection_version=row.connection_version,
                        deployment_id=row.deployment_id,
                        deployment_revision=row.deployment_revision,
                        model_id=model.get("model_id") or "",
                        model_family=model.get("model_family") or "",
                        prompt_version=model.get("prompt_version") or "v1",
                        protocol_function=protocol,
                        route_fingerprint=row.deployment_fingerprint,
                    )
                )
            return CouncilAssignmentPlan(
                run_id=run_id,
                decision_id=rows[0].decision_id,
                organization_id=organization_id,
                template_id="",
                template_version=1,
                routes=tuple(routes),
                plan_fingerprint=rows[0].input_fingerprint,
            )
