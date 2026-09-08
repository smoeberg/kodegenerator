"""Container-local liveness check for the DOR worker process."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, text

from services.runtime_secrets import materialize_runtime_secrets


def main() -> None:
    # Docker healthchecks run as fresh container processes and therefore do not
    # inherit environment values materialized inside PID 1 after startup.
    # Re-materialize file-backed production secrets before probing DATABASE_URL.
    materialize_runtime_secrets()

    command = Path("/proc/1/cmdline").read_bytes().replace(b"\x00", b" ")
    if b"services.worker_agent" not in command:
        raise RuntimeError("worker process is not PID 1")

    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
