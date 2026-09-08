"""SC-101A project identity bridge across Phase-4 delivery boundaries.

The bridge is deliberately narrow: it carries the trusted ``project_id`` and
``organization_id`` already established by onboarding into audit, planning and
Implementation Agent provenance.  It does not activate scope, authorize work,
or implement SC-101B active-plan semantics.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from phase4.context_packet.models import ContextItem, ContextPacket
from phase4.implementation_agent.models import (
    IMPLEMENTATION_ACTION,
    ChangeBudget,
    ImplementationRequest,
)
from phase4.onboarding import ONBOARDING_INTENT_CONTEXT_KEY, OnboardingIntent
from phase4.planner.service import GeneratedPlan
from phase4.project_audit.models import ProjectAuditReport


PROJECT_IDENTITY_CONTEXT_KEY = "sc101a-project-identity"


class ProjectIdentityBridgeError(ValueError):
    """Raised when project/tenant provenance drifts across SC-101A boundaries."""


@dataclass(frozen=True)
class ProjectIdentityProvenance:
    """Content-addressed identity inherited from one audited onboarding intent."""

    organization_id: str
    project_id: str
    source_repository: str
    onboarding_intent_id: str
    audit_report_id: str
    audit_request_fingerprint: str
    provenance_id: str = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "organization_id",
            "project_id",
            "source_repository",
            "onboarding_intent_id",
            "audit_report_id",
            "audit_request_fingerprint",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ProjectIdentityBridgeError(
                    f"{name} must be a non-empty trimmed string"
                )
        object.__setattr__(self, "provenance_id", _digest(self.canonical_payload()))

    @classmethod
    def from_audit(
        cls,
        *,
        intent: OnboardingIntent,
        report: ProjectAuditReport,
    ) -> "ProjectIdentityProvenance":
        """Recover trusted project identity only from an exact audit binding."""

        if not isinstance(intent, OnboardingIntent):
            raise TypeError("intent must be an OnboardingIntent")
        if not isinstance(report, ProjectAuditReport):
            raise TypeError("report must be a ProjectAuditReport")
        if intent.project_id is None:
            raise ProjectIdentityBridgeError(
                "SC-101A requires an onboarding intent bound to an exact project_id"
            )
        if report.request.resource != intent.source_repository:
            raise ProjectIdentityBridgeError(
                "audit report resource does not match onboarding repository"
            )

        matches = [
            item
            for item in report.request.context_packet.items
            if item.source == "onboarding-intent"
            and item.key == ONBOARDING_INTENT_CONTEXT_KEY
        ]
        if (
            report.request.context_packet.truncated
            or len(matches) != 1
            or matches[0].canonical()["value"] != intent.canonical()
        ):
            raise ProjectIdentityBridgeError(
                "audit report is not bound to the exact onboarding intent"
            )

        return cls(
            organization_id=intent.organization_id,
            project_id=intent.project_id,
            source_repository=intent.source_repository,
            onboarding_intent_id=intent.intent_id,
            audit_report_id=report.report_id,
            audit_request_fingerprint=report.request_fingerprint,
        )

    def canonical_payload(self) -> dict[str, str]:
        return {
            "organization_id": self.organization_id,
            "project_id": self.project_id,
            "source_repository": self.source_repository,
            "onboarding_intent_id": self.onboarding_intent_id,
            "audit_report_id": self.audit_report_id,
            "audit_request_fingerprint": self.audit_request_fingerprint,
        }

    def canonical(self) -> dict[str, str]:
        return {"provenance_id": self.provenance_id, **self.canonical_payload()}


@dataclass(frozen=True)
class ProjectBoundPlan:
    """Planning output whose executable provenance is hard-bound to a project."""

    plan: GeneratedPlan
    provenance: ProjectIdentityProvenance
    plan_request_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.plan, GeneratedPlan):
            raise TypeError("plan must be a GeneratedPlan")
        if not isinstance(self.provenance, ProjectIdentityProvenance):
            raise TypeError("provenance must be ProjectIdentityProvenance")
        if self.plan.resource != self.provenance.source_repository:
            raise ProjectIdentityBridgeError(
                "plan resource does not match audited project repository"
            )
        object.__setattr__(
            self,
            "plan_request_fingerprint",
            _digest(
                {
                    "plan_id": self.plan.plan_id,
                    "planner_request_fingerprint": self.plan.request_fingerprint,
                    "project_provenance_id": self.provenance.provenance_id,
                }
            ),
        )

    def canonical_identity(self) -> dict[str, str]:
        return {
            "organization_id": self.provenance.organization_id,
            "project_id": self.provenance.project_id,
            "source_repository": self.provenance.source_repository,
            "onboarding_intent_id": self.provenance.onboarding_intent_id,
            "audit_report_id": self.provenance.audit_report_id,
            "project_provenance_id": self.provenance.provenance_id,
            "plan_id": self.plan.plan_id,
            "plan_request_fingerprint": self.plan_request_fingerprint,
        }


def bind_plan(
    *,
    intent: OnboardingIntent,
    report: ProjectAuditReport,
    plan: GeneratedPlan,
) -> ProjectBoundPlan:
    """Bind one generated plan to exact audited project provenance."""

    return ProjectBoundPlan(
        plan=plan,
        provenance=ProjectIdentityProvenance.from_audit(intent=intent, report=report),
    )


def build_implementation_request(
    *,
    bound_plan: ProjectBoundPlan,
    organization_id: str,
    project_id: str,
    agent_identity: str,
    agent_role: str,
    resource: str,
    instruction: str,
    allowed_paths: tuple[str, ...],
    budget: ChangeBudget | None = None,
) -> ImplementationRequest:
    """Create an IA request only when caller identity matches project provenance.

    The project identity item is inside the ContextPacket whose packet id is part
    of ``ImplementationRequest.request_fingerprint``.  A project/tenant mutation
    therefore changes or invalidates executable provenance rather than remaining
    advisory metadata.
    """

    if not isinstance(bound_plan, ProjectBoundPlan):
        raise TypeError("bound_plan must be a ProjectBoundPlan")
    provenance = bound_plan.provenance
    if organization_id != provenance.organization_id:
        raise ProjectIdentityBridgeError(
            "implementation organization does not match audited project provenance"
        )
    if project_id != provenance.project_id:
        raise ProjectIdentityBridgeError(
            "implementation project_id does not match audited project provenance"
        )
    if resource != provenance.source_repository:
        raise ProjectIdentityBridgeError(
            "implementation resource does not match audited project repository"
        )

    identity_item = ContextItem(
        source="project-identity",
        key=PROJECT_IDENTITY_CONTEXT_KEY,
        value=bound_plan.canonical_identity(),
        provenance=f"sc-101a:{provenance.provenance_id}",
        sensitivity="normal",
    )
    items = (identity_item,)
    packet = ContextPacket(
        packet_id=ContextPacket.derive_id(
            agent_identity,
            IMPLEMENTATION_ACTION,
            items,
        ),
        agent_identity=agent_identity,
        purpose=IMPLEMENTATION_ACTION,
        items=items,
        created_at=datetime.now(timezone.utc).isoformat(),
        truncated=False,
    )
    return ImplementationRequest(
        organization_id=organization_id,
        agent_identity=agent_identity,
        agent_role=agent_role,
        resource=resource,
        context_packet=packet,
        instruction=instruction,
        allowed_paths=allowed_paths,
        budget=budget or ChangeBudget(),
    )


def assert_implementation_binding(
    *,
    bound_plan: ProjectBoundPlan,
    request: ImplementationRequest,
) -> None:
    """Fail closed if an existing IA request drifted from the bound project."""

    if request.organization_id != bound_plan.provenance.organization_id:
        raise ProjectIdentityBridgeError(
            "implementation request tenant differs from project provenance"
        )
    if request.resource != bound_plan.provenance.source_repository:
        raise ProjectIdentityBridgeError(
            "implementation request resource differs from project provenance"
        )
    matches = [
        item
        for item in request.context_packet.items
        if item.source == "project-identity"
        and item.key == PROJECT_IDENTITY_CONTEXT_KEY
    ]
    if (
        request.context_packet.truncated
        or len(matches) != 1
        or matches[0].canonical()["value"] != bound_plan.canonical_identity()
    ):
        raise ProjectIdentityBridgeError(
            "implementation request lacks exact SC-101A project provenance"
        )


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "PROJECT_IDENTITY_CONTEXT_KEY",
    "ProjectBoundPlan",
    "ProjectIdentityBridgeError",
    "ProjectIdentityProvenance",
    "assert_implementation_binding",
    "bind_plan",
    "build_implementation_request",
]
