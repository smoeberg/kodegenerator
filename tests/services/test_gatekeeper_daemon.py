"""
Tests for Gatekeeper Daemon Service

Tests cover:
- Initialization
- GatekeeperResult validation
- PatchSynthesisResult
- verify_patch method
- Audit trail functionality
- Fingerprint computation
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from services.gatekeeper_daemon import (
    GatekeeperDaemon,
    GatekeeperDaemonError,
    GatekeeperResult,
    GatekeeperStatus,
    GatekeeperError,
    PatchSynthesisResult,
)
from domain.architecture_contract_v1 import (
    ArchitectureContractV1,
    LayerV1,
    DependencyRuleV1,
    QualityGateV1,
    ApprovalV1,
)


class TestGatekeeperDaemonInitialization:
    """Tests for GatekeeperDaemon initialization."""
    
    def test_initialization_with_valid_repo(self, tmp_path):
        """Test initialization with valid git repository."""
        # Create a git repository
        repo_path = tmp_path / "test_repo"
        repo_path.mkdir()
        
        # Initialize git repo
        import subprocess
        subprocess.run(["git", "init"], cwd=repo_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, capture_output=True)
        
        # Create initial commit
        (repo_path / "README.md").write_text("# Test Repo")
        subprocess.run(["git", "add", "."], cwd=repo_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_path, capture_output=True)
        
        # Initialize daemon
        daemon = GatekeeperDaemon(repository_root=repo_path)
        
        assert daemon.repository_root == repo_path
        assert daemon.target_branch == "main"
    
    def test_initialization_with_nonexistent_repo(self, tmp_path):
        """Test initialization with non-existent repository."""
        nonexistent_path = tmp_path / "nonexistent"
        
        with pytest.raises(GatekeeperDaemonError, match="Repository root not found"):
            GatekeeperDaemon(repository_root=nonexistent_path)
    
    def test_initialization_with_non_git_repo(self, tmp_path):
        """Test initialization with directory that's not a git repo."""
        non_git_path = tmp_path / "non_git"
        non_git_path.mkdir()
        
        with pytest.raises(GatekeeperDaemonError, match="Not a git repository"):
            GatekeeperDaemon(repository_root=non_git_path)
    
    def test_initialization_with_signing_key(self, tmp_path):
        """Test initialization with custom signing key."""
        repo_path = tmp_path / "test_repo"
        repo_path.mkdir()
        
        import subprocess
        subprocess.run(["git", "init"], cwd=repo_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, capture_output=True)
        (repo_path / "README.md").write_text("# Test Repo")
        subprocess.run(["git", "add", "."], cwd=repo_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_path, capture_output=True)
        
        # Create custom signing key
        import secrets
        signing_key = secrets.token_bytes(32)
        
        daemon = GatekeeperDaemon(repository_root=repo_path, signing_key=signing_key)
        
        assert daemon._signing_key == signing_key


class TestGatekeeperResult:
    """Tests for GatekeeperResult validation."""
    
    def test_valid_passed_result(self):
        """Test creation of valid PASSED result."""
        result = GatekeeperResult(
            result_id="test-result-1",
            branch_name="feature/test",
            target_branch="main",
            status=GatekeeperStatus.PASSED,
            evaluated_at=datetime.now(timezone.utc),
            has_valid_grant=True,
            grant_fingerprint="grant-123",
            ast_validation_passed=True,
            tests_passed=True,
            merge_success=True,
        )
        
        assert result.status == GatekeeperStatus.PASSED
        assert result.has_valid_grant is True
        assert result.ast_validation_passed is True
        assert result.tests_passed is True
        assert result.merge_success is True
    
    def test_invalid_passed_result_missing_grant(self):
        """Test that PASSED result requires valid grant."""
        with pytest.raises(ValueError, match="PASSED status requires valid authority grant"):
            GatekeeperResult(
                result_id="test-result-1",
                branch_name="feature/test",
                target_branch="main",
                status=GatekeeperStatus.PASSED,
                evaluated_at=datetime.now(timezone.utc),
                has_valid_grant=False,  # This should fail
                ast_validation_passed=True,
                tests_passed=True,
                merge_success=True,
            )
    
    def test_invalid_passed_result_ast_failed(self):
        """Test that PASSED result requires AST validation to pass."""
        with pytest.raises(ValueError, match="PASSED status requires AST validation to pass"):
            GatekeeperResult(
                result_id="test-result-1",
                branch_name="feature/test",
                target_branch="main",
                status=GatekeeperStatus.PASSED,
                evaluated_at=datetime.now(timezone.utc),
                has_valid_grant=True,
                ast_validation_passed=False,  # This should fail
                tests_passed=True,
                merge_success=True,
            )
    
    def test_invalid_passed_result_tests_failed(self):
        """Test that PASSED result requires tests to pass."""
        with pytest.raises(ValueError, match="PASSED status requires tests to pass"):
            GatekeeperResult(
                result_id="test-result-1",
                branch_name="feature/test",
                target_branch="main",
                status=GatekeeperStatus.PASSED,
                evaluated_at=datetime.now(timezone.utc),
                has_valid_grant=True,
                ast_validation_passed=True,
                tests_passed=False,  # This should fail
                merge_success=True,
            )
    
    def test_invalid_passed_result_merge_failed(self):
        """Test that PASSED result requires successful merge."""
        with pytest.raises(ValueError, match="PASSED status requires successful merge"):
            GatekeeperResult(
                result_id="test-result-1",
                branch_name="feature/test",
                target_branch="main",
                status=GatekeeperStatus.PASSED,
                evaluated_at=datetime.now(timezone.utc),
                has_valid_grant=True,
                ast_validation_passed=True,
                tests_passed=True,
                merge_success=False,  # This should fail
            )
    
    def test_valid_failed_result(self):
        """Test creation of valid FAILED result."""
        result = GatekeeperResult(
            result_id="test-result-1",
            branch_name="feature/test",
            target_branch="main",
            status=GatekeeperStatus.FAILED,
            evaluated_at=datetime.now(timezone.utc),
            has_valid_grant=False,
            ast_validation_passed=False,
            tests_passed=False,
            merge_success=False,
            ast_errors=("AST error 1",),
            test_errors=("Test error 1",),
        )
        
        assert result.status == GatekeeperStatus.FAILED


class TestPatchSynthesisResult:
    """Tests for PatchSynthesisResult."""
    
    def test_patch_with_valid_authority(self):
        """Test patch with valid authority grant."""
        from phase4.authority.grants import VerifiedAuthorityGrant
        
        # Create a mock grant (simplified for testing)
        grant = VerifiedAuthorityGrant(
            request_id="req-123",
            agent_identity="agent-1",
            action="merge",
            resource="repository:test",
            context_packet_id="ctx-123",
            policy_id="policy-1",
            policy_version="1.0",
            matched_rule_ids=("rule-1",),
            decision="allow",
        )
        
        # Create contract components
        layer = LayerV1(id="domain", path="src/domain")
        rule = DependencyRuleV1(id="DEP-001", source="domain", may_depend_on=("domain",), severity="block")
        gate = QualityGateV1(id="gate-1", type="architecture_tests", required=True)
        
        # Create contract as draft first to get fingerprint
        draft_contract = ArchitectureContractV1(
            schema_version="1.0",
            contract_id="contract-1",
            version="1.0.0",
            status="draft",
            project_name="test",
            style="hexagonal",
            language="python",
            layers=(layer,),
            dependency_rules=(rule,),
            quality_gates=(gate,),
        )
        
        # Get the contract fingerprint
        contract_fingerprint = draft_contract.fingerprint
        
        # Create the approved contract with proper approval
        contract = ArchitectureContractV1(
            schema_version="1.0",
            contract_id="contract-1",
            version="1.0.0",
            status="approved",
            project_name="test",
            style="hexagonal",
            language="python",
            layers=(layer,),
            dependency_rules=(rule,),
            quality_gates=(gate,),
            approval=ApprovalV1(
                status="approved",
                approver_id="approver-1",
                approved_at=datetime.now(timezone.utc),
                content_fingerprint=contract_fingerprint,
            ),
        )
        
        # Mock the verify method to return True and create patch
        with patch.object(VerifiedAuthorityGrant, 'verify', return_value=True):
            patch_result = PatchSynthesisResult(
                patch_id="patch-1",
                contract=contract,
                diff_content="diff --git a/test.py b/test.py\\n...",
                affected_files=("test.py",),
                ast_validation_result={"status": "PASS"},
                test_results={"status": "PASS"},
                authority_grant=grant,
            )
            
            assert patch_result.has_valid_authority is True
    
    def test_patch_without_authority(self):
        """Test patch without authority grant."""
        # Create contract components
        layer = LayerV1(id="domain", path="src/domain")
        rule = DependencyRuleV1(id="DEP-001", source="domain", may_depend_on=("domain",), severity="block")
        gate = QualityGateV1(id="gate-1", type="architecture_tests", required=True)
        
        # Create contract as draft first to get fingerprint
        draft_contract = ArchitectureContractV1(
            schema_version="1.0",
            contract_id="contract-1",
            version="1.0.0",
            status="draft",
            project_name="test",
            style="hexagonal",
            language="python",
            layers=(layer,),
            dependency_rules=(rule,),
            quality_gates=(gate,),
        )
        
        # Get the contract fingerprint
        contract_fingerprint = draft_contract.fingerprint
        
        # Create the approved contract with proper approval
        contract = ArchitectureContractV1(
            schema_version="1.0",
            contract_id="contract-1",
            version="1.0.0",
            status="approved",
            project_name="test",
            style="hexagonal",
            language="python",
            layers=(layer,),
            dependency_rules=(rule,),
            quality_gates=(gate,),
            approval=ApprovalV1(
                status="approved",
                approver_id="approver-1",
                approved_at=datetime.now(timezone.utc),
                content_fingerprint=contract_fingerprint,
            ),
        )
        
        patch_result = PatchSynthesisResult(
            patch_id="patch-1",
            contract=contract,
            diff_content="diff --git a/test.py b/test.py\\n...",
            affected_files=("test.py",),
            ast_validation_result={"status": "PASS"},
            test_results={"status": "PASS"},
            authority_grant=None,  # No grant
        )
        
        assert patch_result.has_valid_authority is False


class TestGatekeeperDaemonVerifyPatch:
    """Tests for verify_patch method."""
    
    def test_verify_patch_with_valid_data(self):
        """Test verification of valid patch."""
        daemon = GatekeeperDaemon(repository_root=".")
        
        # Create contract components
        layer = LayerV1(id="domain", path="src/domain")
        rule = DependencyRuleV1(id="DEP-001", source="domain", may_depend_on=("domain",), severity="block")
        gate = QualityGateV1(id="gate-1", type="architecture_tests", required=True)
        
        # Create contract as draft first to get fingerprint
        draft_contract = ArchitectureContractV1(
            schema_version="1.0",
            contract_id="contract-1",
            version="1.0.0",
            status="draft",
            project_name="test",
            style="hexagonal",
            language="python",
            layers=(layer,),
            dependency_rules=(rule,),
            quality_gates=(gate,),
        )
        
        # Get the contract fingerprint
        contract_fingerprint = draft_contract.fingerprint
        
        # Create the approved contract with proper approval
        contract = ArchitectureContractV1(
            schema_version="1.0",
            contract_id="contract-1",
            version="1.0.0",
            status="approved",
            project_name="test",
            style="hexagonal",
            language="python",
            layers=(layer,),
            dependency_rules=(rule,),
            quality_gates=(gate,),
            approval=ApprovalV1(
                status="approved",
                approver_id="approver-1",
                approved_at=datetime.now(timezone.utc),
                content_fingerprint=contract_fingerprint,
            ),
        )
        
        from phase4.authority.grants import VerifiedAuthorityGrant
        grant = VerifiedAuthorityGrant(
            request_id="req-123",
            agent_identity="agent-1",
            action="merge",
            resource="repository:test",
            context_packet_id="ctx-123",
            policy_id="policy-1",
            policy_version="1.0",
            matched_rule_ids=("rule-1",),
            decision="allow",
        )
        
        patch_result = PatchSynthesisResult(
            patch_id="patch-1",
            contract=contract,
            diff_content="diff --git a/test.py b/test.py\\n...",
            affected_files=("test.py",),
            ast_validation_result={"status": "PASS"},
            test_results={"status": "PASS"},
            authority_grant=grant,
        )
        
        # Mock the verify method
        with patch.object(VerifiedAuthorityGrant, 'verify', return_value=True):
            result = daemon.verify_patch(patch_result)
        
        assert result is True
    
    def test_verify_patch_without_grant(self):
        """Test verification fails without grant."""
        daemon = GatekeeperDaemon(repository_root=".")
        
        # Create contract components
        layer = LayerV1(id="domain", path="src/domain")
        rule = DependencyRuleV1(id="DEP-001", source="domain", may_depend_on=("domain",), severity="block")
        gate = QualityGateV1(id="gate-1", type="architecture_tests", required=True)
        
        # Create contract as draft first to get fingerprint
        draft_contract = ArchitectureContractV1(
            schema_version="1.0",
            contract_id="contract-1",
            version="1.0.0",
            status="draft",
            project_name="test",
            style="hexagonal",
            language="python",
            layers=(layer,),
            dependency_rules=(rule,),
            quality_gates=(gate,),
        )
        
        # Get the contract fingerprint
        contract_fingerprint = draft_contract.fingerprint
        
        # Create the approved contract with proper approval
        contract = ArchitectureContractV1(
            schema_version="1.0",
            contract_id="contract-1",
            version="1.0.0",
            status="approved",
            project_name="test",
            style="hexagonal",
            language="python",
            layers=(layer,),
            dependency_rules=(rule,),
            quality_gates=(gate,),
            approval=ApprovalV1(
                status="approved",
                approver_id="approver-1",
                approved_at=datetime.now(timezone.utc),
                content_fingerprint=contract_fingerprint,
            ),
        )
        
        patch_result = PatchSynthesisResult(
            patch_id="patch-1",
            contract=contract,
            diff_content="diff --git a/test.py b/test.py\\n...",
            affected_files=("test.py",),
            ast_validation_result={"status": "PASS"},
            test_results={"status": "PASS"},
            authority_grant=None,  # No grant
        )
        
        result = daemon.verify_patch(patch_result)
        assert result is False
    
    def test_verify_patch_with_unapproved_contract(self):
        """Test verification fails with unapproved contract."""
        daemon = GatekeeperDaemon(repository_root=".")
        
        # Create contract components
        layer = LayerV1(id="domain", path="src/domain")
        rule = DependencyRuleV1(id="DEP-001", source="domain", may_depend_on=("domain",), severity="block")
        gate = QualityGateV1(id="gate-1", type="architecture_tests", required=True)
        
        contract = ArchitectureContractV1(
            schema_version="1.0",
            contract_id="contract-1",
            version="1.0.0",
            status="draft",  # Not approved
            project_name="test",
            style="hexagonal",
            language="python",
            layers=(layer,),
            dependency_rules=(rule,),
            quality_gates=(gate,),
        )
        
        from phase4.authority.grants import VerifiedAuthorityGrant
        grant = VerifiedAuthorityGrant(
            request_id="req-123",
            agent_identity="agent-1",
            action="merge",
            resource="repository:test",
            context_packet_id="ctx-123",
            policy_id="policy-1",
            policy_version="1.0",
            matched_rule_ids=("rule-1",),
            decision="allow",
        )
        
        patch_result = PatchSynthesisResult(
            patch_id="patch-1",
            contract=contract,
            diff_content="diff --git a/test.py b/test.py\\n...",
            affected_files=("test.py",),
            ast_validation_result={"status": "PASS"},
            test_results={"status": "PASS"},
            authority_grant=grant,
        )
        
        result = daemon.verify_patch(patch_result)
        assert result is False
    
    def test_verify_patch_with_failing_ast(self):
        """Test verification fails with failing AST validation."""
        daemon = GatekeeperDaemon(repository_root=".")
        
        # Create contract components
        layer = LayerV1(id="domain", path="src/domain")
        rule = DependencyRuleV1(id="DEP-001", source="domain", may_depend_on=("domain",), severity="block")
        gate = QualityGateV1(id="gate-1", type="architecture_tests", required=True)
        
        # Create contract as draft first to get fingerprint
        draft_contract = ArchitectureContractV1(
            schema_version="1.0",
            contract_id="contract-1",
            version="1.0.0",
            status="draft",
            project_name="test",
            style="hexagonal",
            language="python",
            layers=(layer,),
            dependency_rules=(rule,),
            quality_gates=(gate,),
        )
        
        # Get the contract fingerprint
        contract_fingerprint = draft_contract.fingerprint
        
        # Create the approved contract with proper approval
        contract = ArchitectureContractV1(
            schema_version="1.0",
            contract_id="contract-1",
            version="1.0.0",
            status="approved",
            project_name="test",
            style="hexagonal",
            language="python",
            layers=(layer,),
            dependency_rules=(rule,),
            quality_gates=(gate,),
            approval=ApprovalV1(
                status="approved",
                approver_id="approver-1",
                approved_at=datetime.now(timezone.utc),
                content_fingerprint=contract_fingerprint,
            ),
        )
        
        from phase4.authority.grants import VerifiedAuthorityGrant
        grant = VerifiedAuthorityGrant(
            request_id="req-123",
            agent_identity="agent-1",
            action="merge",
            resource="repository:test",
            context_packet_id="ctx-123",
            policy_id="policy-1",
            policy_version="1.0",
            matched_rule_ids=("rule-1",),
            decision="allow",
        )
        
        patch_result = PatchSynthesisResult(
            patch_id="patch-1",
            contract=contract,
            diff_content="diff --git a/test.py b/test.py\\n...",
            affected_files=("test.py",),
            ast_validation_result={"status": "FAIL", "errors": ["Forbidden import"]},  # Failing AST
            test_results={"status": "PASS"},
            authority_grant=grant,
        )
        
        result = daemon.verify_patch(patch_result)
        assert result is False
    
    def test_verify_patch_with_failing_tests(self):
        """Test verification fails with failing tests."""
        daemon = GatekeeperDaemon(repository_root=".")
        
        # Create contract components
        layer = LayerV1(id="domain", path="src/domain")
        rule = DependencyRuleV1(id="DEP-001", source="domain", may_depend_on=("domain",), severity="block")
        gate = QualityGateV1(id="gate-1", type="architecture_tests", required=True)
        
        # Create contract as draft first to get fingerprint
        draft_contract = ArchitectureContractV1(
            schema_version="1.0",
            contract_id="contract-1",
            version="1.0.0",
            status="draft",
            project_name="test",
            style="hexagonal",
            language="python",
            layers=(layer,),
            dependency_rules=(rule,),
            quality_gates=(gate,),
        )
        
        # Get the contract fingerprint
        contract_fingerprint = draft_contract.fingerprint
        
        # Create the approved contract with proper approval
        contract = ArchitectureContractV1(
            schema_version="1.0",
            contract_id="contract-1",
            version="1.0.0",
            status="approved",
            project_name="test",
            style="hexagonal",
            language="python",
            layers=(layer,),
            dependency_rules=(rule,),
            quality_gates=(gate,),
            approval=ApprovalV1(
                status="approved",
                approver_id="approver-1",
                approved_at=datetime.now(timezone.utc),
                content_fingerprint=contract_fingerprint,
            ),
        )
        
        from phase4.authority.grants import VerifiedAuthorityGrant
        grant = VerifiedAuthorityGrant(
            request_id="req-123",
            agent_identity="agent-1",
            action="merge",
            resource="repository:test",
            context_packet_id="ctx-123",
            policy_id="policy-1",
            policy_version="1.0",
            matched_rule_ids=("rule-1",),
            decision="allow",
        )
        
        patch_result = PatchSynthesisResult(
            patch_id="patch-1",
            contract=contract,
            diff_content="diff --git a/test.py b/test.py\\n...",
            affected_files=("test.py",),
            ast_validation_result={"status": "PASS"},
            test_results={"status": "FAIL", "failed_tests": ["test_1"]},  # Failing tests
            authority_grant=grant,
        )
        
        result = daemon.verify_patch(patch_result)
        assert result is False
    
    def test_verify_patch_too_large(self):
        """Test verification fails with patch that's too large."""
        daemon = GatekeeperDaemon(repository_root=".", max_patch_size_bytes=100)
        
        # Create contract components
        layer = LayerV1(id="domain", path="src/domain")
        rule = DependencyRuleV1(id="DEP-001", source="domain", may_depend_on=("domain",), severity="block")
        gate = QualityGateV1(id="gate-1", type="architecture_tests", required=True)
        
        # Create contract as draft first to get fingerprint
        draft_contract = ArchitectureContractV1(
            schema_version="1.0",
            contract_id="contract-1",
            version="1.0.0",
            status="draft",
            project_name="test",
            style="hexagonal",
            language="python",
            layers=(layer,),
            dependency_rules=(rule,),
            quality_gates=(gate,),
        )
        
        # Get the contract fingerprint
        contract_fingerprint = draft_contract.fingerprint
        
        # Create the approved contract with proper approval
        contract = ArchitectureContractV1(
            schema_version="1.0",
            contract_id="contract-1",
            version="1.0.0",
            status="approved",
            project_name="test",
            style="hexagonal",
            language="python",
            layers=(layer,),
            dependency_rules=(rule,),
            quality_gates=(gate,),
            approval=ApprovalV1(
                status="approved",
                approver_id="approver-1",
                approved_at=datetime.now(timezone.utc),
                content_fingerprint=contract_fingerprint,
            ),
        )
        
        from phase4.authority.grants import VerifiedAuthorityGrant
        grant = VerifiedAuthorityGrant(
            request_id="req-123",
            agent_identity="agent-1",
            action="merge",
            resource="repository:test",
            context_packet_id="ctx-123",
            policy_id="policy-1",
            policy_version="1.0",
            matched_rule_ids=("rule-1",),
            decision="allow",
        )
        
        # Create a patch that's too large (200 bytes > 100 byte limit)
        large_diff = "x" * 200
        
        patch_result = PatchSynthesisResult(
            patch_id="patch-1",
            contract=contract,
            diff_content=large_diff,
            affected_files=("test.py",),
            ast_validation_result={"status": "PASS"},
            test_results={"status": "PASS"},
            authority_grant=grant,
        )
        
        result = daemon.verify_patch(patch_result)
        assert result is False


class TestGatekeeperDaemonAuditTrail:
    """Tests for audit trail functionality."""
    
    def test_audit_entry_creation(self):
        """Test creation of audit entry."""
        daemon = GatekeeperDaemon(repository_root=".")
        
        entry = daemon._create_audit_entry(
            action="test_action",
            branch_name="feature/test",
            status=GatekeeperStatus.PASSED,
            details={"key": "value"},
        )
        
        assert "timestamp" in entry
        assert entry["action"] == "test_action"
        assert entry["branch"] == "feature/test"
        assert entry["status"] == "passed"
        assert "fingerprint" in entry
        assert "signature" in entry
        assert "details" in entry
    
    def test_audit_entry_fingerprint_consistency(self):
        """Test that fingerprint method produces consistent results for same data."""
        daemon = GatekeeperDaemon(repository_root=".")
        
        details = {"key": "value", "number": 42}
        data = {
            "timestamp": "2024-01-01T00:00:00+00:00",
            "action": "test_action",
            "branch": "feature/test",
            "status": "passed",
            "details": details,
        }
        
        fingerprint1 = daemon._compute_fingerprint(data)
        fingerprint2 = daemon._compute_fingerprint(data)
        
        # Fingerprints should be the same for same data
        assert fingerprint1 == fingerprint2
    
    def test_audit_entry_signature_verification(self):
        """Test that audit entry signature can be verified."""
        daemon = GatekeeperDaemon(repository_root=".")
        
        # Create entry with mock timestamp for consistent testing
        from unittest.mock import patch
        from datetime import datetime, timezone
        fixed_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        
        with patch('services.gatekeeper_daemon.datetime') as mock_datetime:
            mock_datetime.now.return_value = fixed_time
            entry = daemon._create_audit_entry(
                action="test_action",
                branch_name="feature/test",
                status=GatekeeperStatus.PASSED,
                details={"key": "value"},
            )
        
        # Verify signature
        canonical = json.dumps(
            {
                "timestamp": entry["timestamp"],
                "action": entry["action"],
                "branch": entry["branch"],
                "status": entry["status"],
                "details": entry["details"],
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        
        import hmac
        import hashlib
        expected_signature = hmac.new(
            daemon._signing_key, 
            canonical.encode("utf-8"), 
            hashlib.sha256
        ).hexdigest()
        
        assert entry["signature"] == expected_signature


class TestGatekeeperDaemonFingerprint:
    """Tests for fingerprint computation."""
    
    def test_fingerprint_computation(self):
        """Test fingerprint computation."""
        daemon = GatekeeperDaemon(repository_root=".")
        
        data = {"key1": "value1", "key2": "value2"}
        fingerprint1 = daemon._compute_fingerprint(data)
        fingerprint2 = daemon._compute_fingerprint(data)
        
        # Same data should produce same fingerprint
        assert fingerprint1 == fingerprint2
        
        # Different data should produce different fingerprint
        data2 = {"key1": "value1", "key2": "different"}
        fingerprint3 = daemon._compute_fingerprint(data2)
        assert fingerprint1 != fingerprint3
    
    def test_fingerprint_with_nested_data(self):
        """Test fingerprint with nested data structures."""
        daemon = GatekeeperDaemon(repository_root=".")
        
        data = {
            "outer": {
                "inner": {
                    "deep": "value"
                }
            },
            "list": [1, 2, 3],
        }
        
        fingerprint = daemon._compute_fingerprint(data)
        
        # Should be a valid SHA-256 hex string
        assert len(fingerprint) == 64
        assert all(c in "0123456789abcdef" for c in fingerprint)


class TestGatekeeperDaemonCommandExecution:
    """Tests for command execution functionality."""
    
    def test_run_command_success(self):
        """Test successful command execution."""
        daemon = GatekeeperDaemon(repository_root=".")
        
        success, stdout, stderr = daemon._run_command(
            ["echo", "hello"],
            timeout=10,
        )
        
        assert success is True
        assert "hello" in stdout
        assert stderr == ""
    
    def test_run_command_failure(self):
        """Test failed command execution."""
        daemon = GatekeeperDaemon(repository_root=".")
        
        success, stdout, stderr = daemon._run_command(
            ["false"],
            timeout=10,
        )
        
        assert success is False
    
    def test_run_command_timeout(self):
        """Test command timeout."""
        daemon = GatekeeperDaemon(repository_root=".", sandbox_timeout_seconds=1)
        
        import time
        success, stdout, stderr = daemon._run_command(
            ["sleep", "10"],  # This should timeout
            timeout=1,
        )
        
        assert success is False
        assert "timed out" in stderr.lower()


class TestGatekeeperDaemonBranchOperations:
    """Tests for branch operations."""
    
    @pytest.fixture
    def git_repo(self, tmp_path):
        """Create a temporary git repository for testing."""
        repo_path = tmp_path / "test_repo"
        repo_path.mkdir()
        
        import subprocess
        subprocess.run(["git", "init", "-b", "main"], cwd=repo_path, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_path, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, capture_output=True, check=True)
        
        # Create initial commit
        (repo_path / "README.md").write_text("# Test Repo")
        subprocess.run(["git", "add", "."], cwd=repo_path, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_path, capture_output=True, check=True)
        
        return repo_path
    
    def test_branch_exists(self, git_repo):
        """Test branch existence check."""
        daemon = GatekeeperDaemon(repository_root=git_repo)
        assert daemon._branch_exists("main") is True
        assert daemon._branch_exists("nonexistent") is False
    
    def test_get_branch_head(self, git_repo):
        """Test getting branch HEAD commit."""
        daemon = GatekeeperDaemon(repository_root=git_repo)
        head = daemon._get_branch_head("main")
        assert head is not None
        assert len(head) == 40  # SHA-1 hash length
    
    def test_checkout_branch(self, git_repo):
        """Test branch checkout."""
        import subprocess
        # Create a new branch
        subprocess.run(["git", "checkout", "-b", "test-branch"], cwd=git_repo, capture_output=True, check=True)
        subprocess.run(["git", "checkout", "main"], cwd=git_repo, capture_output=True, check=True)
        
        daemon = GatekeeperDaemon(repository_root=git_repo)
        
        # Checkout the branch
        result = daemon._checkout_branch("test-branch")
        assert result is True
        
        # Verify we're on the branch
        current_branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=git_repo,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert current_branch == "test-branch"
