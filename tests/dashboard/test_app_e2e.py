from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

import dashboard.api_client as api_client_module
import dashboard.realtime as realtime_module
from dashboard.api_client import DORAPIError


APP_PATH = Path(__file__).resolve().parents[2] / "dashboard" / "app.py"
PROJECT_PAGE = "🏗️ Logik 1: Projekt & Krav"
DEVELOPMENT_PAGE = "⚙️ Logik 2: Udvikling & Cockpit"
ADMIN_PAGE = "🛡️ Logik 3: Administration & Governance"


class FakeRealtime:
    def __init__(self, _client: Any, workflow_id: str) -> None:
        self.workflow_id = workflow_id
        self.status = "connecting"
        self.stopped = False

    def start(self) -> None:
        self.status = "connected"

    def stop(self) -> None:
        self.status = "offline"
        self.stopped = True

    def drain(self) -> list[Any]:
        return []


class FakeAPI:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.login_calls: list[tuple[str, str]] = []
        self.get_failures: dict[str, DORAPIError] = {}
        self.post_failures: dict[str, DORAPIError] = {}
        self.execution = {
            "workflow_id": "wf-1",
            "project_name": "Demo Project",
            "current_state": "implementation",
            "tasks": [
                {
                    "id": "task-1",
                    "task_type": "implementation",
                    "status": "completed",
                },
                {
                    "id": "task-test",
                    "task_type": "test",
                    "status": "completed",
                },
            ],
            "tests_generated": True,
            "tests_passed": True,
            "context": {
                "requirements": {
                    "requirements": [
                        {
                            "id": "REQ-1",
                            "description": "Controller can inspect provenance.",
                            "acceptance_criteria": ["Trace renders without invented links."],
                        }
                    ]
                },
                "gate_decision_history": [],
            },
        }
        self.gates = [
            {
                "id": "gate-1",
                "name": "Architecture approval",
                "description": "Human decision required.",
                "resolved": False,
                "decision": None,
                "blocking": True,
            }
        ]
        self.proposals = [
            {
                "id": "proposal-1",
                "title": "Implementation proposal",
                "summary": "One reviewed change.",
                "status": "proposed",
                "created_by": "implementation-agent",
                "created_at": "2026-09-05T00:00:00Z",
                "files": [
                    {
                        "path": "service.py",
                        "diff": "+def run():\n+    return True",
                    }
                ],
            }
        ]
        self.redmine_health = {
            "configured": True,
            "reachable": True,
            "verified": True,
            "checked_at": "2026-09-05T00:00:00Z",
            "error": None,
            "missing_configuration": [],
        }

    def login(self, username: str, password: str) -> str:
        self.login_calls.append((username, password))
        return "token-from-login"

    def health(self) -> dict[str, str]:
        self.calls.append(("GET", "/health", {}))
        return {"status": "ok"}

    def readiness(self) -> dict[str, str]:
        self.calls.append(("GET", "/health/ready", {}))
        return {"status": "ready"}

    def get(self, path: str, **kwargs: Any) -> Any:
        self.calls.append(("GET", path, kwargs))
        if path in self.get_failures:
            raise self.get_failures[path]
        if path == "/api/v1/execution/wf-1":
            return deepcopy(self.execution)
        if path == "/api/v1/execution/wf-1/gates":
            return deepcopy(self.gates)
        if path == "/api/v1/execution/wf-1/proposals":
            return deepcopy(self.proposals)
        if path == "/api/v1/integrations/redmine/health":
            return deepcopy(self.redmine_health)
        if path.startswith("/api/v1/bot-governance/"):
            return []
        raise AssertionError(f"unexpected GET in AppTest fake: {path}")

    def post(self, path: str, **kwargs: Any) -> Any:
        self.calls.append(("POST", path, kwargs))
        if path in self.post_failures:
            raise self.post_failures[path]
        if path == "/api/v1/execution/wf-1/gates/decide":
            payload = kwargs["json"]
            decision = payload["decision"]
            self.gates[0]["resolved"] = True
            self.gates[0]["decision"] = decision
            self.gates[0]["blocking"] = decision == "rejected"
            self.execution["context"]["gate_decision_history"] = [
                {
                    "gate_id": payload["gate_id"],
                    "decision": decision,
                    "approver": "controller",
                }
            ]
            return {
                "gate_id": payload["gate_id"],
                "decision": decision,
                "workflow_advanced": decision == "approved",
            }
        return {"ok": True}


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> FakeAPI:
    client = FakeAPI()
    monkeypatch.setattr(
        api_client_module,
        "DORAPIClient",
        lambda *args, **kwargs: client,
    )
    monkeypatch.setattr(realtime_module, "WorkflowRealtime", FakeRealtime)
    return client


def _run_app(*, authenticated: bool = True) -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=5)
    if authenticated:
        at.session_state["access_token"] = "existing-token"
        at.session_state["username"] = "controller"
        at.session_state["organization_id"] = "org-1"
    return at.run(timeout=5)


def _by_label(elements: Any, label: str) -> Any:
    matches = [element for element in elements if getattr(element, "label", None) == label]
    assert len(matches) == 1, f"expected one element labelled {label!r}, got {len(matches)}"
    return matches[0]


def _values(elements: Any) -> list[Any]:
    return [element.value for element in elements]


def _navigate(at: AppTest, page: str) -> AppTest:
    assert at.sidebar.radio[0].value in {PROJECT_PAGE, DEVELOPMENT_PAGE, ADMIN_PAGE}
    return at.sidebar.radio[0].set_value(page).run(timeout=5)


def _open_workflow(at: AppTest, workflow_id: str = "wf-1") -> AppTest:
    at = _navigate(at, DEVELOPMENT_PAGE)
    workflow_input = _by_label(at.text_input, "Aktivt Workflow ID")
    return workflow_input.set_value(workflow_id).run(timeout=5)


def test_login_then_navigate_all_three_canonical_pages(fake_api: FakeAPI) -> None:
    at = _run_app(authenticated=False)

    assert _values(at.title) == ["⚡ DOR Control Plane"]
    _by_label(at.text_input, "Brugernavn").set_value("anna")
    _by_label(at.text_input, "Adgangskode").set_value("secret")
    at = _by_label(at.button, "Log ind").click().run(timeout=5)

    assert fake_api.login_calls == [("anna", "secret")]
    assert at.session_state["access_token"] == "token-from-login"
    assert at.session_state["username"] == "anna"
    assert PROJECT_PAGE in _values(at.sidebar.radio[0])
    assert "🏗️ Logik 1: Projekt & Kravspecifikation" in _values(at.header)

    at = _navigate(at, ADMIN_PAGE)
    assert "🛡️ Logik 3: Systemadministration & Governance" in _values(at.header)

    at = _navigate(at, DEVELOPMENT_PAGE)
    assert "⚙️ Logik 2: Udvikling & Decision Cockpit" in _values(at.header)
    assert any("Angiv et Workflow ID" in value for value in _values(at.info))
    assert not at.exception


def test_execution_401_clears_auth_and_returns_to_login(fake_api: FakeAPI) -> None:
    fake_api.get_failures["/api/v1/execution/wf-expired"] = DORAPIError(
        401, "expired"
    )
    at = _run_app()
    at = _navigate(at, DEVELOPMENT_PAGE)
    at = _by_label(at.text_input, "Aktivt Workflow ID").set_value("wf-expired").run(
        timeout=5
    )

    assert at.session_state["access_token"] is None
    assert at.session_state["username"] is None
    assert at.session_state["organization_id"] is None
    assert _values(at.title) == ["⚡ DOR Control Plane"]
    assert not at.sidebar.radio
    assert not at.exception


@pytest.mark.parametrize(
    ("button_label", "decision", "expected_message"),
    [
        ("✅ Godkend gate", "approved", "Gate er godkendt af backend."),
        (
            "❌ Afvis gate",
            "rejected",
            "Gate er afvist. Workflowet forbliver fail-closed",
        ),
    ],
)
def test_gate_decision_posts_exact_payload_and_rerenders_backend_state(
    fake_api: FakeAPI,
    button_label: str,
    decision: str,
    expected_message: str,
) -> None:
    at = _open_workflow(_run_app())
    at = _by_label(at.button, button_label).click().run(timeout=5)

    assert (
        "POST",
        "/api/v1/execution/wf-1/gates/decide",
        {"json": {"gate_id": "gate-1", "decision": decision}},
    ) in fake_api.calls
    assert fake_api.gates[0]["decision"] == decision
    assert not any(
        button.label in {"✅ Godkend gate", "❌ Afvis gate"} for button in at.button
    )

    visible_messages = _values(at.success) + _values(at.warning)
    assert any(expected_message in message for message in visible_messages)
    assert not at.exception


def test_evidence_trace_renders_canonical_chain(fake_api: FakeAPI) -> None:
    at = _open_workflow(_run_app())

    assert "🔎 Why / Evidence Trace" in _values(at.subheader)
    assert any("REQ-1" in value for value in _values(at.markdown))
    assert any(
        "Requirements → Tasks → Agent work → Proposals → Tests → Gates → Human decisions"
        in value
        for value in _values(at.caption)
    )
    expander_labels = [expander.label for expander in at.expander]
    assert "1 · Requirements" in expander_labels
    assert "7 · Human decisions" in expander_labels
    assert "Provenance-kvalitet & kendte gaps" in expander_labels
    assert not at.exception


def test_admin_renders_governance_redmine_and_health(fake_api: FakeAPI) -> None:
    at = _navigate(_run_app(), ADMIN_PAGE)

    assert "🧠 Bot Governance & Multi-bot Control Plane" in _values(at.subheader)
    assert "Redmine Integration" in _values(at.subheader)
    assert "Readiness & Drift" in _values(at.subheader)

    tab_labels = [tab.label for tab in at.tabs]
    for expected in (
        "Bot Governance",
        "Redmine Integration",
        "System Health",
        "Forbindelser",
        "Deployments",
        "Botprofiler",
        "Roller",
        "Council templates",
        "Allokering",
        "Selection",
        "Evidens",
    ):
        assert expected in tab_labels

    at = _by_label(at.button, "Verificér Redmine-forbindelse").click().run(timeout=5)
    metrics = {metric.label: metric.value for metric in at.metric}
    assert metrics["Konfigureret"] == "Ja"
    assert metrics["Reachable"] == "Ja"
    assert metrics["Verificeret"] == "Ja"
    assert "Redmine-forbindelsen er verificeret af backend." in _values(at.success)
    assert not at.exception


def test_redmine_api_error_is_fail_closed(fake_api: FakeAPI) -> None:
    fake_api.get_failures["/api/v1/integrations/redmine/health"] = DORAPIError(
        503, "upstream unavailable"
    )
    at = _navigate(_run_app(), ADMIN_PAGE)
    at = _by_label(at.button, "Verificér Redmine-forbindelse").click().run(timeout=5)

    assert any("Redmine health-check fejlede (503)" in value for value in _values(at.error))
    assert "Redmine-forbindelsen er verificeret af backend." not in _values(at.success)
    assert not any(metric.label == "Verificeret" for metric in at.metric)
    assert not at.exception
