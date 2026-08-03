# domain/model.py
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
from enum import Enum, auto

class ModelProvider(Enum):
    """Udbyder af LLM'er."""
    OPENAI = "OpenAI"
    ANTHROPIC = "Anthropic"
    DEEPSEEK = "DeepSeek"
    GOOGLE = "Google"
    MISTRAL = "Mistral"
    LOCAL = "Local"  # For lokale modeller (f.eks. Ollama)

@dataclass
class Model:
    """Repræsenterer en LLM-model (f.eks. GPT-5, Claude-3)."""
    id: str  # f.eks. "gpt-5"
    name: str  # f.eks. "GPT-5"
    provider: ModelProvider
    capabilities: List[str] = field(default_factory=list)  # f.eks. ["Python", "Code Review"]
    cost_per_token: float = 0.0  # Pris per token (input + output)
    latency: float = 0.0  # Forventet latency (sekunder)
    max_tokens: int = 0  # Maksimalt antal tokens pr. kald
    context_size: int = 0  # Maksimal kontekststørrelse
    quality_score: float = 0.0  # Kvalitetsscore (0-1)
    reliability: float = 0.0  # Pålidelighed (0-1)
    availability: float = 0.0  # Tilgængelighed (0-1)
    certifications: List[str] = field(default_factory=list)  # f.eks. ["Enterprise Ready"]
    api_key: Optional[str] = None  # API-nøgle (skal gemmes sikkert)
    api_url: Optional[str] = None  # API-endpoint (f.eks. "https://api.openai.com/v1")
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
