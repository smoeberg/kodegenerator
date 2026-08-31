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


def test_severity_to_priority_mapping():
    """Spec: severity levels map onto Redmine priority ids."""
    from services.redmine_contracts import RedmineIssuePriority, RedmineSeverity

    assert (
        RedmineSeverity.CRITICAL.to_priority() == RedmineIssuePriority.IMMEDIATE.value
    )
    assert RedmineSeverity.ERROR.to_priority() == RedmineIssuePriority.NORMAL.value
    assert RedmineSeverity.WARNING.to_priority() == RedmineIssuePriority.LOW.value
    assert RedmineSeverity.INFO.to_priority() == RedmineIssuePriority.LOW.value
    assert RedmineSeverity.DEBUG.to_priority() == RedmineIssuePriority.LOW.value


def test_config_parses_spec_tracker_and_severity_and_custom_fields():
    """Spec env names REDMINE_TRACKER_ID / REDMINE_SEVERITY / REDMINE_FIELD_*."""
    from services.redmine_contracts import RedmineSeverity, redmine_config_from_env

    cfg = redmine_config_from_env(
        {
            "REDMINE_URL": "https://redmine.example.com",
            "REDMINE_API_KEY": "secret",
            "REDMINE_TRACKER_ID": "5",
            "REDMINE_SEVERITY": "CRITICAL",
            "REDMINE_FIELD_ERROR_TYPE": "1:error_type",
            "REDMINE_FIELD_SERVICE": "2:dor",
            "REDMINE_FIELD_GIT_COMMIT": "3:abc123",
        }
    )
    assert cfg is not None
    assert cfg.tracker_id == "5"
    assert cfg.default_severity is RedmineSeverity.CRITICAL
    assert cfg.custom_fields == (
        ("1", "error_type"),
        ("2", "dor"),
        ("3", "abc123"),
    )


def test_config_accepts_dor_style_tracker_alias():
    """REDMINE_ISSUE_TRACKER_ID still works, but the spec name wins."""
    from services.redmine_contracts import redmine_config_from_env

    cfg = redmine_config_from_env(
        {
            "REDMINE_URL": "https://redmine.example.com",
            "REDMINE_API_KEY": "secret",
            "REDMINE_ISSUE_TRACKER_ID": "7",
        }
    )
    assert cfg is not None
    assert cfg.tracker_id == "7"
