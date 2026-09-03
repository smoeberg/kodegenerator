from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]


def test_canonical_runtime_dockerfile_uses_non_root_kodegen_user():
    text = (ROOT / "docker" / "Dockerfile.runtime").read_text()
    assert "python:3.12-slim" in text
    assert "groupadd --system --gid 10001 kodegen" in text
    assert "useradd --system --uid 10001" in text
    assert "USER kodegen" in text
    assert "chmod 0555 /app/scripts/entrypoint.sh" in text
    assert 'ENTRYPOINT ["/app/scripts/entrypoint.sh"]' in text


def test_compose_contains_required_services_and_persistent_volumes():
    data = yaml.safe_load((ROOT / "compose.yml").read_text())
    assert {"api", "worker", "postgres", "minio", "dashboard"} <= set(data["services"])
    assert "postgres-data" in data["volumes"]
    assert data["services"]["worker"]["deploy"]["replicas"] == "${DOR_WORKER_REPLICAS:-2}"


def test_compose_has_healthchecks_and_resource_limits():
    data = yaml.safe_load((ROOT / "compose.yml").read_text())
    for name in ("api", "postgres", "minio", "worker", "dashboard", "otel-collector"):
        assert "healthcheck" in data["services"][name]
    for name in ("api", "worker", "postgres", "minio", "dashboard"):
        limits = data["services"][name]["deploy"]["resources"]["limits"]
        assert "cpus" in limits and "memory" in limits


def test_prod_override_is_restart_safe_and_entrypoint_has_bounded_migrations():
    data = yaml.safe_load((ROOT / "compose.yml").read_text())
    assert data["x-runtime-service"]["restart"] == "unless-stopped"
    script = (ROOT / "scripts" / "entrypoint.sh").read_text()
    assert "DOR_RUN_MIGRATIONS:-0" in script
    assert "alembic upgrade head" in script
    assert 'exec "$@"' in script


def test_legacy_docker_paths_are_explicitly_not_demo_paths():
    paths = (
        "Dockerfile",
        "docker/Dockerfile.api",
        "docker/Dockerfile.worker",
    )
    for path in paths:
        text = (ROOT / path).read_text().lower()
        assert "legacy" in text or "superseded" in text
