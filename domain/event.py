# domain/event.py
"""Domain event primitives used by DOR persistence and audit."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, TYPE_CHECKING
from datetime import datetime, timezone
from enum import Enum, auto
import uuid

if TYPE_CHECKING:
    from domain.actor import Actor
    from domain.organization import Organization
    from domain.workflow import Workflow
    from domain.task import Task
    from domain.artifact import Artifact


class EventType(Enum):
    """Types of Events in DOR."""
    INTENT_CREATED = auto(); INTENT_RESOLVED = auto(); INTENT_FAILED = auto()
    WORKFLOW_CREATED = auto(); WORKFLOW_STARTED = auto(); WORKFLOW_STATE_CHANGED = auto(); WORKFLOW_COMPLETED = auto(); WORKFLOW_FAILED = auto()
    TASK_CREATED = auto(); TASK_ASSIGNED = auto(); TASK_STARTED = auto(); TASK_COMPLETED = auto(); TASK_FAILED = auto(); TASK_BLOCKED = auto()
    ARTIFACT_CREATED = auto(); ARTIFACT_SUBMITTED = auto(); ARTIFACT_APPROVED = auto(); ARTIFACT_REJECTED = auto(); ARTIFACT_RELEASED = auto()
    POLICY_CREATED = auto(); POLICY_VIOLATED = auto(); GOVERNANCE_APPROVAL = auto(); GOVERNANCE_REJECTION = auto()
    AUTHORIZATION_GRANTED = auto(); AUTHORIZATION_DENIED = auto()
    AUTHORITY_ROLE_CREATED = auto(); AUTHORITY_ROLE_ACTIVATED = auto(); AUTHORITY_ROLE_DEACTIVATED = auto()
    AUTHORITY_ROLE_ASSIGNED = auto(); AUTHORITY_ROLE_ASSIGNMENT_ACTIVATED = auto(); AUTHORITY_ROLE_ASSIGNMENT_DEACTIVATED = auto(); AUTHORITY_ROLE_REVOKED = auto()
    EXECUTION_STARTED = auto(); EXECUTION_COMPLETED = auto(); EXECUTION_FAILED = auto(); SIDE_EFFECT_VERIFIED = auto(); SYSTEM_BOOTED = auto(); SYSTEM_SHUTDOWN = auto()


@dataclass
class Event:
    """Base class for all Events in DOR."""
    event_type: EventType
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    aggregate_id: Optional[str] = None
    aggregate_type: Optional[str] = None
    organization_id: Optional[str] = None
    actor_id: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1.0"
    sequence: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "event_type": self.event_type.name, "aggregate_id": self.aggregate_id, "aggregate_type": self.aggregate_type, "organization_id": self.organization_id, "actor_id": self.actor_id, "timestamp": self.timestamp.isoformat(), "correlation_id": self.correlation_id, "causation_id": self.causation_id, "metadata": self.metadata, "schema_version": self.schema_version, "sequence": self.sequence}

    @classmethod
    def from_dict(cls, data: Dict[str, Any], **kwargs) -> "Event":
        return cls(event_type=EventType[data["event_type"]], id=data.get("id", str(uuid.uuid4())), aggregate_id=data.get("aggregate_id"), aggregate_type=data.get("aggregate_type"), organization_id=data.get("organization_id"), actor_id=data.get("actor_id"), timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.now(timezone.utc), correlation_id=data.get("correlation_id"), causation_id=data.get("causation_id"), metadata=data.get("metadata", {}), schema_version=data.get("schema_version", "1.0"), sequence=data.get("sequence", 0), **kwargs)


DomainEvent = Event


def create_intent_created_event(goal: str, organization_id: Optional[str] = None, actor_id: Optional[str] = None, description: str = "", priority: str = "MEDIUM", required_capabilities: Optional[List[str]] = None, constraints: Optional[Dict[str, Any]] = None, correlation_id: Optional[str] = None, causation_id: Optional[str] = None) -> Event:
    return Event(event_type=EventType.INTENT_CREATED, aggregate_type="intent", organization_id=organization_id, actor_id=actor_id, correlation_id=correlation_id, causation_id=causation_id, metadata={"goal": goal, "description": description, "priority": priority, "required_capabilities": required_capabilities or [], "constraints": constraints or {}})


def create_workflow_state_changed_event(workflow_id: str, new_state: str, organization_id: Optional[str] = None, actor_id: Optional[str] = None, old_state: Optional[str] = None, intent_id: Optional[str] = None, artifact_id: Optional[str] = None, evidence: Optional[Dict[str, Any]] = None, correlation_id: Optional[str] = None, causation_id: Optional[str] = None) -> Event:
    return Event(event_type=EventType.WORKFLOW_STATE_CHANGED, aggregate_id=workflow_id, aggregate_type="workflow", organization_id=organization_id, actor_id=actor_id, correlation_id=correlation_id, causation_id=causation_id, metadata={"workflow_id": workflow_id, "old_state": old_state, "new_state": new_state, "intent_id": intent_id, "artifact_id": artifact_id, "evidence": evidence or {}})


def create_task_completed_event(task_id: str, workflow_id: str, organization_id: Optional[str] = None, actor_id: Optional[str] = None, output_artifacts: Optional[List[str]] = None, execution_result: Optional[Dict[str, Any]] = None, correlation_id: Optional[str] = None, causation_id: Optional[str] = None) -> Event:
    return Event(event_type=EventType.TASK_COMPLETED, aggregate_id=task_id, aggregate_type="task", organization_id=organization_id, actor_id=actor_id, correlation_id=correlation_id, causation_id=causation_id, metadata={"task_id": task_id, "workflow_id": workflow_id, "output_artifacts": output_artifacts or [], "execution_result": execution_result or {}})


def create_artifact_created_event(artifact_id: str, artifact_type: str, organization_id: Optional[str] = None, actor_id: Optional[str] = None, version: str = "1.0.0", content_digest: str = "", provenance: Optional[Dict[str, Any]] = None, correlation_id: Optional[str] = None, causation_id: Optional[str] = None) -> Event:
    return Event(event_type=EventType.ARTIFACT_CREATED, aggregate_id=artifact_id, aggregate_type="artifact", organization_id=organization_id, actor_id=actor_id, correlation_id=correlation_id, causation_id=causation_id, metadata={"artifact_id": artifact_id, "artifact_type": artifact_type, "version": version, "content_digest": content_digest, "provenance": provenance or {}})


def create_policy_violated_event(policy_id: str, policy_name: str, violation_type: str, message: str, action: str, organization_id: Optional[str] = None, actor_id: Optional[str] = None, resource_type: Optional[str] = None, resource_id: Optional[str] = None, correlation_id: Optional[str] = None, causation_id: Optional[str] = None) -> Event:
    return Event(event_type=EventType.POLICY_VIOLATED, aggregate_id=resource_id, aggregate_type=resource_type, organization_id=organization_id, actor_id=actor_id, correlation_id=correlation_id, causation_id=causation_id, metadata={"policy_id": policy_id, "policy_name": policy_name, "violation_type": violation_type, "message": message, "action": action, "resource_type": resource_type, "resource_id": resource_id})


def create_authorization_denied_event(decision_id: str, actor_id: str, action: str, resource_type: str, organization_id: Optional[str] = None, resource_id: Optional[str] = None, reason: str = "", violations: Optional[List[Dict[str, Any]]] = None, correlation_id: Optional[str] = None, causation_id: Optional[str] = None) -> Event:
    return Event(event_type=EventType.AUTHORIZATION_DENIED, aggregate_id=resource_id, aggregate_type=resource_type, organization_id=organization_id, actor_id=actor_id, correlation_id=correlation_id, causation_id=causation_id, metadata={"decision_id": decision_id, "action": action, "resource_type": resource_type, "resource_id": resource_id, "reason": reason, "violations": violations or []})
