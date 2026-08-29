"""Compatibility entrypoint for the canonical DOR API application.

The application object lives in :mod:`api.main`.  Re-exporting it here keeps
``uvicorn main:app`` and ``python main.py`` operational without maintaining a
second, partially initialized runtime.
"""

from __future__ import annotations

from api.main import app

__all__ = ["app", "run"]


def run() -> None:
    """Run the canonical API with development-safe defaults.

    Bind defaults match ``runtime.main``: loopback unless ``DOR_HOST`` /
    ``DOR_PORT`` opt into a wider listener (containers should set
    ``DOR_HOST=0.0.0.0`` explicitly, as the Dockerfile already does via
    uvicorn CLI).
    """
    import os

    import uvicorn

    host = os.environ.get("DOR_HOST", "127.0.0.1")
    port = int(os.environ.get("DOR_PORT", "8000"))
    uvicorn.run("api.main:app", host=host, port=port)


if __name__ == "__main__":
    run()
