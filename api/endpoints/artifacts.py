# api/endpoints/artifacts.py
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_dor
from api.models import ArtifactCreate, ArtifactResponse
from domain.artifact import Artifact
from infrastructure.database.dor_runtime_db import DORRuntimeDB

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _response(artifact: Artifact, dor: DORRuntimeDB) -> ArtifactResponse:
    department = (
        dor.db_adapter.get_department(artifact.department_id)
        if artifact.department_id
        else None
    )
    workflow = (
        dor.db_adapter.get_workflow(artifact.workflow_id)
        if artifact.workflow_id
        else None
    )
    return ArtifactResponse(
        id=artifact.id,
        version=artifact.version,
        artifact_type=artifact.artifact_type,
        hash=artifact.hash,
        state=artifact.state,
        owner=artifact.owner.to_dict() if artifact.owner else None,
        department=department.to_dict() if department else None,
        workflow=workflow.to_dict() if workflow else None,
        signatures=[s.to_dict() for s in artifact.signatures],
        parents=artifact.parents,
        children=artifact.children,
        metadata=artifact.metadata,
        created_at=artifact.created_at,
        updated_at=artifact.updated_at,
    )


@router.post("/", response_model=ArtifactResponse, status_code=status.HTTP_201_CREATED)
def create_artifact(
    artifact: ArtifactCreate,
    dor: DORRuntimeDB = Depends(get_dor),
):
    """Opret et nyt Artifact."""
    owner = dor.db_adapter.get_actor(artifact.owner_id)
    if not owner:
        raise HTTPException(status_code=404, detail="Owner not found")

    workflow = dor.db_adapter.get_workflow(artifact.workflow_id) if artifact.workflow_id else None
    if artifact.workflow_id and not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # The current API model carries metadata rather than binary/content data.
    # Keep the existing contract explicit: this is a metadata fingerprint, not
    # a content-integrity hash. A content-addressed artifact store belongs in
    # the next persistence layer.
    import hashlib
    import json

    canonical_metadata = json.dumps(
        artifact.metadata or {}, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    hash_value = hashlib.sha256(canonical_metadata).hexdigest()

    db_artifact = Artifact(
        id=artifact.id,
        version=artifact.version,
        artifact_type=artifact.artifact_type,
        hash=hash_value,
        state=artifact.state,
        owner=owner,
        department_id=artifact.department_id,
        workflow_id=artifact.workflow_id,
        metadata=artifact.metadata,
    )
    return _response(dor.db_adapter.create_artifact(db_artifact), dor)


@router.get("/{artifact_id}", response_model=ArtifactResponse)
def get_artifact(artifact_id: str, dor: DORRuntimeDB = Depends(get_dor)):
    """Hent et Artifact ud fra ID."""
    artifact = dor.db_adapter.get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return _response(artifact, dor)


@router.get("/", response_model=List[ArtifactResponse])
def get_artifacts(
    workflow_id: Optional[str] = None,
    owner_id: Optional[str] = None,
    dor: DORRuntimeDB = Depends(get_dor),
):
    """Hent Artifacts filtreret efter workflow eller owner."""
    if workflow_id:
        artifacts = dor.db_adapter.uow.artifact.get_by_workflow(workflow_id)
    elif owner_id:
        artifacts = dor.db_adapter.uow.artifact.get_by_owner(owner_id)
    else:
        artifacts = dor.db_adapter.uow.artifact.get_all()
    return [_response(artifact, dor) for artifact in artifacts]


@router.post("/{artifact_id}/submit", response_model=ArtifactResponse)
def submit_artifact(
    artifact_id: str,
    actor_id: str,
    dor: DORRuntimeDB = Depends(get_dor),
):
    """Indsend et Artifact til review."""
    artifact = dor.db_adapter.get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    actor = dor.db_adapter.get_actor(actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")

    if not dor.workflow_engine.artifact_manager.submit_artifact(artifact_id, actor):
        raise HTTPException(status_code=400, detail="Failed to submit artifact")

    artifact_model = dor.db_adapter.uow.artifact.get(artifact_id)
    artifact_model.state = "submitted"
    dor.db_adapter.uow.commit()
    return _response(dor.db_adapter.get_artifact(artifact_id), dor)


@router.post("/{artifact_id}/approve", response_model=ArtifactResponse)
def approve_artifact(
    artifact_id: str,
    actor_id: str,
    role_id: str,
    dor: DORRuntimeDB = Depends(get_dor),
):
    """Godkend et Artifact."""
    artifact = dor.db_adapter.get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    actor = dor.db_adapter.get_actor(actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")

    if not dor.workflow_engine.artifact_manager.approve_artifact(artifact_id, actor, role_id):
        raise HTTPException(status_code=400, detail="Failed to approve artifact")
    return _response(dor.db_adapter.get_artifact(artifact_id), dor)
