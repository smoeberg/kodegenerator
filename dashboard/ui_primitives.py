"""Shared presentation primitives for the canonical Streamlit Control Plane.

The helpers in this module are deliberately presentation-only. They format
backend-owned values for operators but never infer workflow authority or mutate
canonical state.
"""
from __future__ import annotations

from datetime import datetime, timezone

_STATUS_LABELS = {
    "approved": "✅ APPROVED",
    "resolved": "✅ RESOLVED",
    "released": "✅ RELEASED",
    "completed": "✅ COMPLETED",
    "success": "✅ SUCCESS",
    "succeeded": "✅ SUCCEEDED",
    "ready": "✅ READY",
    "none": "✅ NO ACTION REQUIRED",
    "terminal": "✅ TERMINAL",
    "rejected": "🛑 REJECTED",
    "failed": "🛑 FAILED",
    "error": "🛑 ERROR",
    "blocking": "🛑 BLOCKING",
    "human_required": "⚠️ HUMAN REQUIRED",
    "human_decision": "⚠️ HUMAN DECISION",
    "pending": "⏳ PENDING",
    "queued": "⏳ QUEUED",
    "running": "🔄 RUNNING",
    "in_progress": "🔄 IN PROGRESS",
    "work_in_progress": "🔄 WORK IN PROGRESS",
    "rework_active": "🛠️ REWORK ACTIVE",
    "cancelled": "⚪ CANCELLED",
    "unknown": "⚪ UNKNOWN",
}


def format_timestamp(value: object) -> str:
    """Format an ISO timestamp consistently; preserve unknown raw values."""
    raw = str(value or "").strip()
    if not raw:
        return "—"

    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return raw

    if parsed.tzinfo is None:
        return parsed.strftime("%Y-%m-%d · %H:%M")

    normalized = parsed.astimezone(timezone.utc)
    return normalized.strftime("%Y-%m-%d · %H:%M UTC")


def status_badge(value: object, *, blocking: bool = False) -> str:
    """Return a compact, consistent text badge for a backend-owned status."""
    normalized = (
        str(value or "unknown")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )
    label = _STATUS_LABELS.get(normalized)
    if label is None:
        readable = normalized.replace("_", " ").upper() or "UNKNOWN"
        label = f"⚪ {readable}"
    if blocking and "BLOCKING" not in label:
        label = f"{label} · 🛑 BLOCKING"
    return label


def count_label(value: object, singular: str, plural: str | None = None) -> str:
    """Format a safe count label for empty/result summaries."""
    try:
        count = max(0, int(value))
    except (TypeError, ValueError):
        count = 0
    noun = singular if count == 1 else (plural or f"{singular}s")
    return f"{count} {noun}"
