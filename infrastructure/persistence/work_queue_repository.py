"""Repository for tenant-scoped durable WorkUnit records (WQ-102)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from domain.capability import Capability, CapabilityLevel
from domain.work_queue import (
    DependencyVersionBinding,
    ImmutableVersionRef,
    WorkUnit,
    WorkUnitState,
    WorkerLease,
)

from .work_queue_models import WorkUnitModel


class WorkUnitPersistenceError(RuntimeError):
    """Raised when WorkUnit persistence or rehydration fails."""


class WorkUnitConflictError(RuntimeError):
    """Raised when a WorkUnit already exists with the same ID in the organization."""


class WorkUnitRepository:
    """Organization-scoped repository for WorkUnits."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, organization_id: str, work_unit: WorkUnit) -> None:
        """Persist a new WorkUnit."""
        existing = self.session.get(WorkUnitModel, (organization_id, work_unit.id))
        if existing is not None:
            raise WorkUnitConflictError(
                f"WorkUnit {work_unit.id} already exists for organization {organization_id}"
            )
        model = self._to_model(organization_id, work_unit)
        self.session.add(model)
        self.session.flush()

    def get(self, organization_id: str, work_unit_id: str) -> Optional[WorkUnit]:
        """Retrieve and rehydrate a WorkUnit by ID."""
        model = self.session.get(WorkUnitModel, (organization_id, work_unit_id))
        if model is None:
            return None
        return self._from_model(model)

    def update(self, organization_id: str, work_unit: WorkUnit) -> None:
        """Update an existing WorkUnit."""
        model = self.session.get(WorkUnitModel, (organization_id, work_unit.id))
        if model is None:
            raise WorkUnitPersistenceError(
                f"WorkUnit {work_unit.id} does not exist for organization {organization_id}"
            )
        updated_model = self._to_model(organization_id, work_unit)
        for key, value in updated_model.__dict__.items():
            if not key.startswith("_"):
                setattr(model, key, value)
        self.session.flush()

    def list_for_organization(self, organization_id: str) -> tuple[WorkUnit, ...]:
        """List all WorkUnits for an organization."""
        stmt = select(WorkUnitModel).where(WorkUnitModel.organization_id == organization_id)
        models = self.session.scalars(stmt).all()
        return tuple(self._from_model(m) for m in models)

    @staticmethod
    def _to_model(organization_id: str, wu: WorkUnit) -> WorkUnitModel:
        cap = wu.required_capability
        cap_dict = {
            "id": cap.id,
            "name": cap.name,
            "description": cap.description,
            "level": cap.level.name if isinstance(cap.level, CapabilityLevel) else str(cap.level),
            "certification": cap.certification,
            "used_by": list(cap.used_by),
        }

        base_ver = {"kind": wu.base_version.kind, "value": wu.base_version.value} if wu.base_version else None
        delivered_ver = (
            {"kind": wu.delivered_artifact_version.kind, "value": wu.delivered_artifact_version.value}
            if wu.delivered_artifact_version
            else None
        )

        snapshots = [
            {
                "work_unit_id": snap.work_unit_id,
                "version": {"kind": snap.version.kind, "value": snap.version.value},
            }
            for snap in wu.depends_on_snapshot
        ]

        lease_dict = (
            {
                "lease_id": wu.lease.lease_id,
                "worker_id": wu.lease.worker_id,
                "claimed_at": wu.lease.claimed_at.isoformat(),
                "expires_at": wu.lease.expires_at.isoformat(),
            }
            if wu.lease
            else None
        )

        return WorkUnitModel(
            organization_id=organization_id,
            work_unit_id=wu.id,
            title=wu.title,
            state=wu.state.name,
            required_capability=cap_dict,
            depends_on=list(wu.depends_on),
            depends_on_snapshot=snapshots,
            base_version=base_ver,
            allowed_resources=list(wu.allowed_resources),
            acceptance_refs=list(wu.acceptance_refs),
            delivered_artifact_version=delivered_ver,
            claimed_by=wu.claimed_by,
            lease=lease_dict,
            previous_worker=wu.previous_worker,
            rework_attempts=wu.rework_attempts,
            created_at=wu.created_at,
            updated_at=wu.updated_at,
        )

    @staticmethod
    def _from_model(model: WorkUnitModel) -> WorkUnit:
        cap_dict = model.required_capability
        try:
            level_name = cap_dict.get("level", "BEGINNER")
            level = CapabilityLevel[level_name] if level_name in CapabilityLevel.__members__ else CapabilityLevel.BEGINNER
        except Exception:
            level = CapabilityLevel.BEGINNER

        cap = Capability(
            id=cap_dict["id"],
            name=cap_dict.get("name", cap_dict["id"]),
            description=cap_dict.get("description", ""),
            level=level,
            certification=cap_dict.get("certification"),
            used_by=list(cap_dict.get("used_by", [])),
        )

        base_ver = (
            ImmutableVersionRef(kind=model.base_version["kind"], value=model.base_version["value"])
            if model.base_version
            else None
        )

        delivered_ver = (
            ImmutableVersionRef(
                kind=model.delivered_artifact_version["kind"],
                value=model.delivered_artifact_version["value"],
            )
            if model.delivered_artifact_version
            else None
        )

        snapshots = tuple(
            DependencyVersionBinding(
                work_unit_id=snap["work_unit_id"],
                version=ImmutableVersionRef(
                    kind=snap["version"]["kind"], value=snap["version"]["value"]
                ),
            )
            for snap in model.depends_on_snapshot
        )

        lease = None
        if model.lease:
            c_at = datetime.fromisoformat(model.lease["claimed_at"])
            if c_at.tzinfo is None:
                c_at = c_at.replace(tzinfo=timezone.utc)
            e_at = datetime.fromisoformat(model.lease["expires_at"])
            if e_at.tzinfo is None:
                e_at = e_at.replace(tzinfo=timezone.utc)
            lease = WorkerLease(
                lease_id=model.lease["lease_id"],
                worker_id=model.lease["worker_id"],
                claimed_at=c_at,
                expires_at=e_at,
            )

        created_at = model.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        updated_at = model.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)

        return WorkUnit(
            id=model.work_unit_id,
            title=model.title,
            required_capability=cap,
            state=WorkUnitState[model.state],
            depends_on=tuple(model.depends_on),
            depends_on_snapshot=snapshots,
            base_version=base_ver,
            allowed_resources=tuple(model.allowed_resources),
            acceptance_refs=tuple(model.acceptance_refs),
            delivered_artifact_version=delivered_ver,
            claimed_by=model.claimed_by,
            lease=lease,
            previous_worker=model.previous_worker,
            rework_attempts=model.rework_attempts,
            created_at=created_at,
            updated_at=updated_at,
        )
