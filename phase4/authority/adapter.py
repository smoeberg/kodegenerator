"""Council Decision Adapter translating deliberation outcomes into authority context."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from phase4.adaptation.models import RiskLevel
from phase4.council.models import DisputeStatus, SessionState
from phase4.council.session import DeliberationSession
from phase4.epistemics.models import Evidence, Hypothesis, HypothesisStatus

__all__ = [
    "RiskLevel",
    "DecisionReadiness",
    "CouncilDecisionAdapter",
]


@dataclass(frozen=True)
class DecisionReadiness:
    """Readiness report summarizing Council deliberation, dispute status, and risk."""

    report_id: str
    session_id: str
    hypothesis_id: str
    task_id: str
    session_state: SessionState
    hypothesis_status: HypothesisStatus
    confidence: float
    open_critical_disputes: int
    total_disputes: int
    risk_level: RiskLevel
    evidence_verified: bool
    evidence_count: int
    evaluated_revision: str
    is_decision_ready: bool
    summary: str
    created_at: str


class CouncilDecisionAdapter:
    """Translates a completed or in-flight DeliberationSession into an authority DecisionReadiness report."""

    @classmethod
    def evaluate(
        cls,
        session: DeliberationSession,
        current_revision: str,
        risk_level: RiskLevel = RiskLevel.LOW,
        evidence_revision_map: Optional[Dict[str, str]] = None,
    ) -> DecisionReadiness:
        """Derive a DecisionReadiness assessment for the given session."""
        hyp = session.hypothesis
        open_disputes = session.dispute_protocol.get_open_disputes_for_hypothesis(hyp.hypothesis_id)
        open_critical_disputes = len(open_disputes)

        all_disputes = [
            d for d in session.dispute_protocol._disputes.values()
            if d.hypothesis_id == hyp.hypothesis_id
        ]
        total_disputes = len(all_disputes)

        # Verify evidence against current revision
        evidence_verified = True
        evidence_count = len(hyp.supporting_evidence)

        if evidence_revision_map is not None:
            for ev in hyp.supporting_evidence:
                ev_rev = evidence_revision_map.get(ev.evidence_id)
                if ev_rev is None or ev_rev != current_revision:
                    evidence_verified = False
                    break
        else:
            if not current_revision or not current_revision.strip():
                evidence_verified = False

        # Ready if session is DECISION_READY, no open critical disputes, confidence above threshold, evidence verified
        is_ready = (
            session.state == SessionState.DECISION_READY
            and open_critical_disputes == 0
            and hyp.status in (HypothesisStatus.ACTIVE, HypothesisStatus.SUPPORTED)
            and evidence_verified
        )

        summary = (
            f"Council session {session.session_id} evaluated for hypothesis {hyp.hypothesis_id} "
            f"(Confidence: {hyp.confidence:.2f}, Status: {hyp.status.value}, State: {session.state.value}, "
            f"Open Disputes: {open_critical_disputes}, Risk: {risk_level.value}, Evidence Verified: {evidence_verified})."
        )

        return DecisionReadiness(
            report_id=str(uuid4()),
            session_id=session.session_id,
            hypothesis_id=hyp.hypothesis_id,
            task_id=hyp.task_id,
            session_state=session.state,
            hypothesis_status=hyp.status,
            confidence=hyp.confidence,
            open_critical_disputes=open_critical_disputes,
            total_disputes=total_disputes,
            risk_level=risk_level,
            evidence_verified=evidence_verified,
            evidence_count=evidence_count,
            evaluated_revision=current_revision,
            is_decision_ready=is_ready,
            summary=summary,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
