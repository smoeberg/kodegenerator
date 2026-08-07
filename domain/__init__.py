# domain/__init__.py
"""
DOR Domain Layer

This module contains the canonical domain models for the Digital Organization Runtime (DOR).
All domain primitives are defined here as dataclasses with clear contracts.

Core Domain Primitives:
- Organization: Juridisk/operationel identitet
- Principal: Authenticated identity (from JWT)
- Actor: Enhed (AI, menneske, service) som kan udføre handlinger
- Role: Stilling med kompetencer, ansvar og autoritet
- Capability: Evne som en Actor kan have
- Intent: Mål/ønsket resultat som udløser et Workflow
- Workflow: Procesdefinition med states, transitions og gates
- Task: Opgave som skal udføres i et Workflow
- Artifact: Verificerbart output med versionering og provenance
- Policy: Governance-regler som styrer execution
- Governance: Governance struktur (boards, decisions)
- Event: Domain events som repræsenterer state changes

Usage:
    from domain.organization import Organization
    from domain.actor import Actor, ActorType
    from domain.workflow import Workflow, WorkflowState
    from domain.task import Task, TaskStatus
    from domain.artifact import Artifact, ArtifactType
    from domain.policy import Policy, PolicyScope
    from domain.governance import GovernanceDepartment, GovernanceBoard
    from domain.event import Event, EventType
"""

# Re-export all domain primitives for convenience
from .organization import Organization
from .department import Department
from .team import Team
from .principal import Principal
from .actor import Actor, ActorType
from .role import RoleDefinition
from .capability import Capability, CapabilityLevel
from .intent import Intent, IntentPriority, IntentStatus
from .workflow import Workflow, WorkflowState, WorkflowStatus, State, Transition, Gate, InvalidTransitionError
from .task import Task, TaskStatus, TaskPriority, DependencyStatus
from .artifact import Artifact, ArtifactType, ArtifactState, GovernanceState, Signature, Provenance
from .policy import Policy, PolicyScope, EnforcementPoint, PolicyAction, PolicyViolation, AuthorizationDecision
from .governance import GovernanceDepartment, GovernanceBoard, GovernanceDecision, BoardType, DecisionStatus, NotAuthorizedError
from .event import Event, EventType, DomainEvent
from .event import (
    create_intent_created_event,
    create_workflow_state_changed_event,
    create_task_completed_event,
    create_artifact_created_event,
    create_policy_violated_event,
    create_authorization_denied_event
)

__all__ = [
    # Organization
    "Organization",
    "Department",
    "Team",
    
    # Identity
    "Principal",
    "Actor",
    "ActorType",
    
    # Roles & Capabilities
    "RoleDefinition",
    "Capability",
    "CapabilityLevel",
    
    # Intent
    "Intent",
    "IntentPriority",
    "IntentStatus",
    
    # Workflow
    "Workflow",
    "WorkflowState",
    "WorkflowStatus",
    "State",
    "Transition",
    "Gate",
    "InvalidTransitionError",
    
    # Task
    "Task",
    "TaskStatus",
    "TaskPriority",
    "DependencyStatus",
    
    # Artifact
    "Artifact",
    "ArtifactType",
    "ArtifactState",
    "GovernanceState",
    "Signature",
    "Provenance",
    
    # Policy
    "Policy",
    "PolicyScope",
    "EnforcementPoint",
    "PolicyAction",
    "PolicyViolation",
    "AuthorizationDecision",
    
    # Governance
    "GovernanceDepartment",
    "GovernanceBoard",
    "GovernanceDecision",
    "BoardType",
    "DecisionStatus",
    "NotAuthorizedError",
    
    # Event
    "Event",
    "EventType",
    "DomainEvent",
    
    # Factory functions
    "create_intent_created_event",
    "create_workflow_state_changed_event",
    "create_task_completed_event",
    "create_artifact_created_event",
    "create_policy_violated_event",
    "create_authorization_denied_event"
]
