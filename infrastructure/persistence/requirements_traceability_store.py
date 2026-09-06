"""Tenant-scoped append-only storage for requirement traceability manifests."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from phase4.requirements_traceability import RequirementTraceabilityManifest

from .requirements_traceability_models import RequirementTraceabilityModel


class RequirementTraceabilityConflictError(RuntimeError):
    """A command ID is already bound to another immutable traceability manifest."""


class RequirementTraceabilityStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(
        self,
        *,
        organization_id: str,
        manifest_id: str,
    ) -> RequirementTraceabilityModel | None:
        return self.session.scalar(
            select(RequirementTraceabilityModel).where(
                RequirementTraceabilityModel.organization_id == organization_id,
                RequirementTraceabilityModel.manifest_id == manifest_id,
            )
        )

    def list(
        self,
        *,
        organization_id: str,
        repository: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[RequirementTraceabilityModel]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        statement = select(RequirementTraceabilityModel).where(
            RequirementTraceabilityModel.organization_id == organization_id
        )
        if repository is not None:
            statement = statement.where(
                RequirementTraceabilityModel.manifest_payload["repository"].as_string()
                == repository
            )
        if status is not None:
            statement = statement.where(RequirementTraceabilityModel.status == status)
        statement = statement.order_by(
            RequirementTraceabilityModel.created_at.desc(),
            RequirementTraceabilityModel.manifest_id.asc(),
        ).limit(limit)
        return list(self.session.scalars(statement))

    def get_for_command(
        self,
        *,
        organization_id: str,
        command_id: str,
    ) -> RequirementTraceabilityModel | None:
        return self.session.scalar(
            select(RequirementTraceabilityModel).where(
                RequirementTraceabilityModel.organization_id == organization_id,
                RequirementTraceabilityModel.command_id == command_id,
            )
        )

    def add(
        self,
        *,
        command_id: str,
        manifest: RequirementTraceabilityManifest,
    ) -> RequirementTraceabilityModel:
        existing = self.get_for_command(
            organization_id=manifest.organization_id,
            command_id=command_id,
        )
        if existing is not None:
            if existing.manifest_id != manifest.manifest_id:
                raise RequirementTraceabilityConflictError(
                    "command_id is already bound to another traceability manifest"
                )
            return existing
        by_id = self.get(
            organization_id=manifest.organization_id,
            manifest_id=manifest.manifest_id,
        )
        if by_id is not None:
            return by_id
        canonical = manifest.canonical()
        row = RequirementTraceabilityModel(
            manifest_id=manifest.manifest_id,
            organization_id=manifest.organization_id,
            certificate_id=manifest.certificate_id,
            candidate_id=manifest.candidate_id,
            plan_id=manifest.plan_id,
            plan_request_fingerprint=manifest.plan_request_fingerprint,
            command_id=command_id,
            status=manifest.status.value,
            created_by=manifest.created_by,
            created_at=manifest.created_at,
            requirements_payload=list(canonical["requirements"]),
            links_payload=list(canonical["links"]),
            manifest_payload=canonical,
        )
        self.session.add(row)
        self.session.flush()
        return row

    @staticmethod
    def response_payload(row: RequirementTraceabilityModel) -> dict[str, Any]:
        return dict(row.manifest_payload)


__all__ = [
    "RequirementTraceabilityConflictError",
    "RequirementTraceabilityStore",
]
