"""Sprint 3 — Self-Healing Synthesis Loop convergence and fail-closed proofs."""

from __future__ import annotations

from pathlib import Path

from domain.task import Task
from phase4.authority import AuthorityEngine, AuthorityPolicy, AuthorityRule, Decision
from phase4.authority.grants import VerifiedAuthorityGrant
from phase4.authority.models import AuthorityRequest
from services.code_patch_synthesizer import (
    SYNTHESIZE_ACTION,
    ArchitectureSpec,
    CodePatchSynthesizer,
    InProcessSandbox,
)
from services.self_healing_synthesis import SelfHealingSynthesisLoop
from services.verification_execution import ExecutionBinding


def _create_grant(resource: str) -> VerifiedAuthorityGrant:
    engine = AuthorityEngine(
        AuthorityPolicy(
            policy_id="policy-test",
            version="1",
            rules=(
                AuthorityRule(
                    rule_id="allow-all",
                    action=SYNTHESIZE_ACTION,
                    resource_pattern="*",
                    effect=Decision.ALLOW,
                    agent_identity="test-bot",
                ),
            ),
        )
    )
    request = AuthorityRequest(
        request_id="req-test-1",
        agent_identity="test-bot",
        action=SYNTHESIZE_ACTION,
        resource=resource,
        context_packet_id="ctx-1",
        requested_at="2026-08-30T00:00:00+00:00",
        parameters=(("task_id", "T-01"),),
        organization_id="org-test",
    )
    decision = engine.evaluate(request)
    return VerifiedAuthorityGrant.from_decision(decision)


def _binding() -> ExecutionBinding:
    return ExecutionBinding(
        package_fingerprint="pkg-payment",
        contract_fingerprint="ctr-payment",
        dispatch_fingerprint="disp-1",
        artifact_fingerprint="art-1",
    )


class _FailingThenFixingVerifier:
    """Fail on the first run, pass once the patched source is on disk."""

    def __init__(self, module_path: Path, good_source: str) -> None:
        self._module_path = module_path
        self._good_source = good_source
        self.calls = 0

    def run(self, binding, *, cwd=None):
        from domain.verification import Evidence

        self.calls += 1
        current = (
            self._module_path.read_text(encoding="utf-8")
            if self._module_path.exists()
            else ""
        )
        passed = current.strip() == self._good_source.strip()
        traceback = (
            ""
            if passed
            else (
                "Traceback (most recent call last):\n"
                '  File "auth/service.py", line 5, in process_payment\n'
                "    assert amount > 0\n"
                "AssertionError: assert -5 > 0\n"
            )
        )
        return (
            Evidence(
                kind="test",
                evidence_id=f"evidence-{self.calls}",
                passed=passed,
                statement=(
                    "verification passed" if passed else "AssertionError: assert -5 > 0"
                ),
                package_fingerprint=binding.package_fingerprint,
                contract_fingerprint=binding.contract_fingerprint,
                dispatch_fingerprint=binding.dispatch_fingerprint,
                artifact_fingerprint=binding.artifact_fingerprint,
            ),
            traceback,
        )


def test_self_healing_loop_converges_with_targeted_feedback(tmp_path: Path) -> None:
    """Fail -> diagnose -> feedback -> synthesize -> write -> re-verify -> pass."""
    broken = "def run():\n    assert False\n    return {'status': 'ok'}\n"
    good = "def run():\n    return {'status': 'ok'}\n"
    module_path = tmp_path / "payment_service.py"
    module_path.write_text(broken, encoding="utf-8")

    verifier = _FailingThenFixingVerifier(module_path, good)
    feedback_seen: list[str] = []

    loop = SelfHealingSynthesisLoop(
        synthesizer=CodePatchSynthesizer(
            sandbox=InProcessSandbox(),
            renderer=lambda task, arch: good,
        ),
        verifier=verifier,
        renderer=lambda task, arch, feedback: (
            feedback_seen.append(feedback)
            or "def run():\n    return {'status': 'ok'}\n"
        ),
        max_attempts=3,
    )

    outcome = loop.run(
        task=Task(id="T-PAY-01", name="Fix payment amount check", status="pending"),
        architecture=ArchitectureSpec(
            contract_id="PAY-01", version="1.0.0", module_name="payment_service"
        ),
        grant=_create_grant("payment_service"),
        binding=_binding(),
        cwd=tmp_path,
    )

    assert outcome.converged is True
    assert outcome.attempt_count == 1
    assert outcome.final_patch is not None and outcome.final_patch.approved
    assert "verification passed" in outcome.reason
    # The patched source is on disk and passes the verifier.
    assert module_path.read_text(encoding="utf-8").strip() == good.strip()
    # The renderer saw the targeted diagnostic feedback.
    assert any("AssertionError" in fb for fb in feedback_seen)
    assert verifier.calls == 2  # one failing run, one passing re-verification


def test_self_healing_loop_fails_closed_on_circular_error(tmp_path: Path) -> None:
    """A repeating identical error must stop the loop instead of looping forever."""

    class _AlwaysFailsSameError:
        def __init__(self) -> None:
            self.calls = 0

        def run(self, binding, *, cwd=None):
            from domain.verification import Evidence

            self.calls += 1
            error = (
                "Traceback (most recent call last):\n"
                '  File "auth/service.py", line 3, in authenticate\n'
                "    raise PermissionDeniedError('denied')\n"
                "PermissionDeniedError: denied\n"
            )
            return (
                Evidence(
                    kind="test",
                    evidence_id=f"evidence-{self.calls}",
                    passed=False,
                    statement="PermissionDeniedError: denied",
                    package_fingerprint=binding.package_fingerprint,
                    contract_fingerprint=binding.contract_fingerprint,
                    dispatch_fingerprint=binding.dispatch_fingerprint,
                    artifact_fingerprint=binding.artifact_fingerprint,
                ),
                error,
            )

    verifier = _AlwaysFailsSameError()
    loop = SelfHealingSynthesisLoop(
        synthesizer=CodePatchSynthesizer(
            sandbox=InProcessSandbox(),
            renderer=lambda task, arch: "def run():\n    return {'status': 'ok'}\n",
        ),
        verifier=verifier,
        renderer=lambda task, arch, feedback: (
            "def run():\n    return {'status': 'ok'}\n"
        ),
        max_attempts=4,
    )

    outcome = loop.run(
        task=Task(id="T-AUTH-01", name="Fix auth", status="pending"),
        architecture=ArchitectureSpec(
            contract_id="AUTH-01", version="1.0.0", module_name="auth_service"
        ),
        grant=_create_grant("auth_service"),
        binding=_binding(),
        cwd=tmp_path,
    )

    assert outcome.converged is False
    # The diagnostic loop detects the repeated error and stops before 4.
    assert outcome.attempt_count <= 3
    assert "repeated" in outcome.reason or "Circular" in outcome.reason


def test_self_healing_loop_passes_without_patch_when_already_green(
    tmp_path: Path,
) -> None:
    """A module that already passes verification leaves immediately."""

    class _PassingVerifier:
        calls = 0

        def run(self, binding, *, cwd=None):
            from domain.verification import Evidence

            self.calls += 1
            return (
                Evidence(
                    kind="test",
                    evidence_id="evidence-1",
                    passed=True,
                    statement="verification passed",
                    package_fingerprint=binding.package_fingerprint,
                    contract_fingerprint=binding.contract_fingerprint,
                    dispatch_fingerprint=binding.dispatch_fingerprint,
                    artifact_fingerprint=binding.artifact_fingerprint,
                ),
                "",
            )

    verifier = _PassingVerifier()
    loop = SelfHealingSynthesisLoop(
        synthesizer=CodePatchSynthesizer(
            sandbox=InProcessSandbox(),
            renderer=lambda task, arch: "def run():\n    return {'status': 'ok'}\n",
        ),
        verifier=verifier,
        max_attempts=3,
    )

    outcome = loop.run(
        task=Task(id="T-OK-01", name="Already fine", status="pending"),
        architecture=ArchitectureSpec(
            contract_id="OK-01", version="1.0.0", module_name="fine_service"
        ),
        grant=_create_grant("fine_service"),
        binding=_binding(),
        cwd=tmp_path,
    )

    assert outcome.converged is True
    assert outcome.attempt_count == 1
    assert outcome.reason == "verification passed"
    assert verifier.calls == 1
