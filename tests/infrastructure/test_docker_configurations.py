from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]


def test_dockerfiles_use_non_root_kodegen_user():
    for name in ("Dockerfile.api", "Dockerfile.worker"):
        text = (ROOT / "docker" / name).read_text()
        assert "python:3.12-slim" in text
        assert "groupadd --system kodegen" in text
        assert "useradd --system --gid kodegen" in text
        assert "USER kodegen" in text
        assert "HEALTHCHECK" in text


def test_compose_contains_required_services_and_persistent_volumes():
    data = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    assert set(("api", "worker-pool", "redis", "tui")) <= set(data["services"])
    assert "sqlite-data" in data["volumes"]
    assert data["services"]["worker-pool"]["deploy"]["replicas"] >= 1


def test_compose_has_healthchecks_and_resource_limits():
    data = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    for name in ("api", "redis"):
        assert "healthcheck" in data["services"][name]
    for name in ("api", "worker-pool", "redis", "tui"):
        limits = data["services"][name]["deploy"]["resources"]["limits"]
        assert "cpus" in limits and "memory" in limits


def test_prod_override_is_restart_safe_and_entrypoint_runs_migrations():
    prod = yaml.safe_load((ROOT / "docker-compose.prod.yml").read_text())
    assert prod["services"]["api"]["restart"] == "unless-stopped"
    script = (ROOT / "scripts" / "entrypoint.sh").read_text()
    assert "alembic upgrade head" in script
    assert 'exec "$@"' in script
