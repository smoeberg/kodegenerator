import json
from pathlib import Path
from urllib.parse import urlparse

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


def test_demo_contract_does_not_claim_current_implementation_is_ready() -> None:
    contract = _contract()

    assert contract["status"] == "contract_frozen_implementation_pending"
    assert contract["certification"]["required_before_demo"] is True
