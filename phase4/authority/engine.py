"""Fail-closed, deterministic AI-3 Authority Engine."""
from __future__ import annotations

from datetime import datetime, timezone
from fnmatch import fnmatchcase
from typing import List, Mapping, Optional, Tuple

from .adapter import DecisionReadiness, RiskLevel
from .audit import AuthorityAuditSink, _as_sink
from .grants import VerifiedAuthorityGrant, _attach_decision_provenance
from .models import AuthorityDecision, AuthorityPolicy, AuthorityRequest, AuthorityRule, Decision


class AuthorityError(Exception):
    """Base class for authority engine errors."""


class PolicyValidationError(AuthorityError):
    """Raised when a policy is malformed or ambiguous."""


class AuthorityEngine:
    """Evaluate explicit authority policies without executing any action."""

    def __init__(
        self,
        policy: AuthorityPolicy,
        *,
        audit_sink: AuthorityAuditSink | None = None,
        max_allowed_risk: RiskLevel = RiskLevel.HIGH,
    ) -> None:
        self._validate_policy(policy)
        self._policy = policy
        self._audit: List[AuthorityDecision] = []
        self._audit_sink = _as_sink(audit_sink)
        self._max_allowed_risk = max_allowed_risk

    @property
    def policy(self) -> AuthorityPolicy:
        return self._policy

    def evaluate(
        self,
        request: AuthorityRequest,
        readiness_report: Optional[DecisionReadiness] = None,
    ) -> AuthorityDecision:
        if not isinstance(request, AuthorityRequest):
            raise TypeError("request must be an AuthorityRequest")

        matched: List[AuthorityRule] = [rule for rule in self._policy.rules if self._matches(rule, request)]
        matched.sort(key=lambda rule: (-rule.priority, rule.rule_id))
        denies = [rule for rule in matched if rule.effect is Decision.DENY]
        allows = [rule for rule in matched if rule.effect is Decision.ALLOW]

        # Epistemic / Council Readiness Gate:
        # If readiness_report is provided, strictly enforce:
        # 1. open_critical_disputes == 0
        # 2. evidence_verified == True
        # 3. risk_level <= max_allowed_risk
        # 4. is_decision_ready == True
        gate_failed_reason: Optional[str] = None
        if readiness_report is not None:
            gate_failed_reason = self._check_readiness_gate(readiness_report)

        if gate_failed_reason is not None:
            decision = Decision.DENY
            reason = f"council/epistemics readiness gate failure: {gate_failed_reason}"
        elif denies:
            decision = Decision.DENY
            reason = "explicit deny rule matched; deny takes precedence"
        elif allows:
            decision = Decision.ALLOW
            reason = "explicit allow rule matched and no deny rule matched"
        else:
            decision = Decision.DENY
            reason = "no applicable authority rule matched; fail closed"

        result = AuthorityDecision(
            request_id=request.request_id,
            decision=decision,
            agent_identity=request.agent_identity,
            action=request.action,
            resource=request.resource,
            context_packet_id=request.context_packet_id,
            policy_id=self._policy.policy_id,
            policy_version=self._policy.version,
            matched_rule_ids=tuple(rule.rule_id for rule in matched),
            reason=reason,
            evaluated_at=datetime.now(timezone.utc).isoformat(),
            parameters=request.parameters,
            organization_id=request.organization_id,
            actor_id=request.actor_id,
            capability=request.capability,
        )
        object.__setattr__(result, "_provenance_token", object())
        _attach_decision_provenance(result)
        self._audit.append(result)
        self._audit_sink.record(result)
        return result

    def issue_grant(
        self,
        request: AuthorityRequest,
        readiness_report: Optional[DecisionReadiness] = None,
    ) -> VerifiedAuthorityGrant:
        decision = self.evaluate(request, readiness_report=readiness_report)
        if decision.decision is not Decision.ALLOW:
            raise AuthorityError(f"cannot issue execution grant for denied authority: {decision.reason}")
        return VerifiedAuthorityGrant.from_decision(decision)

    def audit_trail(self) -> Tuple[AuthorityDecision, ...]:
        return tuple(self._audit)

    def _check_readiness_gate(self, report: DecisionReadiness) -> Optional[str]:
        """Strict fail-closed verification of Council readiness report."""
        if report.open_critical_disputes > 0:
            return f"unresolved critical disputes ({report.open_critical_disputes} open)"
        if not report.evidence_verified:
            return "evidence failed verification against current revision"
        if not self._is_risk_acceptable(report.risk_level):
            return f"risk level {report.risk_level.value} exceeds policy threshold {self._max_allowed_risk.value}"
        if not report.is_decision_ready:
            return "deliberation session is not in decision ready state"
        return None

    def _is_risk_acceptable(self, risk: RiskLevel) -> bool:
        risk_ordering = {
            RiskLevel.LOW: 1,
            RiskLevel.MEDIUM: 2,
            RiskLevel.HIGH: 3,
            RiskLevel.CRITICAL: 4,
        }
        return risk_ordering.get(risk, 99) <= risk_ordering.get(self._max_allowed_risk, 0)

    @staticmethod
    def _matches(rule: AuthorityRule, request: AuthorityRequest) -> bool:
        if rule.action != request.action or not fnmatchcase(request.resource, rule.resource_pattern):
            return False
        if rule.agent_identity is not None and rule.agent_identity != request.agent_identity:
            return False
        if rule.agent_role is not None and rule.agent_role != request.agent_role:
            return False
        context: Mapping[str, str] = dict(request.context)
        return all(context.get(key) == expected for key, expected in rule.required_context)

    @staticmethod
    def _validate_policy(policy: AuthorityPolicy) -> None:
        if not isinstance(policy, AuthorityPolicy):
            raise PolicyValidationError("policy must be an AuthorityPolicy")
        for rule in policy.rules:
            if rule.effect not in {Decision.ALLOW, Decision.DENY}:
                raise PolicyValidationError(f"invalid effect for rule {rule.rule_id}")
