"""Compatibility entrypoint for the canonical DOR API application.

The application object lives in :mod:`api.main`.  Re-exporting it here keeps
``uvicorn main:app`` and ``python main.py`` operational without maintaining a
second, partially initialized runtime.
"""

from __future__ import annotations

from api.main import app

__all__ = ["app", "run"]


def run() -> None:
    """Run the canonical API with development-safe defaults."""
    import uvicorn

    uvicorn.run("api.main:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    run()
