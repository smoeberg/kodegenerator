"""Adaptive prompt synthesizer and self-learning optimizer.

Collects worker-run outcomes per tenant and capability, proposes candidate
prompt templates (few-shot examples + system instructions) from failure
patterns, A/B tests them via :class:`PromptEvaluator`, and maintains a
versioned prompt register with rollback and drift-triggered auto-revert.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Optional, Sequence

from services.prompt_evals import (
    EvalOutcomeKind,
    MetricSnapshot,
    PromptEvaluator,
    RunOutcome,
    SignificanceResult,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PromptVersionStatus(str, Enum):
    """Lifecycle state of a prompt template version."""

    CANDIDATE = "candidate"
    ACTIVE = "active"
    RETIRED = "retired"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True)
class FewShotExample:
    """One few-shot input/output pair attached to a prompt version."""

    input_text: str
    output_text: str
    source: str = "manual"

    def to_dict(self) -> dict[str, str]:
        return {
            "input_text": self.input_text,
            "output_text": self.output_text,
            "source": self.source,
        }


@dataclass
class PromptVersion:
    """Prompt template snapshot (status may transition)."""

    version_id: str
    tenant_id: str
    capability: str
    system_instructions: str
    few_shot: list[FewShotExample] = field(default_factory=list)
    status: PromptVersionStatus = PromptVersionStatus.CANDIDATE
    parent_version_id: Optional[str] = None
    created_at: datetime = field(default_factory=_utcnow)
    activated_at: Optional[datetime] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def content_hash(self) -> str:
        payload = (
            self.system_instructions
            + "||"
            + "||".join(f"{e.input_text}=>{e.output_text}" for e in self.few_shot)
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def render(self, task_description: str = "") -> str:
        """Render a concrete prompt for a worker task."""
        parts = [self.system_instructions.strip()]
        if self.few_shot:
            parts.append("\n## Few-shot examples")
            for idx, ex in enumerate(self.few_shot, start=1):
                parts.append(f"\n### Example {idx}")
                parts.append(f"Input:\n{ex.input_text.strip()}")
                parts.append(f"Output:\n{ex.output_text.strip()}")
        if task_description:
            parts.append("\n## Current task")
            parts.append(task_description.strip())
        return "\n".join(parts).strip() + "\n"

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "tenant_id": self.tenant_id,
            "capability": self.capability,
            "system_instructions": self.system_instructions,
            "few_shot": [e.to_dict() for e in self.few_shot],
            "status": self.status.value,
            "parent_version_id": self.parent_version_id,
            "created_at": self.created_at.isoformat(),
            "activated_at": self.activated_at.isoformat() if self.activated_at else None,
            "content_hash": self.content_hash(),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class AuditEvent:
    """Append-only audit record for prompt lifecycle actions."""

    event_id: str
    tenant_id: str
    capability: str
    action: str
    version_id: str
    detail: str
    timestamp: datetime = field(default_factory=_utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "tenant_id": self.tenant_id,
            "capability": self.capability,
            "action": self.action,
            "version_id": self.version_id,
            "detail": self.detail,
            "timestamp": self.timestamp.isoformat(),
        }


_DEFAULT_INSTRUCTIONS: dict[str, str] = {
    "api": (
        "You are an API engineer. Produce minimal, typed REST/OpenAPI handlers. "
        "Never invent endpoints outside the task scope. Prefer clear error responses."
    ),
    "security": (
        "You are a security engineer. Prefer secure defaults, constant-time checks, "
        "and never log secrets. Reject unsafe patterns (eval, shell=True, pickle)."
    ),
    "service": (
        "You are a service-layer engineer. Keep business logic free of HTTP concerns. "
        "Use explicit dependency injection and pure functions where practical."
    ),
    "domain": (
        "You are a domain modeller. Encode invariants in the type system. "
        "Prefer value objects and aggregate roots; avoid anemic models."
    ),
    "tests": (
        "You are a test engineer. Write deterministic pytest cases with fixtures. "
        "Cover edge cases and failure paths; avoid network and real time."
    ),
    "docs": (
        "You are a technical writer. Produce concise markdown with examples. "
        "Document assumptions, inputs, outputs and failure modes."
    ),
}

_ERROR_HINTS: dict[str, str] = {
    "syntaxerror": "Ensure generated code is syntactically valid Python before finishing.",
    "indentationerror": "Pay careful attention to indentation; emit complete blocks.",
    "typeerror": "Respect declared type signatures; avoid None where a value is required.",
    "assertionerror": "Align implementation with the acceptance tests and edge cases.",
    "importerror": "Only import modules that exist in the project; avoid hallucinated packages.",
    "modulenotfounderror": "Only import modules that exist in the project; avoid hallucinated packages.",
    "permissionerror": "Do not access filesystem paths outside the sandbox workspace.",
    "timeout": "Keep solutions efficient; avoid unbounded loops and heavy recursion.",
}


class PromptOptimizer:
    """Self-learning prompt layer with versioned register and auto-revert.

    Parameters
    ----------
    evaluator:
        Shared :class:`PromptEvaluator` used for A/B significance tests.
    drift_threshold:
        Absolute success-rate drop vs. the activation baseline that triggers
        automatic rollback.
    drift_min_samples:
        Minimum post-activation samples required before drift is evaluated.
    max_few_shot:
        Cap on few-shot examples retained per candidate.
    """

    def __init__(
        self,
        *,
        evaluator: Optional[PromptEvaluator] = None,
        drift_threshold: float = 0.10,
        drift_min_samples: int = 15,
        max_few_shot: int = 5,
    ) -> None:
        if not 0.0 < drift_threshold < 1.0:
            raise ValueError("drift_threshold must be in (0, 1)")
        if drift_min_samples < 1:
            raise ValueError("drift_min_samples must be >= 1")
        self.evaluator = evaluator or PromptEvaluator()
        self.drift_threshold = drift_threshold
        self.drift_min_samples = drift_min_samples
        self.max_few_shot = max_few_shot
        self._lock = threading.RLock()
        self._versions: dict[tuple[str, str], list[PromptVersion]] = defaultdict(list)
        self._active: dict[tuple[str, str], str] = {}
        self._activation_baseline: dict[str, float] = {}
        self._audit: list[AuditEvent] = []

    def ensure_baseline(
        self,
        tenant_id: str,
        capability: str,
        *,
        system_instructions: Optional[str] = None,
    ) -> PromptVersion:
        """Ensure an active baseline exists for *tenant_id*/*capability*."""
        self._require_tenant(tenant_id)
        capability = capability.strip().lower()
        key = (tenant_id, capability)
        with self._lock:
            if key in self._active:
                return self.get_version(self._active[key])
            instructions = (
                system_instructions
                or _DEFAULT_INSTRUCTIONS.get(
                    capability,
                    "You are a careful software engineer. Follow the task exactly.",
                )
            )
            version = PromptVersion(
                version_id=self._new_id("pv"),
                tenant_id=tenant_id,
                capability=capability,
                system_instructions=instructions,
                few_shot=[],
                status=PromptVersionStatus.ACTIVE,
                activated_at=_utcnow(),
                metadata={"seed": True},
            )
            self._versions[key].append(version)
            self._active[key] = version.version_id
            self._activation_baseline[version.version_id] = 0.0
            self._audit_event(
                tenant_id,
                capability,
                "baseline_created",
                version.version_id,
                "seed baseline activated",
            )
            return version

    def get_active(self, tenant_id: str, capability: str) -> PromptVersion:
        capability = capability.strip().lower()
        key = (tenant_id, capability)
        with self._lock:
            if key not in self._active:
                return self.ensure_baseline(tenant_id, capability)
            return self.get_version(self._active[key])

    def get_version(self, version_id: str) -> PromptVersion:
        with self._lock:
            for versions in self._versions.values():
                for version in versions:
                    if version.version_id == version_id:
                        return version
        raise KeyError(f"unknown prompt version: {version_id}")

    def list_versions(self, tenant_id: str, capability: str) -> list[PromptVersion]:
        capability = capability.strip().lower()
        with self._lock:
            return list(self._versions.get((tenant_id, capability), ()))

    def record_outcome(
        self,
        *,
        tenant_id: str,
        capability: str,
        success: bool,
        kind: EvalOutcomeKind | str = EvalOutcomeKind.SUCCESS,
        retry_count: int = 0,
        error_message: str = "",
        latency_ms: float = 0.0,
        prompt_version_id: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> RunOutcome:
        """Record a worker-run outcome against the active (or given) version."""
        self._require_tenant(tenant_id)
        capability = capability.strip().lower()
        if prompt_version_id is None:
            prompt_version_id = self.get_active(tenant_id, capability).version_id
        if isinstance(kind, str):
            kind = EvalOutcomeKind(kind)
        outcome = RunOutcome(
            tenant_id=tenant_id,
            capability=capability,
            prompt_version_id=prompt_version_id,
            success=success,
            kind=kind if not success else EvalOutcomeKind.SUCCESS,
            retry_count=retry_count,
            error_message=error_message or "",
            latency_ms=latency_ms,
            metadata=dict(metadata or {}),
        )
        self.evaluator.record(outcome)
        with self._lock:
            key = (tenant_id, capability)
            if self._active.get(key) == prompt_version_id:
                self._maybe_auto_revert(tenant_id, capability, prompt_version_id)
        return outcome

    def metrics(
        self, tenant_id: str, capability: str, version_id: Optional[str] = None
    ) -> MetricSnapshot:
        capability = capability.strip().lower()
        vid = version_id or self.get_active(tenant_id, capability).version_id
        return self.evaluator.metrics(
            tenant_id=tenant_id,
            capability=capability,
            prompt_version_id=vid,
        )

    def propose_candidate(
        self,
        tenant_id: str,
        capability: str,
        *,
        max_examples: Optional[int] = None,
    ) -> PromptVersion:
        """Synthesize a candidate prompt from recent failure patterns."""
        self._require_tenant(tenant_id)
        capability = capability.strip().lower()
        active = self.get_active(tenant_id, capability)
        limit = max_examples or self.max_few_shot

        failures = [
            o
            for o in self.evaluator.outcomes
            if o.tenant_id == tenant_id
            and o.capability == capability
            and not o.success
        ]
        hints = self._mine_instruction_hints(failures)
        few_shot = self._mine_few_shots(failures, limit=limit)

        base_instructions = active.system_instructions.rstrip()
        if hints:
            extra = "\n".join(f"- {h}" for h in hints)
            system_instructions = (
                f"{base_instructions}\n\n## Hardened rules (auto-derived)\n{extra}\n"
            )
        else:
            system_instructions = (
                f"{base_instructions}\n\n"
                "## Hardened rules (auto-derived)\n"
                "- Prefer small, verifiable changes over speculative rewrites.\n"
            )

        combined: list[FewShotExample] = list(active.few_shot)
        seen = {e.input_text.strip() for e in combined}
        for example in few_shot:
            if example.input_text.strip() not in seen:
                combined.append(example)
                seen.add(example.input_text.strip())
        combined = combined[: self.max_few_shot]

        candidate = PromptVersion(
            version_id=self._new_id("pv"),
            tenant_id=tenant_id,
            capability=capability,
            system_instructions=system_instructions,
            few_shot=combined,
            status=PromptVersionStatus.CANDIDATE,
            parent_version_id=active.version_id,
            metadata={"failure_count": len(failures), "hints": hints},
        )
        with self._lock:
            self._versions[(tenant_id, capability)].append(candidate)
            self._audit_event(
                tenant_id,
                capability,
                "candidate_proposed",
                candidate.version_id,
                f"from parent={active.version_id} failures={len(failures)}",
            )
        logger.info(
            "proposed candidate %s for %s/%s (failures=%d)",
            candidate.version_id,
            tenant_id,
            capability,
            len(failures),
        )
        return candidate

    def evaluate_and_maybe_promote(
        self,
        tenant_id: str,
        capability: str,
        candidate_version_id: str,
    ) -> tuple[bool, SignificanceResult]:
        """A/B test candidate vs active; promote only on statistical significance."""
        capability = capability.strip().lower()
        active = self.get_active(tenant_id, capability)
        candidate = self.get_version(candidate_version_id)
        if candidate.tenant_id != tenant_id or candidate.capability != capability:
            raise ValueError("candidate does not belong to tenant/capability")
        if candidate.status is not PromptVersionStatus.CANDIDATE:
            raise ValueError(f"version {candidate_version_id} is not a candidate")

        ok, result = self.evaluator.should_promote(
            tenant_id=tenant_id,
            capability=capability,
            control_version_id=active.version_id,
            candidate_version_id=candidate_version_id,
        )
        with self._lock:
            if ok:
                self._promote_unlocked(tenant_id, capability, candidate, active, result)
            else:
                self._audit_event(
                    tenant_id,
                    capability,
                    "promotion_rejected",
                    candidate_version_id,
                    result.reason,
                )
        return ok, result

    def rollback(
        self,
        tenant_id: str,
        capability: str,
        *,
        to_version_id: Optional[str] = None,
        reason: str = "manual_rollback",
    ) -> PromptVersion:
        """Roll active prompt back to a previous version (or its parent)."""
        capability = capability.strip().lower()
        with self._lock:
            active = self.get_active(tenant_id, capability)
            target_id = to_version_id or active.parent_version_id
            if not target_id:
                history = self._versions.get((tenant_id, capability), [])
                prior = [
                    v
                    for v in history
                    if v.version_id != active.version_id
                    and v.status
                    in {
                        PromptVersionStatus.RETIRED,
                        PromptVersionStatus.ROLLED_BACK,
                        PromptVersionStatus.ACTIVE,
                    }
                ]
                if not prior:
                    raise ValueError("no prior version available for rollback")
                target_id = prior[0].version_id
            target = self.get_version(target_id)
            active.status = PromptVersionStatus.ROLLED_BACK
            target.status = PromptVersionStatus.ACTIVE
            target.activated_at = _utcnow()
            self._active[(tenant_id, capability)] = target.version_id
            snap = self.evaluator.metrics(
                tenant_id=tenant_id,
                capability=capability,
                prompt_version_id=target.version_id,
            )
            self._activation_baseline[target.version_id] = snap.success_rate
            self._audit_event(
                tenant_id,
                capability,
                "rollback",
                target.version_id,
                f"{reason}; from={active.version_id}",
            )
            return target

    def audit_log(
        self,
        *,
        tenant_id: Optional[str] = None,
        capability: Optional[str] = None,
    ) -> list[AuditEvent]:
        with self._lock:
            events = list(self._audit)
        if tenant_id is not None:
            events = [e for e in events if e.tenant_id == tenant_id]
        if capability is not None:
            cap = capability.strip().lower()
            events = [e for e in events if e.capability == cap]
        return events

    def _promote_unlocked(
        self,
        tenant_id: str,
        capability: str,
        candidate: PromptVersion,
        previous: PromptVersion,
        result: SignificanceResult,
    ) -> None:
        previous.status = PromptVersionStatus.RETIRED
        candidate.status = PromptVersionStatus.ACTIVE
        candidate.activated_at = _utcnow()
        self._active[(tenant_id, capability)] = candidate.version_id
        self._activation_baseline[candidate.version_id] = result.candidate_rate
        self._audit_event(
            tenant_id,
            capability,
            "promoted",
            candidate.version_id,
            f"z={result.z_score:.3f} p={result.p_value:.4f} "
            f"lift={result.improvement:.4f} prev={previous.version_id}",
        )
        logger.info(
            "promoted %s over %s for %s/%s (lift=%.3f)",
            candidate.version_id,
            previous.version_id,
            tenant_id,
            capability,
            result.improvement,
        )

    def _maybe_auto_revert(
        self,
        tenant_id: str,
        capability: str,
        version_id: str,
    ) -> None:
        baseline = self._activation_baseline.get(version_id)
        if baseline is None:
            return
        snap = self.evaluator.metrics(
            tenant_id=tenant_id,
            capability=capability,
            prompt_version_id=version_id,
        )
        if snap.sample_size < self.drift_min_samples:
            return
        drop = baseline - snap.success_rate
        if drop >= self.drift_threshold:
            logger.warning(
                "drift detected for %s/%s version=%s drop=%.3f — auto-revert",
                tenant_id,
                capability,
                version_id,
                drop,
            )
            try:
                self.rollback(
                    tenant_id,
                    capability,
                    reason=f"auto_revert_drift drop={drop:.3f}",
                )
            except ValueError:
                self._audit_event(
                    tenant_id,
                    capability,
                    "drift_detected_no_rollback_target",
                    version_id,
                    f"drop={drop:.3f}",
                )

    @staticmethod
    def _mine_instruction_hints(failures: Sequence[RunOutcome]) -> list[str]:
        hints: list[str] = []
        seen: set[str] = set()
        for outcome in failures:
            blob = (outcome.error_message or "").lower()
            kind_key = outcome.kind.value.lower()
            for token, hint in _ERROR_HINTS.items():
                if token in blob or token in kind_key:
                    if hint not in seen:
                        hints.append(hint)
                        seen.add(hint)
        kind_counts = Counter(o.kind for o in failures)
        if kind_counts.get(EvalOutcomeKind.COMPILE_ERROR, 0) >= 2:
            hint = _ERROR_HINTS["syntaxerror"]
            if hint not in seen:
                hints.append(hint)
        if kind_counts.get(EvalOutcomeKind.TEST_FAILURE, 0) >= 2:
            hint = _ERROR_HINTS["assertionerror"]
            if hint not in seen:
                hints.append(hint)
        return hints[:6]

    @staticmethod
    def _mine_few_shots(
        failures: Sequence[RunOutcome],
        *,
        limit: int,
    ) -> list[FewShotExample]:
        examples: list[FewShotExample] = []
        for outcome in failures:
            if len(examples) >= limit:
                break
            err = (outcome.error_message or "").strip()
            if not err:
                continue
            input_text = f"Fix the following failure:\n{err[:400]}"
            output_text = (
                "Identify the root cause from the error, apply the minimal "
                "corrective change, and re-run the failing check before finishing."
            )
            examples.append(
                FewShotExample(
                    input_text=input_text,
                    output_text=output_text,
                    source="failure_mining",
                )
            )
        return examples

    def _audit_event(
        self,
        tenant_id: str,
        capability: str,
        action: str,
        version_id: str,
        detail: str,
    ) -> None:
        self._audit.append(
            AuditEvent(
                event_id=self._new_id("ae"),
                tenant_id=tenant_id,
                capability=capability,
                action=action,
                version_id=version_id,
                detail=detail,
            )
        )

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _require_tenant(tenant_id: str) -> None:
        if not tenant_id or not tenant_id.strip():
            raise ValueError("tenant_id is required")
