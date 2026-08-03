# runtime/model_registry.py
from typing import Dict, List, Optional
from domain.model import Model, ModelProvider

class ModelRegistry:
    """Centraliseret registrering af tilgængelige LLM-modeller."""

    def __init__(self):
        self.models: Dict[str, Model] = {}  # model_id → Model

    def add_model(self, model: Model) -> None:
        """Tilføj en model til registret."""
        if model.id not in self.models:
            self.models[model.id] = model

    def get_model(self, model_id: str) -> Optional[Model]:
        """Hent en model ud fra ID."""
        return self.models.get(model_id)

    def get_models_by_capability(self, capability: str) -> List[Model]:
        """Hent alle modeller, der understøtter en given evne."""
        return [
            model for model in self.models.values()
            if capability in model.capabilities
        ]

    def get_models_by_provider(self, provider: ModelProvider) -> List[Model]:
        """Hent alle modeller fra en given udbyder."""
        return [
            model for model in self.models.values()
            if model.provider == provider
        ]

    def get_best_model(self, capabilities: List[str], constraints: Dict = None) -> Optional[Model]:
        """
        Hent den bedste model baseret på:
        - Understøttede capabilities
        - Omkostninger (hvis constraints angiver max_cost)
        - Latency (hvis constraints angiver max_latency)
        - Kvalitet (hvis constraints angiver min_quality)
        """
        candidates = [
            model for model in self.models.values()
            if all(cap in model.capabilities for cap in capabilities)
        ]

        if not candidates:
            return None

        # Filtrér baseret på constraints
        if constraints:
            if "max_cost" in constraints:
                candidates = [
                    model for model in candidates
                    if model.cost_per_token <= constraints["max_cost"]
                ]
            if "max_latency" in constraints:
                candidates = [
                    model for model in candidates
                    if model.latency <= constraints["max_latency"]
                ]
            if "min_quality" in constraints:
                candidates = [
                    model for model in candidates
                    if model.quality_score >= constraints["min_quality"]
                ]

        if not candidates:
            return None

        # Rank modeller (højeste score vinder)
        ranked = sorted(
            candidates,
            key=lambda m: (
                m.quality_score * 0.4 +
                (1.0 - m.cost_per_token) * 0.3 +
                (1.0 - m.latency / 10.0) * 0.2 +
                m.reliability * 0.1
            ),
            reverse=True
        )
        return ranked[0]
