"""Idempotent demo seed for the canonical DOR runtime.

Schema lifecycle is owned by DORRuntime.boot() and Alembic. Seed data is written
through the runtime/repository boundary and never creates tables directly.
"""

from __future__ import annotations

import logging
import os

from domain.actor import Actor, ActorType
from domain.organization import Organization
from runtime.core import DORRuntime

logger = logging.getLogger("dor.seed")

ORGANIZATION_ID = "dor-org"
ACTOR_ID = "dor-actor"


def seed() -> None:
    runtime = DORRuntime(os.getenv("DATABASE_URL", "sqlite:///./dor_runtime.db"))
    runtime.boot()

    with runtime.database.session() as session:
        from infrastructure.persistence.uow import UnitOfWork

        with UnitOfWork(session) as uow:
            organization = uow.organizations.get(ORGANIZATION_ID)
            if organization is None:
                uow.organizations.add(
                    Organization(id=ORGANIZATION_ID, name="EIRA Demo Organization")
                )
                logger.info("Created organization %s", ORGANIZATION_ID)

    with runtime.database.session() as session:
        from infrastructure.persistence.uow import UnitOfWork

        with UnitOfWork(session) as uow:
            actor = uow.actors.get_for_organization(ACTOR_ID, ORGANIZATION_ID)
            if actor is None:
                uow.actors.add(
                    Actor(id=ACTOR_ID, type=ActorType.HUMAN, identity="demo@eira.local"),
                    ORGANIZATION_ID,
                )
                logger.info("Created actor %s", ACTOR_ID)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seed()
