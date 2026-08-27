from __future__ import annotations

import unittest
from phase4.pipeline.e2e_runner import E2EPipelineRunner, ContextPacket
from phase4.council.orchestrator import CouncilOrchestrator
from phase4.epistemics.models import Hypothesis, HypothesisStatus

class MockCouncilOrchestrator:
    def run_deliberation(self, task_id: str, task_description: str):
        class MockRes:
            status = "DECISION_READY"
            top_hypothesis = Hypothesis(
                hypothesis_id="hyp-1",
                task_id=task_id,
                statement="Refactor legacy module",
                confidence=0.85,
                status=HypothesisStatus.SUPPORTED
            )
        return MockRes()

class MockAuthorityGate:
    def evaluate(self, organization_id: str, hypothesis, confidence: float):
        return {"approved": confidence >= 0.8}

class MockVerifier:
    def verify(self, branch_name: str) -> bool:
        return "fail" not in branch_name

class MockGitAdapter:
    def apply_patch(self, branch_name: str, patch: str) -> bool:
        return True

    def create_draft_pr(self, branch_name: str, title: str, body: str) -> str:
        return f"https://github.com/org/repo/pull/123-draft"

class TestE2EPipelineRunner(unittest.TestCase):
    def setUp(self):
        self.council = MockCouncilOrchestrator()
        self.authority = MockAuthorityGate()
        self.verifier = MockVerifier()
        self.git = MockGitAdapter()
        self.runner = E2EPipelineRunner(self.council, self.authority, self.verifier, self.git)

    def test_successful_pipeline_to_draft_pr(self):
        packet = ContextPacket(
            organization_id="org-1",
            task_id="task-001",
            correlation_id="corr-001",
            revision_binding="git-rev-abc",
            idempotency_key="idemp-001",
            payload={"description": "Refactor legacy payment module", "patch": "print('fixed')"}
        )

        result = self.runner.execute(packet)
        self.assertEqual(result.status, "SUCCESS")
        self.assertIsNotNone(result.draft_pr_url)
        self.assertIn("pull/123-draft", result.draft_pr_url)

    def test_idempotency(self):
        packet = ContextPacket(
            organization_id="org-1",
            task_id="task-001",
            correlation_id="corr-001",
            revision_binding="git-rev-abc",
            idempotency_key="idemp-002",
            payload={"description": "Refactor", "patch": "patch"}
        )

        res1 = self.runner.execute(packet)
        res2 = self.runner.execute(packet)
        self.assertEqual(res1.status, res2.status)
        self.assertTrue(any("Idempotency cache hit" in log for log in res2.audit_trail))

    def test_verification_failure(self):
        # Branch containing 'fail' will fail verification in MockVerifier
        packet = ContextPacket(
            organization_id="org-1",
            task_id="task-fail",
            correlation_id="corr-003",
            revision_binding="git-rev-abc",
            idempotency_key="idemp-003",
            payload={"description": "Bad refactor", "patch": "bad"}
        )
        # Mock git adapter to return branch with 'fail'
        original_apply = self.git.apply_patch
        self.runner.git_adapter.apply_patch = lambda b, p: True
        
        # Override branch generation or verifier to fail
        self.runner.verifier.verify = lambda b: False

        result = self.runner.execute(packet)
        self.assertEqual(result.status, "VERIFICATION_FAILED")
        self.assertTrue(any("verification failed" in log.lower() for log in result.audit_trail))

if __name__ == "__main__":
    unittest.main()
