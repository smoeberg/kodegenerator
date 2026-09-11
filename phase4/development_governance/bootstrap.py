"""Production composition root for the existing Governance v0 coordinator."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any

from services.governed_llm import GovernedLLMRuntime

from .contracts import ProblemBrief, content_fingerprint
from .coordinator import GovernanceCoordinator, GovernanceRunResult
from .evidence import GitRepositoryEvidenceVerifier
from .providers import (
    GovernedAuditorProvider,
    GovernedCoderProvider,
    GovernedImplementationLifecycleExecutor,
    GovernedOrchestratorProvider,
    GovernedProductOwnerProvider,
    GovernedReviewerProvider,
)

ROLE_NAMES = ("product_owner", "orchestrator", "coder", "auditor", "reviewer")


class GovernanceBootstrapError(RuntimeError):
    """Configuration is incomplete, ambiguous, or violates role separation."""


@dataclass(frozen=True)
class RoleBinding:
    provider_id: str
    factory: str
    model: str
    prompt_version: str
    options_fingerprint: str

    def __post_init__(self) -> None:
        for name in ("provider_id", "factory", "model", "prompt_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise GovernanceBootstrapError(f"{name} must be canonical non-empty text")
        if len(self.options_fingerprint) != 64 or any(c not in "0123456789abcdef" for c in self.options_fingerprint):
            raise GovernanceBootstrapError("options_fingerprint must be lowercase SHA-256")

    @property
    def route_fingerprint(self) -> str:
        payload = {"factory": self.factory, "model": self.model, "options_fingerprint": self.options_fingerprint,
                   "prompt_version": self.prompt_version, "provider_id": self.provider_id}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class GovernanceBootstrapConfig:
    organization_id: str
    repository_root: Path
    roles: Mapping[str, RoleBinding]
    base_sha: str
    audit_path: Path | None = None

    def __post_init__(self) -> None:
        if not self.organization_id.strip() or self.organization_id != self.organization_id.strip():
            raise GovernanceBootstrapError("organization_id must be canonical non-empty text")
        if len(self.base_sha) != 40 or any(c not in "0123456789abcdef" for c in self.base_sha):
            raise GovernanceBootstrapError("base_sha must be an exact lowercase 40-character Git SHA")
        roles = dict(self.roles)
        if set(roles) != set(ROLE_NAMES):
            missing = sorted(set(ROLE_NAMES) - set(roles))
            unknown = sorted(set(roles) - set(ROLE_NAMES))
            raise GovernanceBootstrapError(f"role bindings mismatch: missing={missing!r} unknown={unknown!r}")
        identities = [roles[name].provider_id for name in ROLE_NAMES]
        if len(set(identities)) != len(identities):
            raise GovernanceBootstrapError("all five logical role provider IDs must be pairwise distinct")
        if roles["reviewer"].provider_id == roles["coder"].provider_id:
            raise GovernanceBootstrapError("reviewer and coder must be different logical providers")
        object.__setattr__(self, "roles", MappingProxyType(roles))


ProviderFactory = Callable[[str, RoleBinding, str], object]


class GovernanceProviderRegistry:
    """Immutable registry; selecting a factory is wiring, never authority delegation."""

    def __init__(self, factories: Mapping[str, ProviderFactory]) -> None:
        if not factories or any(not key.strip() or not callable(value) for key, value in factories.items()):
            raise GovernanceBootstrapError("provider registry requires named callable factories")
        self._factories = MappingProxyType(dict(factories))

    @property
    def factory_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))

    def build(self, role: str, binding: RoleBinding, organization_id: str) -> object:
        factory = self._factories.get(binding.factory)
        if factory is None:
            raise GovernanceBootstrapError(f"unknown provider factory {binding.factory!r} for role {role!r}")
        provider = factory(role, binding, organization_id)
        if getattr(provider, "provider_id", None) != binding.provider_id:
            raise GovernanceBootstrapError(f"provider identity mismatch for role {role!r}")
        return provider


class GovernanceAuditLog:
    """Canonical process-local audit record, optionally mirrored to one JSON file."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._records: list[dict[str, Any]] = []

    @property
    def records(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(MappingProxyType(dict(item)) for item in self._records)

    def append(self, event: str, payload: Mapping[str, Any]) -> None:
        record = {"event": event, "observed_at": datetime.now(timezone.utc).isoformat(), "payload": dict(payload)}
        self._records.append(record)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(self.to_json() + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                directory_fd = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

    def to_json(self) -> str:
        return json.dumps({"schema_version": "governance-bootstrap-audit-v1", "records": self._records},
                          sort_keys=True, separators=(",", ":"), ensure_ascii=False)


ROLE_ADAPTERS = MappingProxyType({
    "product_owner": GovernedProductOwnerProvider,
    "orchestrator": GovernedOrchestratorProvider,
    "auditor": GovernedAuditorProvider,
    "reviewer": GovernedReviewerProvider,
})


def governed_llm_factory(runtime_factory: Callable[[RoleBinding], GovernedLLMRuntime]) -> ProviderFactory:
    def build(role: str, binding: RoleBinding, organization_id: str) -> object:
        if role == "coder":
            raise GovernanceBootstrapError("coder requires an injected governed execution runtime; LLM fallback is prohibited")
        adapter = ROLE_ADAPTERS.get(role)
        if adapter is None:
            raise GovernanceBootstrapError(f"unknown governance role {role!r}")
        return adapter(binding.provider_id, runtime_factory(binding), organization_id=organization_id, model=binding.model)
    return build


def governed_execution_factory(
    runtime_builder: Callable[[Path, Callable[[object], object]], tuple[object, object]],
    *, repository_root: Path, base_sha: str, project_id: str | None = None,
    plan_fingerprint: str | None = None,
) -> ProviderFactory:
    """Bind Coder to the existing configured implementation + patch runtime seam."""
    def build(role: str, binding: RoleBinding, organization_id: str) -> object:
        if role != "coder":
            raise GovernanceBootstrapError("governed_execution factory is valid only for coder")
        executor = GovernedImplementationLifecycleExecutor(
            runtime_builder, repository_root=repository_root, base_sha=base_sha,
            organization_id=organization_id, project_id=project_id,
            plan_fingerprint=plan_fingerprint,
        )
        return GovernedCoderProvider(binding.provider_id, executor, repository_root, base_sha)

    return build


class GovernanceBootstrap:
    def __init__(self, config: GovernanceBootstrapConfig, registry: GovernanceProviderRegistry) -> None:
        self.config = config
        self.registry = registry
        self.audit = GovernanceAuditLog(config.audit_path)

    def coordinator(self) -> GovernanceCoordinator:
        self._verify_repository_base()
        return self._coordinator_after_preflight()

    def _coordinator_after_preflight(self) -> GovernanceCoordinator:
        providers = {name: self.registry.build(name, self.config.roles[name], self.config.organization_id)
                     for name in ROLE_NAMES}
        self.audit.append("providers-bound", {name: {"provider_id": self.config.roles[name].provider_id,
                          "route_fingerprint": self.config.roles[name].route_fingerprint} for name in ROLE_NAMES})
        return GovernanceCoordinator(
            product_owner=providers["product_owner"], orchestrator=providers["orchestrator"],
            coder=providers["coder"], auditor=providers["auditor"], reviewer=providers["reviewer"],
            core_evidence=GitRepositoryEvidenceVerifier(self.config.repository_root),
        )

    def run(self, problem: ProblemBrief) -> GovernanceRunResult:
        self._verify_repository_base()
        self.audit.append("run-started", {"problem_id": problem.problem_id, "problem_fingerprint": problem.fingerprint,
                                          "base_sha": self.config.base_sha,
                                          "route_fingerprints": [self.config.roles[name].route_fingerprint for name in ROLE_NAMES]})
        try:
            result = self._coordinator_after_preflight().run_semantic(problem)
        except Exception as exc:
            self.audit.append("run-failed", {"terminal_state": "FAILED_CLOSED",
                                             "error_code": "GOVERNANCE_RUN_FAILED",
                                             "error_type": type(exc).__name__})
            raise
        gates = [
            {"gate": "problem", "input": result.problem.fingerprint, "output": result.problem_approval.fingerprint},
            {"gate": "design", "input": result.problem_approval.fingerprint, "output": result.solution.fingerprint},
            {"gate": "solution", "input": result.solution.fingerprint, "output": result.solution_approval.fingerprint},
            {"gate": "coder", "input": result.solution_approval.fingerprint, "output": content_fingerprint(result.submission)},
            {"gate": "core-evidence", "input": content_fingerprint(result.submission), "output": content_fingerprint(result.core_evidence)},
            {"gate": "audit", "input": content_fingerprint(result.core_evidence), "output": content_fingerprint(result.audit)},
            {"gate": "review", "input": content_fingerprint(result.audit), "output": content_fingerprint(result.review)},
        ]
        self.audit.append("run-completed", {"terminal_state": result.review.decision.value,
                                             "artifact_version": result.submission.artifact_version,
                                             "review_decision": result.review.decision.value, "gates": gates})
        return result

    def _verify_repository_base(self) -> None:
        if self.config.audit_path is not None:
            try:
                self.config.audit_path.resolve().relative_to(self.config.repository_root.resolve())
            except ValueError:
                pass
            else:
                raise GovernanceBootstrapError("audit_path must be outside repository_root")
        try:
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.config.repository_root,
                                  capture_output=True, text=True, check=True).stdout.strip()
            dirty = subprocess.run(["git", "status", "--porcelain"], cwd=self.config.repository_root,
                                   capture_output=True, text=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError) as exc:
            raise GovernanceBootstrapError("repository identity could not be collected") from exc
        if head != self.config.base_sha:
            raise GovernanceBootstrapError(f"repository HEAD {head!r} does not equal configured base_sha")
        if dirty:
            raise GovernanceBootstrapError("repository must be clean before governance provider calls")


def config_from_dict(raw: Mapping[str, Any]) -> GovernanceBootstrapConfig:
    expected = {"organization_id", "repository_root", "roles", "base_sha", "audit_path"}
    if set(raw) - expected:
        raise GovernanceBootstrapError(f"unknown bootstrap fields: {sorted(set(raw) - expected)!r}")
    roles_raw = raw.get("roles")
    if not isinstance(roles_raw, Mapping):
        raise GovernanceBootstrapError("roles must be an object")
    roles: dict[str, RoleBinding] = {}
    for name, value in roles_raw.items():
        fields = {"provider_id", "factory", "model", "prompt_version", "options_fingerprint"}
        if not isinstance(value, Mapping) or set(value) != fields:
            raise GovernanceBootstrapError(f"role {name!r} fields mismatch")
        roles[str(name)] = RoleBinding(**value)
    audit = raw.get("audit_path")
    return GovernanceBootstrapConfig(str(raw.get("organization_id", "")), Path(str(raw.get("repository_root", ""))),
                                     roles, str(raw.get("base_sha", "")), Path(str(audit)) if audit else None)


__all__ = [
    "ROLE_NAMES",
    "GovernanceAuditLog",
    "GovernanceBootstrap",
    "GovernanceBootstrapConfig",
    "GovernanceBootstrapError",
    "GovernanceProviderRegistry",
    "RoleBinding",
    "config_from_dict",
    "governed_execution_factory",
    "governed_llm_factory",
]
