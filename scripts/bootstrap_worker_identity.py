"""Idempotently provision the configured demo worker service account."""

from __future__ import annotations

import os

from infrastructure.runtime.db import build_session_factory
from services.worker_identity import WorkerIdentityStore


def main() -> None:
    capabilities = tuple(
        sorted(
            item.strip()
            for item in os.environ["DOR_WORKER_CAPABILITIES"].split(",")
            if item.strip()
        )
    )
    WorkerIdentityStore(build_session_factory(os.environ["DATABASE_URL"])).provision(
        organization_id=os.environ["DOR_WORKER_ORGANIZATION_ID"],
        service_id=os.environ["DOR_WORKER_SERVICE_ID"],
        credential=os.environ["DOR_WORKER_CREDENTIAL"],
        capabilities=capabilities,
    )


if __name__ == "__main__":
    main()
