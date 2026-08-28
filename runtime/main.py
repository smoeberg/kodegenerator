"""DOR Runtime entrypoint.

Initializes the database schema and launches the FastAPI Uvicorn server.
"""

from __future__ import annotations

import logging
import os
import sys
import uvicorn

from infrastructure.persistence.database import Database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("runtime.main")


def main() -> None:
    host = os.environ.get("DOR_HOST", "0.0.0.0")
    port = int(os.environ.get("DOR_PORT", "8000"))
    
    logger.info("Initializing DOR Database schema...")
    try:
        db = Database()
        db.create_all()
        logger.info("Database schema initialized successfully.")
    except Exception as e:
        logger.warning(f"Database schema init notice: {e}")

    logger.info(f"Starting DOR runtime server on http://{host}:{port}")
    uvicorn.run("api.main:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
