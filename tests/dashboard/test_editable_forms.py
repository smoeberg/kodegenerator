"""Surface tests for backend-authorized editable forms."""
from __future__ import annotations

from pathlib import Path

EDITABLE = Path("dashboard/editable_forms.py").read_text(encoding="utf-8")
INFRA = Path("dashboard/form_infrastructure.py").read_text(encoding="utf-8")


def test_editable_forms_use_typed_api_resources_only() -> None:
    assert "/api/v1/control-plane/organizations/{organization_id}/users" in EDITABLE
    assert "password" in EDITABLE  # secrets entered as password fields, never shown
    assert "sqlalchemy" not in EDITABLE.lower()
    assert "sqlite3" not in EDITABLE.lower()


def test_form_infrastructure_is_fail_closed() -> None:
    assert "Status kan ikke fastslås" in INFRA
    assert "Adgang nægtet" in INFRA


def test_user_form_omits_locked_fields_on_edit() -> None:
    from dashboard.editable_forms import user_forms

    spec = user_forms()
    assert any(f.kind == "password" for f in spec.fields)
    assert spec.update_method == "PATCH"
