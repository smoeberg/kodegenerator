"""Audit events for authority lifecycle mutations."""
from __future__ import annotations

from domain.authority import AuthorizationDecision
from domain.event import Event, EventType

_EVENT_TYPES = {
    "role_created": EventType.AUTHORITY_ROLE_CREATED,
    "role_activated": EventType.AUTHORITY_ROLE_ACTIVATED,
    "role_deactivated": EventType.AUTHORITY_ROLE_DEACTIVATED,
    "role_assigned": EventType.AUTHORITY_ROLE_ASSIGNED,
    "role_assignment_activated": EventType.AUTHORITY_ROLE_ASSIGNMENT_ACTIVATED,
    "role_assignment_deactivated": EventType.AUTHORITY_ROLE_ASSIGNMENT_DEACTIVATED,
    "role_revoked": EventType.AUTHORITY_ROLE_REVOKED,
}


def create_authority_mutation_audit_event(decision: AuthorizationDecision, *, command_id: str, action: str, role_definition_id: str, target_actor_id: str | None = None) -> Event:
    """Create an immutable audit event for an authorized authority mutation."""
    if not decision.allowed:
        raise ValueError("Authority mutation audit requires an allowed decision")
    try:
        event_type = _EVENT_TYPES[action]
    except KeyError as exc:
        raise ValueError(f"Unsupported authority audit action: {action}") from exc
    return Event(
        event_type=event_type,
        aggregate_id=role_definition_id,
        aggregate_type="role_definition",
        organization_id=decision.organization_id,
        actor_id=decision.actor_id,
        correlation_id=command_id,
        metadata={
            "command_id": command_id,
            "action": action,
            "role_definition_id": role_definition_id,
            "target_actor_id": target_actor_id,
            "principal_id": decision.principal_id,
            "capability_id": decision.capability_id,
            "resource_id": decision.resource_id,
            "resource_organization_id": decision.resource_organization_id,
            "allowed": decision.allowed,
            "reason_code": decision.reason_code,
            "reason": decision.reason,
            "decision_fingerprint": decision.fingerprint,
        },
    )
