"""Formalized dispute protocol requiring verifiable evidence or resolution."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from phase4.epistemics.engine import BeliefRevisionEngine
from phase4.epistemics.models import Evidence, Hypothesis
from .models import Dispute, DisputeStatus


class DisputeProtocolError(Exception):
    """Raised when an illegal operation is attempted on a dispute."""
    pass


class DisputeProtocol:
    """Manages disputes against hypotheses requiring verified evidence or resolution."""

    def __init__(self, belief_engine: Optional[BeliefRevisionEngine] = None) -> None:
        self.belief_engine = belief_engine or BeliefRevisionEngine()
        self._disputes: Dict[str, Dispute] = {}

    def raise_dispute(
        self,
        hypothesis: Hypothesis,
        raised_by_agent_id: str,
        reason: str,
        dispute_id: str | None = None,
    ) -> Dispute:
        """Create a new dispute attached to a hypothesis."""
        if not reason or not reason.strip():
            raise DisputeProtocolError("A dispute must contain a clear, non-empty reason.")

        normalized_reason = reason.strip()
        if dispute_id is not None and dispute_id in self._disputes:
            existing = self._disputes[dispute_id]
            if (
                existing.hypothesis_id == hypothesis.hypothesis_id
                and existing.raised_by_agent_id == raised_by_agent_id
                and existing.reason == normalized_reason
            ):
                return existing
            raise DisputeProtocolError(
                "A dispute ID cannot be reused with changed identity."
            )

        values = {
            "hypothesis_id": hypothesis.hypothesis_id,
            "raised_by_agent_id": raised_by_agent_id,
            "reason": normalized_reason,
            "status": DisputeStatus.OPEN,
        }
        if dispute_id is not None:
            values["dispute_id"] = dispute_id
        dispute = Dispute(
            **values,
        )
        self._disputes[dispute.dispute_id] = dispute
        return dispute

    def resolve_with_evidence(
        self,
        dispute_id: str,
        hypothesis: Hypothesis,
        evidence: Evidence,
        resolution_note: str,
    ) -> Dispute:
        """Resolve a dispute by attaching verified evidence and updating belief."""
        dispute = self.get_dispute(dispute_id)
        if dispute.status != DisputeStatus.OPEN:
            raise DisputeProtocolError(f"Cannot resolve dispute in status: {dispute.status}")

        if evidence.hypothesis_id != hypothesis.hypothesis_id:
            raise DisputeProtocolError(
                f"Evidence hypothesis_id ({evidence.hypothesis_id}) mismatch with hypothesis ({hypothesis.hypothesis_id})"
            )

        if not resolution_note or not resolution_note.strip():
            raise DisputeProtocolError("Resolution note is required when resolving with evidence.")

        # Re-evaluate hypothesis confidence through epistemic belief revision
        self.belief_engine.incorporate_evidence(hypothesis, evidence)

        dispute.resolving_evidence = evidence
        dispute.resolution_note = resolution_note.strip()
        dispute.status = DisputeStatus.RESOLVED
        dispute.resolved_at = datetime.now(timezone.utc)
        return dispute

    def dismiss_dispute(
        self,
        dispute_id: str,
        justification: str,
    ) -> Dispute:
        """Dismiss a dispute if formal criteria or counter-evidence invalidate it."""
        dispute = self.get_dispute(dispute_id)
        if dispute.status != DisputeStatus.OPEN:
            raise DisputeProtocolError(f"Cannot dismiss dispute in status: {dispute.status}")

        if not justification or len(justification.strip()) < 10:
            raise DisputeProtocolError("Formal dismissal requires a substantial justification (> 10 chars).")

        dispute.resolution_note = f"DISMISSED: {justification.strip()}"
        dispute.status = DisputeStatus.DISMISSED
        dispute.resolved_at = datetime.now(timezone.utc)
        return dispute

    def get_dispute(self, dispute_id: str) -> Dispute:
        """Fetch dispute by ID or raise error."""
        if dispute_id not in self._disputes:
            raise DisputeProtocolError(f"Dispute with ID {dispute_id} not found.")
        return self._disputes[dispute_id]

    def get_open_disputes_for_hypothesis(self, hypothesis_id: str) -> List[Dispute]:
        """Return all active, unresolved disputes for a specific hypothesis."""
        return [
            d for d in self._disputes.values()
            if d.hypothesis_id == hypothesis_id and d.status == DisputeStatus.OPEN
        ]

    def has_active_disputes(self, hypothesis_id: str) -> bool:
        """Check if any unresolved disputes exist for hypothesis."""
        return len(self.get_open_disputes_for_hypothesis(hypothesis_id)) > 0
