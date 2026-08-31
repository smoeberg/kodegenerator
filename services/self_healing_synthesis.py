"""Sprint 3 — Self-Healing Synthesis Loop.

Binds the governed diagnostic and synthesis components into one loop:

    verify -> diagnose -> feedback -> synthesize -> re-verify

When a verification command (pytest/ruff) fails, the traceback is analyzed
by ``DiagnosticLoop``, the targeted feedback (stacktrace + AST context) is
sent to the synthesis renderer (the LLM boundary, or a deterministic mock in
tests), and ``CodePatchSynthesizer`` validates the new patch through AST
guardrails and an isolated sandbox. The patched source is then written to
disk and the verification command is re-run. The loop converges only when
the verification passes — either directly (nothing to heal) or with an
approved patch — and fails closed after ``max_attempts`` iterations (default
3, per the plan) or when the error repeats (circular detection).

The module never executes untrusted commands itself: verification runs
through fixed allow-listed adapters and the synthesizer owns the sandbox
boundary. Evidence deliberately does not carry raw output; failed output
(traceback text) is returned side-channel by the verifier so ``DiagnosticLoop``
can parse it without weakening the Evidence contract.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

from domain.task import Task
from domain.verification import Evidence
from phase4.authority.grants import VerifiedAuthorityGrant
from services.code_patch_synthesizer import (
    ArchitectureSpec,
    CodePatchSynthesizer,
    PatchSynthesisResult,
)
from services.diagnostic_loop import DiagnosticLoop, DiagnosticResult
from services.verification_execution import ExecutionBinding


class VerificationRunner(Protocol):
    """Runs one fixed command and returns evidence plus failure output.

    The output channel carries the raw traceback/AST context that
    ``DiagnosticLoop`` needs; it is deliberately kept out of ``Evidence``
    (whose statement is a short deterministic identity).
    """

    def run(
        self, binding: ExecutionBinding, *, cwd: str | Path
    ) -> tuple[Evidence, str]: ...


# Renderer receives the latest diagnostic feedback so the LLM/mock boundary
# can produce a targeted patch. Returns python source for the module.
FeedbackRenderer = Callable[[Task, ArchitectureSpec, str], str]


@dataclass
class SelfHealingAttempt:
    """One iteration of the self-healing loop."""

    attempt: int
    evidence: Evidence | None = None
    diagnostic: DiagnosticResult | None = None
    feedback: str = ""
    patch: PatchSynthesisResult | None = None
    converged: bool = False


@dataclass
class SelfHealingOutcome:
    """The terminal state of a self-healing run."""

    task_id: str
    module_name: str
    converged: bool
    attempts: tuple[SelfHealingAttempt, ...]
    final_patch: PatchSynthesisResult | None = None
    reason: str = ""

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)


@dataclass
class SelfHealingSynthesisLoop:
    """Run verify → diagnose → feedback → synthesize → re-verify."""

    synthesizer: CodePatchSynthesizer
    diagnostic_loop: DiagnosticLoop = field(default_factory=DiagnosticLoop)
    verifier: VerificationRunner | None = None
    renderer: FeedbackRenderer | None = None
    max_attempts: int = 3
    error_ticker: object | None = None

    def __post_init__(self) -> None:
        if self.max_attempts < 1 or self.max_attempts > 5:
            raise ValueError("max_attempts must be between 1 and 5")

    def run(
        self,
        *,
        task: Task,
        architecture: ArchitectureSpec,
        grant: VerifiedAuthorityGrant,
        binding: ExecutionBinding,
        cwd: str | Path,
        organization_id: str | None = None,
        principal_id: str = "self-healing",
        actor_id: str = "self-healing-loop",
    ) -> SelfHealingOutcome:
        """Run the loop until verification passes with an approved patch."""
        root = Path(cwd)
        module_path = root / f"{architecture.module_name}.py"
        previous_errors: list[str] = []
        attempts: list[SelfHealingAttempt] = []
        verifier = self.verifier or _default_verifier(self.synthesizer)

        for attempt in range(1, self.max_attempts + 1):
            # 1) verify the current state
            evidence, output = verifier.run(binding, cwd=cwd)
            if evidence.passed:
                attempts.append(
                    SelfHealingAttempt(
                        attempt=attempt, evidence=evidence, converged=True
                    )
                )
                return SelfHealingOutcome(
                    task_id=str(task.id),
                    module_name=architecture.module_name,
                    converged=True,
                    attempts=tuple(attempts),
                    reason="verification passed",
                )
            failure_text = output or evidence.statement

            # 2) diagnose the failure
            diagnostic = self.diagnostic_loop.analyze_traceback(failure_text)
            feedback = self.diagnostic_loop.generate_targeted_feedback(diagnostic)

            # 3) fail closed on circular errors
            should_retry, reason = self.diagnostic_loop.should_retry(
                attempt=attempt,
                previous_errors=previous_errors,
                current_error=failure_text,
            )
            previous_errors.append(failure_text)
            if not should_retry:
                attempts.append(
                    SelfHealingAttempt(
                        attempt=attempt,
                        evidence=evidence,
                        diagnostic=diagnostic,
                        feedback=feedback,
                        converged=False,
                    )
                )
                return SelfHealingOutcome(
                    task_id=str(task.id),
                    module_name=architecture.module_name,
                    converged=False,
                    attempts=tuple(attempts),
                    reason=reason or "self-healing exhausted",
                )

            # 4) synthesize a targeted patch (LLM/mock boundary)
            if self.renderer is not None:
                source = self.renderer(task, architecture, feedback)
                synthesizer = _with_source(self.synthesizer, source)
            else:
                synthesizer = self.synthesizer
            patch = synthesizer.synthesize(
                task,
                architecture,
                grant,
                organization_id=organization_id,
                principal_id=principal_id,
                actor_id=actor_id,
            )
            if not patch.approved:
                attempts.append(
                    SelfHealingAttempt(
                        attempt=attempt,
                        evidence=evidence,
                        diagnostic=diagnostic,
                        feedback=feedback,
                        patch=patch,
                        converged=False,
                    )
                )
                continue

            # 5) write the approved patch and re-verify it
            module_path.write_text(patch.source_code, encoding="utf-8")
            re_evidence, _re_output = verifier.run(binding, cwd=cwd)
            healed = re_evidence.passed
            attempts.append(
                SelfHealingAttempt(
                    attempt=attempt,
                    evidence=re_evidence,
                    diagnostic=diagnostic,
                    feedback=feedback,
                    patch=patch,
                    converged=healed,
                )
            )
            if healed:
                return SelfHealingOutcome(
                    task_id=str(task.id),
                    module_name=architecture.module_name,
                    converged=True,
                    attempts=tuple(attempts),
                    final_patch=patch,
                    reason=(
                        f"patch approved and verification passed on attempt {attempt}"
                    ),
                )

        if self.error_ticker is not None:
            ticker_note = self._report_exhaustion(task, architecture, attempts)
        else:
            ticker_note = ""

        return SelfHealingOutcome(
            task_id=str(task.id),
            module_name=architecture.module_name,
            converged=False,
            attempts=tuple(attempts),
            reason=f"max_attempts ({self.max_attempts}) reached without convergence"
            + (f"; {ticker_note}" if ticker_note else ""),
        )

    def _report_exhaustion(
        self,
        task: Task,
        architecture: ArchitectureSpec,
        attempts: tuple[SelfHealingAttempt, ...],
    ) -> str:
        """Best-effort Redmine ticket for an exhausted self-healing loop."""
        if self.error_ticker is None:
            return ""
        last = attempts[-1] if attempts else None
        error_text = ""
        if last is not None and last.evidence is not None:
            error_text = str(last.evidence.statement or "")
        if not error_text and last is not None and last.diagnostic is not None:
            error_text = str(last.diagnostic.message or last.diagnostic.details or "")
        if not error_text:
            error_text = "self-healing exhausted without diagnostic detail"
        context = {
            "task_id": task.id,
            "attempts": len(attempts),
            "max_attempts": self.max_attempts,
            "reason": "max_attempts reached without convergence",
        }
        try:
            result = self.error_ticker.report_self_healing_exhaustion(
                module=architecture.module_name,
                error=error_text,
                attempts=len(attempts),
                context=context,
            )
        except Exception as exc:  # noqa: BLE001 - pragma: no cover - defensive only
            return f"redmine-ticketing-error: {exc}"
        if result.ok:
            return f"redmine-issue-{result.issue.id}"
        return f"redmine-{result.error}"

    @classmethod
    def with_redmine_from_env(
        cls, env: dict[str, str] | None = None, **overrides: Any
    ) -> SelfHealingSynthesisLoop:
        """Build a loop wired to Redmine from ``REDMINE_*`` variables.

        Falls back to a plain loop (ticketing disabled) when no URL is
        configured, keeping tests and development green.
        """
        from services.redmine_contracts import redmine_config_from_env

        config = redmine_config_from_env(env)
        if config is None:
            return cls(**overrides)
        from services.redmine_api import RedmineAPIClient
        from services.redmine_error_ticketing import RedmineErrorTickerService

        return cls(
            error_ticker=RedmineErrorTickerService(
                RedmineAPIClient(config),
                use_deduplication=True,
                default_severity=config.default_severity,
            ),
            **overrides,
        )


def _with_source(
    synthesizer: CodePatchSynthesizer, source: str
) -> CodePatchSynthesizer:
    """Return a synthesizer whose renderer yields the given source."""
    return replace(synthesizer, renderer=SourcePinnedRenderer(source))


class SourcePinnedRenderer:
    """Callable renderer pinned to one immutable source string."""

    def __init__(self, source: str) -> None:
        self._source = source

    def __call__(self, task: Task, architecture: ArchitectureSpec) -> str:
        return self._source


def _default_verifier(synthesizer: CodePatchSynthesizer) -> VerificationRunner:
    """Default verifier: compile the patched module through the sandbox."""

    from domain.verification import Evidence
    from phase6.execution.sandbox import (
        ExecutionOutcome,
        ExecutionSecurityContext,
        ExecutionSpec,
    )

    class _SandboxVerifier:
        def run(
            self, binding: ExecutionBinding, *, cwd: str | Path
        ) -> tuple[Evidence, str]:
            root = Path(cwd)
            module = root / f"{binding.package_fingerprint or 'module'}.py"
            spec = ExecutionSpec(
                execution_id="self-heal-" + binding.package_fingerprint[:8],
                adapter_id=synthesizer.sandbox.adapter_id,
                argv=(synthesizer.python_executable, "-m", "py_compile", str(module)),
                security=ExecutionSecurityContext(
                    organization_id=binding.package_fingerprint or "org:unknown",
                    principal_id="self-healing",
                    actor_id="self-healing-loop",
                    capabilities=("code.patch.verify",),
                ),
                limits=synthesizer.limits,
                network_allowlist=(),
                environment=(("PYTHONDONTWRITEBYTECODE", "1"),),
            )
            result = synthesizer.sandbox.execute(spec)
            passed = result.outcome is ExecutionOutcome.SUCCEEDED
            error_text = (
                "sandbox verification succeeded"
                if passed
                else (result.error or "sandbox verification failed")
            )
            return (
                Evidence(
                    kind="test",
                    evidence_id="self-heal-evidence",
                    passed=passed,
                    statement=error_text,
                    package_fingerprint=binding.package_fingerprint,
                    contract_fingerprint=binding.contract_fingerprint,
                    dispatch_fingerprint=binding.dispatch_fingerprint,
                    artifact_fingerprint=binding.artifact_fingerprint,
                ),
                "" if passed else error_text,
            )

    return _SandboxVerifier()
