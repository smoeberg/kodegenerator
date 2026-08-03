# runtime/governance_engine.py
from typing import Dict, List, Optional
from domain.artifact import Artifact, ArtifactState
from domain.actor import Actor
from domain.governance import GovernanceDepartment
from domain.event import Event, EventType
from runtime.event_bus import EventBus

class GovernanceEngine:
    """Håndhæver governance-regler via Boards (Architecture, Security, etc.)."""

    def __init__(self, governance: GovernanceDepartment, event_bus: EventBus):
        self.governance = governance
        self.event_bus = event_bus

    def request_approval(
        self,
        artifact: Artifact,
        board_name: str,
        actor: Actor
    ) -> bool:
        """Anmod om godkendelse fra et bestemt Board."""
        board = self.governance.get_board(board_name)
        if not board:
            return False

        # Tjek om Actor har lov til at anmode om godkendelse
        if not actor.can_perform("request_approval"):
            return False

        # Tilføj en signatur (som "pending")
        artifact.add_signature(Signature(
            role_id=f"{board_name}_reviewer",
            actor_id=actor.id,
            status="pending"
        ))

        self._emit_event(
            EventType.GOVERNANCE_APPROVAL,
            actor=actor,
            artifact=artifact,
            metadata={"board": board_name, "status": "requested"}
        )
        return True

    def approve_artifact(
        self,
        artifact: Artifact,
        board_name: str,
        actor: Actor
    ) -> bool:
        """Godkend et Artefakt via et Board."""
        board = self.governance.get_board(board_name)
        if not board:
            return False

        # Tjek om Actor er medlem af Boardet
        if actor not in board:
            return False

        # Godkend Artefaktet
        artifact.add_signature(Signature(
            role_id=f"{board_name}_reviewer",
            actor_id=actor.id,
            status="approved"
        ))

        # Tjek om alle medlemmer af Boardet har godkendt
        if self.governance.approve_artifact(artifact, board_name):
            artifact.state = ArtifactState.APPROVED
            self._emit_event(
                EventType.ARTIFACT_APPROVED,
                actor=actor,
                artifact=artifact,
                metadata={"board": board_name, "status": "approved"}
            )
        else:
            artifact.state = ArtifactState.IN_REVIEW
            self._emit_event(
                EventType.ARTIFACT_APPROVED,  # Eller en ny EventType: ARTIFACT_PARTIALLY_APPROVED
                actor=actor,
                artifact=artifact,
                metadata={"board": board_name, "status": "partially_approved"}
            )
        return True

    def _emit_event(self, event_type: EventType, **kwargs) -> None:
        """Udsend et Event via EventBus."""
        event = Event(
            id=f"event_{len(self.event_bus.events) + 1}",
            event_type=event_type,
            **kwargs
        )
        self.event_bus.publish(event)
