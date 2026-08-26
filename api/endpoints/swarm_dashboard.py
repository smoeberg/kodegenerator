"""FastAPI endpoints for the swarm operations dashboard."""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/v1/swarm/dashboard", tags=["swarm-dashboard"])


def _default_summary() -> dict[str, Any]:
    """Return a safe empty dashboard snapshot."""
    return {"active_workers": 0, "queue": {"pending": 0, "active": 0, "dlq": 0}, "approvals": 0, "cost": {"estimated_cost": 0, "prompt_tokens": 0, "completion_tokens": 0}, "projects": [], "workers": []}


@router.get("/summary")
async def summary(provider: Callable[[], dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return the current aggregate swarm summary."""
    return provider() if provider is not None else _default_summary()


async def _events(provider: Callable[[], dict[str, Any]] | None) -> AsyncIterator[str]:
    """Emit dashboard snapshots as server-sent events."""
    while True:
        payload = provider() if provider is not None else _default_summary()
        yield f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
        await asyncio.sleep(5)


@router.get("/events")
async def events(provider: Callable[[], dict[str, Any]] | None = None) -> StreamingResponse:
    """Stream live dashboard updates over SSE."""
    return StreamingResponse(_events(provider), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
