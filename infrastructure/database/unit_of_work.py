# infrastructure/database/unit_of_work.py
from sqlalchemy.orm import Session
from .repositories import (
    OrganizationRepository, DepartmentRepository, ActorRepository,
    RoleDefinitionRepository, CapabilityRepository, IntentRepository,
    WorkflowRepository, TaskRepository, ArtifactRepository,
    EventRepository, PolicyRepository, GovernanceRepository
)

class UnitOfWork:
    """Unit of Work for at håndtere database-transaktioner."""

    def __init__(self, db: Session):
        self.db = db
        self.organization = OrganizationRepository(db)
        self.department = DepartmentRepository(db)
        self.actor = ActorRepository(db)
        self.role_definition = RoleDefinitionRepository(db)
        self.capability = CapabilityRepository(db)
        self.intent = IntentRepository(db)
        self.workflow = WorkflowRepository(db)
        self.task = TaskRepository(db)
        self.artifact = ArtifactRepository(db)
        self.event = EventRepository(db)
        self.policy = PolicyRepository(db)
        self.governance = GovernanceRepository(db)

    def commit(self):
        """Commit alle ændringer til databasen."""
        self.db.commit()

    def rollback(self):
        """Rollback alle ændringer."""
        self.db.rollback()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
