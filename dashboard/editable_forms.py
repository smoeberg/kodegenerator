"""Backend-authorized editable forms for the operator dashboard.

Every form is a declarative FormSpec against an existing typed API
resource. The backend keeps ownership of rules, authorization and
validation; the dashboard renders and submits only.
"""
from __future__ import annotations

from typing import Mapping

import streamlit as st

from dashboard.api_client import DORAPIClient
from dashboard.form_infrastructure import (
    FormField,
    FormRenderer,
    FormSpec,
)

def _org_id() -> str:
    return str(st.session_state.get("organization_id") or "").strip()

def _require_org() -> str | None:
    organization_id = _org_id()
    if not organization_id:
        st.warning("Status kan ikke fastslås")
        return None
    return organization_id

def user_forms() -> FormSpec:
    """Organization users via the canonical organization_users endpoints."""
    organization_id = _org_id()
    return FormSpec(
        form_id="org-users",
        title="Brugere",
        description="Opret og rediger brugere i organisationen. Backend ejer reglerne.",
        fields=(
            FormField(name="username", label="Brugernavn", required=True),
            FormField(name="password", label="Adgangskode (min. 12 tegn)", kind="password", required=True, help="Lad feltet være tomt ved redigering for at beholde den gemte værdi"),
            FormField(name="email", label="E-mail"),
            FormField(name="full_name", label="Fulde navn"),
            FormField(name="is_admin", label="Administrator", kind="checkbox"),
            FormField(name="disabled", label="Deaktiveret", kind="checkbox"),
        ),
        create_path=f"/api/v1/control-plane/organizations/{organization_id}/users",
        update_path=f"/api/v1/control-plane/organizations/{organization_id}/users/{{id}}",
        list_path=f"/api/v1/control-plane/organizations/{organization_id}/users",
        id_field="username",
        display_field="full_name",
        update_method="PATCH",
        record_to_values=lambda record: {"disabled": bool(record.get("disabled", False)), "is_admin": bool(record.get("is_admin", False))},
    )

def render_editable_forms(client: DORAPIClient) -> None:
    """Render all backend-authorized editable forms in one tab."""
    st.markdown("### Formularer")
    st.caption("Alle formularder henter data fra og skriver til backendens typed API-endpoints. Backend ejer reglerne.")
    if _require_org() is None:
        return
    specs = (user_forms(),)
    for spec in specs:
        if spec.list_path:
            FormRenderer(client, spec).render()
        else:
            _render_single_config_form(client, spec)
            if not submitted:
                continue
            missing = [f.label for f in spec.fields if f.required and not str(values.get(f.name, "")).strip()]
            if missing:
                st.error("Udfyld obligatoriske felter: " + ", ".join(missing))
                continue
            payload = {k: v for k, v in values.items() if isinstance(v, str) and v.strip()}
            try:
                client.put(spec.update_path, json=payload)
            except Exception as exc:
                st.error(f"Kunne ikke gemme: {exc}")
                continue
            st.success(f"{spec.title} er gemt af backenden.")
            st.rerun()

def _current_config(client: DORAPIClient, spec: FormSpec) -> Mapping:
    """Fetch the current backend-owned config for prefilling."""
    organization_id = _org_id()
    try:
        payload = client.get(spec.list_path or spec.update_path, params={"organization_id": organization_id})
        return payload if isinstance(payload, Mapping) else {}
    except Exception:
        return {}

def _render_single_config_form(client: DORAPIClient, spec: FormSpec) -> None:
    st.markdown(f"### {spec.title}")
    if spec.description:
        st.caption(spec.description)
    current = _current_config(client, spec)
    with st.form(f"{spec.form_id}-single-form"):
        values = {}
        for field_spec in spec.fields:
            preset = "" if field_spec.kind == "password" else str(current.get(field_spec.name, "") or "")
            if field_spec.kind == "password":
                values[field_spec.name] = st.text_input(field_spec.label, value="", type="password", help=field_spec.help or "Lad feltet være tomt for at beholde den gemte værdi")
            else:
                values[field_spec.name] = st.text_input(field_spec.label, value=preset, help=field_spec.help)
        submitted = st.form_submit_button("Gem", type="primary")
