"""Deliberation engine coordinating specialist AI agents."""
from __future__ import annotations

import hashlib
import json
from typing import Optional

from domain.council_agents import AgentPosition, AgentRole, DeliberationAgenda
from domain.decision import AgentVote, Decision, DecisionAlternative, DecisionCategory, RiskLevel


class DeliberationEngine:
    """Coordinates council deliberation between specialized AI agents."""

    def __init__(self) -> None:
        pass

    def calculate_provenance(self, agenda: DeliberationAgenda, positions: list[AgentPosition]) -> str:
        payload = {
            "agenda_id": agenda.agenda_id,
            "topic": agenda.topic,
            "positions": [p.model_dump() for p in positions],
        }
        raw = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    def deliberate_and_synthesize(
        self,
        agenda: DeliberationAgenda,
        positions: list[AgentPosition],
        *,
        category: DecisionCategory = DecisionCategory.ARCHITECTURE,
        risk_level: RiskLevel = RiskLevel.HIGH,
    ) -> Decision:
        """Synthesize positions into a structured Decision candidate for human/gate review."""
        if not positions:
            raise ValueError("Deliberation requires at least one agent position")

        # Check for vetos
        vetoes = [p for p in positions if p.veto]

        # Normalize options to uppercase keys matching DecisionAlternative validation
        normalized_options = [opt.strip().upper() for opt in agenda.options]

        # Compute votes and scores per alternative
        score_by_alt: dict[str, float] = {opt: 0.0 for opt in normalized_options}
        votes: list[AgentVote] = []
        risks_by_alt: dict[str, list[str]] = {opt: [] for opt in normalized_options}

        for pos in positions:
            pos_key = pos.preferred_alternative.strip().upper()
            pos_hash = hashlib.sha256(f"{pos.agent_id}:{pos_key}:{pos.reasoning}".encode()).hexdigest()
            votes.append(
                AgentVote(
                    agent_id=pos.agent_id,
                    selected_alternative=pos_key,
                    argument=pos.reasoning,
                    confidence=pos.confidence,
                    risk_level=RiskLevel.HIGH if pos.veto else RiskLevel.LOW,
                    provenance_id=pos_hash,
                )
            )
            if pos_key in score_by_alt:
                score_by_alt[pos_key] += pos.confidence
            for risk in pos.identified_risks:
                if pos_key in risks_by_alt:
                    risks_by_alt[pos_key].append(risk)

        # Build alternatives
        alternatives: list[DecisionAlternative] = []
        for orig_opt, norm_opt in zip(agenda.options, normalized_options):
            has_veto = any(v.preferred_alternative.strip().upper() == norm_opt for v in vetoes)
            alternatives.append(
                DecisionAlternative(
                    key=norm_opt,
                    title=f"Option {orig_opt}",
                    description=f"Adopt strategy: {orig_opt}",
                    pros=[f"Supported by score {score_by_alt.get(norm_opt, 0.0):.2f}"],
                    cons=risks_by_alt.get(norm_opt, []),
                    risks=risks_by_alt.get(norm_opt, []),
                    risk_level=RiskLevel.CRITICAL if has_veto else RiskLevel.LOW,
                )
            )

        provenance_id = self.calculate_provenance(agenda, positions)

        return Decision(
            decision_id=f"dec-{agenda.agenda_id}",
            project_id=agenda.project_id,
            category=category,
            risk_level=risk_level,
            question=f"Choose strategy for: {agenda.topic}",
            alternatives=alternatives,
            agent_votes=votes,
            provenance_id=provenance_id,
        )
