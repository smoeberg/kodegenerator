# domain/policy.py
"""
Policy Domain Model

Represents governance rules that constrain and control execution in DOR.
Policies are the mechanism by which organizations enforce compliance and governance.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, TYPE_CHECKING
from datetime import datetime, timezone
from enum import Enum, auto
import uuid

if TYPE_CHECKING:
    from domain.organization import Organization
    from domain.actor import Actor


class PolicyScope(Enum):
    """Scope of a Policy."""
    GLOBAL = auto()
    DEPARTMENT = auto()
    TEAM = auto()
    WORKFLOW = auto()
    TASK = auto()
    ARTIFACT = auto()
    ORGANIZATION = auto()


class EnforcementPoint(Enum):
    """When a Policy is enforced."""
    PRE_EXECUTION = auto()
    POST_EXECUTION = auto()
    ON_EVENT = auto()
    SCHEDULED = auto()


class PolicyAction(Enum):
    """Action to take when a Policy is violated."""
    BLOCK = auto()
    WARN = auto()
    NOTIFY = auto()
    AUDIT = auto()
    ESCALATE = auto()


@dataclass
class Policy:
    """Represents a governance rule that constrains and controls execution in DOR."""
    id: str
    name: str
    scope: PolicyScope = PolicyScope.GLOBAL
    scope_id: Optional[str] = None
    enforcement_point: EnforcementPoint = EnforcementPoint.PRE_EXECUTION
    description: str = ""
    
    conditions: Dict[str, Any] = field(default_factory=dict)
    actions: Dict[str, Any] = field(default_factory=dict)
    
    organization: Optional["Organization"] = None
    enabled: bool = True
    priority: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        if not hasattr(self, 'id') or self.id is None:
            object.__setattr__(self, 'id', str(uuid.uuid4()))

    def applies_to(self, target_type: str, target_id: Optional[str] = None) -> bool:
        if self.scope == PolicyScope.GLOBAL:
            return True
        
        if self.scope == PolicyScope.DEPARTMENT:
            return target_type == "department" and target_id == self.scope_id
        elif self.scope == PolicyScope.TEAM:
            return target_type == "team" and target_id == self.scope_id
        elif self.scope == PolicyScope.WORKFLOW:
            return target_type == "workflow" and (target_id == self.scope_id or self.scope_id is None)
        elif self.scope == PolicyScope.TASK:
            return target_type == "task" and (target_id == self.scope_id or self.scope_id is None)
        elif self.scope == PolicyScope.ARTIFACT:
            return target_type == "artifact" and (target_id == self.scope_id or self.scope_id is None)
        elif self.scope == PolicyScope.ORGANIZATION:
            return target_type == "organization" and target_id == self.scope_id
        
        return False

    def get_action(self, violation_type: str = "default") -> PolicyAction:
        if violation_type in self.actions:
            action_str = self.actions[violation_type]
            try:
                return PolicyAction[action_str.upper()]
            except KeyError:
                pass
        
        if "on_violation" in self.actions:
            action_str = self.actions["on_violation"]
            try:
                return PolicyAction[action_str.upper()]
            except KeyError:
                pass
        
        if self.enforcement_point == EnforcementPoint.PRE_EXECUTION:
            return PolicyAction.BLOCK
        return PolicyAction.WARN

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "scope": self.scope.name,
            "scope_id": self.scope_id,
            "enforcement_point": self.enforcement_point.name,
            "conditions": self.conditions,
            "actions": self.actions,
            "organization_id": self.organization.id if self.organization else None,
            "enabled": self.enabled,
            "priority": self.priority,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], **kwargs) -> "Policy":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data["name"],
            description=data.get("description", ""),
            scope=PolicyScope[data.get("scope", "GLOBAL")],
            scope_id=data.get("scope_id"),
            enforcement_point=EnforcementPoint[data.get("enforcement_point", "PRE_EXECUTION")],
            conditions=data.get("conditions", {}),
            actions=data.get("actions", {}),
            enabled=data.get("enabled", True),
            priority=data.get("priority", 0),
            metadata=data.get("metadata", {}),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now(timezone.utc),
            updated_at=datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else datetime.now(timezone.utc),
            organization=None,
            **kwargs
        )


@dataclass
class PolicyViolation:
    """Represents a violation of a Policy."""
    policy_id: str
    policy_name: str
    violation_type: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    actor_id: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "policy_name": self.policy_name,
            "violation_type": self.violation_type,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
            "actor_id": self.actor_id,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PolicyViolation":
        return cls(
            policy_id=data["policy_id"],
            policy_name=data["policy_name"],
            violation_type=data["violation_type"],
            message=data["message"],
            details=data.get("details", {}),
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.now(timezone.utc),
            actor_id=data.get("actor_id"),
            resource_type=data.get("resource_type"),
            resource_id=data.get("resource_id")
        )


@dataclass
class AuthorizationDecision:
    """Represents a decision about whether an action is authorized."""
    action: str
    resource_type: str
    decision_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    subject: Optional["Principal"] = None
    actor_id: Optional[str] = None
    organization_id: Optional[str] = None
    resource_id: Optional[str] = None
    policy_ids: List[str] = field(default_factory=list)
    violations: List[PolicyViolation] = field(default_factory=list)
    decision: bool = True
    reason: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)
    issued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None

    def is_allowed(self) -> bool:
        return self.decision

    def is_denied(self) -> bool:
        return not self.decision

    def has_violations(self) -> bool:
        return len(self.violations) > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "actor_id": self.actor_id,
            "organization_id": self.organization_id,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "policy_ids": self.policy_ids,
            "violations": [v.to_dict() for v in self.violations],
            "decision": self.decision,
            "reason": self.reason,
            "evidence": self.evidence,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], **kwargs) -> "AuthorizationDecision":
        violations = [PolicyViolation.from_dict(v) for v in data.get("violations", [])]
        return cls(
            action=data["action"],
            resource_type=data["resource_type"],
            decision_id=data.get("decision_id", str(uuid.uuid4())),
            actor_id=data.get("actor_id"),
            organization_id=data.get("organization_id"),
            resource_id=data.get("resource_id"),
            policy_ids=data.get("policy_ids", []),
            violations=violations,
            decision=data.get("decision", True),
            reason=data.get("reason", ""),
            evidence=data.get("evidence", {}),
            issued_at=datetime.fromisoformat(data["issued_at"]) if "issued_at" in data else datetime.now(timezone.utc),
            expires_at=datetime.fromisoformat(data["expires_at"]) if "expires_at" in data else None,
            subject=None,
            **kwargs
        )
