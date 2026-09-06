from dashboard.context_navigation import (
    normalize_organization_catalog,
    normalize_project_catalog,
)
from dashboard.operator_overview import (
    filter_executions_for_project,
    normalize_execution_overview,
)


def test_organization_catalog_preserves_only_canonical_backend_entries() -> None:
    catalog = normalize_organization_catalog(
        {
            "active_organization_id": "org-2",
            "organizations": [
                {
                    "id": "org-1",
                    "name": "Alpha",
                    "description": "Primary tenant",
                    "is_admin": True,
                    "created_at": "2026-09-06T10:00:00Z",
                    "updated_at": "2026-09-06T10:00:00Z",
                },
                {
                    "id": "org-2",
                    "name": "Beta",
                    "description": "Second tenant",
                    "is_admin": False,
                },
                {"id": "", "name": "Malformed"},
                {"id": "org-ignored", "name": ""},
                "not-a-mapping",
            ],
        }
    )

    assert catalog["active_organization_id"] == "org-2"
    assert [(item["id"], item["name"], item["is_admin"]) for item in catalog["organizations"]] == [
        ("org-1", "Alpha", True),
        ("org-2", "Beta", False),
    ]


def test_project_catalog_normalizes_authenticated_tenant_context() -> None:
    catalog = normalize_project_catalog(
        {
            "organization_id": "org-1",
            "projects": [
                {
                    "project_id": "project-1",
                    "organization_id": "org-1",
                    "name": "DOR GUI",
                    "status": "launch_requested",
                    "project_fingerprint": "a" * 64,
                    "updated_at": "2026-09-05T12:00:00Z",
                }
            ],
        }
    )

    assert catalog["organization_id"] == "org-1"
    assert catalog["projects"] == [
        {
            "project_id": "project-1",
            "organization_id": "org-1",
            "name": "DOR GUI",
            "status": "launch_requested",
            "project_fingerprint": "a" * 64,
            "updated_at": "2026-09-05T12:00:00Z",
        }
    ]


def test_execution_overview_preserves_explicit_project_identity() -> None:
    executions = normalize_execution_overview(
        [
            {
                "workflow_id": "wf-1",
                "organization_id": "org-1",
                "project_id": "project-1",
                "project_name": "DOR GUI",
                "current_state": "implementation",
                "task_total": 1,
                "task_open": 1,
                "terminal": False,
                "blocking_gate": None,
                "rework": None,
                "action_required": "work_in_progress",
            }
        ]
    )

    assert executions[0]["organization_id"] == "org-1"
    assert executions[0]["project_id"] == "project-1"


def test_project_filter_never_uses_project_name_as_provenance() -> None:
    executions = normalize_execution_overview(
        [
            {
                "workflow_id": "wf-linked",
                "project_id": "project-1",
                "project_name": "Same Name",
                "current_state": "implementation",
                "terminal": False,
            },
            {
                "workflow_id": "wf-unlinked",
                "project_id": None,
                "project_name": "Same Name",
                "current_state": "implementation",
                "terminal": False,
            },
            {
                "workflow_id": "wf-other",
                "project_id": "project-2",
                "project_name": "Same Name",
                "current_state": "implementation",
                "terminal": False,
            },
        ]
    )

    filtered = filter_executions_for_project(executions, "project-1")

    assert [item["workflow_id"] for item in filtered] == ["wf-linked"]
    assert {item["workflow_id"] for item in filter_executions_for_project(executions, None)} == {
        "wf-linked",
        "wf-unlinked",
        "wf-other",
    }
