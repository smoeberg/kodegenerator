"""Pure Danish greeting copy based on the Europe/Copenhagen clock."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


_COPENHAGEN = ZoneInfo("Europe/Copenhagen")


def greeting_for_hour(hour: int) -> str:
    """Return deterministic Danish greeting copy for a local clock hour."""
    if not 0 <= hour <= 23:
        raise ValueError("hour must be between 0 and 23")
    if 5 <= hour < 12:
        return "Godmorgen"
    if 12 <= hour < 18:
        return "God eftermiddag"
    return "Godaften"


def copenhagen_greeting(now: datetime | None = None) -> str:
    """Resolve the greeting against a Copenhagen-aware timestamp."""
    current = now.astimezone(_COPENHAGEN) if now is not None else datetime.now(_COPENHAGEN)
    return greeting_for_hour(current.hour)
