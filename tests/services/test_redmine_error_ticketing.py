"""Tests for the Redmine error-ticketing orchestration adapter."""

from __future__ import annotations

from services.redmine_contracts import (
    RedmineConfig,
    RedmineIssue,
)
from services.redmine_error_ticketing import (
    FailureSignature,
    RedmineErrorTickerService,
    redmine_config_from_env,
)


class _FakeRedmineClient:
    """In-memory stand-in for the REST client, recording traffic."""

    def __init__(self) -> None:
        self.config = RedmineConfig(url="https://redmine.example.com", api_key="k")
        self.issues: list[RedmineIssue] = []
        self.drafts: list = []
        self._next_id = 100
        self.updates: list[tuple[int, dict]] = []

    def create_issue(self, draft) -> RedmineIssue:
        self.drafts.append(draft)
        self._next_id += 1
        issue = RedmineIssue(
            id=self._next_id,
            subject=draft.subject,
            project_id=draft.project_id,
            tracker_id=draft.tracker_id,
            status_id=draft.status_id,
            priority_id=draft.priority_id,
            url=f"https://redmine.example.com/issues/{self._next_id}",
        )
        self.issues.append(issue)
        return issue

    def search_issue(self, subject: str, *, limit: int = 5) -> list[RedmineIssue]:
        return [i for i in self.issues if i.subject == subject]

    def update_issue(self, issue_id: int, **kwargs) -> RedmineIssue:
        issue = next(i for i in self.issues if i.id == issue_id)
        self.updates.append((issue_id, kwargs))
        return issue


def _ticker(client) -> RedmineErrorTickerService:
    return RedmineErrorTickerService(client)


def test_not_configured_is_non_fatal() -> None:
    result = RedmineErrorTickerService(None).report_verification_failure(
        module="a", error="boom"
    )
    assert result.ok is False
    assert result.error == "not-configured"
    assert result.issue is None


def test_creates_issue_on_first_failure() -> None:
    client = _FakeRedmineClient()
    result = _ticker(client).report_verification_failure(
        module="mod", error="assert failed"
    )
    assert result.ok is True
    assert result.issue is not None
    assert result.issue.subject.startswith("[DOR] verification failure: mod:")
    assert "[DOR]" in result.issue.subject
    assert "Fingerprint" in client.drafts[0].description
    assert len(client.issues) == 1


def test_recurring_failure_deduplicates() -> None:
    client = _FakeRedmineClient()
    ticker = _ticker(client)
    first = ticker.report_verification_failure(module="mod", error="same error")
    second = ticker.report_verification_failure(module="mod", error="same error")
    assert first.ok and second.ok
    assert len(client.issues) == 1
    assert second.issue is not None and second.issue.id == first.issue.id
    assert second.deduplicated is True
    assert client.updates and client.updates[-1][1].get("status_id") == "2"


def test_different_errors_create_separate_issues() -> None:
    client = _FakeRedmineClient()
    ticker = _ticker(client)
    ticker.report_verification_failure(module="mod", error="error one")
    ticker.report_verification_failure(module="mod", error="error two")
    assert len(client.issues) == 2


def test_self_healing_exhaustion_reports_attempts() -> None:
    client = _FakeRedmineClient()
    result = _ticker(client).report_self_healing_exhaustion(
        module="mod", error="loop failure", attempts=3
    )
    assert result.ok and result.issue is not None
    assert result.issue.subject.startswith("[DOR] self_healing failure:")
    assert "self_healing_attempts" in client.drafts[0].description


def test_env_parsing_returns_config() -> None:
    config = redmine_config_from_env(
        {
            "REDMINE_URL": "https://redmine.example.com",
            "REDMINE_API_KEY": "secret",
            "REDMINE_PROJECT_ID": "5",
            "REDMINE_TRACKER_ID": "7",
        }
    )
    assert config is not None
    assert config.project_id == "5"
    assert config.tracker_id == "7"
    assert config.api_key == "secret"


def test_env_parsing_disabled_without_url() -> None:
    assert redmine_config_from_env({"REDMINE_API_KEY": "secret"}) is None


def test_signature_fingerprint_is_stable_and_scoped() -> None:
    a = FailureSignature.from_verification(module="m", error="boom")
    b = FailureSignature.from_verification(module="m", error="boom")
    c = FailureSignature.from_verification(module="other", error="boom")
    assert a.fingerprint == b.fingerprint
    assert a.fingerprint != c.fingerprint
    assert len(a.fingerprint) == 10


def test_with_redmine_from_env_disabled_without_url() -> None:
    from services.self_healing_synthesis import SelfHealingSynthesisLoop

    loop = SelfHealingSynthesisLoop.with_redmine_from_env(
        {"REDMINE_API_KEY": "secret"}, synthesizer=None
    )
    assert loop.error_ticker is None
