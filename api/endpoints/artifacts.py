# api/endpoints/artifacts.py
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from typing import List
from api.models import ArtifactCreate, ArtifactResponse
from infrastructure.database.dor_runtime_db import DORRuntimeDB
from domain.artifact import Artifact, ArtifactState, ArtifactType
import hashlib

router = APIRouter(prefix="/artifacts", tags=["artifacts"])

@router.post("/", response_model=ArtifactResponse, status_code=status.HTTP_201_CREATED)
def create_artifact(
    artifact: ArtifactCreate,
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Opret et nyt Artifact."""
    owner = dor.db_adapter.get_actor(artifact.owner_id)
    if not owner:
        raise HTTPException(status_code=404, detail="Owner not found")

    workflow = dor.db_adapter.get_workflow(artifact.workflow_id) if artifact.workflow_id else None

    # Beregn hash (simplificeret: hash af metadata)
    hash_value = hashlib.sha256(str(artifact.metadata).encode()).hexdigest()

    db_artifact = Artifact(
        id=artifact.id,
        version=artifact.version,
        artifact_type=artifact.artifact_type,
        hash=hash_value,
        state=artifact.state,
        owner=owner,
        department_id=artifact.department_id,
        workflow_id=artifact.workflow_id,
        metadata=artifact.metadata
    )

    # Gem Artifact i databasen
    artifact_model = dor.db_adapter.create_artifact(db_artifact)

    return ArtifactResponse(
        id=artifact_model.id,
        version=artifact_model.version,
        artifact_type=artifact_model.artifact_type,
        hash=artifact_model.hash,
        state=artifact_model.state,
        owner=owner.to_dict(),
        department=dor.db_adapter.get_department(artifact.department_id).to_dict() if artifact.department_id else None,
        workflow=workflow.to_dict() if workflow else None,
        signatures=[],
        parents=artifact_model.parents,
        children=artifact_model.children,
        metadata=artifact_model.metadata,
        created_at=artifact_model.created_at,
        updated_at=artifact_model.updated_at
    )

@router.get("/{artifact_id}", response_model=ArtifactResponse)
def get_artifact(
    artifact_id: str,
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Hent et Artifact ud fra ID."""
    artifact = dor.db_adapter.get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    return ArtifactResponse(
        id=artifact.id,
        version=artifact.version,
        artifact_type=artifact.artifact_type,
        hash=artifact.hash,
        state=artifact.state,
        owner=artifact.owner.to_dict() if artifact.owner else None,
        department=dor.db_adapter.get_department(artifact.department_id).to_dict() if artifact.department_id else None,
        workflow=dor.db_adapter.get_workflow(artifact.workflow_id).to_dict() if artifact.workflow_id else None,
        signatures=[s.to_dict() for s in artifact.signatures],
        parents=artifact.parents,
        children=artifact.children,
        metadata=artifact.metadata,
        created_at=artifact.created_at,
        updated_at=artifact.updated_at
    )

@router.get("/", response_model=List[ArtifactResponse])
def get_artifacts(
    workflow_id: Optional[str] = None,
    owner_id: Optional[str] = None,
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Hent alle Artifacts (filtreret efter workflow, owner)."""
    if workflow_id:
        artifacts = dor.db_adapter.uow.artifact.get_by_workflow(workflow_id)
    elif owner_id:
        artifacts = dor.db_adapter.uow.artifact.get_by_owner(owner_id)
    else:
        artifacts = dor.db_adapter.uow.artifact.get_all()

    return [
        ArtifactResponse(
            id=a.id,
            version=a.version,
            artifact_type=a.artifact_type,
            hash=a.hash,
            state=a.state,
            owner=a.owner.to_dict() if a.owner else None,
            department=dor.db_adapter.get_department(a.department_id).to_dict() if a.department_id else None,
            workflow=dor.db_adapter.get_workflow(a.workflow_id).to_dict() if a.workflow_id else None,
            signatures=[s.to_dict() for s in a.signatures],
            parents=a.parents,
            children=a.children,
            metadata=a.metadata,
            created_at=a.created_at,
            updated_at=a.updated_at
        )
        for a in artifacts
    ]

@router.post("/{artifact_id}/submit", response_model=ArtifactResponse)
def submit_artifact(
    artifact_id: str,
    actor_id: str,
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Indsend et Artifact til review."""
    artifact = dor.db_adapter.get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    actor = dor.db_adapter.get_actor(actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")

    # Indsend Artifact
    success = dor.workflow_engine.artifact_manager.submit_artifact(artifact_id, actor)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to submit artifact")

    # Opdater Artifact i databasen
    artifact_model = dor.db_adapter.uow.artifact.get(artifact_id)
    artifact_model.state = "submitted"
    dor.db_adapter.uow.commit()

    # Returner opdateret Artifact
    updated_artifact = dor.db_adapter.get_artifact(artifact_id)
    return ArtifactResponse(
        id=updated_artifact.id,
        version=updated_artifact.version,
        artifact_type=updated_artifact.artifact_type,
        hash=updated_artifact.hash,
        state=updated_artifact.state,
        owner=updated_artifact.owner.to_dict() if updated_artifact.owner else None,
        department=dor.db_adapter.get_department(updated_artifact.department_id).to_dict() if updated_artifact.department_id else None,
        workflow=dor.db_adapter.get_workflow(updated_artifact.workflow_id).to_dict() if updated_artifact.workflow_id else None,
        signatures=[s.to_dict() for s in updated_artifact.signatures],
        parents=updated_artifact.parents,
        children=updated_artifact.children,
        metadata=updated_artifact.metadata,
        created_at=updated_artifact.created_at,
        updated_at=updated_artifact.updated_at
    )

@router.post("/{artifact_id}/approve", response_model=ArtifactResponse)
def approve_artifact(
    artifact_id: str,
    actor_id: str,
    role_id: str,
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Godkend et Artifact."""
    artifact = dor.db_adapter.get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    actor = dor.db_adapter.get_actor(actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")

    # Godkend Artifact
    success = dor.workflow_engine.artifact_manager.approve_artifact(artifact_id, actor, role_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to approve artifact")

    # Returner opdateret Artifact
    updated_artifact = dor.db_adapter.get_artifact(artifact_id)
    return ArtifactResponse(
        id=updated_artifact.id,
        version=updated_artifact.version,
        artifact_type=updated_artifact.artifact_type,
        hash=updated_artifact.hash,
        state=updated_artifact.state,
        owner=updated_artifact.owner.to_dict() if updated_artifact.owner else None,
        department=dor.db_adapter.get_department(updated_artifact.department_id).to_dict() if updated_artifact.department_id else None,
        workflow=dor.db_adapter.get_workflow(updated_artifact.workflow_id).to_dict() if updated_artifact.workflow_id else None,
        signatures=[s.to_dict() for s in updated_artifact.signatures],
        parents=updated_artifact.parents,
        children=updated_artifact.children,
        metadata=updated_artifact.metadata,
        created_at=updated_artifact.created_at,
        updated_at=updated_artifact.updated_at
    )
