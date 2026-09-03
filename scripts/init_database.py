#!/usr/bin/env python3
"""Automatisk database initialisering for DOR.

Dette script:
1. Venter på at PostgreSQL er klar
2. Opretter databasen hvis den ikke eksisterer
3. Sikrer at brugeren har adgang til databasen
"""

import os
import time
import psycopg
from psycopg.sql import SQL


def wait_for_postgres(max_attempts=30, interval=2):
    """Vent på at PostgreSQL serveren er klar til forbindelse."""
    user = os.environ.get("POSTGRES_USER", "dor")
    password = os.environ.get("POSTGRES_PASSWORD")
    host = os.environ.get("POSTGRES_HOST", "postgres")

    if not password:
        raise RuntimeError("POSTGRES_PASSWORD er ikke sat i miljøvariable")

    for attempt in range(max_attempts):
        try:
            conn = psycopg.connect(
                host=host,
                port=5432,
                user=user,
                password=password,
                dbname="postgres",  # Forbind til default database
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
    user = os.environ.get("POSTGRES_USER", "dor")
    password = os.environ.get("POSTGRES_PASSWORD")
    dbname = os.environ.get("POSTGRES_DB", "dor")
    host = os.environ.get("POSTGRES_HOST", "postgres")

    if not password:
        raise RuntimeError("POSTGRES_PASSWORD er ikke sat")

    # Forbind til default 'postgres' database for at oprette ny database
    conn = psycopg.connect(
        host=host,
        port=5432,
        user=user,
        password=password,
        dbname="postgres"
    )
    cursor = conn.cursor()

    # Tjek om databasen eksisterer
    cursor.execute(SQL("SELECT 1 FROM pg_database WHERE datname = {}").format(SQL(dbname)))
    if cursor.fetchone() is None:
        # Opret database
        cursor.execute(SQL("CREATE DATABASE {} OWNER {}").format(
            SQL(dbname), SQL(user)
        ))
        print(f"✅ Oprettede database: {dbname}")
    else:
        print(f"ℹ️  Database {dbname} eksisterer allerede")

    # Giv brugeren fuld adgang til databasen
    cursor.execute(SQL("GRANT ALL PRIVILEGES ON DATABASE {} TO {}").format(
        SQL(dbname), SQL(user)
    ))
    
    # Sikre at brugeren har nødvendige rettigheder
    cursor.execute(SQL("ALTER DATABASE {} OWNER TO {}").format(
        SQL(dbname), SQL(user)
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
