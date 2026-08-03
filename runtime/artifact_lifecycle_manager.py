# runtime/artifact_lifecycle_manager.py
from typing import Dict, List, Optional
from domain.artifact import Artifact, ArtifactState, ArtifactType
from domain.actor import Actor
from domain.event import Event, EventType
from runtime.event_bus import EventBus

class ArtifactLifecycleManager:
    """Håndterer livscyklussen for Artefakter (oprettelse, godkendelse, arkivering)."""

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.artifacts: Dict[str, Artifact] = {}  # artifact_id → Artifact

    def create_artifact(
        self,
        artifact_type: ArtifactType,
        owner: Actor,
        department_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        **kwargs
    ) -> Artifact:
        """Opret et nyt Artefakt."""
        artifact_id = f"artifact_{len(self.artifacts) + 1}"
        artifact = Artifact(
            id=artifact_id,
            version="1.0.0",
            artifact_type=artifact_type,
            owner=owner,
            department_id=department_id,
            workflow_id=workflow_id,
            **kwargs
        )
        self.artifacts[artifact_id] = artifact
        self._emit_event(
            EventType.ARTIFACT_CREATED,
            actor=owner,
            artifact=artifact
        )
        return artifact

    def submit_artifact(self, artifact_id: str, actor: Actor) -> bool:
        """Indsend et Artefakt til review."""
        artifact = self.artifacts.get(artifact_id)
        if not artifact:
            return False
        if artifact.state != ArtifactState.DRAFT:
            return False
        artifact.state = ArtifactState.SUBMITTED
        self._emit_event(
            EventType.ARTIFACT_CREATED,  # Eller en ny EventType: ARTIFACT_SUBMITTED
            actor=actor,
            artifact=artifact
        )
        return True

    def approve_artifact(self, artifact_id: str, actor: Actor, role_id: str) -> bool:
        """Godkend et Artefakt."""
        artifact = self.artifacts.get(artifact_id)
        if not artifact:
            return False
        if artifact.state != ArtifactState.SUBMITTED and artifact.state != ArtifactState.IN_REVIEW:
            return False
        artifact.add_signature(Signature(
            role_id=role_id,
            actor_id=actor.id,
            status="approved"
        ))
        # Tjek om alle nødvendige godkendelser er modtaget
        if self._is_fully_approved(artifact):
            artifact.state = ArtifactState.APPROVED
            self._emit_event(
                EventType.ARTIFACT_APPROVED,
                actor=actor,
                artifact=artifact
            )
        else:
            artifact.state = ArtifactState.IN_REVIEW
        return True

    def reject_artifact(self, artifact_id: str, actor: Actor, role_id: str, reason: str) -> bool:
        """Afvis et Artefakt."""
        artifact = self.artifacts.get(artifact_id)
        if not artifact:
            return False
        if artifact.state != ArtifactState.SUBMITTED and artifact.state != ArtifactState.IN_REVIEW:
            return False
        artifact.add_signature(Signature(
            role_id=role_id,
            actor_id=actor.id,
            status="rejected",
            comments=reason
        ))
        artifact.state = ArtifactState.REJECTED
        self._emit_event(
            EventType.ARTIFACT_REJECTED,
            actor=actor,
            artifact=artifact,
            metadata={"reason": reason}
        )
        return True

    def _is_fully_approved(self, artifact: Artifact) -> bool:
        """Tjek om alle nødvendige godkendelser er modtaget."""
        # Simplificeret: Antag, at alle signaturer skal være "approved"
        return all(sig.status == "approved" for sig in artifact.signatures)

    def _emit_event(self, event_type: EventType, **kwargs) -> None:
        """Udsend et Event via EventBus."""
        event = Event(
            id=f"event_{len(self.event_bus.events) + 1}",
            event_type=event_type,
            **kwargs
        )
        self.event_bus.publish(event)
