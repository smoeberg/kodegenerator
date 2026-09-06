"""Tests for idempotent bootstrap admin runtime context seeding."""

from domain.actor import Actor, ActorType
from domain.organization import Organization
from infrastructure.persistence.repositories import RepositoryError


class _SeededRuntime:
    """Minimal DORRuntime stand-in that records seeded orgs/actors."""

    def __init__(self) -> None:
        self.organizations: dict[str, str] = {}
        self.actors: set[tuple[str, str]] = set()

    def create_organization(self, organization: Organization) -> None:
        if organization.id in self.organizations:
            raise RepositoryError(f"Organization already exists: {organization.id}")
        self.organizations[organization.id] = organization.name

    def register_actor(self, actor: Actor, organization_id: str) -> None:
        key = (actor.id, organization_id)
        if key in self.actors:
            raise RepositoryError(f"Actor already exists: {actor.id}")
        if organization_id not in self.organizations:
            raise RepositoryError(f"Organization not found: {organization_id}")
        self.actors.add(key)


def _patch_runtime(monkeypatch, runtime):
    """Route api.dependencies.get_dor (dynamically imported by auth) to runtime."""
    import api.dependencies as deps

    monkeypatch.setattr(deps, "get_dor", lambda: runtime)


def test_seeds_org_and_actor_when_missing(monkeypatch) -> None:
    from api import auth as auth_mod

    runtime = _SeededRuntime()
    _patch_runtime(monkeypatch, runtime)
    monkeypatch.setenv("DOR_ADMIN_ORGANIZATION_ID", "dor-org")
    monkeypatch.setenv("DOR_ADMIN_USERNAME", "admin")

    auth_mod.ensure_bootstrap_runtime_context()

    assert runtime.organizations == {"dor-org": "dor-org"}
    assert ("admin", "dor-org") in runtime.actors


def test_seeding_is_idempotent(monkeypatch) -> None:
    from api import auth as auth_mod

    runtime = _SeededRuntime()
    _patch_runtime(monkeypatch, runtime)
    monkeypatch.setenv("DOR_ADMIN_ORGANIZATION_ID", "dor-org")
    monkeypatch.setenv("DOR_ADMIN_USERNAME", "admin")

    auth_mod.ensure_bootstrap_runtime_context()
    auth_mod.ensure_bootstrap_runtime_context()

    assert runtime.organizations == {"dor-org": "dor-org"}
    assert len(runtime.actors) == 1
    assert ("admin", "dor-org") in runtime.actors


def test_seeding_skips_when_runtime_unavailable(monkeypatch, caplog) -> None:
    from api import auth as auth_mod

    def boom() -> None:
        raise RuntimeError("no runtime in this environment")

    _patch_runtime(monkeypatch, boom)
    monkeypatch.setenv("DOR_ADMIN_ORGANIZATION_ID", "dor-org")
    monkeypatch.setenv("DOR_ADMIN_USERNAME", "admin")

    auth_mod.ensure_bootstrap_runtime_context()
    assert any("skipped" in r.message for r in caplog.records)


def test_seeding_uses_custom_org_and_username(monkeypatch) -> None:
    from api import auth as auth_mod

    runtime = _SeededRuntime()
    _patch_runtime(monkeypatch, runtime)
    monkeypatch.setenv("DOR_ADMIN_ORGANIZATION_ID", "acme-org")
    monkeypatch.setenv("DOR_ADMIN_USERNAME", "alice")

    auth_mod.ensure_bootstrap_runtime_context()

    assert runtime.organizations == {"acme-org": "acme-org"}
    assert ("alice", "acme-org") in runtime.actors
