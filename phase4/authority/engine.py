"""Fail-closed, deterministic AI-3 Authority Engine."""
from __future__ import annotations

from datetime import datetime, timezone
from fnmatch import fnmatchcase
from typing import List, Mapping, Tuple

from .audit import AuthorityAuditSink, _as_sink
from .grants import VerifiedAuthorityGrant, _attach_decision_provenance
from .models import AuthorityDecision, AuthorityPolicy, AuthorityRequest, AuthorityRule, Decision
from .grants import VerifiedAuthorityGrant


class AuthorityError(Exception):
    """Base class for authority engine errors."""


class PolicyValidationError(AuthorityError):
    """Raised when a policy is malformed or ambiguous."""


class AuthorityEngine:
    """Evaluate explicit authority policies without executing any action.

    Security contract:
    - declared capabilities are not authority;
    - no matching rule means DENY;
    - any matching DENY wins over ALLOW;
    - the engine never executes commands or mutates agent identity/context;
    - every evaluation produces an immutable decision suitable for audit;
<<<<<<< HEAD
    - only decisions issued here carry provenance that can become an execution grant;
    - optional ``AuthorityAuditSink`` observes decisions without granting power.
=======
    - only decisions issued here carry provenance that can become an execution grant.
>>>>>>> origin/agent/phase7-production-runtime
    """

    def __init__(
        self,
        policy: AuthorityPolicy,
        *,
        audit_sink: AuthorityAuditSink | None = None,
    ) -> None:
        self._validate_policy(policy)
        self._policy = policy
        self._audit: List[AuthorityDecision] = []
        self._audit_sink = _as_sink(audit_sink)

    @property
    def policy(self) -> AuthorityPolicy:
        return self._policy

    def evaluate(self, request: AuthorityRequest) -> AuthorityDecision:
        """Evaluate one request. The engine always returns ALLOW or DENY."""
        matched: List[AuthorityRule] = [
            rule for rule in self._policy.rules if self._matches(rule, request)
        ]
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

        evaluated_at = datetime.now(timezone.utc).isoformat()
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
            evaluated_at=evaluated_at,
            parameters=request.parameters,
            organization_id=request.organization_id,
            actor_id=request.actor_id,
            capability=request.capability,
        )
<<<<<<< HEAD
        # AI-4 validates this tamper-evident provenance before any dispatch.
        _attach_decision_provenance(result)
=======
        # The token is an object-identity capability owned by this authority
        # engine. It is intentionally not representable in AuthorityDecision's
        # public constructor and cannot be recreated from copied fields.
        object.__setattr__(result, "_provenance_token", object())
>>>>>>> origin/agent/phase7-production-runtime
        self._audit.append(result)
        self._audit_sink.record(result)
        return result

    def issue_grant(self, request: AuthorityRequest) -> VerifiedAuthorityGrant:
        """Evaluate and issue a verified execution grant for an ALLOW decision."""
        decision = self.evaluate(request)
        if decision.decision is not Decision.ALLOW:
            raise AuthorityError("cannot issue execution grant for denied authority")
        return VerifiedAuthorityGrant.from_decision(decision)

    def audit_trail(self) -> Tuple[AuthorityDecision, ...]:
        """Return an immutable snapshot of all authority decisions."""
        return tuple(self._audit)

    @staticmethod
    def _matches(rule: AuthorityRule, request: AuthorityRequest) -> bool:
        if rule.action != request.action:
            return False
        if not fnmatchcase(request.resource, rule.resource_pattern):
            return False
        if rule.agent_identity is not None and rule.agent_identity != request.agent_identity:
            return False
        if rule.agent_role is not None and rule.agent_role != request.agent_role:
            return False

        context: Mapping[str, str] = dict(request.context)
        for key, expected in rule.required_context:
            if context.get(key) != expected:
                return False
        return True

    @staticmethod
    def _validate_policy(policy: AuthorityPolicy) -> None:
        if not isinstance(policy, AuthorityPolicy):
            raise PolicyValidationError("policy must be an AuthorityPolicy")
        for rule in policy.rules:
            if rule.effect not in {Decision.ALLOW, Decision.DENY}:
                raise PolicyValidationError(f"invalid effect for rule {rule.rule_id}")
