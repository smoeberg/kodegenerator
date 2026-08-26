"""Compatibility process entrypoint for the canonical :mod:`api.main` app."""

from api.main import app

__all__ = ["app", "run"]


def run() -> None:
    import uvicorn

    uvicorn.run("api.main:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    run()
