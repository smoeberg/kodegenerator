# runtime/policy_engine.py
from typing import Dict, List, Optional
from domain.policy import Policy
from domain.artifact import Artifact
from domain.workflow import Workflow
from domain.actor import Actor

class PolicyEngine:
    """Håndhæver Policies for Workflows og Artifacts."""

    def __init__(self, policies: List[Policy]):
        self.policies = policies

    def check_compliance(self, target: str, action: str, **kwargs) -> bool:
        """Tjek om en handling overholder alle relevante Policies."""
        for policy in self.policies:
            if not self._check_policy(policy, target, action, **kwargs):
                return False
        return True

    def _check_policy(
        self,
        policy: Policy,
        target: str,
        action: str,
        **kwargs
    ) -> bool:
        """Tjek en enkelt Policy."""
        if not policy.applies_to(target):
            return True  # Policy gælder ikke for dette mål

        # Tjek betingelserne
        for key, value in policy.conditions.items():
            if key == "min_coverage" and kwargs.get("test_coverage", 0.0) < value:
                return False
            elif key == "required_approvals":
                artifact = kwargs.get("artifact")
                if artifact:
                    for required_approval in value:
                        if not any(
                            getattr(sig, "role_id", getattr(sig, "role_id", None)) == required_approval and getattr(sig, "status", getattr(sig, "status", None)) == "approved"
                            for sig in artifact.signatures
                        ):
                            return False
            elif key == "min_consensus_score":
                artifact = kwargs.get("artifact")
                if artifact and artifact.get_consensus_score() < value:
                    return False

        return True

    def get_violations(self, target: str, action: str, **kwargs) -> List[Policy]:
        """Hent liste af Policies, der brydes af en handling."""
        violations = []
        for policy in self.policies:
            if policy.applies_to(target) and not self._check_policy(policy, target, action, **kwargs):
                violations.append(policy)
        return violations
