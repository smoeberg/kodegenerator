"""Tests for Redmine integration contracts."""

from __future__ import annotations

import pytest

from services.redmine_contracts import (
    RedmineConfig,
    RedmineErrorKind,
    RedmineIssue,
    RedmineIssueDraft,
    RedmineIssuePriority,
)


def test_config_requires_url() -> None:
    with pytest.raises(ValueError):
        RedmineConfig(url="").validate()


def test_config_rejects_non_http() -> None:
    with pytest.raises(ValueError):
        RedmineConfig(url="ftp://redmine.example.com").validate()


def test_config_requires_credentials() -> None:
    with pytest.raises(ValueError):
        RedmineConfig(url="https://redmine.example.com").validate()


def test_config_accepts_api_key_only() -> None:
    RedmineConfig(url="https://redmine.example.com", api_key="secret").validate()


def test_config_requires_project_and_tracker() -> None:
    with pytest.raises(ValueError):
        RedmineConfig(
            url="https://redmine.example.com",
            api_key="secret",
            project_id="",
            tracker_id="",
        ).validate()


def test_issue_draft_payload_shape() -> None:
    draft = RedmineIssueDraft(
        subject="boom",
        description="traceback",
        category_id="2",
        assigned_to_id="7",
        custom_fields=(("1", "dor"),),
    )
    assert draft.payload() == {
        "issue": {
            "subject": "boom",
            "description": "traceback",
            "project_id": "1",
            "tracker_id": "1",
            "priority_id": RedmineIssuePriority.NORMAL.value,
            "status_id": "1",
            "category_id": "2",
            "assigned_to_id": "7",
            "custom_fields": [{"id": "1", "value": "dor"}],
        }
    }


def test_issue_from_api_builds_url() -> None:
    issue = RedmineIssue.from_api(
        {
            "id": 42,
            "subject": "boom",
            "project": {"id": 1},
            "tracker": {"id": 2},
            "status": {"id": 3},
            "priority": {"id": 4},
            "author": {"id": 9},
        },
        base_url="https://redmine.example.com/",
    )
    assert issue.id == 42
    assert issue.url == "https://redmine.example.com/issues/42"
    assert issue.priority_id == "4"


def test_error_kinds_are_stable() -> None:
    assert {k.value for k in RedmineErrorKind} == {
        "verification",
        "generation",
        "self_healing",
        "execution",
    }
