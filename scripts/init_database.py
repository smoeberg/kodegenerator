#!/usr/bin/env python3
"""Vent på PostgreSQL database er klar.

PostgreSQL Docker container opretter allerede databasen og brugeren automatisk
baseret på POSTGRES_DB, POSTGRES_USER og POSTGRES_PASSWORD miljøvariable.
Dette script venter blot på at databasen er klar til forbindelse.

Bruger direkte miljøvariable (POSTGRES_*) for at undgå URL parsing problemer
med specialtegn i passwordet.
"""

import os
import time
import psycopg


def wait_for_postgres(max_attempts=30, interval=2):
    """Vent på at PostgreSQL serveren og databasen er klar til forbindelse."""
    dbname = os.environ.get("POSTGRES_DB", "dor")
    user = os.environ.get("POSTGRES_USER", "dor")
    password = os.environ.get("POSTGRES_PASSWORD")
    host = os.environ.get("POSTGRES_HOST", "postgres")

    if not password:
        raise RuntimeError("POSTGRES_PASSWORD er ikke sat i miljøvariable")

    for attempt in range(max_attempts):
        try:
            # Forbind direkte til den database der skal bruges
            # PostgreSQL container har allerede oprettet den baseret på POSTGRES_DB
            conn = psycopg.connect(
                host=host,
                port=5432,
                user=user,
                password=password,
                dbname=dbname,
                connect_timeout=5
            )
            conn.close()
            print(f"✅ PostgreSQL database '{dbname}' er klar")
            return True
        except Exception as e:
            print(f"⏳ Venter på PostgreSQL (forsøg {attempt + 1}/{max_attempts}): {e}")
            time.sleep(interval)
    
    raise RuntimeError("PostgreSQL startede ikke i tide - tjek container logs")


if __name__ == "__main__":
    print("🚀 Venter på PostgreSQL database...")
    wait_for_postgres()
    print("✨ PostgreSQL er klar - database oprettet af container")
