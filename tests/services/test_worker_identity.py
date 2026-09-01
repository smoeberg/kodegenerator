import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session, sessionmaker

from infrastructure.persistence.models import Base
from infrastructure.persistence.worker_identity_models import WorkerServiceIdentityModel
from services.worker_identity import WorkerIdentityError, WorkerIdentityStore


def _store() -> tuple[WorkerIdentityStore, sessionmaker[Session]]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[WorkerServiceIdentityModel.__table__])
    sessions = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    return WorkerIdentityStore(sessions), sessions


def test_authentication_returns_tenant_bound_capabilities() -> None:
    store, _ = _store()
    store.provision(
        organization_id="org-1",
        service_id="factory-worker",
        credential="a" * 32,
        capabilities=("pipeline.code", "pipeline.tests"),
    )

    principal = store.authenticate(
        organization_id="org-1",
        service_id="factory-worker",
        instance_id="container-1",
        credential="a" * 32,
    )

    assert principal.worker_id == "factory-worker@container-1"
    assert principal.capabilities == ("pipeline.code", "pipeline.tests")


@pytest.mark.parametrize(
    "organization,credential", [("org-2", "a" * 32), ("org-1", "b" * 32)]
)
def test_authentication_fails_closed(organization: str, credential: str) -> None:
    store, _ = _store()
    store.provision(
        organization_id="org-1",
        service_id="worker",
        credential="a" * 32,
        capabilities=("pipeline.code",),
    )
    with pytest.raises(WorkerIdentityError, match="authentication failed"):
        store.authenticate(
            organization_id=organization,
            service_id="worker",
            instance_id="container-1",
            credential=credential,
        )


def test_disabled_identity_is_rejected_on_revalidation() -> None:
    store, sessions = _store()
    store.provision(
        organization_id="org-1",
        service_id="worker",
        credential="a" * 32,
        capabilities=("pipeline.code",),
    )
    with sessions() as session:
        session.execute(update(WorkerServiceIdentityModel).values(disabled=True))
        session.commit()
    with pytest.raises(WorkerIdentityError):
        store.authenticate(
            organization_id="org-1",
            service_id="worker",
            instance_id="container-1",
            credential="a" * 32,
        )
