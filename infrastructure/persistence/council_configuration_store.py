"""Validated tenant-scoped persistence for Council roles, templates, and pools."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from phase4.council.configuration import (
    AllocationMember,
    AutonomyLevel,
    CouncilRoleDefinition,
    CouncilTemplate,
    IndependenceLevel,
    ProtocolFunction,
    RoleAllocationPool,
    TemplateStage,
)

from .bot_catalog_models import BotProfileModel
from .council_configuration_models import (
    CouncilRoleAllocationMemberModel,
    CouncilRoleAllocationModel,
    CouncilRoleConfigurationModel,
    CouncilTemplateModel,
)
from .database import apply_tenant_context


class CouncilConfigurationError(ValueError):
    pass


class CouncilConfigurationConflictError(RuntimeError):
    pass


class CouncilConfigurationStore:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._sessions = session_factory

    def add_role(self, value: CouncilRoleDefinition) -> CouncilRoleDefinition:
        self._insert(
            value.organization_id,
            CouncilRoleConfigurationModel(
                organization_id=value.organization_id,
                role_id=value.role_id,
                version=value.version,
                name=value.name,
                purpose=value.purpose,
                protocol_function=value.protocol_function.value,
                required_capabilities=list(value.required_capabilities),
                input_schema_ref=value.input_schema_ref,
                output_schema_ref=value.output_schema_ref,
                rubric_ref=value.rubric_ref,
                independent_verification=value.independent_verification,
                enabled=value.enabled,
                fingerprint=value.fingerprint,
                created_at=value.created_at,
            ),
        )
        return value

    def get_role(
        self, organization_id: str, role_id: str, version: int | None = None
    ) -> CouncilRoleDefinition | None:
        row = self._one(
            organization_id,
            CouncilRoleConfigurationModel,
            CouncilRoleConfigurationModel.role_id,
            role_id,
            CouncilRoleConfigurationModel.version,
            version,
        )
        return None if row is None else self._role(row)

    def list_roles(self, organization_id: str) -> tuple[CouncilRoleDefinition, ...]:
        return tuple(
            self._role(row)
            for row in self._latest(
                organization_id,
                CouncilRoleConfigurationModel,
                CouncilRoleConfigurationModel.role_id,
                CouncilRoleConfigurationModel.version,
            )
        )

    def add_template(self, value: CouncilTemplate) -> CouncilTemplate:
        for stage in value.stages:
            for role_id, version in stage.role_versions:
                role = self.get_role(value.organization_id, role_id, version)
                if role is None or not role.enabled:
                    raise CouncilConfigurationError(
                        "template references a missing or disabled role version"
                    )
                if role.protocol_function is not stage.protocol_function:
                    raise CouncilConfigurationError(
                        "stage protocol function does not match role"
                    )
        self._insert(
            value.organization_id,
            CouncilTemplateModel(
                organization_id=value.organization_id,
                template_id=value.template_id,
                version=value.version,
                name=value.name,
                stages=[stage.canonical() for stage in value.stages],
                approved_by=value.approved_by,
                enabled=value.enabled,
                fingerprint=value.fingerprint,
                created_at=value.created_at,
            ),
        )
        return value

    def get_template(
        self, organization_id: str, template_id: str, version: int | None = None
    ) -> CouncilTemplate | None:
        row = self._one(
            organization_id,
            CouncilTemplateModel,
            CouncilTemplateModel.template_id,
            template_id,
            CouncilTemplateModel.version,
            version,
        )
        return None if row is None else self._template(row)

    def list_templates(self, organization_id: str) -> tuple[CouncilTemplate, ...]:
        return tuple(
            self._template(row)
            for row in self._latest(
                organization_id,
                CouncilTemplateModel,
                CouncilTemplateModel.template_id,
                CouncilTemplateModel.version,
            )
        )

    def add_allocation(self, value: RoleAllocationPool) -> RoleAllocationPool:
        role = self.get_role(value.organization_id, value.role_id, value.role_version)
        if role is None or not role.enabled:
            raise CouncilConfigurationError(
                "allocation references a missing or disabled role version"
            )
        with self._sessions() as session:
            apply_tenant_context(session, value.organization_id)
            for member in value.members:
                profile = session.get(
                    BotProfileModel,
                    (
                        value.organization_id,
                        member.bot_profile_id,
                        member.bot_profile_version,
                    ),
                )
                if profile is None or not profile.enabled:
                    raise CouncilConfigurationError(
                        "allocation references a missing or disabled "
                        "bot profile version"
                    )
                if not set(role.required_capabilities).issubset(
                    set(profile.capabilities)
                ):
                    raise CouncilConfigurationError(
                        "bot profile lacks a required Council role capability"
                    )
        try:
            with self._sessions() as session, session.begin():
                apply_tenant_context(session, value.organization_id)
                session.add(
                    CouncilRoleAllocationModel(
                        organization_id=value.organization_id,
                        allocation_id=value.allocation_id,
                        version=value.version,
                        role_id=value.role_id,
                        role_version=value.role_version,
                        independence_level=value.independence_level.value,
                        autonomy_level=value.autonomy_level.value,
                        hard_constraints=dict(value.hard_constraints),
                        approved_by=value.approved_by,
                        enabled=value.enabled,
                        fingerprint=value.fingerprint,
                        created_at=value.created_at,
                    )
                )
                session.flush()
                for member in value.members:
                    session.add(
                        CouncilRoleAllocationMemberModel(
                            organization_id=value.organization_id,
                            allocation_id=value.allocation_id,
                            allocation_version=value.version,
                            bot_profile_id=member.bot_profile_id,
                            bot_profile_version=member.bot_profile_version,
                            preference_rank=member.preference_rank,
                            fallback_rank=member.fallback_rank,
                        )
                    )
        except IntegrityError as exc:
            raise CouncilConfigurationConflictError(
                "Council allocation version conflicts"
            ) from exc
        return value

    def get_allocation(
        self, organization_id: str, allocation_id: str, version: int | None = None
    ) -> RoleAllocationPool | None:
        row = self._one(
            organization_id,
            CouncilRoleAllocationModel,
            CouncilRoleAllocationModel.allocation_id,
            allocation_id,
            CouncilRoleAllocationModel.version,
            version,
        )
        if row is None:
            return None
        with self._sessions() as session:
            apply_tenant_context(session, organization_id)
            members = session.scalars(
                select(CouncilRoleAllocationMemberModel)
                .where(
                    CouncilRoleAllocationMemberModel.organization_id == organization_id,
                    CouncilRoleAllocationMemberModel.allocation_id == row.allocation_id,
                    CouncilRoleAllocationMemberModel.allocation_version == row.version,
                )
                .order_by(CouncilRoleAllocationMemberModel.preference_rank)
            ).all()
            return self._allocation(row, members)

    def _insert(self, organization_id: str, row: object) -> None:
        try:
            with self._sessions() as session, session.begin():
                apply_tenant_context(session, organization_id)
                session.add(row)
        except IntegrityError as exc:
            raise CouncilConfigurationConflictError(
                "Council configuration version conflicts"
            ) from exc

    def _one(
        self, organization_id, model, identity_column, identity, version_column, version
    ):
        with self._sessions() as session:
            apply_tenant_context(session, organization_id)
            query = select(model).where(
                model.organization_id == organization_id, identity_column == identity
            )
            query = (
                query.where(version_column == version)
                if version is not None
                else query.order_by(version_column.desc()).limit(1)
            )
            return session.scalar(query)

    def _latest(self, organization_id, model, identity_column, version_column):
        with self._sessions() as session:
            apply_tenant_context(session, organization_id)
            rows = session.scalars(
                select(model)
                .where(model.organization_id == organization_id)
                .order_by(identity_column, version_column.desc())
            ).all()
            latest: dict[str, Any] = {}
            for row in rows:
                latest.setdefault(str(getattr(row, identity_column.key)), row)
            return tuple(latest[key] for key in sorted(latest))

    @staticmethod
    def _role(row) -> CouncilRoleDefinition:
        return CouncilRoleDefinition(
            role_id=row.role_id,
            organization_id=row.organization_id,
            name=row.name,
            purpose=row.purpose,
            protocol_function=ProtocolFunction(row.protocol_function),
            required_capabilities=tuple(row.required_capabilities),
            input_schema_ref=row.input_schema_ref,
            output_schema_ref=row.output_schema_ref,
            rubric_ref=row.rubric_ref,
            independent_verification=row.independent_verification,
            enabled=row.enabled,
            version=row.version,
            created_at=_utc(row.created_at),
        )

    @staticmethod
    def _template(row) -> CouncilTemplate:
        stages = tuple(
            TemplateStage(
                stage_id=item["stage_id"],
                protocol_function=ProtocolFunction(item["protocol_function"]),
                role_versions=tuple(
                    (role, int(version)) for role, version in item["role_versions"]
                ),
                minimum_assignments=int(item["minimum_assignments"]),
                maximum_assignments=int(item["maximum_assignments"]),
                parallel=bool(item["parallel"]),
                blocking=bool(item["blocking"]),
            )
            for item in row.stages
        )
        return CouncilTemplate(
            template_id=row.template_id,
            organization_id=row.organization_id,
            name=row.name,
            stages=stages,
            approved_by=row.approved_by,
            enabled=row.enabled,
            version=row.version,
            created_at=_utc(row.created_at),
        )

    @staticmethod
    def _allocation(row, members) -> RoleAllocationPool:
        return RoleAllocationPool(
            allocation_id=row.allocation_id,
            organization_id=row.organization_id,
            role_id=row.role_id,
            role_version=row.role_version,
            members=tuple(
                AllocationMember(
                    bot_profile_id=m.bot_profile_id,
                    bot_profile_version=m.bot_profile_version,
                    preference_rank=m.preference_rank,
                    fallback_rank=m.fallback_rank,
                )
                for m in members
            ),
            independence_level=IndependenceLevel(row.independence_level),
            autonomy_level=AutonomyLevel(row.autonomy_level),
            hard_constraints=tuple(sorted(row.hard_constraints.items())),
            approved_by=row.approved_by,
            enabled=row.enabled,
            version=row.version,
            created_at=_utc(row.created_at),
        )


def _utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )
