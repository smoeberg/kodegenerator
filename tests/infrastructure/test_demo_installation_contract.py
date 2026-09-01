import json
from pathlib import Path
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).parents[2]
CONTRACT_PATH = ROOT / "ci" / "manifests" / "demo_installation_contract.json"


def _contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_demo_contract_has_one_canonical_compose_entrypoint() -> None:
    contract = _contract()
    compose = contract["compose"]

    assert compose["file"] == "compose.demo.yml"
    assert compose["start_command"] == (
        "docker compose -f compose.demo.yml up --build -d"
    )
    assert compose["stop_command"] == "docker compose -f compose.demo.yml down"


def test_demo_contract_requires_production_equivalent_durable_wiring() -> None:
    runtime = _contract()["runtime"]

    assert runtime["production_equivalent_wiring"] is True
    assert runtime["allows_sqlite"] is False
    assert runtime["allows_process_local_queue"] is False
    assert runtime["allows_file_pipeline_state"] is False
    assert runtime["requires_non_root_containers"] is True
    assert runtime["requires_read_only_root_filesystem"] is True


def test_demo_contract_fixes_required_service_inventory_and_dependencies() -> None:
    contract = _contract()
    services = contract["services"]

    assert set(services) == {
        "postgres",
        "minio",
        "migrate",
        "api",
        "worker",
        "dashboard",
        "otel-collector",
    }
    assert services["api"]["depends_on"] == ["migrate", "postgres", "minio"]
    assert services["worker"]["depends_on"] == ["migrate", "postgres", "minio"]
    assert contract["shared_boundaries"]["database_queue"] == ["api", "worker"]


def test_demo_contract_exposes_only_api_and_dashboard_application_ports() -> None:
    contract = _contract()
    services = contract["services"]

    public_services = {name for name, value in services.items() if value["public"]}
    assert public_services == {"api", "dashboard"}
    assert services["api"]["host_port"] == 8000
    assert services["dashboard"]["host_port"] == 8501

    for endpoint in contract["public_endpoints"].values():
        parsed = urlparse(endpoint)
        assert parsed.scheme == "http"
        assert parsed.hostname == "localhost"
        assert parsed.port in {8000, 8501}


def test_demo_contract_requires_security_and_recovery_certification() -> None:
    certification = _contract()["certification"]

    assert certification
    assert all(value is True for value in certification.values())


def test_demo_contract_records_uncertified_implementation() -> None:
    contract = _contract()

    assert contract["status"] == "implementation_present_certification_pending"
    assert contract["implementation"] == {
        "runtime_dockerfile": "docker/Dockerfile.runtime",
        "environment_example": ".env.demo.example",
        "migration_entrypoint": "scripts/entrypoint.sh",
        "certified": False,
    }
    assert contract["certification"]["required_before_demo"] is True


def test_demo_compose_implements_frozen_service_inventory() -> None:
    contract = _contract()
    compose = yaml.safe_load((ROOT / contract["compose"]["file"]).read_text())

    assert set(compose["services"]) == set(contract["services"])
    assert compose["name"] == contract["compose"]["project_name"]
    assert set(compose["volumes"]) == {"postgres-data", "object-data"}


def test_demo_compose_uses_one_hardened_runtime_image() -> None:
    compose = yaml.safe_load((ROOT / "compose.demo.yml").read_text())
    expected_dockerfile = _contract()["implementation"]["runtime_dockerfile"]

    for service_name in ("migrate", "api", "worker", "dashboard"):
        service = compose["services"][service_name]
        assert service["build"]["dockerfile"] == expected_dockerfile
        assert service["read_only"] is True
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert service["cap_drop"] == ["ALL"]


def test_demo_compose_has_no_sqlite_or_file_state_configuration() -> None:
    raw = (ROOT / "compose.demo.yml").read_text()
    compose = yaml.safe_load(raw)

    assert "sqlite:" not in raw
    assert "DOR_PIPELINE_QUEUE_PATH" not in raw
    assert "DOR_PIPELINE_STATE_PATH" not in raw
    for service_name in ("migrate", "api", "worker"):
        environment = compose["services"][service_name]["environment"]
        assert environment["DOR_QUEUE_BACKEND"] == "database"
        assert environment["DATABASE_URL"].startswith("postgresql+psycopg://")
        assert environment["DOR_PIPELINE_DATABASE_URL"].startswith(
            "postgresql+psycopg://"
        )


def test_demo_compose_exposes_contract_ports_and_healthchecks() -> None:
    contract = _contract()
    compose = yaml.safe_load((ROOT / "compose.demo.yml").read_text())

    assert compose["services"]["api"]["ports"] == ["${DOR_API_PORT:-8000}:8000"]
    assert compose["services"]["dashboard"]["ports"] == [
        "${DOR_DASHBOARD_PORT:-8501}:8501"
    ]
    for name, expected in contract["services"].items():
        if expected["healthcheck"]:
            assert "healthcheck" in compose["services"][name]


def test_demo_application_services_declare_startup_validation_roles() -> None:
    contract = _contract()
    compose = yaml.safe_load((ROOT / contract["compose"]["file"]).read_text())

    for role in ("api", "dashboard", "migrate", "worker"):
        assert compose["services"][role]["environment"]["DOR_RUNTIME_ROLE"] == role
    assert contract["runtime"]["requires_role_startup_validation"] is True
    assert contract["runtime"]["readiness_requires_canonical_schema"] is True


def test_demo_runtime_start_order_has_single_migration_owner() -> None:
    compose = yaml.safe_load((ROOT / "compose.demo.yml").read_text())
    services = compose["services"]

    assert services["migrate"]["environment"]["DOR_RUN_MIGRATIONS"] == "1"
    assert "DOR_RUN_MIGRATIONS" not in services["api"]["environment"]
    assert "DOR_RUN_MIGRATIONS" not in services["worker"]["environment"]
    assert services["api"]["depends_on"]["migrate"]["condition"] == (
        "service_completed_successfully"
    )
    assert services["worker"]["depends_on"]["migrate"]["condition"] == (
        "service_completed_successfully"
    )
