"""Compatibility process entrypoint for the canonical :mod:`api.main` app."""

import os

from api.main import app

__all__ = ["app", "run"]


def run() -> None:
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host=os.environ.get("DOR_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("DOR_API_PORT", "8000")),
    )


if __name__ == "__main__":
    run()
