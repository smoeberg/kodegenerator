"""Intelligent capability router for swarm / WBS tasks.

Classifies work items into worker capabilities using deterministic keyword
signals and score-based ranking. Low-confidence routes surface a
HumanApprovalGate-compatible review recommendation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Sequence


# Canonical capability tokens returned by the router.
CAPABILITIES: tuple[str, ...] = (
    "api",
    "security",
    "service",
    "domain",
    "tests",
    "docs",
)

DEFAULT_CAPABILITY = "service"
DEFAULT_CONFIDENCE_THRESHOLD = 0.55
DEFAULT_AMBIGUITY_MARGIN = 0.08  # top vs second score gap below this → ambiguous

# Keyword signals: (regex pattern, weight). Patterns are matched case-insensitively
# against the concatenated classification text.
_KEYWORD_RULES: dict[str, tuple[tuple[str, float], ...]] = {
    "api": (
        (r"\bapi\b", 1.0),
        (r"\bendpoint\b", 1.1),
        (r"\broute(?:r|s|ing)?\b", 0.9),
        (r"\brest(?:ful)?\b", 1.0),
        (r"\bgraphql\b", 1.0),
        (r"\bopenapi\b", 0.9),
        (r"\bswagger\b", 0.8),
        (r"\bhttp\b", 0.6),
        (r"\bcontroller\b", 0.8),
        (r"\bhandler\b", 0.5),
        (r"\brequest\b", 0.3),
        (r"\bresponse\b", 0.3),
    ),
    "security": (
        (r"\bsecurity\b", 1.2),
        (r"\bauth(?:n|z|entication|orization)?\b", 1.1),
        (r"\boauth\b", 1.0),
        (r"\bjwt\b", 0.9),
        (r"\bencrypt(?:ion|ed)?\b", 0.9),
        (r"\bsecret\b", 0.8),
        (r"\bvulnerabilit(?:y|ies)\b", 1.1),
        (r"\bthreat\b", 0.8),
        (r"\bpenetration\b", 1.0),
        (r"\baudit\b", 0.6),
        (r"\brbac\b", 0.9),
        (r"\bpermission\b", 0.7),
        (r"\bsanitiz", 0.7),
        (r"\bhmac\b", 0.8),
    ),
    "service": (
        (r"\bservice\b", 0.9),
        (r"\bintegration\b", 0.9),
        (r"\badapter\b", 0.8),
        (r"\bworker\b", 0.7),
        (r"\bqueue\b", 0.6),
        (r"\bclient\b", 0.5),
        (r"\binfrastructure\b", 0.7),
        (r"\bdeploy", 0.6),
        (r"\borchestr", 0.6),
        (r"\bpipeline\b", 0.5),
        (r"\bbusiness logic\b", 0.4),
    ),
    "domain": (
        (r"\bdomain\b", 1.1),
        (r"\bmodel(?:s|ling|ing)?\b", 0.9),
        (r"\bentity\b", 0.9),
        (r"\baggregate\b", 1.0),
        (r"\bvalue object\b", 0.9),
        (r"\brepository\b", 0.7),
        (r"\bschema\b", 0.5),
        (r"\bubiquitous language\b", 1.0),
        (r"\bbounded context\b", 1.0),
        (r"\binvariant\b", 0.7),
        (r"\bbusiness rule\b", 0.8),
    ),
    "tests": (
        (r"\btest(?:s|ing)?\b", 1.2),
        (r"\bunit test\b", 1.1),
        (r"\bintegration test\b", 1.1),
        (r"\be2e\b", 1.0),
        (r"\bpytest\b", 1.0),
        (r"\bcoverage\b", 0.8),
        (r"\bspec\b", 0.4),
        (r"\bassert(?:ion)?\b", 0.6),
        (r"\bfixture\b", 0.7),
        (r"\bmock\b", 0.6),
        (r"\btdd\b", 0.8),
        (r"\bqa\b", 0.5),
    ),
    "docs": (
        (r"\bdoc(?:s|umentation)?\b", 1.2),
        (r"\breadme\b", 1.1),
        (r"\bguide\b", 0.8),
        (r"\bmanual\b", 0.7),
        (r"\bmarkdown\b", 0.7),
        (r"\badoc\b", 0.6),
        (r"\brst\b", 0.5),
        (r"\bchangelog\b", 0.7),
        (r"\bcomment\b", 0.3),
        (r"\btutorial\b", 0.8),
        (r"\breference\b", 0.5),
    ),
}

# Soft priors applied when a WBS phase is known.
_PHASE_PRIORS: dict[str, dict[str, float]] = {
    "requirements": {"docs": 0.35, "domain": 0.25},
    "architecture": {"domain": 0.35, "service": 0.2, "api": 0.15},
    "design": {"domain": 0.3, "api": 0.2, "docs": 0.15},
    "implementation": {"service": 0.2, "api": 0.2, "domain": 0.15},
    "coding": {"service": 0.2, "api": 0.2, "domain": 0.1},
    "testing": {"tests": 0.55},
    "verification": {"tests": 0.4, "security": 0.25},
    "security": {"security": 0.55},
    "review": {"docs": 0.2, "security": 0.15, "tests": 0.15},
    "documentation": {"docs": 0.55},
    "deployment": {"service": 0.35, "security": 0.15},
    "release": {"service": 0.25, "docs": 0.2, "security": 0.15},
}


@dataclass(frozen=True)
class RouteDecision:
    """Immutable routing outcome with score breakdown for auditability."""

    task_id: str
    capability: str
    confidence: float
    scores: Mapping[str, float]
    requires_human_review: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "capability": self.capability,
            "confidence": self.confidence,
            "scores": dict(self.scores),
            "requires_human_review": self.requires_human_review,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class HumanReviewRequest:
    """HumanApprovalGate-compatible payload for low-confidence routes."""

    task_id: str
    recommended_capability: str
    confidence: float
    scores: Mapping[str, float]
    gate_status: str = "HUMAN_REQUIRED"
    reason: str = "low_confidence_routing"

    def requires_human(self) -> bool:
        return self.gate_status == "HUMAN_REQUIRED"


class HumanApprovalGate:
    """Minimal gate that collects low-confidence routing decisions for review.

    Compatible with the control-policy notion of HUMAN_REQUIRED vs AUTONOMOUS.
    """

    def __init__(self, *, confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD) -> None:
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be in [0, 1]")
        self.confidence_threshold = confidence_threshold
        self._pending: list[HumanReviewRequest] = []

    def evaluate(self, decision: RouteDecision) -> str:
        """Return gate status for a routing decision."""
        if decision.requires_human_review or decision.confidence < self.confidence_threshold:
            return "HUMAN_REQUIRED"
        return "AUTONOMOUS"

    def submit(self, decision: RouteDecision) -> Optional[HumanReviewRequest]:
        """Enqueue a human review request when the gate requires it."""
        status = self.evaluate(decision)
        if status != "HUMAN_REQUIRED":
            return None
        req = HumanReviewRequest(
            task_id=decision.task_id,
            recommended_capability=decision.capability,
            confidence=decision.confidence,
            scores=dict(decision.scores),
            gate_status=status,
            reason=decision.reason or "low_confidence_routing",
        )
        self._pending.append(req)
        return req

    @property
    def pending_reviews(self) -> tuple[HumanReviewRequest, ...]:
        return tuple(self._pending)

    def clear(self) -> None:
        self._pending.clear()


@dataclass
class TaskRouter:
    """Rule- and score-based capability router.

    Parameters
    ----------
    confidence_threshold:
        Minimum confidence (0..1) for autonomous routing. Below this the
        decision is flagged for human review.
    ambiguity_margin:
        If the gap between the top two capability scores is smaller than this
        fraction of the top score, the route is treated as ambiguous (confidence
        is reduced).
    default_capability:
        Fallback when no signals match.
    human_gate:
        Optional HumanApprovalGate; when provided, low-confidence decisions are
        submitted automatically from :meth:`route_detailed`.
    """

    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
    ambiguity_margin: float = DEFAULT_AMBIGUITY_MARGIN
    default_capability: str = DEFAULT_CAPABILITY
    human_gate: Optional[HumanApprovalGate] = None
    _cache: dict[str, RouteDecision] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be in [0, 1]")
        if self.ambiguity_margin < 0:
            raise ValueError("ambiguity_margin must be non-negative")
        if self.default_capability not in CAPABILITIES:
            raise ValueError(
                f"default_capability must be one of {CAPABILITIES}"
            )
        # Pre-compile keyword patterns once.
        self._compiled: dict[str, tuple[tuple[re.Pattern[str], float], ...]] = {
            cap: tuple(
                (re.compile(pat, re.IGNORECASE), weight)
                for pat, weight in rules
            )
            for cap, rules in _KEYWORD_RULES.items()
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def route(self, task: Any) -> str:
        """Return the selected capability for *task*."""
        return self.route_detailed(task).capability

    def route_batch(self, tasks: Sequence[Any]) -> dict[str, str]:
        """Bulk-route tasks; results are cached and deterministic."""
        result: dict[str, str] = {}
        for task in tasks:
            decision = self.route_detailed(task)
            result[decision.task_id] = decision.capability
        return result

    def confidence(self, task: Any) -> float:
        """Expose routing confidence in ``[0, 1]``."""
        return self.route_detailed(task).confidence

    def route_detailed(self, task: Any) -> RouteDecision:
        """Full decision with scores, confidence, and human-review flag."""
        task_id = self._task_id(task)
        cache_key = self._cache_key(task)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        text = self._classification_text(task)
        phase = self._wbs_phase(task)
        scores = self._score(text, phase)
        capability, confidence, reason = self._select(scores)

        requires_human = confidence < self.confidence_threshold
        decision = RouteDecision(
            task_id=task_id,
            capability=capability,
            confidence=round(confidence, 4),
            scores={k: round(v, 4) for k, v in scores.items()},
            requires_human_review=requires_human,
            reason=reason,
        )
        self._cache[cache_key] = decision

        if self.human_gate is not None and requires_human:
            self.human_gate.submit(decision)

        return decision

    def clear_cache(self) -> None:
        self._cache.clear()

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score(self, text: str, phase: Optional[str]) -> dict[str, float]:
        scores = {cap: 0.0 for cap in CAPABILITIES}
        if text:
            for cap, patterns in self._compiled.items():
                for pattern, weight in patterns:
                    matches = pattern.findall(text)
                    if matches:
                        # Diminishing returns for repeated hits of the same pattern.
                        scores[cap] += weight * min(len(matches), 3)
        if phase:
            priors = _PHASE_PRIORS.get(phase.lower().strip(), {})
            for cap, prior in priors.items():
                if cap in scores:
                    scores[cap] += prior
        return scores

    def _select(self, scores: Mapping[str, float]) -> tuple[str, float, str]:
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        top_cap, top_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        total = sum(max(0.0, s) for s in scores.values())

        if top_score <= 0.0 or total <= 0.0:
            return (
                self.default_capability,
                0.0,
                "no_signals_default",
            )

        # Softmax-style confidence from the top share, penalised by ambiguity.
        share = top_score / total
        gap = (top_score - second_score) / top_score if top_score else 0.0
        confidence = share * (0.55 + 0.45 * min(1.0, gap / max(self.ambiguity_margin, 1e-6)))
        confidence = max(0.0, min(1.0, confidence))

        if gap < self.ambiguity_margin:
            reason = f"ambiguous_top={top_cap}_gap={gap:.3f}"
        else:
            reason = f"keyword_match_{top_cap}"

        return top_cap, confidence, reason

    # ------------------------------------------------------------------
    # Task field extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _task_id(task: Any) -> str:
        for name in ("task_id", "id"):
            if isinstance(task, Mapping) and name in task and task[name] is not None:
                return str(task[name])
            value = getattr(task, name, None)
            if value is not None:
                return str(value)
        return repr(task)

    @staticmethod
    def _field(task: Any, *names: str) -> str:
        for name in names:
            if isinstance(task, Mapping) and name in task and task[name] is not None:
                return str(task[name])
            value = getattr(task, name, None)
            if value is not None:
                return str(value)
        return ""

    def _classification_text(self, task: Any) -> str:
        parts = [
            self._field(task, "title", "name"),
            self._field(task, "description", "summary", "body"),
            self._field(task, "wbs_phase", "phase", "stage"),
        ]
        # Also fold metadata phase/tags if present.
        metadata = None
        if isinstance(task, Mapping):
            metadata = task.get("metadata")
        else:
            metadata = getattr(task, "metadata", None)
        if isinstance(metadata, Mapping):
            for key in ("phase", "wbs_phase", "tags", "labels"):
                if key in metadata and metadata[key] is not None:
                    parts.append(str(metadata[key]))
        return " ".join(p for p in parts if p).strip()

    def _wbs_phase(self, task: Any) -> Optional[str]:
        phase = self._field(task, "wbs_phase", "phase", "stage")
        if phase:
            return phase
        metadata = None
        if isinstance(task, Mapping):
            metadata = task.get("metadata")
        else:
            metadata = getattr(task, "metadata", None)
        if isinstance(metadata, Mapping):
            for key in ("wbs_phase", "phase", "stage"):
                if metadata.get(key):
                    return str(metadata[key])
        return None

    def _cache_key(self, task: Any) -> str:
        return (
            f"{self._task_id(task)}|"
            f"{self._classification_text(task).lower()}|"
            f"{(self._wbs_phase(task) or '').lower()}"
        )
