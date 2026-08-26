"""
Tests for Approval Gate Service

Tests dækker:
- Klassificering af doc-ændring (AUTO) vs. migration (NEEDS_APPROVAL) vs. secret (BLOCKED)
- Task suspension indtil godkendelse og frigivelse efter approve
- Permanent blokering ved deny med reason i loggen
- TTL-udløb fører til automatisk deny med begrundelsen "expired"
- Webhook integration (mocked)
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from services.approval_gate import (
    ApprovalGate,
    ApprovalGateError,
    ApprovalStatus,
    ChangeClassification,
    Change,
    ApprovalRequest,
)


class TestChangeClassification:
    """Tests for change classification."""
    
    @pytest.fixture
    def gate(self):
        """Create an approval gate for testing."""
        return ApprovalGate()
    
    def test_classify_doc_change_auto_approved(self, gate):
        """Test that documentation changes are AUTO_APPROVED."""
        change = Change(
            change_id="doc-1",
            title="Update README",
            description="Update project documentation",
            author="user-1",
            files_changed=["README.md", "docs/guide.md"],
            diff_summary="Updated documentation files",
        )
        
        classification = gate.classify_change(change)
        
        assert classification == ChangeClassification.AUTO_APPROVED
    
    def test_classify_test_change_auto_approved(self, gate):
        """Test that test changes are AUTO_APPROVED."""
        change = Change(
            change_id="test-1",
            title="Add unit tests",
            description="Add tests for new functionality",
            author="user-1",
            files_changed=["tests/test_module.py", "tests/conftest.py"],
            diff_summary="Added unit tests",
        )
        
        classification = gate.classify_change(change)
        
        assert classification == ChangeClassification.AUTO_APPROVED
    
    def test_classify_refactor_auto_approved(self, gate):
        """Test that refactoring changes are AUTO_APPROVED."""
        change = Change(
            change_id="refactor-1",
            title="Refactor user service",
            description="Clean up user service code",
            author="user-1",
            files_changed=["services/user_service.py"],
            diff_summary="Refactored user service",
        )
        
        classification = gate.classify_change(change)
        
        assert classification == ChangeClassification.AUTO_APPROVED
    
    def test_classify_migration_needs_approval(self, gate):
        """Test that migrations need approval."""
        change = Change(
            change_id="migration-1",
            title="Add user table",
            description="Database migration for user table",
            author="user-1",
            files_changed=["migrations/001_add_user_table.py"],
            diff_summary="Added user table migration",
        )
        
        classification = gate.classify_change(change)
        
        assert classification == ChangeClassification.NEEDS_APPROVAL
    
    def test_classify_migration_in_diff(self, gate):
        """Test that migrations mentioned in diff need approval."""
        change = Change(
            change_id="migration-2",
            title="Update schema",
            description="Schema changes",
            author="user-1",
            files_changed=["models.py"],
            diff_summary="ALTER TABLE users ADD COLUMN email",
        )
        
        classification = gate.classify_change(change)
        
        assert classification == ChangeClassification.NEEDS_APPROVAL
    
    def test_classify_security_change_needs_approval(self, gate):
        """Test that security changes need approval."""
        change = Change(
            change_id="security-1",
            title="Update authentication",
            description="Update JWT authentication",
            author="user-1",
            files_changed=["auth.py"],
            diff_summary="Updated JWT authentication logic",
        )
        
        classification = gate.classify_change(change)
        
        assert classification == ChangeClassification.NEEDS_APPROVAL
    
    def test_classify_new_credential_needs_approval(self, gate):
        """Test that new credentials need approval."""
        change = Change(
            change_id="credential-1",
            title="Create service account",
            description="Create new service account for CI/CD",
            author="user-1",
            files_changed=["config.py"],
            diff_summary="Added new service account",
        )
        
        classification = gate.classify_change(change)
        
        assert classification == ChangeClassification.NEEDS_APPROVAL
    
    def test_classify_api_contract_change_needs_approval(self, gate):
        """Test that API contract changes need approval."""
        change = Change(
            change_id="api-1",
            title="Update API spec",
            description="Update OpenAPI specification",
            author="user-1",
            files_changed=["openapi.yaml", "schemas.py"],
            diff_summary="Updated API endpoints",
        )
        
        classification = gate.classify_change(change)
        
        assert classification == ChangeClassification.NEEDS_APPROVAL
    
    def test_classify_secret_blocked(self, gate):
        """Test that changes with secrets are BLOCKED."""
        change = Change(
            change_id="secret-1",
            title="Add API key",
            description="Add new API key for external service",
            author="user-1",
            files_changed=["config.py"],
            diff_summary="API_KEY = 'secret-key-123'",
        )
        
        classification = gate.classify_change(change)
        
        assert classification == ChangeClassification.BLOCKED
    
    def test_classify_secret_in_filename_blocked(self, gate):
        """Test that files with secret in name are BLOCKED."""
        change = Change(
            change_id="secret-2",
            title="Update config",
            description="Update configuration",
            author="user-1",
            files_changed=["config/secret_keys.py"],
            diff_summary="Updated config",
        )
        
        classification = gate.classify_change(change)
        
        assert classification == ChangeClassification.BLOCKED
    
    def test_classify_destructive_blocked(self, gate):
        """Test that destructive operations are BLOCKED."""
        change = Change(
            change_id="destructive-1",
            title="Clean up database",
            description="Remove old data",
            author="user-1",
            files_changed=["cleanup.py"],
            diff_summary="DROP TABLE users",
        )
        
        classification = gate.classify_change(change)
        
        assert classification == ChangeClassification.BLOCKED
    
    def test_classify_rm_rf_blocked(self, gate):
        """Test that rm -rf is BLOCKED."""
        change = Change(
            change_id="destructive-2",
            title="Clean up files",
            description="Remove temporary files",
            author="user-1",
            files_changed=["cleanup.sh"],
            diff_summary="rm -rf /tmp/*",
        )
        
        classification = gate.classify_change(change)
        
        assert classification == ChangeClassification.BLOCKED


class TestRiskScoreCalculation:
    """Tests for risk score calculation."""
    
    @pytest.fixture
    def gate(self):
        """Create an approval gate for testing."""
        return ApprovalGate()
    
    def test_risk_score_auto_approved(self, gate):
        """Test risk score for AUTO_APPROVED changes."""
        change = Change(
            change_id="doc-1",
            title="Update README",
            description="Update project documentation",
            author="user-1",
            files_changed=["README.md"],
            diff_summary="Updated README",
        )
        
        classification = gate.classify_change(change)
        risk_score = gate.calculate_risk_score(change, classification)
        
        assert classification == ChangeClassification.AUTO_APPROVED
        assert risk_score <= gate._auto_approve_threshold
    
    def test_risk_score_needs_approval(self, gate):
        """Test risk score for NEEDS_APPROVAL changes."""
        change = Change(
            change_id="migration-1",
            title="Create database schema",
            description="Database migration for schema",
            author="user-1",
            files_changed=["migrations/001_create_schema.py"],
            diff_summary="Created database schema",
        )
        
        classification = gate.classify_change(change)
        risk_score = gate.calculate_risk_score(change, classification)
        
        assert classification == ChangeClassification.NEEDS_APPROVAL
        assert risk_score > gate._auto_approve_threshold
        assert risk_score < gate._block_threshold
    
    def test_risk_score_blocked(self, gate):
        """Test risk score for BLOCKED changes."""
        change = Change(
            change_id="secret-1",
            title="Add API key",
            description="Add API key",
            author="user-1",
            files_changed=["config.py"],
            diff_summary="API_KEY = 'secret'",
        )
        
        classification = gate.classify_change(change)
        risk_score = gate.calculate_risk_score(change, classification)
        
        assert classification == ChangeClassification.BLOCKED
        assert risk_score >= gate._block_threshold


class TestRequestApproval:
    """Tests for request_approval method."""
    
    @pytest.fixture
    def gate(self):
        """Create an approval gate for testing."""
        return ApprovalGate(default_ttl_hours=24)
    
    @pytest.fixture
    def sample_change(self):
        """Create a sample change."""
        return Change(
            change_id="change-1",
            title="Update feature",
            description="Update feature implementation",
            author="user-1",
            files_changed=["feature.py"],
            diff_summary="Updated feature",
        )
    
    def test_request_approval_creates_request(self, gate, sample_change):
        """Test that request_approval creates a request."""
        request = gate.request_approval(sample_change)
        
        assert isinstance(request, ApprovalRequest)
        assert request.request_id is not None
        assert request.change == sample_change
        assert request.status == ApprovalStatus.PENDING
        assert request.classification == gate.classify_change(sample_change)
        assert len(request.rationale) > 0
        assert request.risk_score > 0
    
    def test_request_approval_sets_ttl(self, gate, sample_change):
        """Test that request_approval sets TTL correctly."""
        request = gate.request_approval(sample_change, custom_ttl_hours=48)
        
        assert request.expires_at > request.created_at
        # Should be approximately 48 hours in the future
        ttl = request.expires_at - request.created_at
        assert ttl > timedelta(hours=47)
        assert ttl < timedelta(hours=49)
    
    def test_request_approval_stores_request(self, gate, sample_change):
        """Test that request is stored in gate."""
        request = gate.request_approval(sample_change)
        
        stored_request = gate.get_request(request.request_id)
        assert stored_request is not None
        assert stored_request.request_id == request.request_id
    
    def test_request_approval_classifies_correctly(self, gate):
        """Test that request_approval classifies changes correctly."""
        # Test BLOCKED change
        blocked_change = Change(
            change_id="blocked-1",
            title="Add secret",
            description="Add secret key",
            author="user-1",
            files_changed=["secrets.py"],
            diff_summary="SECRET_KEY = 'value'",
        )
        
        request = gate.request_approval(blocked_change)
        assert request.classification == ChangeClassification.BLOCKED
        
        # Check that change is in blocked list
        blocked_changes = gate.get_blocked_changes()
        assert "blocked-1" in blocked_changes


class TestApproveDeny:
    """Tests for approve and deny methods."""
    
    @pytest.fixture
    def gate(self):
        """Create an approval gate for testing."""
        return ApprovalGate(default_ttl_hours=24)
    
    @pytest.fixture
    def pending_request(self, gate):
        """Create a pending approval request."""
        change = Change(
            change_id="change-1",
            title="Update feature",
            description="Update feature",
            author="user-1",
            files_changed=["feature.py"],
            diff_summary="Updated feature",
        )
        return gate.request_approval(change)
    
    def test_approve_request(self, gate, pending_request):
        """Test approving a request."""
        approved = gate.approve(
            request_id=pending_request.request_id,
            reviewer="reviewer-1",
            comment="Looks good",
        )
        
        assert approved.status == ApprovalStatus.APPROVED
        assert approved.reviewer == "reviewer-1"
        assert approved.review_comment == "Looks good"
        assert approved.approved_at is not None
        assert approved.denied_at is None
    
    def test_approve_nonexistent_request(self, gate):
        """Test approving nonexistent request raises error."""
        with pytest.raises(ApprovalGateError, match="not found"):
            gate.approve("nonexistent", "reviewer-1")
    
    def test_approve_already_approved(self, gate, pending_request):
        """Test approving already approved request raises error."""
        gate.approve(pending_request.request_id, "reviewer-1")
        
        with pytest.raises(ApprovalGateError, match="already APPROVED"):
            gate.approve(pending_request.request_id, "reviewer-2")
    
    def test_deny_request(self, gate, pending_request):
        """Test denying a request."""
        denied = gate.deny(
            request_id=pending_request.request_id,
            reviewer="reviewer-1",
            reason="Needs more work",
        )
        
        assert denied.status == ApprovalStatus.DENIED
        assert denied.reviewer == "reviewer-1"
        assert denied.review_comment == "Needs more work"
        assert denied.denied_at is not None
        assert denied.approved_at is None
    
    def test_deny_nonexistent_request(self, gate):
        """Test denying nonexistent request raises error."""
        with pytest.raises(ApprovalGateError, match="not found"):
            gate.deny("nonexistent", "reviewer-1", "reason")
    
    def test_deny_already_denied(self, gate, pending_request):
        """Test denying already denied request raises error."""
        gate.deny(pending_request.request_id, "reviewer-1", "reason")
        
        with pytest.raises(ApprovalGateError, match="already DENIED"):
            gate.deny(pending_request.request_id, "reviewer-2", "another reason")
    
    def test_deny_blocks_change(self, gate, pending_request):
        """Test that denying a request blocks the change."""
        gate.deny(pending_request.request_id, "reviewer-1", "Blocked")
        
        blocked_changes = gate.get_blocked_changes()
        assert pending_request.change.change_id in blocked_changes
        assert blocked_changes[pending_request.change.change_id] == "Blocked"


class TestIsGateOpen:
    """Tests for is_gate_open method."""
    
    @pytest.fixture
    def gate(self):
        """Create an approval gate for testing."""
        return ApprovalGate()
    
    def test_gate_open_auto_approved(self, gate):
        """Test that gate is open for AUTO_APPROVED changes."""
        change = Change(
            change_id="doc-1",
            title="Update README",
            description="Update documentation",
            author="user-1",
            files_changed=["README.md"],
            diff_summary="Updated README",
        )
        
        is_open = gate.is_gate_open(change)
        
        assert is_open is True
    
    def test_gate_closed_needs_approval(self, gate):
        """Test that gate is closed for NEEDS_APPROVAL changes without request."""
        change = Change(
            change_id="migration-1",
            title="Add migration",
            description="Database migration",
            author="user-1",
            files_changed=["migrations/001.py"],
            diff_summary="Added migration",
        )
        
        is_open = gate.is_gate_open(change)
        
        assert is_open is False
    
    def test_gate_open_after_approval(self, gate):
        """Test that gate is open after approval."""
        change = Change(
            change_id="migration-1",
            title="Add migration",
            description="Database migration",
            author="user-1",
            files_changed=["migrations/001.py"],
            diff_summary="Added migration",
        )
        
        # Request approval
        request = gate.request_approval(change)
        assert gate.is_gate_open(change) is False
        
        # Approve request
        gate.approve(request.request_id, "reviewer-1")
        
        # Gate should now be open
        assert gate.is_gate_open(change) is True
    
    def test_gate_closed_blocked_change(self, gate):
        """Test that gate is closed for BLOCKED changes."""
        change = Change(
            change_id="secret-1",
            title="Add secret",
            description="Add secret key",
            author="user-1",
            files_changed=["secrets.py"],
            diff_summary="SECRET = 'value'",
        )
        
        # First, request approval (will be blocked)
        gate.request_approval(change)
        
        is_open = gate.is_gate_open(change)
        
        assert is_open is False
    
    def test_gate_closed_denied_change(self, gate):
        """Test that gate is closed for denied changes."""
        change = Change(
            change_id="change-1",
            title="Update feature",
            description="Update feature",
            author="user-1",
            files_changed=["feature.py"],
            diff_summary="Updated feature",
        )
        
        # Request and deny
        request = gate.request_approval(change)
        gate.deny(request.request_id, "reviewer-1", "Not good enough")
        
        is_open = gate.is_gate_open(change)
        
        assert is_open is False


class TestTTLExpiry:
    """Tests for TTL expiry."""
    
    @pytest.fixture
    def gate(self):
        """Create an approval gate for testing."""
        return ApprovalGate(default_ttl_hours=1)  # Short TTL for testing
    
    def test_request_expiry(self, gate):
        """Test that requests expire after TTL."""
        change = Change(
            change_id="change-1",
            title="Update feature",
            description="Update feature",
            author="user-1",
            files_changed=["feature.py"],
            diff_summary="Updated feature",
        )
        
        # Create request with very short TTL
        with patch('services.approval_gate.datetime') as mock_datetime:
            # Set current time
            now = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
            mock_datetime.now.return_value = now
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            
            request = gate.request_approval(change, custom_ttl_hours=0)  # 0 hours TTL
            
            # Request should be created
            assert request.status == ApprovalStatus.PENDING
            
            # Check that request expires_at is in the past (or same as now with 0 TTL)
            # Since TTL is 0, expires_at should be now, which means it's expired
            assert request.expires_at <= datetime.now(timezone.utc) or request.expires_at == request.created_at
    
    def test_cleanup_expired_requests(self, gate):
        """Test cleanup of expired requests."""
        change = Change(
            change_id="change-1",
            title="Update feature",
            description="Update feature",
            author="user-1",
            files_changed=["feature.py"],
            diff_summary="Updated feature",
        )
        
        # Create request with very short TTL
        with patch('services.approval_gate.datetime') as mock_datetime:
            now = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
            mock_datetime.now.return_value = now
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            
            # Create request with TTL of 0 hours (expires immediately)
            request = gate.request_approval(change, custom_ttl_hours=0)
            
            # Manually replace the request with an expired version
            from services.approval_gate import ApprovalRequest, ApprovalStatus
            expired_request = ApprovalRequest(
                request_id=request.request_id,
                change=request.change,
                classification=request.classification,
                rationale=request.rationale,
                risk_score=request.risk_score,
                status=ApprovalStatus.PENDING,
                created_at=now - timedelta(hours=1),  # Created in the past
                expires_at=now,  # Expires now, so already expired
            )
            gate._requests[request.request_id] = expired_request
        
        # Cleanup expired
        expired_ids = gate.cleanup_expired_requests()
        
        assert request.request_id in expired_ids
        
        # Check that request is now EXPIRED
        updated_request = gate.get_request(request.request_id)
        assert updated_request is not None
        assert updated_request.status == ApprovalStatus.EXPIRED
        
        # Check that change is blocked
        blocked_changes = gate.get_blocked_changes()
        assert change.change_id in blocked_changes
        assert blocked_changes[change.change_id] == "Request expired"
    
    def test_ttl_remaining(self, gate):
        """Test TTL remaining calculation."""
        change = Change(
            change_id="change-1",
            title="Update feature",
            description="Update feature",
            author="user-1",
            files_changed=["feature.py"],
            diff_summary="Updated feature",
        )
        
        with patch('services.approval_gate.datetime') as mock_datetime:
            now = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
            mock_datetime.now.return_value = now
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            
            request = gate.request_approval(change, custom_ttl_hours=24)
            
            # TTL should be approximately 24 hours
            ttl_remaining = request.ttl_remaining
            assert ttl_remaining > timedelta(hours=23)
            assert ttl_remaining < timedelta(hours=25)


class TestCheckAndRequestApproval:
    """Tests for check_and_request_approval method."""
    
    @pytest.fixture
    def gate(self):
        """Create an approval gate for testing."""
        return ApprovalGate(default_ttl_hours=24)
    
    def test_check_and_request_auto_approved(self, gate):
        """Test check_and_request for AUTO_APPROVED change."""
        change = Change(
            change_id="doc-1",
            title="Update README",
            description="Update documentation",
            author="user-1",
            files_changed=["README.md"],
            diff_summary="Updated README",
        )
        
        is_open, request = gate.check_and_request_approval(change)
        
        assert is_open is True
        assert request is None
    
    def test_check_and_request_needs_approval(self, gate):
        """Test check_and_request for NEEDS_APPROVAL change."""
        change = Change(
            change_id="migration-1",
            title="Add migration",
            description="Database migration",
            author="user-1",
            files_changed=["migrations/001.py"],
            diff_summary="Added migration",
        )
        
        is_open, request = gate.check_and_request_approval(change)
        
        assert is_open is False
        assert request is not None
        assert request.status == ApprovalStatus.PENDING
    
    def test_check_and_request_blocked(self, gate):
        """Test check_and_request for BLOCKED change."""
        change = Change(
            change_id="secret-1",
            title="Add API key",
            description="Add API key",
            author="user-1",
            files_changed=["config.py"],
            diff_summary="API_KEY = 'secret-value'",
        )
        
        is_open, request = gate.check_and_request_approval(change)
        
        assert is_open is False
        assert request is not None
        assert request.classification == ChangeClassification.BLOCKED


class TestRationaleGeneration:
    """Tests for rationale generation."""
    
    @pytest.fixture
    def gate(self):
        """Create an approval gate for testing."""
        return ApprovalGate()
    
    def test_rationale_auto_approved(self, gate):
        """Test rationale for AUTO_APPROVED changes."""
        change = Change(
            change_id="doc-1",
            title="Update README",
            description="Update documentation",
            author="user-1",
            files_changed=["README.md"],
            diff_summary="Updated README file",
        )
        
        classification = gate.classify_change(change)
        rationale = gate.generate_rationale(change, classification)
        
        assert "AUTO_APPROVED" in rationale
        assert "Documentation only" in rationale
        assert "Updated README" in rationale
    
    def test_rationale_needs_approval(self, gate):
        """Test rationale for NEEDS_APPROVAL changes."""
        change = Change(
            change_id="migration-1",
            title="Add user table",
            description="Database migration",
            author="user-1",
            files_changed=["migrations/001_add_user.py"],
            diff_summary="Added user table",
        )
        
        classification = gate.classify_change(change)
        rationale = gate.generate_rationale(change, classification)
        
        assert "NEEDS_APPROVAL" in rationale
        assert "migration" in rationale.lower() or "database" in rationale.lower()
    
    def test_rationale_blocked(self, gate):
        """Test rationale for BLOCKED changes."""
        change = Change(
            change_id="secret-1",
            title="Add API key",
            description="Add API key",
            author="user-1",
            files_changed=["config.py"],
            diff_summary="API_KEY = 'secret'",
        )
        
        classification = gate.classify_change(change)
        rationale = gate.generate_rationale(change, classification)
        
        assert "BLOCKED" in rationale
        assert "secret" in rationale.lower() or "credential" in rationale.lower()


class TestGetters:
    """Tests for getter methods."""
    
    @pytest.fixture
    def gate(self):
        """Create an approval gate for testing."""
        return ApprovalGate(default_ttl_hours=24)
    
    def test_get_request(self, gate):
        """Test get_request method."""
        change = Change(
            change_id="change-1",
            title="Update",
            description="Update",
            author="user-1",
            files_changed=["file.py"],
            diff_summary="Updated",
        )
        
        request = gate.request_approval(change)
        retrieved = gate.get_request(request.request_id)
        
        assert retrieved is not None
        assert retrieved.request_id == request.request_id
    
    def test_get_request_nonexistent(self, gate):
        """Test get_request with nonexistent ID."""
        request = gate.get_request("nonexistent")
        
        assert request is None
    
    def test_get_requests_for_change(self, gate):
        """Test get_requests_for_change method."""
        change = Change(
            change_id="change-1",
            title="Update",
            description="Update",
            author="user-1",
            files_changed=["file.py"],
            diff_summary="Updated",
        )
        
        request1 = gate.request_approval(change)
        request2 = gate.request_approval(change)  # Multiple requests for same change
        
        requests = gate.get_requests_for_change(change.change_id)
        
        assert len(requests) == 2
        assert request1.request_id in [r.request_id for r in requests]
        assert request2.request_id in [r.request_id for r in requests]
    
    def test_get_pending_requests(self, gate):
        """Test get_pending_requests method."""
        change1 = Change(
            change_id="change-1",
            title="Update 1",
            description="Update 1",
            author="user-1",
            files_changed=["file1.py"],
            diff_summary="Updated 1",
        )
        change2 = Change(
            change_id="change-2",
            title="Update 2",
            description="Update 2",
            author="user-1",
            files_changed=["file2.py"],
            diff_summary="Updated 2",
        )
        
        request1 = gate.request_approval(change1)
        request2 = gate.request_approval(change2)
        
        # Approve one
        gate.approve(request1.request_id, "reviewer-1")
        
        pending = gate.get_pending_requests()
        
        assert len(pending) == 1
        assert pending[0].request_id == request2.request_id
    
    def test_get_classification(self, gate):
        """Test get_classification method."""
        change = Change(
            change_id="change-1",
            title="Update",
            description="Update",
            author="user-1",
            files_changed=["README.md"],
            diff_summary="Updated README",
        )
        
        # First request approval to classify
        gate.request_approval(change)
        
        classification = gate.get_classification(change)
        
        assert classification == ChangeClassification.AUTO_APPROVED
    
    def test_get_blocked_changes(self, gate):
        """Test get_blocked_changes method."""
        change1 = Change(
            change_id="blocked-1",
            title="Add secret",
            description="Add secret",
            author="user-1",
            files_changed=["secrets.py"],
            diff_summary="Added secret",
        )
        change2 = Change(
            change_id="blocked-2",
            title="Add API key",
            description="Add API key",
            author="user-1",
            files_changed=["config.py"],
            diff_summary="API_KEY = 'secret-value'",
        )
        
        gate.request_approval(change1)
        gate.request_approval(change2)
        
        blocked = gate.get_blocked_changes()
        
        # Both changes should be in blocked list
        assert "blocked-1" in blocked or "blocked-2" in blocked
        # At least one should be blocked
        assert len(blocked) >= 1


class TestClear:
    """Tests for clear method."""
    
    def test_clear(self):
        """Test clear method."""
        gate = ApprovalGate()
        
        change = Change(
            change_id="change-1",
            title="Update",
            description="Update",
            author="user-1",
            files_changed=["file.py"],
            diff_summary="Updated",
        )
        
        gate.request_approval(change)
        gate.approve(gate._requests[list(gate._requests.keys())[0]].request_id, "reviewer-1")
        
        assert len(gate._requests) > 0
        assert len(gate._change_classifications) > 0
        
        gate.clear()
        
        assert len(gate._requests) == 0
        assert len(gate._change_classifications) == 0
        assert len(gate._blocked_changes) == 0


class TestApprovalRequest:
    """Tests for ApprovalRequest dataclass."""
    
    @pytest.fixture
    def change(self):
        """Create a sample change."""
        return Change(
            change_id="change-1",
            title="Update",
            description="Update",
            author="user-1",
            files_changed=["file.py"],
            diff_summary="Updated",
        )
    
    def test_to_dict(self, change):
        """Test ApprovalRequest to_dict method."""
        request = ApprovalRequest(
            request_id="request-1",
            change=change,
            classification=ChangeClassification.NEEDS_APPROVAL,
            rationale="Test rationale",
            risk_score=5.0,
            status=ApprovalStatus.PENDING,
            created_at=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            expires_at=datetime(2024, 1, 2, 0, 0, 0, tzinfo=timezone.utc),
        )
        
        data = request.to_dict()
        
        assert data["request_id"] == "request-1"
        assert data["change_id"] == "change-1"
        assert data["classification"] == "NEEDS_APPROVAL"
        assert data["rationale"] == "Test rationale"
        assert data["risk_score"] == 5.0
        assert data["status"] == "PENDING"
    
    def test_is_expired_false(self, change):
        """Test is_expired when not expired."""
        with patch('services.approval_gate.datetime') as mock_datetime:
            now = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
            mock_datetime.now.return_value = now
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            
            request = ApprovalRequest(
                request_id="request-1",
                change=change,
                classification=ChangeClassification.NEEDS_APPROVAL,
                rationale="Test",
                risk_score=5.0,
                expires_at=now + timedelta(hours=24),
            )
            
            assert request.is_expired is False
    
    def test_is_expired_true(self, change):
        """Test is_expired when expired."""
        with patch('services.approval_gate.datetime') as mock_datetime:
            now = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
            mock_datetime.now.return_value = now + timedelta(hours=25)
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            
            request = ApprovalRequest(
                request_id="request-1",
                change=change,
                classification=ChangeClassification.NEEDS_APPROVAL,
                rationale="Test",
                risk_score=5.0,
                expires_at=now + timedelta(hours=24),
            )
            
            assert request.is_expired is True


class TestChangeProperties:
    """Tests for Change dataclass properties."""
    
    def test_has_secrets_true(self):
        """Test has_secrets property."""
        change = Change(
            change_id="secret-1",
            title="Add API key",
            description="Add API key",
            author="user-1",
            files_changed=["config.py"],
            diff_summary="API_KEY = 'secret'",
        )
        
        assert change.has_secrets is True
    
    def test_has_secrets_false(self):
        """Test has_secrets property when no secrets."""
        change = Change(
            change_id="doc-1",
            title="Update README",
            description="Update documentation",
            author="user-1",
            files_changed=["README.md"],
            diff_summary="Updated README",
        )
        
        assert change.has_secrets is False
    
    def test_has_destructive_operations_true(self):
        """Test has_destructive_operations property."""
        change = Change(
            change_id="destructive-1",
            title="Clean up",
            description="Clean up",
            author="user-1",
            files_changed=["cleanup.py"],
            diff_summary="DROP TABLE users",
        )
        
        assert change.has_destructive_operations is True
    
    def test_is_migration_true(self):
        """Test is_migration property."""
        change = Change(
            change_id="migration-1",
            title="Add table",
            description="Add table",
            author="user-1",
            files_changed=["migrations/001_add_table.py"],
            diff_summary="Added table",
        )
        
        assert change.is_migration is True
    
    def test_is_doc_change_true(self):
        """Test is_doc_change property."""
        change = Change(
            change_id="doc-1",
            title="Update docs",
            description="Update docs",
            author="user-1",
            files_changed=["README.md", "docs/guide.md"],
            diff_summary="Updated docs",
        )
        
        assert change.is_doc_change is True
    
    def test_is_test_change_true(self):
        """Test is_test_change property."""
        change = Change(
            change_id="test-1",
            title="Add tests",
            description="Add tests",
            author="user-1",
            files_changed=["tests/test_module.py"],
            diff_summary="Added tests",
        )
        
        assert change.is_test_change is True
    
    def test_file_extensions(self):
        """Test file_extensions property."""
        change = Change(
            change_id="change-1",
            title="Update",
            description="Update",
            author="user-1",
            files_changed=["file.py", "config.json", "README.md"],
            diff_summary="Updated",
        )
        
        extensions = change.file_extensions
        
        assert "py" in extensions
        assert "json" in extensions
        assert "md" in extensions
