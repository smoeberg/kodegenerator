"""Repository for tenant-scoped durable WorkUnit records and revisions (WQ-102)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from domain.capability import Capability, CapabilityLevel
from domain.work_queue import (
    DependencyVersionBinding,
    ImmutableVersionRef,
    WorkUnit,
    WorkUnitState,
    WorkerLease,
)

from .work_queue_models import WorkUnitModel, WorkUnitRevisionModel


class WorkUnitPersistenceError(RuntimeError):
    """Raised when WorkUnit persistence or rehydration fails."""


class WorkUnitConflictError(RuntimeError):
    """Raised when a WorkUnit already exists with the same ID in the organization."""


class WorkUnitRepository:
    """Organization-scoped repository for WorkUnits with provenance revisions."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, organization_id: str, work_unit: WorkUnit) -> None:
        """Persist a new WorkUnit and record revision 1."""
        existing = self.session.get(WorkUnitModel, (organization_id, work_unit.id))
        if existing is not None:
            raise WorkUnitConflictError(
                f"WorkUnit {work_unit.id} already exists for organization {organization_id}"
            )
        model = self._to_model(organization_id, work_unit)
        self.session.add(model)

        payload = self._serialize_payload(work_unit)
        rev_model = WorkUnitRevisionModel(
            organization_id=organization_id,
            work_unit_id=work_unit.id,
            revision=1,
            payload=payload,
            recorded_at=work_unit.updated_at,
        )
        self.session.add(rev_model)
        self.session.flush()

    def get(self, organization_id: str, work_unit_id: str) -> Optional[WorkUnit]:
        """Retrieve and rehydrate a WorkUnit by ID."""
        model = self.session.get(WorkUnitModel, (organization_id, work_unit_id))
        if model is None:
            return None
        return self._from_model(model)

    def update(self, organization_id: str, work_unit: WorkUnit) -> None:
        """Update an existing WorkUnit and record a new append-only revision."""
        model = self.session.get(WorkUnitModel, (organization_id, work_unit.id))
        if model is None:
            raise WorkUnitPersistenceError(
                f"WorkUnit {work_unit.id} does not exist for organization {organization_id}"
            )
        updated_model = self._to_model(organization_id, work_unit)
        for key, value in updated_model.__dict__.items():
            if not key.startswith("_"):
                setattr(model, key, value)

        max_rev_stmt = (
            select(func.max(WorkUnitRevisionModel.revision))
            .where(WorkUnitRevisionModel.organization_id == organization_id)
            .where(WorkUnitRevisionModel.work_unit_id == work_unit.id)
        )
        max_rev = self.session.scalar(max_rev_stmt) or 0
        new_rev = max_rev + 1

        payload = self._serialize_payload(work_unit)
        rev_model = WorkUnitRevisionModel(
            organization_id=organization_id,
            work_unit_id=work_unit.id,
            revision=new_rev,
            payload=payload,
            recorded_at=datetime.now(timezone.utc),
        )
        self.session.add(rev_model)
        self.session.flush()

    def list_for_organization(self, organization_id: str) -> tuple[WorkUnit, ...]:
        """List all WorkUnits for an organization."""
        stmt = select(WorkUnitModel).where(WorkUnitModel.organization_id == organization_id)
        models = self.session.scalars(stmt).all()
        return tuple(self._from_model(m) for m in models)

    def list_history(self, organization_id: str, work_unit_id: str) -> tuple[WorkUnit, ...]:
        """List all historical revisions for a WorkUnit in chronological order."""
        stmt = (
            select(WorkUnitRevisionModel)
            .where(WorkUnitRevisionModel.organization_id == organization_id)
            .where(WorkUnitRevisionModel.work_unit_id == work_unit_id)
            .order_by(WorkUnitRevisionModel.revision.asc())
        )
        models = self.session.scalars(stmt).all()
        if not models:
            return ()
        return tuple(self._from_payload(m.payload) for m in models)

    @staticmethod
    def _serialize_payload(wu: WorkUnit) -> dict:
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

        return {
            "id": wu.id,
            "title": wu.title,
            "state": wu.state.name,
            "required_capability": cap_dict,
            "depends_on": list(wu.depends_on),
            "depends_on_snapshot": snapshots,
            "base_version": base_ver,
            "allowed_resources": list(wu.allowed_resources),
            "acceptance_refs": list(wu.acceptance_refs),
            "delivered_artifact_version": delivered_ver,
            "claimed_by": wu.claimed_by,
            "lease": lease_dict,
            "previous_worker": wu.previous_worker,
            "rework_attempts": wu.rework_attempts,
            "created_at": wu.created_at.isoformat(),
            "updated_at": wu.updated_at.isoformat(),
        }

    @classmethod
    def _to_model(cls, organization_id: str, wu: WorkUnit) -> WorkUnitModel:
        payload = cls._serialize_payload(wu)
        return WorkUnitModel(
            organization_id=organization_id,
            work_unit_id=wu.id,
            title=wu.title,
            state=wu.state.name,
            required_capability=payload["required_capability"],
            depends_on=list(wu.depends_on),
            depends_on_snapshot=payload["depends_on_snapshot"],
            base_version=payload["base_version"],
            allowed_resources=list(wu.allowed_resources),
            acceptance_refs=list(wu.acceptance_refs),
            delivered_artifact_version=payload["delivered_artifact_version"],
            claimed_by=wu.claimed_by,
            lease=payload["lease"],
            previous_worker=wu.previous_worker,
            rework_attempts=wu.rework_attempts,
            created_at=wu.created_at,
            updated_at=wu.updated_at,
        )

    @classmethod
    def _from_model(cls, model: WorkUnitModel) -> WorkUnit:
        payload = {
            "id": model.work_unit_id,
            "title": model.title,
            "state": model.state,
            "required_capability": model.required_capability,
            "depends_on": model.depends_on,
            "depends_on_snapshot": model.depends_on_snapshot,
            "base_version": model.base_version,
            "allowed_resources": model.allowed_resources,
            "acceptance_refs": model.acceptance_refs,
            "delivered_artifact_version": model.delivered_artifact_version,
            "claimed_by": model.claimed_by,
            "lease": model.lease,
            "previous_worker": model.previous_worker,
            "rework_attempts": model.rework_attempts,
            "created_at": model.created_at.isoformat(),
            "updated_at": model.updated_at.isoformat(),
        }
        return cls._from_payload(payload)

    @staticmethod
    def _from_payload(payload: dict) -> WorkUnit:
        if not isinstance(payload, dict):
            raise WorkUnitPersistenceError("Invalid payload: must be a dictionary")

        cap_dict = payload.get("required_capability")
        if not isinstance(cap_dict, dict):
            raise WorkUnitPersistenceError("Invalid capability: missing or malformed capability object")

        cap_id = cap_dict.get("id")
        if not isinstance(cap_id, str) or not cap_id.strip():
            raise WorkUnitPersistenceError("Invalid capability: missing or invalid 'id'")

        cap_name = cap_dict.get("name")
        if not isinstance(cap_name, str) or not cap_name.strip():
            raise WorkUnitPersistenceError("Invalid capability: missing or invalid 'name'")

        level_name = cap_dict.get("level")
        if not isinstance(level_name, str) or level_name not in CapabilityLevel.__members__:
            raise WorkUnitPersistenceError(f"Invalid capability: unknown or missing level '{level_name}'")

        level = CapabilityLevel[level_name]

        cap = Capability(
            id=cap_id,
            name=cap_name,
            description=cap_dict.get("description", ""),
            level=level,
            certification=cap_dict.get("certification"),
            used_by=list(cap_dict.get("used_by", [])),
        )

        base_v = payload.get("base_version")
        base_ver = (
            ImmutableVersionRef(kind=base_v["kind"], value=base_v["value"])
            if base_v and isinstance(base_v, dict) and "kind" in base_v and "value" in base_v
            else None
        )

        del_v = payload.get("delivered_artifact_version")
        delivered_ver = (
            ImmutableVersionRef(kind=del_v["kind"], value=del_v["value"])
            if del_v and isinstance(del_v, dict) and "kind" in del_v and "value" in del_v
            else None
        )

        raw_snapshots = payload.get("depends_on_snapshot", [])
        snapshots_list = []
        if isinstance(raw_snapshots, list):
            for snap in raw_snapshots:
                if isinstance(snap, dict) and "work_unit_id" in snap and "version" in snap:
                    v_dict = snap["version"]
                    if isinstance(v_dict, dict) and "kind" in v_dict and "value" in v_dict:
                        snapshots_list.append(
                            DependencyVersionBinding(
                                work_unit_id=snap["work_unit_id"],
                                version=ImmutableVersionRef(kind=v_dict["kind"], value=v_dict["value"]),
                            )
                        )
        snapshots = tuple(snapshots_list)

        lease_dict = payload.get("lease")
        lease = None
        if lease_dict and isinstance(lease_dict, dict):
            c_at_str = lease_dict.get("claimed_at")
            e_at_str = lease_dict.get("expires_at")
            if c_at_str and e_at_str:
                c_at = datetime.fromisoformat(c_at_str)
                if c_at.tzinfo is None:
                    c_at = c_at.replace(tzinfo=timezone.utc)
                e_at = datetime.fromisoformat(e_at_str)
                if e_at.tzinfo is None:
                    e_at = e_at.replace(tzinfo=timezone.utc)
                lease = WorkerLease(
                    lease_id=lease_dict.get("lease_id", "lease-unknown"),
                    worker_id=lease_dict.get("worker_id", "worker-unknown"),
                    claimed_at=c_at,
                    expires_at=e_at,
                )

        created_at = datetime.fromisoformat(payload["created_at"])
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        updated_at = datetime.fromisoformat(payload["updated_at"])
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)

        state_name = payload.get("state", "PENDING")
        if state_name not in WorkUnitState.__members__:
            raise WorkUnitPersistenceError(f"Invalid state: '{state_name}'")

        return WorkUnit(
            id=payload["id"],
            title=payload.get("title", ""),
            required_capability=cap,
            state=WorkUnitState[state_name],
            depends_on=tuple(payload.get("depends_on", [])),
            depends_on_snapshot=snapshots,
            base_version=base_ver,
            allowed_resources=tuple(payload.get("allowed_resources", [])),
            acceptance_refs=tuple(payload.get("acceptance_refs", [])),
            delivered_artifact_version=delivered_ver,
            claimed_by=payload.get("claimed_by"),
            lease=lease,
            previous_worker=payload.get("previous_worker"),
            rework_attempts=int(payload.get("rework_attempts", 0)),
            created_at=created_at,
            updated_at=updated_at,
        )
