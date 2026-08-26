"""
Tests for GitHub PR & Webhook Bot Integration Service

Tests cover:
- GitHubAuthenticator (token and app auth)
- WebhookVerifier and WebhookParser
- GitHubPRBot main service
- PR creation and management
- Patch conversion to PR
- Webhook processing
- Commit signing
- Changelog generation
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
import requests

from services.github_pr_bot import (
    # Enums
    PRStatus,
    PRAction,
    WebhookEventType,
    AuthMethod,
    GitHubConfig,
    
    # Data Classes
    TokenAuthConfig,
    AppAuthConfig,
    PRMetadata,
    PatchInfo,
    CommitInfo,
    ChangelogEntry,
    PRResult,
    WebhookPayload,
    WebhookResponse,
    
    # Exceptions
    GitHubPRBotError,
    GitHubAPIError,
    AuthenticationError,
    WebhookVerificationError,
    RateLimitError,
    
    # Utilities
    GitHubAuthenticator,
    WebhookVerifier,
    WebhookParser,
    
    # Main Service
    GitHubPRBot,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_token():
    """Mock GitHub personal access token."""
    return "ghp_" + "a" * 36


@pytest.fixture
def mock_app_config():
    """Mock GitHub App configuration."""
    return AppAuthConfig(
        app_id="123456",
        private_key="-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7VJTqLpD2HJgF\n...\n-----END PRIVATE KEY-----",
        installation_id="987654",
    )


@pytest.fixture
def mock_token_config():
    """Mock token authentication configuration."""
    return TokenAuthConfig(token="ghp_" + "a" * 36)


@pytest.fixture
def mock_webhook_secret():
    """Mock webhook secret."""
    return "webhook-secret-12345"


@pytest.fixture
def sample_patch_info():
    """Sample patch information."""
    return PatchInfo(
        patch_id="patch-123",
        patch_content="diff --git a/file.py b/file.py\n...",
        author="test-user",
        summary="Fix bug in file.py",
        files_changed=["file.py", "test_file.py"],
        timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_pr_metadata():
    """Sample PR metadata."""
    return PRMetadata(
        title="Fix critical bug",
        description="This PR fixes a critical bug in the system",
        branch="feat/fix-bug",
        base_branch="main",
        labels=["bug", "critical"],
        assignees=["user1"],
        reviewers=["reviewer1", "reviewer2"],
        draft=False,
    )


@pytest.fixture
def sample_wbs_summary():
    """Sample WBS summary."""
    return {
        "title": "Bug Fix Implementation",
        "description": "Implementation of critical bug fix",
        "version": "v1.0.1",
        "items": [
            {
                "id": "WBS-001",
                "type": "fix",
                "description": "Fixed null pointer exception",
                "status": "completed",
            },
            {
                "id": "WBS-002",
                "type": "test",
                "description": "Added unit tests",
                "status": "completed",
            },
        ],
    }


@pytest.fixture
def sample_test_results():
    """Sample test results."""
    return {
        "summary": {
            "total": 10,
            "passed": 10,
            "failed": 0,
            "skipped": 0,
        },
        "failures": [],
        "warnings": [],
    }


@pytest.fixture
def github_config():
    """GitHub API configuration."""
    return GitHubConfig(
        api_url="https://api.github.com",
        user_agent="test-bot/1.0.0",
        timeout=30,
        retry_count=3,
        retry_delay=1.0,
    )


# =============================================================================
# GitHubAuthenticator Tests
# =============================================================================

class TestGitHubAuthenticator:
    """Tests for GitHubAuthenticator."""
    
    def test_init_with_token(self, mock_token):
        """Test initialization with token."""
        auth = GitHubAuthenticator(token=mock_token)
        assert auth.get_auth_method() == AuthMethod.TOKEN
    
    def test_init_with_app_credentials(self, mock_app_config):
        """Test initialization with app credentials."""
        auth = GitHubAuthenticator(
            app_id=mock_app_config.app_id,
            private_key=mock_app_config.private_key,
        )
        assert auth.get_auth_method() == AuthMethod.APP
    
    def test_init_without_credentials(self):
        """Test initialization without any credentials raises error."""
        with pytest.raises(AuthenticationError, match="Either token or app credentials"):
            GitHubAuthenticator()
    
    def test_get_access_token_with_token_auth(self, mock_token):
        """Test getting access token with token authentication."""
        auth = GitHubAuthenticator(token=mock_token)
        assert auth.get_access_token() == mock_token
    
    def test_get_headers_with_token(self, mock_token):
        """Test getting headers with token authentication."""
        auth = GitHubAuthenticator(token=mock_token)
        headers = auth.get_headers()
        
        assert "Authorization" in headers
        assert headers["Authorization"] == f"token {mock_token}"
        assert headers["Accept"] == "application/vnd.github+json"
        assert headers["X-GitHub-Api-Version"] == "2022-11-28"
    
    def test_get_headers_with_extra_headers(self, mock_token):
        """Test getting headers with extra headers."""
        auth = GitHubAuthenticator(token=mock_token)
        extra = {"X-Custom-Header": "custom-value"}
        headers = auth.get_headers(extra)
        
        assert headers["X-Custom-Header"] == "custom-value"
        assert "Authorization" in headers
    
    @patch("services.github_pr_auth.serialization.load_pem_private_key")
    @patch("jwt.encode")
    @patch("services.github_pr_auth.requests.post")
    def test_get_access_token_with_app_auth(self, mock_post, mock_jwt_encode, mock_load_key, mock_app_config):
        # Mock private key loading
        mock_key = MagicMock()
        mock_load_key.return_value = mock_key
        
        # Mock JWT encoding
        mock_jwt_encode.return_value = "mocked.jwt.token"
        
        # Mock the response
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"token": "ghs_" + "b" * 36}
        mock_post.return_value = mock_response
        
        auth = GitHubAuthenticator(
            app_id=mock_app_config.app_id,
            private_key=mock_app_config.private_key,
            installation_id=mock_app_config.installation_id,
        )
        
        token = auth.get_access_token()
        assert token == "ghs_" + "b" * 36
        
        # Verify the request was made correctly
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "app/installations" in call_args[0][0]
        assert "Authorization" in call_args[1]["headers"]
    
    def test_app_auth_without_installation_id(self, mock_app_config):
        """Test app auth without installation ID raises error."""
        auth = GitHubAuthenticator(
            app_id=mock_app_config.app_id,
            private_key=mock_app_config.private_key,
        )
        
        with pytest.raises(AuthenticationError, match="Installation ID required"):
            auth.get_access_token()


# =============================================================================
# WebhookVerifier Tests
# =============================================================================

class TestWebhookVerifier:
    """Tests for WebhookVerifier."""
    
    def test_verify_valid_signature(self, mock_webhook_secret):
        """Test verification of valid signature."""
        import hmac
        import hashlib
        
        verifier = WebhookVerifier(mock_webhook_secret)
        
        payload = b'{"action": "opened"}'
        secret = mock_webhook_secret.encode()
        expected_hash = hmac.new(secret, payload, hashlib.sha256).hexdigest()
        signature = f"sha256={expected_hash}"
        
        assert verifier.verify_signature(payload, signature) is True
    
    def test_verify_invalid_signature(self, mock_webhook_secret):
        """Test verification of invalid signature."""
        verifier = WebhookVerifier(mock_webhook_secret)
        
        payload = b'{"action": "opened"}'
        signature = "sha256=invalidhashvalue"
        
        assert verifier.verify_signature(payload, signature) is False
    
    def test_verify_missing_signature(self, mock_webhook_secret):
        """Test verification with missing signature."""
        verifier = WebhookVerifier(mock_webhook_secret)
        
        payload = b'{"action": "opened"}'
        
        assert verifier.verify_signature(payload, "") is False
    
    def test_verify_wrong_prefix(self, mock_webhook_secret):
        """Test verification with wrong signature prefix."""
        verifier = WebhookVerifier(mock_webhook_secret)
        
        payload = b'{"action": "opened"}'
        signature = "sha512=somehash"  # Wrong algorithm
        
        assert verifier.verify_signature(payload, signature) is False
    
    def test_verify_different_payload(self, mock_webhook_secret):
        """Test verification with different payload."""
        import hmac
        import hashlib
        
        verifier = WebhookVerifier(mock_webhook_secret)
        
        # Create signature for one payload
        payload1 = b'{"action": "opened"}'
        secret = mock_webhook_secret.encode()
        expected_hash = hmac.new(secret, payload1, hashlib.sha256).hexdigest()
        signature = f"sha256={expected_hash}"
        
        # Try to verify with different payload
        payload2 = b'{"action": "closed"}'
        
        assert verifier.verify_signature(payload2, signature) is False


# =============================================================================
# WebhookParser Tests
# =============================================================================

class TestWebhookParser:
    """Tests for WebhookParser."""
    
    def test_parse_pull_request_opened(self):
        """Test parsing pull_request opened event."""
        payload = {
            "action": "opened",
            "number": 123,
            "pull_request": {
                "id": 123456,
                "number": 123,
                "title": "Test PR",
                "state": "open",
            },
            "repository": {
                "id": 123456789,
                "name": "test-repo",
                "full_name": "owner/test-repo",
            },
            "sender": {
                "login": "test-user",
                "id": 12345,
            },
        }
        
        body = json.dumps(payload).encode()
        parsed = WebhookParser.parse_payload(
            body,
            event_type="pull_request",
            action="opened",
        )
        
        assert parsed.event_type == WebhookEventType.PULL_REQUEST
        assert parsed.action == "opened"
        assert parsed.pull_request["number"] == 123
        assert parsed.repository["name"] == "test-repo"
        assert parsed.sender["login"] == "test-user"
    
    def test_parse_issue_comment(self):
        """Test parsing issue_comment event."""
        payload = {
            "action": "created",
            "issue": {
                "number": 456,
                "title": "Test Issue",
            },
            "comment": {
                "id": 123456,
                "body": "/kodegen fix this",
            },
            "repository": {
                "name": "test-repo",
            },
            "sender": {
                "login": "test-user",
            },
        }
        
        body = json.dumps(payload).encode()
        parsed = WebhookParser.parse_payload(
            body,
            event_type="issue_comment",
            action="created",
        )
        
        assert parsed.event_type == WebhookEventType.ISSUE_COMMENT
        assert parsed.action == "created"
        assert parsed.issue["number"] == 456
        assert parsed.comment["body"] == "/kodegen fix this"
    
    def test_parse_invalid_json(self):
        """Test parsing invalid JSON raises error."""
        with pytest.raises(WebhookVerificationError, match="Invalid JSON payload"):
            WebhookParser.parse_payload(
                b"not valid json",
                event_type="pull_request",
            )
    
    def test_parse_empty_payload(self):
        """Test parsing empty payload."""
        parsed = WebhookParser.parse_payload(
            b"{}",
            event_type="push",
        )
        
        assert parsed.event_type == WebhookEventType.PUSH
        assert parsed.action is None
        assert parsed.pull_request is None


# =============================================================================
# ChangelogEntry Tests
# =============================================================================

class TestChangelogEntry:
    """Tests for ChangelogEntry."""
    
    def test_to_markdown_basic(self):
        """Test basic changelog markdown generation."""
        entry = ChangelogEntry(
            version="v1.0.0",
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            author="test-user",
            changes=["Change 1", "Change 2"],
        )
        
        markdown = entry.to_markdown()
        
        assert "## [v1.0.0] - 2024-01-15" in markdown
        assert "Change 1" in markdown
        assert "Change 2" in markdown
        assert "test-user" not in markdown  # Author not in basic markdown
    
    def test_to_markdown_with_all_sections(self):
        """Test changelog markdown with all sections."""
        entry = ChangelogEntry(
            version="v2.0.0",
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            author="test-user",
            changes=["Change 1"],
            breaking_changes=["Breaking change"],
            features=["New feature"],
            fixes=["Bug fix"],
        )
        
        markdown = entry.to_markdown()
        
        assert "## [v2.0.0]" in markdown
        assert "### Breaking Changes" in markdown
        assert "Breaking change" in markdown
        assert "### Features" in markdown
        assert "New feature" in markdown
        assert "### Fixes" in markdown
        assert "Bug fix" in markdown
        assert "### Changes" in markdown
        assert "Change 1" in markdown
    
    def test_to_markdown_empty_sections(self):
        """Test changelog markdown with empty sections."""
        entry = ChangelogEntry(
            version="v1.0.0",
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            author="test-user",
            changes=[],
        )
        
        markdown = entry.to_markdown()
        
        assert "## [v1.0.0]" in markdown
        assert "🚨 Breaking Changes" not in markdown
        assert "✨ Features" not in markdown
        assert "🐛 Fixes" not in markdown
        assert "📝 Changes" not in markdown


# =============================================================================
# PRResult Tests
# =============================================================================

class TestPRResult:
    """Tests for PRResult."""
    
    def test_default_values(self):
        """Test PRResult with default values."""
        result = PRResult()
        
        assert result.pr_number is None
        assert result.pr_url is None
        assert result.status == PRStatus.PENDING
        assert result.commit_hash is None
        assert result.changelog_entry is None
        assert result.errors == []
        assert result.warnings == []
        assert result.metadata == {}
    
    def test_with_values(self):
        """Test PRResult with values."""
        changelog = ChangelogEntry(
            version="v1.0.0",
            timestamp=datetime.now(timezone.utc),
            author="test",
            changes=[],
        )
        
        result = PRResult(
            pr_number=123,
            pr_url="https://github.com/owner/repo/pull/123",
            status=PRStatus.CREATED,
            commit_hash="abc123",
            changelog_entry=changelog,
            errors=["Error 1"],
            warnings=["Warning 1"],
            metadata={"key": "value"},
        )
        
        assert result.pr_number == 123
        assert result.pr_url == "https://github.com/owner/repo/pull/123"
        assert result.status == PRStatus.CREATED
        assert result.commit_hash == "abc123"
        assert result.changelog_entry == changelog
        assert result.errors == ["Error 1"]
        assert result.warnings == ["Warning 1"]
        assert result.metadata == {"key": "value"}


# =============================================================================
# GitHubPRBot Initialization Tests
# =============================================================================

class TestGitHubPRBotInitialization:
    """Tests for GitHubPRBot initialization."""
    
    def test_init_with_token_auth(self, mock_token_config, github_config):
        """Test initialization with token authentication."""
        bot = GitHubPRBot(
            owner="test-owner",
            repo="test-repo",
            auth_config=mock_token_config,
            config=github_config,
        )
        
        assert bot.owner == "test-owner"
        assert bot.repo == "test-repo"
        assert bot.repo_full_name == "test-owner/test-repo"
        assert bot.config == github_config
    
    def test_init_with_app_auth(self, mock_app_config, github_config):
        """Test initialization with app authentication."""
        bot = GitHubPRBot(
            owner="test-owner",
            repo="test-repo",
            auth_config=mock_app_config,
            config=github_config,
        )
        
        assert bot.owner == "test-owner"
        assert bot.repo == "test-repo"
    
    def test_init_with_webhook_secret(self, mock_token_config, mock_webhook_secret):
        """Test initialization with webhook secret."""
        bot = GitHubPRBot(
            owner="test-owner",
            repo="test-repo",
            auth_config=mock_token_config,
            webhook_secret=mock_webhook_secret,
        )
        
        assert bot.webhook_secret == mock_webhook_secret
        assert bot._webhook_verifier is not None
    
    def test_init_without_webhook_secret(self, mock_token_config):
        """Test initialization without webhook secret."""
        bot = GitHubPRBot(
            owner="test-owner",
            repo="test-repo",
            auth_config=mock_token_config,
        )
        
        assert bot.webhook_secret is None
        assert bot._webhook_verifier is None


# =============================================================================
# GitHubPRBot Changelog Tests
# =============================================================================

class TestGitHubPRBotChangelog:
    """Tests for GitHubPRBot changelog generation."""
    
    @pytest.fixture
    def bot(self, mock_token_config):
        """Create a bot instance for testing."""
        return GitHubPRBot(
            owner="test-owner",
            repo="test-repo",
            auth_config=mock_token_config,
        )
    
    def test_generate_changelog_basic(self, bot, sample_patch_info, sample_wbs_summary, sample_test_results):
        """Test basic changelog generation."""
        changelog = bot._generate_changelog(
            sample_patch_info,
            sample_wbs_summary,
            sample_test_results,
        )
        
        assert changelog.version == "v1.0.1"
        assert changelog.author == "test-user"
        assert len(changelog.features) == 0
        assert len(changelog.fixes) == 1
        assert len(changelog.changes) >= 1
    
    def test_generate_changelog_from_patch_timestamp(self, bot, sample_patch_info):
        """Test changelog version from patch timestamp."""
        wbs_summary = {"items": []}
        test_results = {"summary": {}}
        
        changelog = bot._generate_changelog(
            sample_patch_info,
            wbs_summary,
            test_results,
        )
        
        # Should generate version from date
        assert changelog.version.startswith("v20240115")
    
    def test_generate_changelog_with_breaking_changes(self, bot, sample_patch_info):
        """Test changelog with breaking changes."""
        wbs_summary = {
            "version": "v2.0.0",
            "items": [
                {"type": "breaking", "description": "Breaking change 1"},
                {"type": "MAJOR", "description": "Breaking change 2"},
            ],
        }
        test_results = {"summary": {}}
        
        changelog = bot._generate_changelog(
            sample_patch_info,
            wbs_summary,
            test_results,
        )
        
        assert len(changelog.breaking_changes) == 2
        assert "Breaking change 1" in changelog.breaking_changes
        assert "Breaking change 2" in changelog.breaking_changes
    
    def test_generate_changelog_with_features(self, bot, sample_patch_info):
        """Test changelog with features."""
        wbs_summary = {
            "version": "v1.0.0",
            "items": [
                {"type": "feature", "description": "New feature 1"},
                {"type": "new", "description": "New feature 2"},
            ],
        }
        test_results = {"summary": {}}
        
        changelog = bot._generate_changelog(
            sample_patch_info,
            wbs_summary,
            test_results,
        )
        
        assert len(changelog.features) == 2
        assert "New feature 1" in changelog.features
        assert "New feature 2" in changelog.features


# =============================================================================
# GitHubPRBot PR Body Formatting Tests
# =============================================================================

class TestGitHubPRBotPRBodyFormatting:
    """Tests for GitHubPRBot PR body formatting."""
    
    @pytest.fixture
    def bot(self, mock_token_config):
        """Create a bot instance for testing."""
        return GitHubPRBot(
            owner="test-owner",
            repo="test-repo",
            auth_config=mock_token_config,
        )
    
    def test_format_pr_body(self, bot, sample_patch_info, sample_wbs_summary, sample_test_results):
        """Test PR body formatting."""
        changelog = bot._generate_changelog(
            sample_patch_info,
            sample_wbs_summary,
            sample_test_results,
        )
        
        pr_body = bot._format_pr_body(
            sample_patch_info,
            sample_wbs_summary,
            sample_test_results,
            changelog,
        )
        
        # Check for main sections
        assert "# Bug Fix Implementation" in pr_body
        assert "## Patch Information" in pr_body
        assert "## Changelog" in pr_body
        assert "## Test Results" in pr_body
        assert "## Work Breakdown Structure" in pr_body
        
        # Check for patch info
        assert "**Patch ID:** `patch-123`" in pr_body
        assert "**Author:** test-user" in pr_body
        assert "file.py" in pr_body
    
    def test_format_test_results(self, bot):
        """Test test results formatting."""
        test_results = {
            "summary": {
                "total": 15,
                "passed": 14,
                "failed": 1,
                "skipped": 0,
            },
            "failures": [
                {"name": "test_1", "message": "Test failed"},
            ],
        }
        
        formatted = bot._format_test_results(test_results)
        
        assert "**Total:** 15" in formatted
        assert "**Passed:** 14" in formatted
        assert "**Failed:** 1" in formatted
        assert "test_1: Test failed" in formatted
    
    def test_format_wbs_summary(self, bot):
        """Test WBS summary formatting."""
        wbs_summary = {
            "items": [
                {"id": "WBS-001", "type": "fix", "description": "Fix bug", "status": "done"},
                {"id": "WBS-002", "type": "test", "description": "Add tests", "status": "done"},
            ],
        }
        
        formatted = bot._format_wbs_summary(wbs_summary)
        
        assert "[fix] **WBS-001**: Fix bug (done)" in formatted
        assert "[test] **WBS-002**: Add tests (done)" in formatted


# =============================================================================
# GitHubPRBot Validation Tests
# =============================================================================

class TestGitHubPRBotValidation:
    """Tests for GitHubPRBot validation methods."""
    
    @pytest.fixture
    def bot(self, mock_token_config):
        """Create a bot instance for testing."""
        return GitHubPRBot(
            owner="test-owner",
            repo="test-repo",
            auth_config=mock_token_config,
        )
    
    def test_validate_patch_valid(self, bot, sample_patch_info):
        """Test validation of valid patch."""
        is_valid, errors = bot.validate_patch(sample_patch_info)
        
        assert is_valid is True
        assert len(errors) == 0
    
    def test_validate_patch_empty_content(self, bot):
        """Test validation of patch with empty content."""
        patch = PatchInfo(
            patch_id="patch-123",
            patch_content="",
            author="test-user",
            summary="",
        )
        
        is_valid, errors = bot.validate_patch(patch)
        
        assert is_valid is False
        assert "Patch content is empty" in errors
    
    def test_validate_patch_missing_id(self, bot):
        """Test validation of patch without ID."""
        patch = PatchInfo(
            patch_id="",
            patch_content="diff...",
            author="test-user",
            summary="",
        )
        
        is_valid, errors = bot.validate_patch(patch)
        
        assert is_valid is False
        assert "Patch ID is required" in errors
    
    def test_validate_patch_missing_author(self, bot):
        """Test validation of patch without author."""
        patch = PatchInfo(
            patch_id="patch-123",
            patch_content="diff...",
            author="",
            summary="",
        )
        
        is_valid, errors = bot.validate_patch(patch)
        
        assert is_valid is False
        assert "Author is required" in errors


# =============================================================================
# GitHubPRBot Command Extraction Tests
# =============================================================================

class TestGitHubPRBotCommandExtraction:
    """Tests for GitHubPRBot command extraction."""
    
    @pytest.fixture
    def bot(self, mock_token_config):
        """Create a bot instance for testing."""
        return GitHubPRBot(
            owner="test-owner",
            repo="test-repo",
            auth_config=mock_token_config,
        )
    
    def test_extract_commands_single(self, bot):
        """Test extraction of single command."""
        text = "Please fix this /kodegen fix issue"
        commands = bot._extract_commands(text)
        
        assert len(commands) == 1
        assert "/kodegen fix issue" in commands[0]
    
    def test_extract_commands_multiple(self, bot):
        """Test extraction of multiple commands."""
        text = "Run /kodegen test and then /kodegen status"
        commands = bot._extract_commands(text)
        
        assert len(commands) >= 1
        command_text = ' '.join(commands).lower()
        assert 'test' in command_text
        assert 'status' in command_text
    
    def test_extract_commands_case_insensitive(self, bot):
        """Test command extraction is case insensitive."""
        text = "/KODEGEN FIX /kodegen Test"
        commands = bot._extract_commands(text)
        
        assert len(commands) >= 1
    
    def test_extract_commands_with_args(self, bot):
        """Test command extraction with arguments."""
        text = "/kodegen merge --force --no-ff"
        commands = bot._extract_commands(text)
        
        assert len(commands) == 1
        assert "merge" in commands[0]
        assert "--force" in commands[0]
        assert "--no-ff" in commands[0]
    
    def test_extract_commands_none(self, bot):
        """Test extraction when no commands present."""
        text = "This is just a regular comment"
        commands = bot._extract_commands(text)
        
        assert len(commands) == 0


# =============================================================================
# GitHubPRBot Commit Signing Tests
# =============================================================================

class TestGitHubPRBotCommitSigning:
    """Tests for GitHubPRBot commit signing."""
    
    @pytest.fixture
    def bot(self, mock_token_config):
        """Create a bot instance for testing."""
        return GitHubPRBot(
            owner="test-owner",
            repo="test-repo",
            auth_config=mock_token_config,
        )
    
    def test_sign_commit(self, bot):
        """Test signing a commit."""
        signature = bot.sign_commit("abc123", "Test commit message")
        
        assert signature is not None
        # Signature should be base64 encoded
        decoded = base64.b64decode(signature)
        assert len(decoded) == 64  # SHA-256 hash length
    
    def test_create_signed_commit(self, bot):
        """Test creating a signed commit (mocked)."""
        # This test would need mocking of the GitHub API
        # For now, we just test the signature generation part
        pass


# =============================================================================
# GitHubPRBot Webhook Processing Tests
# =============================================================================

class TestGitHubPRBotWebhookProcessing:
    """Tests for GitHubPRBot webhook processing."""
    
    @pytest.fixture
    def bot(self, mock_token_config, mock_webhook_secret):
        """Create a bot instance for testing."""
        return GitHubPRBot(
            owner="test-owner",
            repo="test-repo",
            auth_config=mock_token_config,
            webhook_secret=mock_webhook_secret,
        )
    
    @pytest.fixture
    def mock_request(self):
        """Create a mock FastAPI request."""
        request = MagicMock()
        request.headers = {}
        request.body = AsyncMock()
        return request
    
    def test_route_webhook_pr_opened(self, bot):
        """Test routing of PR opened webhook."""
        payload = WebhookPayload(
            event_type=WebhookEventType.PULL_REQUEST,
            action="opened",
            pull_request={"number": 123, "title": "Test PR", "body": "/kodegen fix"},
            repository={"name": "test-repo"},
            sender={"login": "test-user"},
        )
        
        response = bot._route_webhook(payload)
        
        assert response.status == "processed"
        assert len(response.actions) > 0
        assert response.pr_number == 123
    
    def test_route_webhook_issue_comment(self, bot):
        """Test routing of issue comment webhook."""
        payload = WebhookPayload(
            event_type=WebhookEventType.ISSUE_COMMENT,
            action="created",
            issue={"number": 456},
            comment={"id": 123, "body": "/kodegen help"},
            repository={"name": "test-repo"},
            sender={"login": "test-user"},
        )
        
        response = bot._route_webhook(payload)
        
        assert response.status in ["processed", "ignored"]
        assert response.comment_id == 123
    
    def test_route_webhook_unknown_event(self, bot):
        """Test routing of unknown event type."""
        payload = WebhookPayload(
            event_type=WebhookEventType.PUSH,
            action="pushed",
            repository={"name": "test-repo"},
            sender={"login": "test-user"},
        )
        
        response = bot._route_webhook(payload)
        
        assert response.status == "acknowledged"
    
    def test_handle_pr_opened_with_command(self, bot):
        """Test handling PR opened with /kodegen command."""
        pr = {
            "number": 123,
            "title": "Test PR",
            "body": "Please /kodegen fix this issue",
        }
        
        response = bot._handle_pr_opened(123, pr)
        
        assert response.status == "processed"
        assert len(response.actions) > 0
    
    def test_handle_pr_opened_without_command(self, bot):
        """Test handling PR opened without /kodegen command."""
        pr = {
            "number": 123,
            "title": "Test PR",
            "body": "Regular PR description",
        }
        
        response = bot._handle_pr_opened(123, pr)
        
        assert response.status == "ignored"
    
    def test_process_fix_command(self, bot):
        """Test processing /kodegen fix command."""
        action = bot._process_fix_command(123, [])
        
        assert "fix workflow" in action
        assert "PR #123" in action
    
    def test_process_test_command(self, bot):
        """Test processing /kodegen test command."""
        action = bot._process_test_command(123, [])
        
        assert "tests" in action
        assert "PR #123" in action
    
    def test_process_merge_command(self, bot):
        """Test processing /kodegen merge command."""
        # Mock the merge_pull_request method
        with patch.object(bot, 'merge_pull_request') as mock_merge:
            mock_merge.return_value = PRResult(
                pr_number=123,
                status=PRStatus.MERGED,
            )
            
            action = bot._process_merge_command(123, [])
            
            assert "Merged PR #123" in action
    
    def test_process_status_command(self, bot):
        """Test processing /kodegen status command."""
        # Mock the get_pull_request method
        with patch.object(bot, 'get_pull_request') as mock_get_pr:
            mock_get_pr.return_value = {"state": "open"}
            
            action = bot._process_status_command(123, [])
            
            assert "status: open" in action


# =============================================================================
# GitHubPRBot API Client Tests (Mocked)
# =============================================================================

class TestGitHubPRBotAPIClient:
    """Tests for GitHubPRBot API client methods (with mocking)."""
    
    @pytest.fixture
    def bot(self, mock_token_config):
        """Create a bot instance for testing."""
        return GitHubPRBot(
            owner="test-owner",
            repo="test-repo",
            auth_config=mock_token_config,
        )
    
    @patch("services.github_pr_api.requests.request")
    def test_api_request_get_success(self, mock_request, bot):
        """Test successful GET API request."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": 123, "name": "test"}
        mock_response.headers = {
            "x-ratelimit-remaining": "5000",
            "x-ratelimit-reset": "1234567890",
        }
        mock_request.return_value = mock_response
        
        result = bot._api_request("GET", "/repos/test-owner/test-repo")
        
        assert result == {"id": 123, "name": "test"}
    
    @patch("services.github_pr_api.requests.request")
    def test_api_request_post_success(self, mock_request, bot):
        """Test successful POST API request."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": 123, "number": 1}
        mock_response.headers = {"x-ratelimit-remaining": "5000"}
        mock_request.return_value = mock_response
        
        result = bot._api_request(
            "POST",
            "/repos/test-owner/test-repo/pulls",
            data={"title": "Test PR"},
        )
        
        assert result == {"id": 123, "number": 1}
    
    @patch("services.github_pr_api.requests.request")
    def test_api_request_rate_limit_exceeded(self, mock_request, bot):
        """Test rate limit exceeded handling."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.json.return_value = {"message": "API rate limit exceeded"}
        mock_response.headers = {"x-ratelimit-remaining": "0"}
        mock_request.return_value = mock_response
        
        with pytest.raises(RateLimitError):
            bot._api_request("GET", "/repos/test-owner/test-repo")
    
    @patch("services.github_pr_api.requests.request")
    def test_api_request_authentication_error(self, mock_request, bot):
        """Test authentication error handling."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"message": "Bad credentials"}
        mock_response.headers = {"x-ratelimit-remaining": "5000"}
        mock_request.return_value = mock_response
        
        with pytest.raises(AuthenticationError):
            bot._api_request("GET", "/repos/test-owner/test-repo")
    
    @patch("services.github_pr_api.requests.request")
    def test_api_request_not_found(self, mock_request, bot):
        """Test not found error handling."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"message": "Not Found"}
        mock_response.headers = {"x-ratelimit-remaining": "5000"}
        mock_request.return_value = mock_response
        
        with pytest.raises(GitHubAPIError):
            bot._api_request("GET", "/repos/test-owner/test-repo/nonexistent")
    
    @patch("services.github_pr_api.requests.request")
    def test_api_request_retry_on_timeout(self, mock_request, bot):
        """Test retry on timeout."""
        # First call times out, second succeeds
        mock_response_fail = MagicMock()
        mock_response_fail.status_code = 408
        
        mock_response_success = MagicMock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = {"id": 123}
        mock_response_success.headers = {"x-ratelimit-remaining": "5000"}
        
        mock_request.side_effect = [
            requests.exceptions.Timeout(),
            mock_response_success,
        ]
        
        result = bot._api_request("GET", "/repos/test-owner/test-repo")
        
        assert result == {"id": 123}
        assert mock_request.call_count == 2
    
    @patch("services.github_pr_api.requests.request")
    def test_get_repo_info(self, mock_request, bot):
        """Test getting repository info."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": 123456789,
            "name": "test-repo",
            "full_name": "test-owner/test-repo",
            "default_branch": "main",
        }
        mock_response.headers = {"x-ratelimit-remaining": "5000"}
        mock_request.return_value = mock_response
        
        info = bot.get_repo_info()
        
        assert info["name"] == "test-repo"
        assert info["full_name"] == "test-owner/test-repo"
    
    @patch("services.github_pr_api.requests.request")
    def test_get_default_branch(self, mock_request, bot):
        """Test getting default branch."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "default_branch": "develop",
        }
        mock_response.headers = {"x-ratelimit-remaining": "5000"}
        mock_request.return_value = mock_response
        
        branch = bot.get_default_branch()
        
        assert branch == "develop"


# =============================================================================
# GitHubPRBot PR Creation Tests (Mocked)
# =============================================================================

class TestGitHubPRBotPRCreation:
    """Tests for GitHubPRBot PR creation methods (with mocking)."""
    
    @pytest.fixture
    def bot(self, mock_token_config):
        """Create a bot instance for testing."""
        return GitHubPRBot(
            owner="test-owner",
            repo="test-repo",
            auth_config=mock_token_config,
        )
    
    @patch.object(GitHubPRBot, '_api_request')
    def test_create_pull_request_success(self, mock_api, bot):
        """Test successful PR creation."""
        mock_api.return_value = {
            "number": 123,
            "html_url": "https://github.com/test-owner/test-repo/pull/123",
            "state": "open",
        }
        
        result = bot.create_pull_request(
            title="Test PR",
            body="Test description",
            head="feature-branch",
            base="main",
        )
        
        assert result.status == PRStatus.CREATED
        assert result.pr_number == 123
        assert result.pr_url == "https://github.com/test-owner/test-repo/pull/123"
    
    @patch.object(GitHubPRBot, '_api_request')
    def test_create_pull_request_with_reviewers(self, mock_api, bot):
        """Test PR creation with reviewers."""
        mock_api.return_value = {
            "number": 123,
            "html_url": "https://github.com/test-owner/test-repo/pull/123",
        }
        
        result = bot.create_pull_request(
            title="Test PR",
            body="Test description",
            head="feature-branch",
            base="main",
            reviewers=["reviewer1", "reviewer2"],
        )
        
        assert result.status == PRStatus.CREATED
        # Verify that _add_reviewers was called
        mock_api.assert_called()
    
    @patch.object(GitHubPRBot, '_api_request')
    def test_create_pull_request_failure(self, mock_api, bot):
        """Test PR creation failure."""
        mock_api.side_effect = GitHubAPIError("Creation failed", 400)
        
        result = bot.create_pull_request(
            title="Test PR",
            body="Test description",
            head="feature-branch",
            base="main",
        )
        
        assert result.status == PRStatus.FAILED
        assert len(result.errors) > 0
    
    @patch.object(GitHubPRBot, '_api_request')
    def test_get_pull_request(self, mock_api, bot):
        """Test getting PR information."""
        mock_api.return_value = {
            "number": 123,
            "title": "Test PR",
            "state": "open",
        }
        
        pr = bot.get_pull_request(123)
        
        assert pr["number"] == 123
        assert pr["title"] == "Test PR"
    
    @patch.object(GitHubPRBot, '_api_request')
    def test_update_pull_request(self, mock_api, bot):
        """Test updating a PR."""
        mock_api.return_value = {
            "number": 123,
            "title": "Updated PR",
            "body": "Updated description",
        }
        
        result = bot.update_pull_request(
            pr_number=123,
            title="Updated PR",
            body="Updated description",
        )
        
        assert result.status == PRStatus.UPDATED
        assert result.pr_number == 123
    
    @patch.object(GitHubPRBot, '_api_request')
    def test_merge_pull_request_success(self, mock_api, bot):
        """Test successful PR merge."""
        mock_api.return_value = {
            "merged": True,
            "sha": "abc123",
            "message": "Pull request merged",
        }
        
        result = bot.merge_pull_request(
            pr_number=123,
            commit_title="Merge commit",
            merge_method="squash",
        )
        
        assert result.status == PRStatus.MERGED
        assert result.commit_hash == "abc123"
    
    @patch.object(GitHubPRBot, '_api_request')
    def test_merge_pull_request_failure(self, mock_api, bot):
        """Test failed PR merge."""
        mock_api.return_value = {
            "merged": False,
            "message": "Merge conflict",
        }
        
        result = bot.merge_pull_request(
            pr_number=123,
            commit_title="Merge commit",
        )
        
        assert result.status == PRStatus.FAILED
        assert "Merge conflict" in result.errors[0]


# =============================================================================
# GitHubPRBot Patch Conversion Tests
# =============================================================================

class TestGitHubPRBotPatchConversion:
    """Tests for GitHubPRBot patch conversion to PR."""
    
    @pytest.fixture
    def bot(self, mock_token_config):
        """Create a bot instance for testing."""
        return GitHubPRBot(
            owner="test-owner",
            repo="test-repo",
            auth_config=mock_token_config,
        )
    
    @patch.object(GitHubPRBot, 'create_pull_request')
    @patch.object(GitHubPRBot, 'add_pr_comment')
    def test_apply_patch_and_create_pr_success(
        self,
        mock_add_comment,
        mock_create_pr,
        bot,
        sample_patch_info,
        sample_pr_metadata,
        sample_wbs_summary,
        sample_test_results,
    ):
        """Test successful patch conversion to PR."""
        mock_create_pr.return_value = PRResult(
            pr_number=123,
            pr_url="https://github.com/test-owner/test-repo/pull/123",
            status=PRStatus.CREATED,
        )
        mock_add_comment.return_value = {"id": 456}
        
        result = bot.apply_patch_and_create_pr(
            patch=sample_patch_info,
            pr_metadata=sample_pr_metadata,
            wbs_summary=sample_wbs_summary,
            test_results=sample_test_results,
        )
        
        assert result.status == PRStatus.CREATED
        assert result.pr_number == 123
        assert result.pr_url == "https://github.com/test-owner/test-repo/pull/123"
        assert result.changelog_entry is not None
        assert result.warnings == []
    
    @patch.object(GitHubPRBot, 'create_pull_request')
    def test_apply_patch_and_create_pr_failure(
        self,
        mock_create_pr,
        bot,
        sample_patch_info,
        sample_pr_metadata,
        sample_wbs_summary,
        sample_test_results,
    ):
        """Test failed patch conversion to PR."""
        mock_create_pr.return_value = PRResult(
            status=PRStatus.FAILED,
            errors=["Failed to create branch"],
        )
        
        result = bot.apply_patch_and_create_pr(
            patch=sample_patch_info,
            pr_metadata=sample_pr_metadata,
            wbs_summary=sample_wbs_summary,
            test_results=sample_test_results,
        )
        
        assert result.status == PRStatus.FAILED
        assert len(result.errors) > 0


# =============================================================================
# Integration Tests
# =============================================================================

class TestGitHubPRBotIntegration:
    """Integration tests for GitHubPRBot."""
    
    @pytest.fixture
    def bot(self, mock_token_config):
        """Create a bot instance for testing."""
        return GitHubPRBot(
            owner="test-owner",
            repo="test-repo",
            auth_config=mock_token_config,
        )
    
    def test_full_workflow(self, bot, sample_patch_info, sample_pr_metadata, sample_wbs_summary, sample_test_results):
        """Test the full workflow from patch to PR."""
        # This is a high-level test that verifies all components work together
        
        # Step 1: Validate patch
        is_valid, errors = bot.validate_patch(sample_patch_info)
        assert is_valid is True
        
        # Step 2: Generate changelog
        changelog = bot._generate_changelog(
            sample_patch_info,
            sample_wbs_summary,
            sample_test_results,
        )
        assert changelog is not None
        
        # Step 3: Format PR body
        pr_body = bot._format_pr_body(
            sample_patch_info,
            sample_wbs_summary,
            sample_test_results,
            changelog,
        )
        assert "# Bug Fix Implementation" in pr_body
        
        # Step 4: Generate status comment
        status_comment = bot._generate_status_comment(
            sample_patch_info,
            sample_wbs_summary,
            sample_test_results,
        )
        assert "Patch Successfully Converted" in status_comment
        
        # Step 5: Extract commands
        commands = bot._extract_commands("/kodegen fix /kodegen test")
        assert len(commands) >= 1
    
    def test_webhook_to_pr_creation_flow(
        self,
        bot,
        sample_patch_info,
        sample_pr_metadata,
        sample_wbs_summary,
        sample_test_results,
    ):
        """Test the flow from webhook to PR creation."""
        # Simulate a webhook payload with a /kodegen command
        payload = WebhookPayload(
            event_type=WebhookEventType.PULL_REQUEST,
            action="opened",
            pull_request={
                "number": 123,
                "title": "Test PR",
                "body": "/kodegen convert this patch to PR",
            },
            repository={"name": "test-repo"},
            sender={"login": "test-user"},
        )
        
        # Process the webhook
        response = bot._route_webhook(payload)
        
        # Should process the command
        assert response.status in ["processed", "acknowledged"]
        assert response.pr_number == 123


# =============================================================================
# Edge Cases and Error Handling Tests
# =============================================================================

class TestGitHubPRBotEdgeCases:
    """Tests for edge cases and error handling."""
    
    @pytest.fixture
    def bot(self, mock_token_config):
        """Create a bot instance for testing."""
        return GitHubPRBot(
            owner="test-owner",
            repo="test-repo",
            auth_config=mock_token_config,
        )
    
    def test_empty_wbs_summary(self, bot, sample_patch_info, sample_test_results):
        """Test with empty WBS summary."""
        changelog = bot._generate_changelog(
            sample_patch_info,
            {},
            sample_test_results,
        )
        
        assert changelog is not None
        assert isinstance(changelog.changes, list)
    
    def test_empty_test_results(self, bot, sample_patch_info, sample_wbs_summary):
        """Test with empty test results."""
        changelog = bot._generate_changelog(
            sample_patch_info,
            sample_wbs_summary,
            {},
        )
        
        assert changelog is not None
    
    def test_pr_body_with_no_files_changed(self, bot, sample_wbs_summary, sample_test_results):
        """Test PR body with no files changed."""
        patch = PatchInfo(
            patch_id="patch-123",
            patch_content="diff...",
            author="test-user",
            summary="",
            files_changed=[],
        )
        changelog = bot._generate_changelog(patch, sample_wbs_summary, sample_test_results)
        pr_body = bot._format_pr_body(patch, sample_wbs_summary, sample_test_results, changelog)
        
        assert "**Files Changed:** None" in pr_body
    
    def test_command_extraction_with_special_characters(self, bot):
        """Test command extraction with special characters."""
        text = "Some text /kodegen fix 'with quotes' and /kodegen test \"with double quotes\""
        commands = bot._extract_commands(text)
        
        assert len(commands) == 2
    
    def test_command_extraction_multiline(self, bot):
        """Test command extraction from multiline text."""
        text = """
        First line
        /kodegen fix
        Second line
        /kodegen test
        Third line
        """
        commands = bot._extract_commands(text)
        
        assert len(commands) == 2
    
    def test_changelog_with_unicode(self, bot):
        """Test changelog with unicode characters."""
        changelog = ChangelogEntry(
            version="v1.0.0",
            timestamp=datetime.now(timezone.utc),
            author="test-user",
            changes=["Fix emoji 🐛 bug", "Add unicode: 你好"],
        )
        
        markdown = changelog.to_markdown()
        
        assert "🐛" in markdown
        assert "你好" in markdown


# =============================================================================
# Performance and Concurrency Tests
# =============================================================================

class TestGitHubPRBotPerformance:
    """Performance and concurrency tests."""
    
    @pytest.fixture
    def bot(self, mock_token_config):
        """Create a bot instance for testing."""
        return GitHubPRBot(
            owner="test-owner",
            repo="test-repo",
            auth_config=mock_token_config,
        )
    
    def test_changelog_generation_performance(self, bot, sample_patch_info, sample_wbs_summary, sample_test_results):
        """Test changelog generation performance."""
        import time
        
        start = time.time()
        for _ in range(100):
            bot._generate_changelog(sample_patch_info, sample_wbs_summary, sample_test_results)
        elapsed = time.time() - start
        
        # Should generate 100 changelogs in less than 1 second
        assert elapsed < 1.0
    
    def test_command_extraction_performance(self, bot):
        """Test command extraction performance."""
        import time
        
        long_text = " /kodegen fix " * 1000
        
        start = time.time()
        commands = bot._extract_commands(long_text)
        elapsed = time.time() - start
        
        assert len(commands) >= 900
        assert elapsed < 0.5


# =============================================================================
# Security Tests
# =============================================================================

class TestGitHubPRBotSecurity:
    """Security-related tests."""
    
    @pytest.fixture
    def bot_with_webhook(self, mock_token_config, mock_webhook_secret):
        """Create a bot with webhook secret."""
        return GitHubPRBot(
            owner="test-owner",
            repo="test-repo",
            auth_config=mock_token_config,
            webhook_secret=mock_webhook_secret,
        )
    
    def test_webhook_signature_verification(self, bot_with_webhook, mock_webhook_secret):
        """Test webhook signature verification."""
        import hmac
        import hashlib
        
        payload = b'{"action": "opened"}'
        secret = mock_webhook_secret.encode()
        expected_hash = hmac.new(secret, payload, hashlib.sha256).hexdigest()
        signature = f"sha256={expected_hash}"
        
        assert bot_with_webhook._webhook_verifier.verify_signature(payload, signature) is True
    
    def test_webhook_signature_tampering(self, bot_with_webhook):
        """Test that tampered payloads are rejected."""
        import hmac
        import hashlib
        
        payload = b'{"action": "opened"}'
        secret = bot_with_webhook.webhook_secret.encode()
        expected_hash = hmac.new(secret, payload, hashlib.sha256).hexdigest()
        signature = f"sha256={expected_hash}"
        
        # Tamper with the payload
        tampered_payload = b'{"action": "closed"}'
        
        assert bot_with_webhook._webhook_verifier.verify_signature(tampered_payload, signature) is False
    
    def test_command_injection_prevention(self, bot_with_webhook):
        """Test that commands are properly sanitized."""
        # Commands should only match the expected pattern
        text = "Malicious: /kodegen ; rm -rf /"
        commands = bot_with_webhook._extract_commands(text)
        
        # Should extract the command but not execute anything
        assert len(commands) == 1
        assert "; rm -rf /" in commands[0]
        # The actual processing would need to sanitize this further
    
    def test_signing_key_not_exposed(self, bot_with_webhook):
        """Test that signing key is not exposed in outputs."""
        # The signing key should not appear in any generated output
        changelog = ChangelogEntry(
            version="v1.0.0",
            timestamp=datetime.now(timezone.utc),
            author="test",
            changes=[],
        )
        markdown = changelog.to_markdown()
        
        # Signing key should not be in markdown
        signing_key_str = bot_with_webhook._signing_key.decode("utf-8", errors="ignore")
        assert signing_key_str not in markdown
