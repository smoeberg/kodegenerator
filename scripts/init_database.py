#!/usr/bin/env python3
"""Vent på PostgreSQL database er klar.

PostgreSQL Docker container opretter allerede databasen og brugeren automatisk
baseret på POSTGRES_DB, POSTGRES_USER og POSTGRES_PASSWORD miljøvariable.
Dette script venter blot på at databasen er klar til forbindelse.

Bruger DATABASE_URL som single source of truth for alle database credentials.
"""

import os
import time
import psycopg
from urllib.parse import urlparse


def get_db_params():
    """Parse database forbindelsesparametre fra DATABASE_URL."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL er ikke sat i miljøvariable")

    parsed = urlparse(db_url)

    if parsed.scheme not in ("postgresql", "postgresql+psycopg"):
        raise RuntimeError(
            f"DATABASE_URL skal starte med postgresql:// eller postgresql+psycopg://, got: {parsed.scheme}"
        )

    return {
        "host": parsed.hostname or "postgres",
        "port": parsed.port or 5432,
        "user": parsed.username or "dor",
        "password": parsed.password or "",
        "dbname": parsed.path.lstrip("/") or "dor"
    }


def wait_for_postgres(max_attempts=30, interval=2):
    """Vent på at PostgreSQL serveren og databasen er klar til forbindelse."""
    params = get_db_params()

    for attempt in range(max_attempts):
        try:
            # Forbind direkte til den database der skal bruges
            # PostgreSQL container har allerede oprettet den baseret på POSTGRES_DB
            conn = psycopg.connect(
                host=params["host"],
                port=params["port"],
                user=params["user"],
                password=params["password"],
                dbname=params["dbname"],
                connect_timeout=5
            )
            conn.close()
            print(f"✅ PostgreSQL database '{params['dbname']}' er klar")
            return True
        except Exception as e:
            print(f"⏳ Venter på PostgreSQL (forsøg {attempt + 1}/{max_attempts}): {e}")
            time.sleep(interval)
    
    raise RuntimeError("PostgreSQL startede ikke i tide - tjek container logs")


if __name__ == "__main__":
    print("🚀 Venter på PostgreSQL database...")
    wait_for_postgres()
    print("✨ PostgreSQL er klar - database oprettet af container")
