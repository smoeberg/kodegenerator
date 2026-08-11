"""Environment-backed production runtime settings."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeSettings:
    database_url: str
    artifact_store_url: str | None
    artifact_bucket: str
    queue_backend: str
    queue_poll_interval_seconds: float
    queue_lease_seconds: int

    @classmethod
    def from_env(cls) -> "RuntimeSettings":
        return cls(
            database_url=os.getenv("DATABASE_URL", "sqlite:///./dor_runtime.db"),
            artifact_store_url=os.getenv("ARTIFACT_STORE_URL"),
            artifact_bucket=os.getenv("ARTIFACT_BUCKET", "dor-artifacts"),
            queue_backend=os.getenv("DOR_QUEUE_BACKEND", "database"),
            queue_poll_interval_seconds=float(
                os.getenv("DOR_QUEUE_POLL_INTERVAL_SECONDS", "1.0")
            ),
            queue_lease_seconds=int(os.getenv("DOR_QUEUE_LEASE_SECONDS", "60")),
        )

    @property
    def is_production_database(self) -> bool:
        return self.database_url.startswith(("postgresql://", "postgresql+psycopg://"))

    def validate_production(self) -> None:
        """Fail closed when production is explicitly requested."""
        if os.getenv("DOR_ENV", "development").lower() != "production":
            return
        if not self.is_production_database:
            raise ValueError("Production runtime requires PostgreSQL DATABASE_URL")
        if not self.artifact_store_url:
            raise ValueError("Production runtime requires ARTIFACT_STORE_URL")
