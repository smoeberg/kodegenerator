# runtime/capability_registry.py
from typing import Dict, List, Optional
from domain.capability import Capability, CapabilityLevel
from domain.actor import Actor

class CapabilityRegistry:
    """Centraliseret registrering af alle Capabilities."""

    def __init__(self):
        self.capabilities: Dict[str, Capability] = {}  # capability_id → Capability
        self.actor_capabilities: Dict[str, List[str]] = {}  # actor_id → Liste af Capability-ID'er

    def add_capability(self, capability: Capability) -> None:
        """Tilføj en Capability til registret."""
        if capability.id not in self.capabilities:
            self.capabilities[capability.id] = capability

    def get_capability(self, capability_id: str) -> Optional[Capability]:
        """Hent en Capability ud fra ID."""
        return self.capabilities.get(capability_id)

    def register_actor_capability(self, actor_id: str, capability_id: str) -> None:
        """Registrer en Capability for en Actor."""
        if actor_id not in self.actor_capabilities:
            self.actor_capabilities[actor_id] = []
        if capability_id not in self.actor_capabilities[actor_id]:
            self.actor_capabilities[actor_id].append(capability_id)

    def get_actor_capabilities(self, actor_id: str) -> List[Capability]:
        """Hent alle Capabilities for en Actor."""
        if actor_id not in self.actor_capabilities:
            return []
        return [
            self.capabilities[cap_id]
            for cap_id in self.actor_capabilities[actor_id]
            if cap_id in self.capabilities
        ]

    def get_actors_by_capability(self, capability_id: str) -> List[str]:
        """Hent alle Actors, der har en given Capability."""
        return [
            actor_id for actor_id, caps in self.actor_capabilities.items()
            if capability_id in caps
        ]
