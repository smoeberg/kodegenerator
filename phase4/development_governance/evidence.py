"""Deterministic source-of-truth evidence checks for Governance v0."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol

from .contracts import ArtifactSubmission, AuditDecision, EvidenceReport, SolutionProposal


class EvidenceCollectionError(RuntimeError):
    """Repository evidence could not be collected reliably."""


class SupplementalEvidenceSource(Protocol):
    """Adapter for CI/test/migration observations collected outside local Git."""

    def test_results(self, artifact_version: str) -> tuple[str, ...]: ...

    def ci_results(self, artifact_version: str) -> tuple[str, ...]: ...

    def migration_results(self, artifact_version: str) -> tuple[str, ...]: ...


class GitRepositoryEvidenceVerifier:
    """Verify immutable Git identity/lineage/diff plus optional observed CI facts.

    This verifier never decides whether a design is desirable and never claims
    that a test proves its named invariant. Those semantic checks belong to the
    Auditor provider.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        supplemental: SupplementalEvidenceSource | None = None,
    ) -> None:
        self.root = Path(root)
        self.supplemental = supplemental

    def verify(
        self, submission: ArtifactSubmission, solution: SolutionProposal
    ) -> EvidenceReport:
        del solution  # contract conformance is the Auditor's concern
        mismatches: list[str] = []
        verified: list[str] = []
        try:
            self._run("git", "rev-parse", "--is-inside-work-tree")
            artifact = self._run("git", "rev-parse", f"{submission.artifact_version}^{{commit}}")
            base = self._run("git", "rev-parse", f"{submission.base_version}^{{commit}}")
            if artifact != submission.artifact_version:
                mismatches.append(
                    f"artifact_version resolves to {artifact}, expected {submission.artifact_version}"
                )
            else:
                verified.append(f"artifact={artifact}")
            if base != submission.base_version:
                mismatches.append(f"base_version resolves to {base}, expected {submission.base_version}")
            else:
                verified.append(f"base={base}")
            ancestor = subprocess.run(
                ["git", "merge-base", "--is-ancestor", base, artifact],
                cwd=self.root,
                capture_output=True,
                text=True,
                check=False,
            )
            if ancestor.returncode != 0:
                mismatches.append("base is not an ancestor of artifact")
            else:
                verified.append("base-is-ancestor")
            actual_files = tuple(
                line
                for line in self._run(
                    "git", "diff", "--name-only", f"{base}...{artifact}"
                ).splitlines()
                if line
            )
            if tuple(sorted(actual_files)) != tuple(sorted(submission.changed_files)):
                mismatches.append(
                    f"changed_files mismatch: actual={sorted(actual_files)!r} claimed={sorted(submission.changed_files)!r}"
                )
            else:
                verified.append("changed-files-exact")

            if self.supplemental is not None:
                self._compare_claims(
                    "tests",
                    submission.test_claims,
                    self.supplemental.test_results(artifact),
                    verified,
                    mismatches,
                )
                self._compare_claims(
                    "ci",
                    submission.ci_claims,
                    self.supplemental.ci_results(artifact),
                    verified,
                    mismatches,
                )
                self._compare_claims(
                    "migrations",
                    submission.migration_claims,
                    self.supplemental.migration_results(artifact),
                    verified,
                    mismatches,
                )
        except EvidenceCollectionError as exc:
            mismatches.append(str(exc))

        if mismatches:
            return EvidenceReport(
                decision=AuditDecision.VETO,
                facts_verified=tuple(verified),
                mismatches=tuple(mismatches),
            )
        return EvidenceReport(
            decision=AuditDecision.VERIFIED,
            facts_verified=tuple(verified),
            proof_construction_verified=False,
            solution_conformance_verified=False,
        )

    def _run(self, *command: str) -> str:
        result = subprocess.run(
            list(command),
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
            raise EvidenceCollectionError(f"{' '.join(command)} failed: {detail}")
        return result.stdout.strip()

    @staticmethod
    def _compare_claims(
        label: str,
        claimed: tuple[str, ...],
        observed: tuple[str, ...],
        verified: list[str],
        mismatches: list[str],
    ) -> None:
        if tuple(sorted(claimed)) != tuple(sorted(observed)):
            mismatches.append(
                f"{label} claims mismatch: observed={sorted(observed)!r} claimed={sorted(claimed)!r}"
            )
        else:
            verified.append(f"{label}-claims-exact")


__all__ = [
    "EvidenceCollectionError",
    "GitRepositoryEvidenceVerifier",
    "SupplementalEvidenceSource",
]
