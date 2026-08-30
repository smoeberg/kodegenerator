"""AI-6 LLM planning service and provider boundary.

The planner proposes structured continuation or delivery plans from an
untrusted natural-language specification.  It owns no execution authority:
every proposal is immutable, bounded and deterministic after generation.
A deterministic baseline provider produces the same contract when no LLM
transport is configured.

Provider boundary rules (mirrors phase4/project_audit/openai_provider.py):
  - provider receives only the bounded plan prompt;
  - provider returns a strict JSON payload;
  - the service performs authority/validation, never the provider.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from phase4.planner.models import (
    PlanRequest,
    PlanStatus,
)


class PlanParseError(ValueError):
    """Raised when a provider payload cannot be converted to a plan."""


class PlanProvider(Protocol):
    """Minimal provider surface: prompt in, JSON-candidate out."""

    def generate_plan(self, prompt: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class GeneratedPlan:
    """Immutable, bounded, non-executable plan produced by the planner service."""

    plan_id: str
    request_fingerprint: str
    resource: str
    action: str
    steps: tuple[str, ...]
    rationale: str
    confidence: float
    created_at: str
    status: PlanStatus = PlanStatus.PROPOSED
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.plan_id or not self.request_fingerprint:
            raise ValueError("plan_id and request_fingerprint are required")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0.0, 1.0]")
        if self.status is not PlanStatus.PROPOSED:
            raise ValueError("a generated plan may only be proposed")


class DeterministicBaselinePlanner:
    """Fail-closed, deterministic plan generator.

    Used when no LLM transport is configured.  It derives a bounded plan from
    the bounded spec text and never fabricates execution authority.
    """

    def generate_plan(self, prompt: str) -> dict[str, Any]:
        try:
            payload = json.loads(prompt)
        except json.JSONDecodeError as exc:
            raise PlanParseError(f"baseline planner requires a JSON spec: {exc}") from exc
        spec = payload.get("spec", {})
        if not isinstance(spec, dict):
            raise PlanParseError("spec must be an object")

        title = str(spec.get("title") or "untitled")
        description = str(spec.get("description") or "")
        action = str(spec.get("action") or "implement")
        resource = str(spec.get("resource") or "unknown")
        steps = spec.get("steps") or []

        # Cap the number of steps and derive a minimal bounded plan.
        bounded_steps = [str(s) for s in steps[:16] if str(s).strip()]
        if not bounded_steps:
            bounded_steps = [f"Implement `{resource}` from specification `{title}`"]

        deterministic_signature = hashlib.sha256(
            json.dumps(
                {"title": title, "description": description, "action": action, "steps": bounded_steps},
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

        return {
            "plan_id": f"plan-baseline-{deterministic_signature[:12]}",
            "request_fingerprint": str(payload.get("fingerprint") or deterministic_signature),
            "resource": resource,
            "action": action,
            "steps": bounded_steps,
            "rationale": "Deterministic baseline plan derived from the bounded specification.",
            "confidence": 0.5,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }


class OpenAIPlannerProvider:
    """OpenAI Responses-API provider for plan generation.

    The provider has no authority and performs no repository I/O.  It only
    converts the bounded prompt into a strict JSON candidate; the service
    validates and bounds it afterwards.
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

    def generate_plan(self, prompt: str) -> dict[str, Any]:
        body = {
            "model": self._model,
            "input": prompt,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "plan_candidate",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "plan_id": {"type": "string"},
                            "request_fingerprint": {"type": "string"},
                            "resource": {"type": "string"},
                            "action": {"type": "string"},
                            "steps": {"type": "array", "items": {"type": "string"}},
                            "rationale": {"type": "string"},
                            "confidence": {"type": "number"},
                        },
                        "required": [
                            "plan_id",
                            "request_fingerprint",
                            "resource",
                            "action",
                            "steps",
                            "rationale",
                            "confidence",
                        ],
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
                    raise PlanParseError("provider returned empty output")
                parsed = json.loads(text)
                if not isinstance(parsed, dict):
                    raise PlanParseError("provider output is not an object")
                return parsed
            except (urllib.error.URLError, json.JSONDecodeError, PlanParseError) as exc:
                last_error = exc
        raise PlanParseError(f"plan provider failed after {self._max_attempts} attempts: {last_error}")


class PlannerService:
    """Boundary service: spec -> immutable GeneratedPlan.

    The service owns the conversion from an untrusted specification to the
    immutable plan contract.  It bounds the LLM candidate, enforces the
    proposed-only invariant, computes a content-addressable plan id, and
    never exposes execution authority.
    """

    def __init__(
        self,
        provider: PlanProvider | None = None,
        *,
        max_steps: int = 16,
    ) -> None:
        self._provider = provider or DeterministicBaselinePlanner()
        self._max_steps = max_steps

    def plan_from_spec(
        self,
        spec: dict[str, Any],
        *,
        fingerprint: str | None = None,
        created_at: str | None = None,
    ) -> GeneratedPlan:
        if not isinstance(spec, dict) or not spec:
            raise ValueError("spec must be a non-empty object")

        prompt = json.dumps(
            {
                "role": "You are the DOR AI-6 planner. You propose structured, bounded implementation plans. You never authorize execution.",
                "spec": spec,
                "fingerprint": fingerprint,
            },
            sort_keys=True,
        )
        candidate = self._provider.generate_plan(prompt)

        resource = str(candidate.get("resource") or "unknown")
        action = str(candidate.get("action") or "implement")
        steps_raw = candidate.get("steps") or []
        if not isinstance(steps_raw, list):
            raise PlanParseError("steps must be a list")
        steps = tuple(str(s) for s in steps_raw[: self._max_steps] if str(s).strip())
        if not steps:
            raise PlanParseError("planner must produce at least one step")

        rationale = str(candidate.get("rationale") or "")
        try:
            confidence = float(candidate.get("confidence") or 0.5)
        except (TypeError, ValueError) as exc:
            raise PlanParseError(f"confidence must be numeric: {exc}") from exc
        confidence = max(0.0, min(1.0, confidence))

        request_fingerprint = str(candidate.get("request_fingerprint") or fingerprint or "")
        canonical = json.dumps(
            {
                "request_fingerprint": request_fingerprint,
                "resource": resource,
                "action": action,
                "steps": list(steps),
                "rationale": rationale,
                "confidence": confidence,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        plan_id = f"plan-{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:16]}"

        return GeneratedPlan(
            plan_id=plan_id,
            request_fingerprint=request_fingerprint,
            resource=resource,
            action=action,
            steps=steps,
            rationale=rationale,
            confidence=confidence,
            created_at=created_at or datetime.now(timezone.utc).isoformat(),
        )

    def plan_from_request(
        self,
        request: PlanRequest,
        *,
        spec: dict[str, Any] | None = None,
    ) -> GeneratedPlan | None:
        """Plan continuation work for an AI-5 outcome (non-executable)."""
        if request.outcome.status.value in {"succeeded", "unknown"}:
            return None
        return self.plan_from_spec(
            spec or {"title": request.resource, "action": request.action, "resource": request.resource},
            fingerprint=request.request_fingerprint,
        )


__all__ = [
    "DeterministicBaselinePlanner",
    "GeneratedPlan",
    "OpenAIPlannerProvider",
    "PlanParseError",
    "PlanProvider",
    "PlannerService",
]
