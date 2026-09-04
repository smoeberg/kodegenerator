"""Machine-derived inventory for the mounted DOR API surface.

The inventory deliberately consumes ``FastAPI.routes`` so the source of truth is
what the application actually mounts, rather than hand-maintained endpoint
notes. Importing this module alone has no application side effects.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Iterable

from fastapi.routing import APIRoute
from starlette.routing import BaseRoute
from starlette.routing import WebSocketRoute


@dataclass(frozen=True, order=True)
class EndpointRecord:
    """Stable representation of one mounted HTTP or WebSocket operation."""

    path: str
    method: str
    name: str
    module: str
    tags: tuple[str, ...]


def _route_record(route: BaseRoute) -> EndpointRecord | None:
    if isinstance(route, APIRoute):
        methods = sorted(method.upper() for method in route.methods)
        # APIRoute normally contains one or more methods. Emit one record per
        # method so path+method is the unique operation key.
        return EndpointRecord(
            path=route.path,
            method=methods[0] if len(methods) == 1 else ",".join(methods),
            name=route.name,
            module=getattr(route.endpoint, "__module__", ""),
            tags=tuple(sorted(route.tags or ())),
        )
    if isinstance(route, WebSocketRoute):
        return EndpointRecord(
            path=route.path,
            method="WEBSOCKET",
            name=route.name,
            module=getattr(route.endpoint, "__module__", ""),
            tags=tuple(sorted(route.tags or ())),
        )
    return None


def build_inventory(routes: Iterable[BaseRoute]) -> list[EndpointRecord]:
    """Build a deterministic inventory from the application's mounted routes."""
    records: list[EndpointRecord] = []
    for route in routes:
        record = _route_record(route)
        if record is None:
            continue
        # APIRoute can expose multiple methods. Expand those into individual
        # path+method records instead of relying on the route's method set.
        if isinstance(route, APIRoute) and len(route.methods) > 1:
            for method in sorted(route.methods):
                records.append(
                    EndpointRecord(
                        path=route.path,
                        method=method.upper(),
                        name=route.name,
                        module=getattr(route.endpoint, "__module__", ""),
                        tags=tuple(sorted(route.tags or ())),
                    )
                )
        else:
            records.append(record)
    return sorted(records)


def inventory_payload(routes: Iterable[BaseRoute]) -> dict[str, Any]:
    """Return a JSON-serializable deterministic inventory payload."""
    records = build_inventory(routes)
    keys = [(record.path, record.method) for record in records]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate mounted endpoint path+method detected")
    return {
        "schema_version": 1,
        "source": "FastAPI app.routes",
        "count": len(records),
        "endpoints": [asdict(record) for record in records],
    }


def write_inventory(app: Any, destination: str | Path) -> Path:
    """Write the mounted-route inventory for CI or documentation generation."""
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = inventory_payload(app.routes)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
