#!/usr/bin/env python3
"""Automatisk database initialisering for DOR.

Dette script:
1. Venter på at PostgreSQL er klar
2. Opretter databasen hvis den ikke eksisterer
3. Sikrer at brugeren har adgang til databasen

Bruger DATABASE_URL som single source of truth for alle database credentials.
"""

import os
import time
import psycopg
from psycopg.sql import SQL
from urllib.parse import urlparse


def get_db_params():
    """Parse database forbindelsesparametre fra DATABASE_URL."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL er ikke sat i miljøvariable")

    parsed = urlparse(db_url)

    # Forventet format: postgresql+psycopg://user:password@host:port/database
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
    """Vent på at PostgreSQL serveren er klar til forbindelse."""
    params = get_db_params()

    for attempt in range(max_attempts):
        try:
            conn = psycopg.connect(
                host=params["host"],
                port=params["port"],
                user=params["user"],
                password=params["password"],
                dbname="postgres",  # Forbind til default database for at oprette ny
                connect_timeout=5
            )
            conn.close()
            print("✅ PostgreSQL server er klar")
            return True
        except Exception as e:
            print(f"⏳ Venter på PostgreSQL (forsøg {attempt + 1}/{max_attempts}): {e}")
            time.sleep(interval)
    
    raise RuntimeError("PostgreSQL startede ikke i tide - tjek container logs")


def create_database():
    """Opret database og konfigurer brugeradgang."""
    params = get_db_params()
    dbname = params["dbname"]

    # Forbind til default 'postgres' database for at oprette ny database
    conn = psycopg.connect(
        host=params["host"],
        port=params["port"],
        user=params["user"],
        password=params["password"],
        dbname="postgres"
    )
    cursor = conn.cursor()

    # Tjek om databasen eksisterer
    cursor.execute(SQL("SELECT 1 FROM pg_database WHERE datname = {}").format(SQL(dbname)))
    if cursor.fetchone() is None:
        # Opret database
        cursor.execute(SQL("CREATE DATABASE {} OWNER {}").format(
            SQL(dbname), SQL(params["user"])
        ))
        print(f"✅ Oprettede database: {dbname}")
    else:
        print(f"ℹ️  Database {dbname} eksisterer allerede")

    # Giv brugeren fuld adgang til databasen
    cursor.execute(SQL("GRANT ALL PRIVILEGES ON DATABASE {} TO {}").format(
        SQL(dbname), SQL(params["user"])
    ))
    
    # Sikre at brugeren har nødvendige rettigheder
    cursor.execute(SQL("ALTER DATABASE {} OWNER TO {}").format(
        SQL(dbname), SQL(params["user"])
    ))
    
    conn.commit()
    cursor.close()
    conn.close()
    print("✅ Database konfiguration færdig")


if __name__ == "__main__":
    print("🚀 Starter database initialisering...")
    wait_for_postgres()
    create_database()
    print("✨ Database initialisering fuldført")
