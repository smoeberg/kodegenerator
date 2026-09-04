from pathlib import Path

import yaml


def test_redmine_secret_is_only_injected_into_canonical_api_service() -> None:
    compose = yaml.safe_load(Path("compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    api_environment = services["api"]["environment"]
    assert api_environment["REDMINE_URL"] == "${REDMINE_URL:-}"
    assert api_environment["REDMINE_API_KEY"] == "${REDMINE_API_KEY:-}"
    assert api_environment["REDMINE_PROJECT_ID"] == "${REDMINE_PROJECT_ID:-}"

    for service_name in ("dashboard", "worker", "migrate"):
        environment = services[service_name]["environment"]
        assert "REDMINE_URL" not in environment
        assert "REDMINE_API_KEY" not in environment
        assert "REDMINE_PROJECT_ID" not in environment


def test_redmine_secret_is_not_shared_with_legacy_worker_or_tui() -> None:
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    api_environment = services["api"]["environment"]
    assert api_environment["REDMINE_API_KEY"] == "${REDMINE_API_KEY:-}"

    for service_name in ("worker-pool", "tui"):
        assert "REDMINE_API_KEY" not in services[service_name]["environment"]
