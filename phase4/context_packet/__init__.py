"""AI-2 Context Packet Engine.

AI-2 assembles deterministic, bounded context packets for agents. It does not
make authorization or execution decisions; those remain AI-3/AI-4 concerns.
"""

from .models import ContextItem, ContextPacket, ContextRequest
from .engine import ContextPacketEngine, ContextError, ContextLimitError, ContextSourceError

__all__ = [
    "ContextItem",
    "ContextPacket",
    "ContextRequest",
    "ContextPacketEngine",
    "ContextError",
    "ContextLimitError",
    "ContextSourceError",
]

__version__ = "4.0.0"
