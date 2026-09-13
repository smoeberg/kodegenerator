"""Tests for the generic form infrastructure."""
from __future__ import annotations

from dashboard.form_infrastructure import FormField, FormRenderer, FormSpec

CREATE = "dashboard/form_infrastructure.py"


def test_form_infrastructure_exists_and_is_presentation_only() -> None:
    source = __import__("pathlib").Path(CREATE).read_text(encoding="utf-8")
    assert "sqlalchemy" not in source.lower()
    assert "sqlite3" not in source.lower()
    assert "DORAPIClient" in source


def test_form_spec_holds_typed_resource_endpoints() -> None:
    spec = FormSpec(
        form_id="demo",
        title="Demo",
        fields=(FormField(name="name", label="Navn", required=True),),
        create_path="/api/v1/demo",
        update_path="/api/v1/demo/{id}",
        list_path="/api/v1/demo",
    )
    assert spec.create_method == "POST"
    assert spec.update_method == "PUT"


def test_renderer_rejects_unusable_client_responses() -> None:
    from dashboard.api_client import DORAPIError

    class BrokenClient:
        def get(self, path):
            raise DORAPIError(500, "boom")

    renderer = FormRenderer(BrokenClient(), FormSpec(form_id="demo", title="Demo", list_path="/api/v1/demo"))
    assert renderer._fetch_list() is None


def test_renderer_omits_non_editable_fields_on_update() -> None:
    spec = FormSpec(
        form_id="demo",
        title="Demo",
        fields=(
            FormField(name="name", label="Navn", required=True),
            FormField(name="locked", label="Låst", editable=False),
        ),
    )
    renderer = FormRenderer(None, spec)
    payload = renderer._build_payload("k", {"k::name": "x", "k::locked": "y"}, editing=True, record={"locked": "orig"})
    assert "locked" not in payload
    assert payload["name"] == "x"
