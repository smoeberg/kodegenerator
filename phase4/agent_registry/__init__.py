"""DOR Phase 4 AI-1: Agent Registry.

Identity and registry primitives only. Authorization belongs to AI-3.
"""

from .models import AgentIdentity, AgentRecord, AgentRole, AgentVersion, Capability
from .registry import AgentRegistry, AgentNotFoundError, DuplicateIdentityError, RegistrationError
from .bot_profiles import (
    BotBudgetPolicy,
    BotDataPolicy,
    BotProfile,
    ModelDeployment,
    ProviderConnection,
)

__all__ = [
    "AgentIdentity",
    "AgentRecord",
    "AgentRole",
    "AgentVersion",
    "Capability",
    "AgentRegistry",
    "AgentNotFoundError",
    "DuplicateIdentityError",
    "RegistrationError",
    "BotBudgetPolicy",
    "BotDataPolicy",
    "BotProfile",
    "ModelDeployment",
    "ProviderConnection",
]
