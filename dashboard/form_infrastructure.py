"""Generic form infrastructure for the canonical operator dashboard.

Backend owns every rule; the dashboard renders declarative field
specifications and submits to the same typed resource endpoints that
the API already exposes. No direct database access, no authority
inference, fail-closed on any unusable response.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

import streamlit as st

from dashboard.api_client import DORAPIError, DORAPIClient


@dataclass(frozen=True)
class FormField:
    """One declarative field rendered by the generic renderer."""

    name: str
    label: str
    kind: str = "text"  # text | textarea | password | number | select | checkbox
    required: bool = False
    default: Any = None
    help: str = ""
    options: Sequence[str] = ()
    editable: bool = True
    transform: Callable[[Any], Any] | None = None


@dataclass(frozen=True)
class FormSpec:
    """Declarative specification of one editable form."""

    form_id: str
    title: str
    description: str = ""
    fields: Sequence[FormField] = field(default_factory=tuple)
    create_path: str = ""
    update_path: str = ""
    list_path: str = ""
    id_field: str = "id"
    display_field: str = ""
    create_method: str = "POST"
    update_method: str = "PUT"
    record_to_values: Callable[[Mapping], dict] | None = None


def _strip(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def human_form_error(exc: DORAPIError, action: str) -> str:
    message = str(exc) or "Ukendt fejl"
    if exc.status_code == 403:
        return f"Adgang nægtet ({exc.status_code}). {message}"
    if exc.status_code == 404:
        return f"Ressourcen blev ikke fundet ({exc.status_code}). {message}"
    if exc.status_code >= 500:
        return f"Backend-fejl ({exc.status_code}). {message}"
    return f"{message} ({exc.status_code})"


class FormRenderer:
    """Render one FormSpec as list + create + edit forms."""

    def __init__(self, client: DORAPIClient, spec: FormSpec) -> None:
        self.client = client
        self.spec = spec

    def render(self) -> None:
        st.markdown(f"### {self.spec.title}")
        if self.spec.description:
            st.caption(self.spec.description)
        records = self._fetch_list()
        if records is None:
            return
        self._render_list(records)
        self._render_create_form()
        self._render_edit_forms(records)

    def _fetch_list(self) -> list[Mapping] | None:
        if not self.spec.list_path:
            return []
        try:
            payload = self.client.get(self.spec.list_path)
        except DORAPIError as exc:
            st.error(human_form_error(exc, f"hente {self.spec.title}"))
            return None
        except Exception:
            st.error("Status kan ikke fastslås")
            return None
        if not isinstance(payload, list):
            st.error("Status kan ikke fastslås")
            return None
        return [dict(item) for item in payload if isinstance(item, Mapping)]

    def _render_list(self, records: list[Mapping]) -> None:
        if not records:
            st.info(f"Ingen {self.spec.title} endnu.")
            return
        display_field = self.spec.display_field or self.spec.id_field
        rows = [
            {
                "ID": record.get(self.spec.id_field, ""),
                "Visning": record.get(display_field, ""),
            }
            for record in records
        ]
        st.dataframe(rows, hide_index=True, use_container_width=True)

    def _field_value(self, form_values: Mapping, form_key: str, field_spec: FormField) -> Any:
        raw = form_values.get(f"{form_key}::{field_spec.name}", field_spec.default)
        if field_spec.transform is not None:
            return field_spec.transform(raw)
        return _strip(raw) if isinstance(raw, str) else raw

    def _missing_required(self, form_key: str, values: Mapping) -> list[str]:
        missing = []
        for spec in self.spec.fields:
            if not spec.required:
                continue
            value = self._field_value(values, form_key, spec)
            if value is None or (isinstance(value, str) and not value.strip()):
                missing.append(spec.label)
        return missing

    def _build_payload(
        self,
        form_key: str,
        values: Mapping,
        *,
        editing: bool,
        record: Mapping | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for spec in self.spec.fields:
            if editing and not spec.editable:
                continue
            payload[spec.name] = self._field_value(values, form_key, spec)
        if editing and record is not None and self.spec.record_to_values is not None:
            payload.update(self.spec.record_to_values(record))
        return payload

    def _submit(self, path: str, method: str, payload: dict, action: str) -> Mapping | None:
        try:
            if method == "PUT":
                response = self.client.put(path, json=payload)
            elif method == "PATCH":
                response = self.client.patch(path, json=payload)
            else:
                response = self.client.post(path, json=payload)
        except DORAPIError as exc:
            st.error(human_form_error(exc, action))
            return None
        except Exception:
            st.error("Status kan ikke fastslås")
            return None
        if not isinstance(response, Mapping):
            st.error("Status kan ikke fastslås")
            return None
        return response

    def _render_create_form(self) -> None:
        if not self.spec.create_path:
            return
        form_key = f"{self.spec.form_id}-create"
        with st.expander(f"Opret {self.spec.title}", expanded=False):
            with st.form(f"{form_key}-form", clear_on_submit=True):
                values = self._render_fields(form_key, editing=False)
                submitted = st.form_submit_button("Opret", type="primary")
            if not submitted:
                return
            missing = self._missing_required(form_key, values)
            if missing:
                st.error("Udfyld obligatoriske felter: " + ", ".join(missing))
                return
            payload = self._build_payload(form_key, values, editing=False)
            created = self._submit(self.spec.create_path, self.spec.create_method, payload, f"oprette {self.spec.title}")
            if created is None:
                return
            st.success(f"{self.spec.title} er oprettet af backenden.")
            st.rerun()

    def _render_edit_forms(self, records: list[Mapping]) -> None:
        if not self.spec.update_path or not records:
            return
        for record in records:
            record_id = str(record.get(self.spec.id_field, "")).strip()
            if not record_id:
                continue
            form_key = f"{self.spec.form_id}-edit-{record_id}"
            path = self.spec.update_path.format(id=record_id)
            label = str(record.get(self.spec.display_field or self.spec.id_field, record_id))
            with st.expander(f"Rediger: {label}", expanded=False):
                with st.form(f"{form_key}-form"):
                    values = self._render_fields(form_key, editing=True, record=record)
                    submitted = st.form_submit_button("Gem", type="primary")
                if not submitted:
                    continue
                missing = self._missing_required(form_key, values)
                if missing:
                    st.error("Udfyld obligatoriske felter: " + ", ".join(missing))
                    continue
                payload = self._build_payload(form_key, values, editing=True, record=record)
                updated = self._submit(path, self.spec.update_method, payload, f"gemme {self.spec.title}")
                if updated is None:
                    continue
                st.success(f"{self.spec.title} er gemt af backenden.")
                st.rerun()

    def _render_fields(self, form_key: str, *, editing: bool, record: Mapping | None = None) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for spec in self.spec.fields:
            key = f"{form_key}::{spec.name}"
            disabled = editing and not spec.editable
            if record is not None:
                current = record.get(spec.name, spec.default)
            else:
                current = spec.default
            help_text = spec.help or None
            if spec.kind == "textarea":
                values[spec.name] = st.text_area(spec.label, value=str(current or ""), disabled=disabled, help=help_text)
            elif spec.kind == "password":
                values[spec.name] = st.text_input(spec.label, value="", type="password", disabled=disabled, help=help_text or "Lad feltet være tomt for at beholde den gemte værdi")
            elif spec.kind == "number":
                values[spec.name] = st.number_input(spec.label, value=float(current) if current is not None else 0.0, disabled=disabled, help=help_text)
            elif spec.kind == "select":
                options = list(spec.options)
                values[spec.name] = st.selectbox(spec.label, options, index=options.index(current) if current in options else 0, disabled=disabled, help=help_text)
            elif spec.kind == "checkbox":
                values[spec.name] = st.checkbox(spec.label, value=bool(current), disabled=disabled, help=help_text)
            else:
                values[spec.name] = st.text_input(spec.label, value=str(current or ""), disabled=disabled, help=help_text)
        return values
