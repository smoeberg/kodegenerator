"""Audit event construction for authorization decisions.

Authorization audit records use the canonical Event model. They deliberately
contain decision metadata only; credentials, tokens and command payloads are
never copied into the audit stream.
"""
from __future__ import annotations

from domain.authority import AuthorizationDecision
from domain.event import Event, EventType


def create_authorization_audit_event(
    decision: AuthorizationDecision,
    *,
    command_id: str,
    command_type: str,
    allowed: bool,
) -> Event:
    """Create an immutable authorization audit event for a command decision."""
    if allowed != decision.allowed:
        raise ValueError("Audit outcome must match the authorization decision")

    event_type = EventType.AUTHORIZATION_GRANTED if allowed else EventType.AUTHORIZATION_DENIED
    return Event(
        event_type=event_type,
        aggregate_id=decision.resource_id,
        aggregate_type="workflow",
        organization_id=decision.organization_id,
        actor_id=decision.actor_id,
        correlation_id=command_id,
        metadata={
            "command_id": command_id,
            "command_type": command_type,
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
