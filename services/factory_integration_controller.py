"""Fail-closed integration of exact candidate commits into one attested branch."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from domain.factory_integration import (
    IntegrationPlan,
    IntegrationReceipt,
    IntegrationStatus,
    ReleaseHandoff,
)
from domain.factory_work import CandidateDelivery, CandidateSelection, fingerprint
from phase4.authority.grants import VerifiedAuthorityGrant

from .side_effects import (
    SideEffectCoordinator,
    SideEffectInProgressError,
    canonical_fingerprint,
)


class IntegrationError(RuntimeError):
    pass


class CandidateReader(Protocol):
    def get_candidate(
        self, organization_id: str, candidate_id: str
    ) -> CandidateDelivery | None: ...

    def get_selection(
        self, organization_id: str, selection_id: str
    ) -> CandidateSelection | None: ...


class IntegrationPlanStore(Protocol):
    def get_plan(
        self, organization_id: str, plan_id: str
    ) -> IntegrationPlan | None: ...

    def get_receipt_for_plan(
        self, organization_id: str, plan_fingerprint: str
    ) -> IntegrationReceipt | None: ...

    def save_plan(
        self, value: IntegrationPlan, *, expected_version: int
    ) -> IntegrationPlan: ...

    def append_receipt(
        self, value: IntegrationReceipt, *, side_effect_result: dict
    ) -> IntegrationReceipt: ...


class SuiteRunner(Protocol):
    def run(self, workspace: Path, checks: tuple[str, ...]) -> Mapping[str, str]: ...


class FactoryIntegrationController:
    def __init__(
        self,
        repository: str | Path,
        *,
        candidates: CandidateReader,
        plans: IntegrationPlanStore,
        side_effects: SideEffectCoordinator,
        suite_runner: SuiteRunner,
    ) -> None:
        self._repository = Path(repository).resolve()
        self._candidates = candidates
        self._plans = plans
        self._side_effects = side_effects
        self._suite = suite_runner
        self._git(self._repository, "rev-parse", "--git-dir")

    def integrate(
        self, plan: IntegrationPlan, grant: VerifiedAuthorityGrant
    ) -> tuple[IntegrationReceipt, ReleaseHandoff | None, bool]:
        self._validate_grant(plan, grant)
        self._validate_candidates(plan)
        current = self._plans.get_plan(plan.organization_id, plan.plan_id)
        if current is None or current.content_fingerprint != plan.content_fingerprint:
            raise IntegrationError("integration plan is unavailable or changed")
        if current.status is IntegrationStatus.SUCCEEDED:
            receipt = self._plans.get_receipt_for_plan(
                plan.organization_id, plan.content_fingerprint
            )
            if receipt is None:
                raise IntegrationError("completed integration has no durable receipt")
            return receipt, self._handoff(plan, receipt), True
        if current.status is IntegrationStatus.READY:
            running = current.transition(IntegrationStatus.RUNNING)
            self._plans.save_plan(running, expected_version=current.version)
        elif current.status is IntegrationStatus.RUNNING:
            running = current
        else:
            raise IntegrationError("integration plan is terminal and cannot be retried")
        request = {
            "organization_id": plan.organization_id,
            "plan_id": plan.plan_id,
            "plan_fingerprint": plan.content_fingerprint,
            "repository": plan.repository,
            "base_sha": plan.base_sha,
            "integration_branch": plan.integration_branch,
            "candidates": [
                {
                    "candidate_id": item.candidate_id,
                    "head_sha": item.head_sha,
                    "commit_shas": item.commit_shas,
                }
                for item in plan.candidates
            ],
            "required_checks": plan.required_checks,
        }
        try:
            result, replayed = self._side_effects.execute(
                organization_id=plan.organization_id,
                action="factory.integrate",
                idempotency_key=plan.idempotency_key,
                request_data=request,
                operation=lambda: self._execute(plan),
            )
        except SideEffectInProgressError:
            raise
        except Exception:
            self._plans.save_plan(
                running.transition(IntegrationStatus.FAILED),
                expected_version=running.version,
            )
            raise
        terminal = (
            IntegrationStatus.SUCCEEDED
            if result["status"] == "passed"
            else IntegrationStatus.CONFLICT
        )
        attestation = dict(result["suite_attestation"])
        attestation["result_fingerprint"] = canonical_fingerprint(result)
        provisional = IntegrationReceipt(
            organization_id=plan.organization_id,
            receipt_id="0" * 64,
            plan_id=plan.plan_id,
            plan_fingerprint=plan.content_fingerprint,
            side_effect_idempotency_key=plan.idempotency_key,
            side_effect_request_fingerprint=canonical_fingerprint(request),
            integration_branch=plan.integration_branch,
            integration_head_sha=result["integration_head_sha"],
            integrated_candidate_ids=tuple(result["candidate_ids"]),
            conflict_paths=tuple(result["conflict_paths"]),
            suite_attestation=tuple(sorted(attestation.items())),
            status=terminal,
        )
        receipt = replace(provisional, receipt_id=provisional.content_fingerprint)
        receipt = self._plans.append_receipt(receipt, side_effect_result=result)
        completed = running.transition(terminal)
        self._plans.save_plan(completed, expected_version=running.version)
        handoff = None
        if terminal is IntegrationStatus.SUCCEEDED:
            handoff = self._handoff(plan, receipt, result=result)
        return receipt, handoff, replayed

    def _handoff(
        self,
        plan: IntegrationPlan,
        receipt: IntegrationReceipt,
        *,
        result: dict | None = None,
    ) -> ReleaseHandoff:
        patch = (
            result["patch_content"]
            if result is not None
            else self._git(
                self._repository,
                "diff",
                "--binary",
                plan.base_sha,
                receipt.integration_head_sha,
            )
        )
        evidence = {
            key: value
            for key, value in receipt.suite_attestation
            if key != "result_fingerprint"
        }
        return ReleaseHandoff(
            organization_id=plan.organization_id,
            integration_receipt_id=receipt.receipt_id,
            plan_fingerprint=plan.content_fingerprint,
            repository=plan.repository,
            base_sha=plan.base_sha,
            head_sha=receipt.integration_head_sha,
            branch=plan.integration_branch,
            patch_content=patch,
            patch_fingerprint=fingerprint(patch),
            test_attestation=tuple(sorted(evidence.items())),
        )

    def _validate_grant(
        self, plan: IntegrationPlan, grant: VerifiedAuthorityGrant
    ) -> None:
        parameters = dict(grant.parameters)
        if (
            not grant.verified
            or grant.action != "factory.integrate"
            or grant.capability != "factory.integrate"
            or grant.organization_id != plan.organization_id
            or grant.resource != f"repository:{plan.repository}"
            or parameters.get("plan_fingerprint") != plan.content_fingerprint
            or parameters.get("base_sha") != plan.base_sha
        ):
            raise IntegrationError("authority grant is not bound to integration plan")

    def _validate_candidates(self, plan: IntegrationPlan) -> None:
        for expected in plan.candidates:
            actual = self._candidates.get_candidate(
                plan.organization_id, expected.candidate_id
            )
            selection = self._candidates.get_selection(
                plan.organization_id, expected.selection_id
            )
            if (
                actual is None
                or selection is None
                or selection.winner_candidate_id != expected.candidate_id
                or selection.work_package_fingerprint
                != expected.work_package_fingerprint
                or actual.base_sha != plan.base_sha
                or actual.work_package_fingerprint != expected.work_package_fingerprint
                or actual.head_sha != expected.head_sha
                or actual.commit_shas != expected.commit_shas
            ):
                raise IntegrationError("candidate evidence changed or is unavailable")
            commits = tuple(
                filter(
                    None,
                    self._git(
                        self._repository,
                        "rev-list",
                        "--reverse",
                        f"{plan.base_sha}..{actual.head_sha}",
                    ).splitlines(),
                )
            )
            if commits != actual.commit_shas:
                raise IntegrationError("candidate commit ancestry is invalid")

    def _execute(self, plan: IntegrationPlan) -> dict:
        if (
            self._git(
                self._repository, "rev-parse", f"{plan.base_sha}^{{commit}}"
            ).strip()
            != plan.base_sha
        ):
            raise IntegrationError("integration base no longer resolves exactly")
        path = Path(tempfile.mkdtemp(prefix="dor-integration-"))
        self._git(
            self._repository, "worktree", "add", "--detach", str(path), plan.base_sha
        )
        try:
            for candidate in plan.candidates:
                for commit in candidate.commit_shas:
                    result = self._run(path, "cherry-pick", commit)
                    if result.returncode:
                        conflicts = tuple(
                            sorted(
                                filter(
                                    None,
                                    self._git(
                                        path, "diff", "--name-only", "--diff-filter=U"
                                    ).splitlines(),
                                )
                            )
                        )
                        self._run(path, "cherry-pick", "--abort")
                        return {
                            "status": "conflict",
                            "integration_head_sha": self._git(
                                path, "rev-parse", "HEAD"
                            ).strip(),
                            "candidate_ids": [
                                item.candidate_id for item in plan.candidates
                            ],
                            "conflict_paths": list(conflicts),
                            "suite_attestation": {"status": "not_run"},
                            "patch_content": "",
                            "patch_fingerprint": fingerprint(""),
                        }
            head = self._git(path, "rev-parse", "HEAD").strip()
            evidence = dict(self._suite.run(path, plan.required_checks))
            if evidence.get("status") != "passed":
                raise IntegrationError("required integration suite did not pass")
            patch = self._git(path, "diff", "--binary", plan.base_sha, head)
            self._publish(path, plan.integration_branch, head)
            return {
                "status": "passed",
                "integration_head_sha": head,
                "candidate_ids": [item.candidate_id for item in plan.candidates],
                "conflict_paths": [],
                "suite_attestation": evidence,
                "patch_content": patch,
                "patch_fingerprint": fingerprint(patch),
            }
        finally:
            self._git(self._repository, "worktree", "remove", "--force", str(path))
            shutil.rmtree(path, ignore_errors=True)
            self._git(self._repository, "worktree", "prune")

    def _publish(self, path: Path, branch: str, head: str) -> None:
        existing = self._git(
            path, "ls-remote", "--heads", "origin", f"refs/heads/{branch}"
        ).strip()
        if existing:
            if existing.split()[0] != head:
                raise IntegrationError("integration branch exists at another head")
            return
        self._git(path, "push", "origin", f"HEAD:refs/heads/{branch}")

    @staticmethod
    def _run(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=path, text=True, capture_output=True, check=False
        )

    @classmethod
    def _git(cls, path: Path, *args: str) -> str:
        result = cls._run(path, *args)
        if result.returncode:
            raise IntegrationError(result.stderr.strip() or "git command failed")
        return result.stdout
