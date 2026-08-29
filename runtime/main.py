"""DOR Runtime entrypoint.

Initializes the database schema and launches the FastAPI Uvicorn server.
"""

from __future__ import annotations

import logging
import os

import uvicorn

from runtime.core import DORRuntime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("runtime.main")


def main() -> None:
    # Safe local default. Container/orchestrator deployments must opt in to an
    # externally reachable listener with DOR_HOST=0.0.0.0.
    host = os.environ.get("DOR_HOST", "127.0.0.1")
    port = int(os.environ.get("DOR_PORT", "8000"))
    
    logger.info("Applying and verifying DOR database migrations...")
    runtime = DORRuntime(os.environ.get("DATABASE_URL", "sqlite:///./dor_runtime.db"))
    # Deliberately fail closed. Uvicorn must never start when connectivity,
    # credentials or the canonical Alembic migration fails.
    runtime.boot()
    logger.info("Database migrations verified successfully.")

    logger.info(f"Starting DOR runtime server on http://{host}:{port}")
    uvicorn.run("api.main:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
