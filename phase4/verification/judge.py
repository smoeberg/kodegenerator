"""LLM-augmented verification judge for Phase 4.

The deterministic :class:`~phase4.verification.engine.VerificationEngine`
evaluates votes already produced.  This module supplies the *producer* side:
a configurable LLM judge that converts a bounded evidence bundle into a
``bool`` verdict.  A deterministic baseline judge provides the same contract
when no transport is configured, so the pipeline remains fail-closed.

The judge has no authority and performs no repository I/O: it only converts
a bounded prompt into a verdict.  State transitions and materialization stay
with :class:`~phase4.verification.flow.BrainVerificationFlow`.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from phase4.contracts import Evidence, KnowledgeRecord


class JudgeInputError(ValueError):
    """Raised when the bounded evidence cannot be converted to a verdict."""


class VerdictProvider(Protocol):
    """Minimal provider surface: prompt in, JSON verdict out."""

    def judge(self, prompt: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class JudgeVerdict:
    """Immutable, bounded judge output for one evidence bundle.

    ``ac_coverage`` is the fraction of acceptance criteria the bundle
    addresses (1.0 = full coverage).  A verdict of ``True`` with
    ``ac_coverage < 1.0`` therefore means "all supplied evidence passed,
    but the bundle is incomplete" — callers that require 100% AC coverage
    must check ``ac_coverage == 1.0`` explicitly.
    """

    candidate_id: str
    verdict: bool
    confidence: float
    reasoning: str
    judged_at: str
    provider: str
    fingerprint: str
    ac_coverage: float = 1.0

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate_id must be non-empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0.0, 1.0]")
        if not 0.0 <= self.ac_coverage <= 1.0:
            raise ValueError("ac_coverage must be within [0.0, 1.0]")
        if not self.fingerprint.strip():
            raise ValueError("fingerprint must be non-empty")


class DeterministicBaselineJudge:
    """Fail-closed deterministic judge.

    Verdict is derived from the bounded evidence bundle only: it confirms
    only when every evidence item is marked ``passed`` and at least one
    exists.  This mirrors the DETERMINISTIC mode of the verification engine.
    """

    def judge(self, prompt: str) -> dict[str, Any]:
        try:
            payload = json.loads(prompt)
        except json.JSONDecodeError as exc:
            raise JudgeInputError(f"baseline judge requires a JSON bundle: {exc}") from exc
        bundle = payload.get("bundle", {})
        candidate_id = str(bundle.get("candidate_id") or "")
        if not candidate_id:
            raise JudgeInputError("bundle.candidate_id is required")
        evidence = bundle.get("evidence") or []
        passed = [
            e for e in evidence
            if isinstance(e, dict) and e.get("supports") is True
        ]
        verdict = bool(passed) and len(passed) == len(evidence)

        # AC coverage: the bundle may declare the full acceptance-criteria
        # list (from the spec); otherwise criteria are inferred from the
        # evidence items themselves.  Coverage is the share of the full
        # criteria list that has at least one passing evidence item.
        declared_acs = [
            str(ac)
            for ac in (bundle.get("acceptance_criteria") or [])
            if str(ac).strip()
        ]
        if declared_acs:
            total_acs: set[str] = set(declared_acs)
        else:
            total_acs = set()
        passed_acs: set[str] = set()
        for item in evidence if isinstance(evidence, list) else []:
            if not isinstance(item, dict):
                continue
            ac = str(item.get("acceptance_criterion") or item.get("ac_id") or "")
            if ac:
                if not total_acs:
                    total_acs.add(ac)
                if item.get("supports") is True:
                    passed_acs.add(ac)
        ac_coverage = (
            len(passed_acs) / len(total_acs) if total_acs else (1.0 if verdict else 0.0)
        )
        coverage_note = f" (AC coverage {len(passed_acs)}/{len(total_acs)})" if total_acs else ""
        return {
            "candidate_id": candidate_id,
            "verdict": verdict,
            "confidence": 1.0 if verdict else 0.0,
            "reasoning": (
                f"baseline: all evidence passed{coverage_note}"
                if verdict
                else f"baseline: one or more evidence items failed{coverage_note}"
            ),
            "provider": "baseline",
            "ac_coverage": ac_coverage,
        }


class OpenAIJudgeProvider:
    """OpenAI Responses-API provider for verdict generation.

    The provider has no authority and performs no repository I/O.  It only
    converts the bounded evidence bundle into a strict JSON verdict; the
    calling service validates and bounds it afterwards.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        timeout: int = 60,
        max_attempts: int = 2,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not self._api_key:
            raise ValueError("OpenAI API key is required (or set OPENAI_API_KEY)")
        self._model = model
        self._timeout = timeout
        self._max_attempts = max_attempts

    def judge(self, prompt: str) -> dict[str, Any]:
        body = {
            "model": self._model,
            "input": prompt,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "verdict_candidate",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "candidate_id": {"type": "string"},
                            "verdict": {"type": "boolean"},
                            "confidence": {"type": "number"},
                            "reasoning": {"type": "string"},
                        },
                        "required": ["candidate_id", "verdict", "confidence", "reasoning"],
                        "additionalProperties": False,
                    },
                }
            },
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                req = urllib.request.Request(
                    "https://api.openai.com/v1/responses",
                    data=json.dumps(body).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # nosec B310 - URL is explicitly restricted to HTTPS.
                    raw = json.loads(resp.read().decode("utf-8"))
                text = raw.get("output_text") or ""
                for item in raw.get("output") or []:
                    if item.get("type") == "message":
                        for content in item.get("content") or []:
                            if content.get("type") == "output_text":
                                text += content.get("text", "")
                if not text.strip():
                    raise JudgeInputError("provider returned empty output")
                parsed = json.loads(text)
                if not isinstance(parsed, dict):
                    raise JudgeInputError("provider output is not an object")
                return parsed
            except (urllib.error.URLError, json.JSONDecodeError, JudgeInputError) as exc:
                last_error = exc
        raise JudgeInputError(f"judge provider failed after {self._max_attempts} attempts: {last_error}")


class LLMJudge:
    """Boundary judge: evidence bundle -> immutable :class:`JudgeVerdict`.

    The judge owns the conversion from an untrusted provider payload to the
    bounded verdict contract.  It computes a content-addressable fingerprint
    over the verdict and never exposes execution authority.
    """

    def __init__(
        self,
        provider: VerdictProvider | None = None,
        *,
        default_confidence: float = 0.5,
    ) -> None:
        self._provider = provider or DeterministicBaselineJudge()
        self._default_confidence = default_confidence

    def judge_record(
        self,
        record: KnowledgeRecord,
        *,
        evidence: Sequence[Evidence] | None = None,
        judged_at: str | None = None,
    ) -> JudgeVerdict:
        evidence_items = list(evidence if evidence is not None else record.evidence)
        acs = sorted(
            {
                ac
                for e in evidence_items
                if (ac := getattr(e, "acceptance_criterion", "") or "")
            }
        )
        bundle = {
            "candidate_id": record.record_id,
            "subject": record.subject,
            "claim": record.claim,
            "evidence": [
                {
                    "evidence_id": e.evidence_id,
                    "source": e.source,
                    "content_digest": e.content_digest,
                    "supports": e.supports,
                    "acceptance_criterion": getattr(e, "acceptance_criterion", "") or "",
                }
                for e in evidence_items
            ],
            "acceptance_criteria": acs,
        }
        prompt = json.dumps(
            {
                "role": (
                    "You are the DOR verification judge.  You evaluate ONE bounded "
                    "evidence bundle and return a strict JSON verdict.  You have no "
                    "authority and perform no repository I/O.  Judgement must require "
                    "evidence for EVERY acceptance criterion (100% AC coverage)."
                ),
                "bundle": bundle,
            },
            sort_keys=True,
        )
        candidate = self._provider.judge(prompt)

        candidate_id = str(candidate.get("candidate_id") or record.record_id)
        verdict = bool(candidate.get("verdict"))
        try:
            raw_confidence = candidate.get("confidence")
            confidence = (
                float(raw_confidence)
                if raw_confidence is not None
                else self._default_confidence
            )
        except (TypeError, ValueError):
            confidence = self._default_confidence
        confidence = max(0.0, min(1.0, confidence))
        reasoning = str(candidate.get("reasoning") or "")
        provider = str(candidate.get("provider") or type(self._provider).__name__)

        # AC coverage: fraction of criteria that has at least one passing item.
        accepted_criteria: set[str] = set()
        for e in evidence_items:
            ac = getattr(e, "acceptance_criterion", "") or ""
            if ac:
                accepted_criteria.add(ac)
        if accepted_criteria:
            covered = sum(
                1
                for ac in accepted_criteria
                if any(getattr(e, "acceptance_criterion", "") == ac and e.supports for e in evidence_items)
            )
            ac_coverage = covered / len(accepted_criteria)
        else:
            # No explicit criteria on the bundle: coverage is full iff verdict.
            ac_coverage = 1.0 if verdict else 0.0

        canonical = json.dumps(
            {
                "candidate_id": candidate_id,
                "verdict": verdict,
                "confidence": confidence,
                "reasoning": reasoning,
                "ac_coverage": ac_coverage,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        return JudgeVerdict(
            candidate_id=candidate_id,
            verdict=verdict,
            confidence=confidence,
            reasoning=reasoning,
            judged_at=judged_at or datetime.now(timezone.utc).isoformat(),
            provider=provider,
            fingerprint=fingerprint,
            ac_coverage=ac_coverage,
        )


__all__ = [
    "DeterministicBaselineJudge",
    "JudgeInputError",
    "JudgeVerdict",
    "LLMJudge",
    "OpenAIJudgeProvider",
    "VerdictProvider",
]
