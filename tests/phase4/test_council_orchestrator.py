"""Unit tests for CouncilOrchestrator and Council Roles."""
import unittest
from phase4.council.orchestrator import CouncilOrchestrator, DeliberationConfig
from phase4.council.session import Dispute, SessionState
from phase4.council.roles import CouncilRole, ROLE_PERSONAS
from phase4.epistemics.models import Hypothesis


class TestCouncilOrchestrator(unittest.TestCase):

    def test_roles_and_personas(self):
        self.assertIn(CouncilRole.SECURITY_SKEPTIC, ROLE_PERSONAS)
        self.assertTrue(ROLE_PERSONAS[CouncilRole.SECURITY_SKEPTIC].must_find_issues)

    def test_orchestrator_successful_deliberation(self):
        orchestrator = CouncilOrchestrator(
            organization_id="org-acme",
            project_id="proj-legacy"
        )
        hyp = Hypothesis(
            hypothesis_id="hyp-1",
            task_id="task-001",
            agent_id="proposer-1",
            statement="Use Strangler Fig pattern for legacy modernization.",
            confidence=0.75
        )
        disputes = [
            Dispute(
                dispute_id="dsp-1",
                session_id="ses-1",
                hypothesis_id="hyp-1",
                challenger_role="security_skeptic",
                argument="Unauthenticated endpoint risk on legacy adapter route.",
                severity="high"
            )
        ]
        result = orchestrator.run_deliberation(
            session_id="ses-1",
            task_id="task-001",
            hypothesis=hyp,
            initial_disputes=disputes
        )
        self.assertEqual(result.organization_id, "org-acme")
        self.assertEqual(result.project_id, "proj-legacy")
        self.assertTrue(result.final_state in [SessionState.DECISION_READY, SessionState.IN_DISPUTE])

    def test_orchestrator_anti_tube_trigger(self):
        orchestrator = CouncilOrchestrator(
            organization_id="org-acme",
            project_id="proj-legacy"
        )
        hyp = Hypothesis(
            hypothesis_id="hyp-2",
            task_id="task-002",
            agent_id="proposer-1",
            statement="Retry same failed SQL migration.",
            confidence=0.4
        )
        previous_failures = [
            {"attempt": 1, "error": "SQL Syntax Error"},
            {"attempt": 2, "error": "SQL Syntax Error"}
        ]
        result = orchestrator.run_deliberation(
            session_id="ses-2",
            task_id="task-002",
            hypothesis=hyp,
            previous_failures=previous_failures
        )
        self.assertTrue(result.pivot_requested)
        self.assertEqual(result.final_state, SessionState.DEADLOCKED)


if __name__ == "__main__":
    unittest.main()
