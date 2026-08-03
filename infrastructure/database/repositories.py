# infrastructure/database/repositories.py
from typing import Dict, List, Optional, Type, TypeVar, Generic
from sqlalchemy.orm import Session
from pydantic import BaseModel
from .models import (
    OrganizationModel, DepartmentModel, TeamModel, ActorModel,
    RoleDefinitionModel, CapabilityModel, IntentModel, WorkflowModel,
    TaskModel, ArtifactModel, SignatureModel, EventModel, PolicyModel,
    GovernanceDepartmentModel
)

# TypeVar for generiske repositories
T = TypeVar('T', bound=BaseModel)

class BaseRepository(Generic[T]):
    """Base-klasse for alle repositories."""

    def __init__(self, db: Session, model_class: Type[T]):
        self.db = db
        self.model_class = model_class

    def create(self, **kwargs) -> T:
        """Opret en ny instans."""
        instance = self.model_class(**kwargs)
        self.db.add(instance)
        self.db.commit()
        self.db.refresh(instance)
        return instance

    def get(self, id: str) -> Optional[T]:
        """Hent en instans ud fra ID."""
        return self.db.query(self.model_class).filter_by(id=id).first()

    def get_all(self) -> List[T]:
        """Hent alle instanser."""
        return self.db.query(self.model_class).all()

    def update(self, id: str, **kwargs) -> Optional[T]:
        """Opdater en instans."""
        instance = self.get(id)
        if not instance:
            return None
        for key, value in kwargs.items():
            setattr(instance, key, value)
        self.db.commit()
        self.db.refresh(instance)
        return instance

    def delete(self, id: str) -> bool:
        """Slet en instans."""
        instance = self.get(id)
        if not instance:
            return False
        self.db.delete(instance)
        self.db.commit()
        return True

# Specifikke Repositories
class OrganizationRepository(BaseRepository[OrganizationModel]):
    def __init__(self, db: Session):
        super().__init__(db, OrganizationModel)

    def get_by_name(self, name: str) -> Optional[OrganizationModel]:
        return self.db.query(OrganizationModel).filter_by(name=name).first()

class DepartmentRepository(BaseRepository[DepartmentModel]):
    def __init__(self, db: Session):
        super().__init__(db, DepartmentModel)

    def get_by_organization(self, organization_id: str) -> List[DepartmentModel]:
        return self.db.query(DepartmentModel).filter_by(organization_id=organization_id).all()

class ActorRepository(BaseRepository[ActorModel]):
    def __init__(self, db: Session):
        super().__init__(db, ActorModel)

    def get_by_organization(self, organization_id: str) -> List[ActorModel]:
        return self.db.query(ActorModel).filter_by(organization_id=organization_id).all()

    def get_by_capability(self, capability_id: str) -> List[ActorModel]:
        # Brug association table
        return self.db.query(ActorModel).join(
            actor_capability, ActorModel.id == actor_capability.c.actor_id
        ).filter(actor_capability.c.capability_id == capability_id).all()

class RoleDefinitionRepository(BaseRepository[RoleDefinitionModel]):
    def __init__(self, db: Session):
        super().__init__(db, RoleDefinitionModel)

class CapabilityRepository(BaseRepository[CapabilityModel]):
    def __init__(self, db: Session):
        super().__init__(db, CapabilityModel)

class IntentRepository(BaseRepository[IntentModel]):
    def __init__(self, db: Session):
        super().__init__(db, IntentModel)

class WorkflowRepository(BaseRepository[WorkflowModel]):
    def __init__(self, db: Session):
        super().__init__(db, WorkflowModel)

    def get_by_intent(self, intent_id: str) -> Optional[WorkflowModel]:
        return self.db.query(WorkflowModel).filter_by(intent_id=intent_id).first()

class TaskRepository(BaseRepository[TaskModel]):
    def __init__(self, db: Session):
        super().__init__(db, TaskModel)

    def get_by_workflow(self, workflow_id: str) -> List[TaskModel]:
        return self.db.query(TaskModel).filter_by(workflow_id=workflow_id).all()

    def get_pending(self) -> List[TaskModel]:
        return self.db.query(TaskModel).filter_by(status="pending").all()

class ArtifactRepository(BaseRepository[ArtifactModel]):
    def __init__(self, db: Session):
        super().__init__(db, ArtifactModel)

    def get_by_workflow(self, workflow_id: str) -> List[ArtifactModel]:
        return self.db.query(ArtifactModel).filter_by(workflow_id=workflow_id).all()

    def get_by_owner(self, owner_id: str) -> List[ArtifactModel]:
        return self.db.query(ArtifactModel).filter_by(owner_id=owner_id).all()

    def get_children(self, artifact_id: str) -> List[ArtifactModel]:
        artifact = self.get(artifact_id)
        if not artifact:
            return []
        return artifact.children

    def get_parents(self, artifact_id: str) -> List[ArtifactModel]:
        artifact = self.get(artifact_id)
        if not artifact:
            return []
        return artifact.parents

class EventRepository(BaseRepository[EventModel]):
    def __init__(self, db: Session):
        super().__init__(db, EventModel)

    def get_by_workflow(self, workflow_id: str) -> List[EventModel]:
        return self.db.query(EventModel).filter_by(workflow_id=workflow_id).all()

    def get_by_actor(self, actor_id: str) -> List[EventModel]:
        return self.db.query(EventModel).filter_by(actor_id=actor_id).all()

class PolicyRepository(BaseRepository[PolicyModel]):
    def __init__(self, db: Session):
        super().__init__(db, PolicyModel)

    def get_by_scope(self, scope: str) -> List[PolicyModel]:
        return self.db.query(PolicyModel).filter_by(scope=scope).all()

class GovernanceRepository(BaseRepository[GovernanceDepartmentModel]):
    def __init__(self, db: Session):
        super().__init__(db, GovernanceDepartmentModel)

    def get_boards(self, governance_id: str) -> Dict[str, List[ActorModel]]:
        governance = self.get(governance_id)
        if not governance:
            return {}
        return {
            "architecture": governance.architecture_board,
            "security": governance.security_board,
            "compliance": governance.compliance_board,
            "quality": governance.quality_board
        }
