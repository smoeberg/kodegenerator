"""Factory console (completion plan step 1, GUI skeleton).

The console is a thin client: it shows backend state and sends the project
manager's commands. Malformed backend payloads fail closed.
"""

from __future__ import annotations

from typing import Any

import pytest

from dashboard import factory_console as fc
from dashboard.api_client import DORAPIError

ORG = "org-1"
WF = "wf-1234567890"

STATUS = {
    "workflow_id": WF,
    "current_state": "architecture_generated",
    "tasks": [
        {"id": "t1", "task_type": "generate_architecture", "status": "COMPLETED"}
    ],
    "context": {
        "requirements_ref": {
            "revision": 2,
            "fingerprint": "a" * 64,
            "declared_version": "1.0",
            "requirement_ids": ["REG-01", "REG-02"],
        },
        "requirements_history": [
            {
                "revision": 1,
                "fingerprint": "b" * 64,
                "superseded_by": 2,
                "superseded_at": "2026-11-27T09:00:00+00:00",
            }
        ],
        "artifact_provenance": {
            "generate_architecture": {
                "task_id": "t1",
                "requirements_ref": {
                    "revision": 2,
                    "requirement_ids": ["REG-01", "REG-02"],
                },
                "result_keys": ["architecture"],
            }
        },
    },
    "jobs": [
        {
            "role": "architect",
            "task_type": "generate_architecture",
            "attempt": 1,
            "status": "succeeded",
            "agent": {"tool": "claude-code", "brand": "anthropic"},
            "requirements": {"revision": 2},
            "duration_seconds": 12.5,
            "error": None,
        }
    ],
    "error": None,
}


class FakeClient:
    def __init__(self, responses: dict[tuple[str, str], Any]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict]] = []

    def _respond(self, method: str, path: str, kwargs: dict) -> Any:
        self.calls.append((method, path, kwargs))
        value = self.responses[(method, path)]
        if isinstance(value, Exception):
            raise value
        return value

    def get(self, path: str, **kwargs: Any) -> Any:
        return self._respond("GET", path, kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self._respond("POST", path, kwargs)


def _client(overrides: dict[tuple[str, str], Any] | None = None) -> FakeClient:
    responses = {
        ("GET", "/pipeline/"): {
            "items": [
                {
                    "workflow_id": WF,
                    "name": "husregel-register",
                    "current_state": "architecture_generated",
                    "project_name": "husregel-register",
                    "updated_at": "2026-11-27T10:00:00",
                },
            ]
        },
        ("GET", f"/pipeline/{WF}"): STATUS,
        ("GET", f"/api/v1/pipeline-gates/{WF}"): [
            {
                "id": "g-arch",
                "name": "Architecture Approval",
                "description": "Review the architecture",
                "resolved": False,
                "pending": True,
            },
            {
                "id": "g-req",
                "name": "Requirements Approval",
                "description": "",
                "resolved": True,
                "pending": False,
            },
        ],
        ("GET", f"/pipeline/{WF}/requirements"): {
            "workflow_id": WF,
            "requirements_yaml": "project_name: x\n",
        },
        ("POST", "/api/v1/pipeline-gates/approve"): {
            "workflow_id": WF,
            "gate_id": "g-arch",
            "approved": True,
        },
        ("POST", "/pipeline/start"): {"workflow_id": "wf-new"},
    }
    responses.update(overrides or {})
    return FakeClient(responses)


# --------------------------------------------------------------------- #
# API access
# --------------------------------------------------------------------- #
def test_list_pipelines_is_scoped_to_the_organization() -> None:
    client = _client()
    (row,) = fc.list_pipelines(client, ORG)
    assert row.workflow_id == WF and row.state == "architecture_generated"
    assert client.calls[0][2]["params"]["organization_id"] == ORG


@pytest.mark.parametrize(
    "payload", [None, {"items": "x"}, {"items": [{"name": "no id"}]}]
)
def test_malformed_pipeline_list_fails_closed(payload) -> None:
    with pytest.raises(fc.FactoryConsoleError):
        fc.list_pipelines(_client({("GET", "/pipeline/"): payload}), ORG)


def test_api_errors_become_console_errors() -> None:
    client = _client({("GET", "/pipeline/"): DORAPIError(403, "forbidden")})
    with pytest.raises(fc.FactoryConsoleError, match="403"):
        fc.list_pipelines(client, ORG)


def test_status_for_another_pipeline_is_rejected() -> None:
    client = _client({("GET", f"/pipeline/{WF}"): {**STATUS, "workflow_id": "other"}})
    with pytest.raises(fc.FactoryConsoleError):
        fc.pipeline_status(client, ORG, WF)


def test_gate_decision_sends_exact_payload() -> None:
    client = _client()
    fc.decide_gate(client, ORG, WF, "g-arch", approve=False)
    method, path, kwargs = client.calls[-1]
    assert (method, path) == ("POST", "/api/v1/pipeline-gates/approve")
    assert kwargs["json"] == {
        "workflow_id": WF,
        "gate_id": "g-arch",
        "decision": "rejected",
    }
    assert kwargs["params"] == {"organization_id": ORG}


def test_start_requires_a_kravspec() -> None:
    client = _client()
    with pytest.raises(fc.FactoryConsoleError, match="tom"):
        fc.start_pipeline(client, ORG, "   ")
    assert client.calls == []
    assert fc.start_pipeline(client, ORG, "project_name: x")["workflow_id"] == "wf-new"


# --------------------------------------------------------------------- #
# View model
# --------------------------------------------------------------------- #
def test_inbox_lists_only_pending_unresolved_gates() -> None:
    client = _client()
    pipelines = fc.list_pipelines(client, ORG)
    gates = {WF: fc.pipeline_gates(client, ORG, WF)}
    (item,) = fc.inbox_items(pipelines, gates)
    assert (item.gate_id, item.gate_name, item.project_name) == (
        "g-arch",
        "Architecture Approval",
        "husregel-register",
    )


def test_requirements_revision_history_jobs_and_provenance() -> None:
    summary = fc.requirements_summary(STATUS)
    assert summary == {
        "revision": 2,
        "declared_version": "1.0",
        "fingerprint": "a" * 12,
        "requirement_ids": ["REG-01", "REG-02"],
    }
    assert fc.requirements_history(STATUS)[0]["superseded_by"] == 2
    (job,) = fc.job_rows(STATUS)
    assert (job["rolle"], job["producent"], job["kravspec-revision"]) == (
        "architect",
        "anthropic",
        2,
    )
    (artifact,) = fc.provenance_rows(STATUS)
    assert artifact["krav"] == "REG-01, REG-02"
    assert fc.requirements_summary({"context": {}}) is None


# --------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------- #
def _console_script() -> None:
    import streamlit as st

    from dashboard.factory_console import render_factory_console

    render_factory_console(st.session_state["client"], st.session_state.get("org"))


def _app(client: FakeClient, org: str | None = ORG):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_function(_console_script, default_timeout=30)
    at.session_state["client"] = client
    at.session_state["org"] = org
    return at.run()


def test_console_renders_overview_inbox_and_configuration() -> None:
    at = _app(_client())
    assert not at.exception
    assert [tab.label for tab in at.tabs] == [
        "📋 Projektoverblik",
        "📥 Godkendelsesindbakke",
        "⚙️ Projektkonfiguration",
    ]
    assert any("Venter på din beslutning (1)" in h.value for h in at.subheader)
    assert any(m.label == "Kravspec-revision" and m.value == "2" for m in at.metric)


def test_console_approves_from_the_inbox() -> None:
    client = _client()
    at = _app(client)
    next(b for b in at.button if b.label == "✅ Godkend").click().run(timeout=30)
    decisions = [c for c in client.calls if c[1] == "/api/v1/pipeline-gates/approve"]
    assert decisions and decisions[0][2]["json"]["decision"] == "approved"


def test_console_requires_an_organization() -> None:
    client = _client()
    at = _app(client, org=None)
    assert any("organisation" in w.value for w in at.warning)
    assert client.calls == []
