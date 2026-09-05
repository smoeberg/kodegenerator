from types import SimpleNamespace

from api.endpoints.execution_overview import _execution_summary


class FakeOrchestrator:
    def get_pipeline_status(self, workflow_id: str):
        return {
            "workflow_id": workflow_id,
            "project_name": "Shared Name",
            "current_state": "implementation",
            "created_at": "2026-09-05T10:00:00Z",
            "updated_at": "2026-09-05T11:00:00Z",
            "tasks": [],
        }

    def get_blocking_gate(self, workflow_id: str):
        return None


def test_execution_summary_surfaces_explicit_project_id() -> None:
    workflow = SimpleNamespace(
        id="wf-1",
        context={"organization_id": "org-1", "project_id": "project-1"},
        metadata={},
    )

    summary = _execution_summary(FakeOrchestrator(), workflow)

    assert summary["organization_id"] == "org-1"
    assert summary["project_id"] == "project-1"


def test_execution_summary_does_not_infer_project_id_from_project_name() -> None:
    workflow = SimpleNamespace(
        id="wf-legacy",
        context={"organization_id": "org-1", "project_name": "Shared Name"},
        metadata={},
    )

    summary = _execution_summary(FakeOrchestrator(), workflow)

    assert summary["project_name"] == "Shared Name"
    assert summary["project_id"] is None
