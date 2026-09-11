from __future__ import annotations

import subprocess
from pathlib import Path

from phase4.development_governance.contracts import (
    ArtifactSubmission,
    AuditDecision,
    ScopeConformance,
    SolutionProposal,
)
from phase4.development_governance.evidence import GitRepositoryEvidenceVerifier


def run(root: Path, *args: str) -> str:
    result = subprocess.run(args, cwd=root, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def repo(tmp_path: Path) -> tuple[Path, str, str]:
    root = tmp_path / "repo"
    root.mkdir()
    run(root, "git", "init")
    run(root, "git", "config", "user.email", "governance@example.test")
    run(root, "git", "config", "user.name", "Governance Test")
    (root / "base.txt").write_text("base\n", encoding="utf-8")
    run(root, "git", "add", "base.txt")
    run(root, "git", "commit", "-m", "base")
    base = run(root, "git", "rev-parse", "HEAD")
    (root / "change.txt").write_text("candidate\n", encoding="utf-8")
    run(root, "git", "add", "change.txt")
    run(root, "git", "commit", "-m", "candidate")
    artifact = run(root, "git", "rev-parse", "HEAD")
    return root, base, artifact


def solution() -> SolutionProposal:
    return SolutionProposal(
        solution_id="s",
        version=1,
        problem_id="p",
        problem_approval_fingerprint="a" * 64,
        proposed_design="change one file",
        why_this_is_minimal="one file",
        scope_conformance=ScopeConformance.WITHIN_APPROVED_SCOPE,
        approved_scope=("one file",),
        explicit_non_goals=("no migration",),
    )


def test_git_evidence_verifies_exact_artifact_base_ancestry_and_diff(tmp_path: Path) -> None:
    root, base, artifact = repo(tmp_path)
    report = GitRepositoryEvidenceVerifier(root).verify(
        ArtifactSubmission(
            artifact_version=artifact,
            base_version=base,
            changed_files=("change.txt",),
        ),
        solution(),
    )
    assert report.decision is AuditDecision.VERIFIED
    assert "base-is-ancestor" in report.facts_verified
    assert "changed-files-exact" in report.facts_verified
    assert report.proof_construction_verified is False
    assert report.solution_conformance_verified is False


def test_git_evidence_vetoes_false_changed_file_claim(tmp_path: Path) -> None:
    root, base, artifact = repo(tmp_path)
    report = GitRepositoryEvidenceVerifier(root).verify(
        ArtifactSubmission(
            artifact_version=artifact,
            base_version=base,
            changed_files=("invented.txt",),
        ),
        solution(),
    )
    assert report.decision is AuditDecision.VETO
    assert any("changed_files mismatch" in mismatch for mismatch in report.mismatches)


def test_git_evidence_vetoes_nonexistent_artifact(tmp_path: Path) -> None:
    root, base, _ = repo(tmp_path)
    report = GitRepositoryEvidenceVerifier(root).verify(
        ArtifactSubmission(
            artifact_version="0" * 40,
            base_version=base,
            changed_files=("change.txt",),
        ),
        solution(),
    )
    assert report.decision is AuditDecision.VETO
    assert report.mismatches


def test_git_evidence_rejects_symbolic_or_noncanonical_revisions_before_git(tmp_path: Path) -> None:
    root, base, artifact = repo(tmp_path)
    verifier = GitRepositoryEvidenceVerifier(root)
    symbolic = verifier.verify(
        ArtifactSubmission(artifact_version="HEAD", base_version=base, changed_files=("change.txt",)),
        solution(),
    )
    uppercase = verifier.verify(
        ArtifactSubmission(artifact_version=artifact.upper(), base_version=base, changed_files=("change.txt",)),
        solution(),
    )
    assert symbolic.decision is AuditDecision.VETO
    assert uppercase.decision is AuditDecision.VETO
    assert all("exact lowercase" in report.mismatches[0] for report in (symbolic, uppercase))


class Supplemental:
    def test_results(self, artifact_version: str) -> tuple[str, ...]:
        return ("tests=pass",)

    def ci_results(self, artifact_version: str) -> tuple[str, ...]:
        return ("ci=success",)

    def migration_results(self, artifact_version: str) -> tuple[str, ...]:
        return ("migration=head",)

    def dependency_results(self, artifact_version: str) -> tuple[str, ...]:
        return ()


def test_supplemental_observations_must_match_claims_exactly(tmp_path: Path) -> None:
    root, base, artifact = repo(tmp_path)
    verifier = GitRepositoryEvidenceVerifier(root, supplemental=Supplemental())
    good = verifier.verify(
        ArtifactSubmission(
            artifact_version=artifact,
            base_version=base,
            changed_files=("change.txt",),
            test_claims=("tests=pass",),
            ci_claims=("ci=success",),
            migration_claims=("migration=head",),
        ),
        solution(),
    )
    assert good.decision is AuditDecision.VERIFIED

    bad = verifier.verify(
        ArtifactSubmission(
            artifact_version=artifact,
            base_version=base,
            changed_files=("change.txt",),
            test_claims=("tests=23 passed",),
            ci_claims=("ci=success",),
            migration_claims=("migration=head",),
        ),
        solution(),
    )
    assert bad.decision is AuditDecision.VETO
    assert any("tests claims mismatch" in mismatch for mismatch in bad.mismatches)


def test_nonempty_claims_without_observation_source_are_vetoed(tmp_path: Path) -> None:
    root, base, artifact = repo(tmp_path)
    report = GitRepositoryEvidenceVerifier(root).verify(
        ArtifactSubmission(artifact, base, ("change.txt",), dependency_versions=("python=3",)),
        solution(),
    )
    assert report.decision is AuditDecision.VETO
    assert "dependencies claims are unverifiable" in report.mismatches[-1]
