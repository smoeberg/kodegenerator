"""Machine-derived inventory for the mounted DOR API surface.

The inventory deliberately consumes ``FastAPI.routes`` so the source of truth is
what the application actually mounts, rather than hand-maintained endpoint
notes. Importing this module alone has no application side effects.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import json
from pathlib import Path
from typing import Any, Iterable

from fastapi.routing import APIRoute
from starlette.routing import BaseRoute, WebSocketRoute


@dataclass(frozen=True, order=True)
class EndpointRecord:
    """Stable representation of one mounted HTTP or WebSocket operation."""

    path: str
    method: str
    name: str
    module: str
    tags: tuple[str, ...]


def _flatten_routes(routes: Iterable[BaseRoute]) -> list[BaseRoute]:
    """Recursively extract all nested routes from FastAPI routers."""
    flat: list[BaseRoute] = []
    for route in routes:
        if hasattr(route, "routes"):
            flat.extend(_flatten_routes(route.routes))
        elif hasattr(route, "original_router") and hasattr(route.original_router, "routes"):
            flat.extend(_flatten_routes(route.original_router.routes))
        else:
            flat.append(route)
    return flat


def build_inventory(routes: Iterable[BaseRoute]) -> list[EndpointRecord]:
    """Build a deterministic inventory from the application's mounted routes."""
    flat_routes = _flatten_routes(routes)
    records: list[EndpointRecord] = []
    seen_keys: set[tuple[str, str]] = set()

    for route in flat_routes:
        if isinstance(route, APIRoute):
            for method in sorted(route.methods):
                method_upper = method.upper()
                key = (route.path, method_upper)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                records.append(
                    EndpointRecord(
                        path=route.path,
                        method=method_upper,
                        name=route.name,
                        module=getattr(route.endpoint, "__module__", ""),
                        tags=tuple(sorted(getattr(route, "tags", None) or ())),
                    )
                )
        elif isinstance(route, WebSocketRoute):
            key = (route.path, "WEBSOCKET")
            if key in seen_keys:
                continue
            seen_keys.add(key)
            records.append(
                EndpointRecord(
                    path=route.path,
                    method="WEBSOCKET",
                    name=route.name,
                    module=getattr(route.endpoint, "__module__", ""),
                    tags=tuple(sorted(getattr(route, "tags", None) or ())),
                )
            )
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="docs/api-endpoint-inventory.json")
    args = parser.parse_args()

    # Import the application only when generation is explicitly requested.
    from api.main import app

    write_inventory(app, args.output)


if __name__ == "__main__":
    main()
