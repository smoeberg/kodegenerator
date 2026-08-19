"""Fail-closed, deterministic AI-3 Authority Engine."""
from __future__ import annotations

from datetime import datetime, timezone
from fnmatch import fnmatchcase
from typing import List, Mapping, Tuple

from .audit import AuthorityAuditSink, _as_sink
from .grants import VerifiedAuthorityGrant, _attach_decision_provenance
from .models import AuthorityDecision, AuthorityPolicy, AuthorityRequest, AuthorityRule, Decision


class AuthorityError(Exception):
    """Base class for authority engine errors."""


class PolicyValidationError(AuthorityError):
    """Raised when a policy is malformed or ambiguous."""


class AuthorityEngine:
    """Evaluate explicit authority policies without executing any action."""

    def __init__(self, policy: AuthorityPolicy, *, audit_sink: AuthorityAuditSink | None = None) -> None:
        self._validate_policy(policy)
        self._policy = policy
        self._audit: List[AuthorityDecision] = []
        self._audit_sink = _as_sink(audit_sink)

    @property
    def policy(self) -> AuthorityPolicy:
        return self._policy

    def evaluate(self, request: AuthorityRequest) -> AuthorityDecision:
        if not isinstance(request, AuthorityRequest):
            raise TypeError("request must be an AuthorityRequest")
        matched: List[AuthorityRule] = [rule for rule in self._policy.rules if self._matches(rule, request)]
        matched.sort(key=lambda rule: (-rule.priority, rule.rule_id))
        denies = [rule for rule in matched if rule.effect is Decision.DENY]
        allows = [rule for rule in matched if rule.effect is Decision.ALLOW]
        if denies:
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

    def issue_grant(self, request: AuthorityRequest) -> VerifiedAuthorityGrant:
        decision = self.evaluate(request)
        if decision.decision is not Decision.ALLOW:
            raise AuthorityError("cannot issue execution grant for denied authority")
        return VerifiedAuthorityGrant.from_decision(decision)

    def audit_trail(self) -> Tuple[AuthorityDecision, ...]:
        return tuple(self._audit)

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
