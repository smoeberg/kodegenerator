from pathlib import Path


APP = Path("customer_gui/app.py")
CLIENT = Path("customer_gui/client.py")
VIEW_MODEL = Path("customer_gui/view_model.py")
COMPOSE = Path("compose.customer.yml")
OPERATOR = Path("dashboard/operator_center.py")


def test_customer_portal_has_customer_information_architecture() -> None:
    source = APP.read_text(encoding="utf-8")
    assert 'NAV = ("Dashboard", "Projekter", "Beslutninger", "Historik")' in source
    for label in ("Sag", "Plan", "Aktivt arbejdsgrundlag", "Execution", "Proposal", "Beslutning"):
        assert label in VIEW_MODEL.read_text(encoding="utf-8")


def test_customer_portal_has_explicit_port_8502_deployment() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    assert "customer_gui/app.py" in compose
    assert "--server.port=8502" in compose
    assert "${DOR_CUSTOMER_PORTAL_PORT:-8502}:8502" in compose


def test_customer_api_exposes_no_execution_start_advance_or_patch_apply_path() -> None:
    source = CLIENT.read_text(encoding="utf-8") + "\n" + APP.read_text(encoding="utf-8")
    forbidden = (
        "/api/v1/execution/start",
        "/advance",
        "/implementation-agent/executions",
        "implementation_apply",
        "apply_patch(",
        "create_pr(",
        ".deploy(",
        ".execute(",
        "execute_release(",
        "run_workflow(",
    )
    for value in forbidden:
        assert value not in source


def test_customer_portal_only_mutates_existing_gate_decision_and_rework_paths() -> None:
    source = CLIENT.read_text(encoding="utf-8")
    assert '/gates/decide"' in source
    assert '/gates/rework"' in source
    assert '/proposals"' in source
    assert '.post(f"/api/v1/execution/{workflow_id}/proposals"' not in source


def test_customer_portal_does_not_import_or_modify_operator_entrypoint() -> None:
    source = APP.read_text(encoding="utf-8") + CLIENT.read_text(encoding="utf-8")
    assert "operator_center" not in source
    assert OPERATOR.exists()


def test_unknown_copy_is_explicit_and_not_ready_fallback() -> None:
    source = VIEW_MODEL.read_text(encoding="utf-8")
    assert 'UNKNOWN_STATUS = "Status kan ikke fastslås"' in source
    assert "_PIPELINE_STATUS.get" in source


def test_customer_compose_preserves_hardened_dashboard_runtime_contract() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    assert "DOR_ENV: production" in compose
    assert "DOR_RUNTIME_ROLE: dashboard" in compose
    for secret in (
        "postgres_password",
        "minio_root_user",
        "minio_root_password",
        "dor_jwt_signing_keys",
        "dor_authority_signing_key",
        "dor_encryption_key",
        "dor_admin_password",
    ):
        assert f"- {secret}" in compose
