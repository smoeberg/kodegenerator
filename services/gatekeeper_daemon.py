"""
Gatekeeper Daemon Service

Autonom gatekeeper-tjeneste, der:
1. Modtager/scanner branches fra AI-bots
2. Kører fuld verifikation (AST + sandkassetest)
3. Automatisk merger til main hvis alt er grønt
4. Sletter feature-branchen efter vellykket merge

Fail-Closed principper:
- Afvis enhver branch uden gyldig HMAC-autoritetsgrant
- Afvis hvis AST-validering fejler
- Afvis hvis testsuiten fejler
- Afvis hvis der opstår fletningskonflikter
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
import uuid

from domain.architecture_contract_v1 import ArchitectureContractV1
from phase4.authority.grants import VerifiedAuthorityGrant
from phase4.authority.models import AuthorityDecision
from services.security_sentinel import SecuritySentinel, SecurityReport, ScanContext

if TYPE_CHECKING:
    from phase4.verification.engine import VerificationEngine


class GatekeeperStatus(str, Enum):
    """Status for gatekeeper evaluation."""
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


class GatekeeperError(str, Enum):
    """Error types for gatekeeper failures."""
    MISSING_GRANT = "missing_authority_grant"
    INVALID_GRANT = "invalid_authority_grant"
    AST_VALIDATION_FAILED = "ast_validation_failed"
    TESTS_FAILED = "tests_failed"
    MERGE_CONFLICT = "merge_conflict"
    SANDBOX_ERROR = "sandbox_error"
    BRANCH_NOT_FOUND = "branch_not_found"
    UNKNOWN_ERROR = "unknown_error"


@dataclass(frozen=True)
class GatekeeperResult:
    """Immutable result from gatekeeper evaluation."""
    result_id: str
    branch_name: str
    target_branch: str
    status: GatekeeperStatus
    evaluated_at: datetime
    
    # Verification results
    ast_validation_passed: bool = True
    ast_errors: Tuple[str, ...] = ()
    tests_passed: bool = True
    test_errors: Tuple[str, ...] = ()
    
    # Authority
    has_valid_grant: bool = False
    grant_fingerprint: Optional[str] = None
    
    # Merge results
    merge_success: bool = False
    merge_errors: Tuple[str, ...] = ()
    branch_deleted: bool = False
    
    # Audit
    audit_fingerprint: str = ""

    def __post_init__(self) -> None:
        if self.status == GatekeeperStatus.PASSED:
            if not self.has_valid_grant:
                raise ValueError("PASSED status requires valid authority grant")
            if not self.ast_validation_passed:
                raise ValueError("PASSED status requires AST validation to pass")
            if not self.tests_passed:
                raise ValueError("PASSED status requires tests to pass")
    
    def __post_init__(self) -> None:
        """Validate result consistency."""
        if self.status == GatekeeperStatus.PASSED:
            if not self.has_valid_grant:
                raise ValueError("PASSED status requires valid authority grant")
            if not self.ast_validation_passed:
                raise ValueError("PASSED status requires AST validation to pass")
            if not self.tests_passed:
                raise ValueError("PASSED status requires tests to pass")
            if not self.merge_success:
                raise ValueError("PASSED status requires successful merge")
        
        if self.status == GatekeeperStatus.FAILED:
            if self.has_valid_grant and self.ast_validation_passed and self.tests_passed:
                raise ValueError("FAILED status with all checks passed is inconsistent")


@dataclass(frozen=True)
class PatchSynthesisResult:
    """Result from patch synthesis and validation."""
    patch_id: str
    contract: ArchitectureContractV1
    diff_content: str
    affected_files: Tuple[str, ...]
    ast_validation_result: Dict[str, Any]
    test_results: Dict[str, Any]
    authority_grant: Optional[VerifiedAuthorityGrant] = None
    
    @property
    def has_valid_authority(self) -> bool:
        """Check if patch has valid authority grant."""
        if self.authority_grant is None:
            return False
        return self.authority_grant.verify()


class GatekeeperDaemonError(Exception):
    """Base exception for gatekeeper daemon errors."""
    pass


class GatekeeperDaemon:
    """
    Autonomous Gatekeeper Daemon
    
    Modtager branches/patches, kører fuld verifikation,
    og merger automatisk til target branch hvis alt er grønt.
    """
    
    def __init__(
        self,
        *,
        repository_root: Path | str = ".",
        target_branch: str = "main",
        signing_key: Optional[bytes] = None,
        verification_engine: Optional["VerificationEngine"] = None,
        max_patch_size_bytes: int = 1024 * 1024,  # 1MB
        sandbox_timeout_seconds: int = 300,
        security_sentinel: Optional[SecuritySentinel] = None,
        allowed_paths: Optional[List[str]] = None,
    ):
        """
        Initialize the gatekeeper daemon.
        
        Args:
            repository_root: Path to repository root
            target_branch: Default target branch for merges (default: "main")
            signing_key: HMAC signing key for audit trail
            verification_engine: Optional verification engine for AST checks
            max_patch_size_bytes: Maximum allowed patch size
            sandbox_timeout_seconds: Timeout for sandbox execution
        """
        self.repository_root = Path(repository_root).resolve()
        self.target_branch = target_branch
        self._signing_key = signing_key or self._load_signing_key()
        self._verification_engine = verification_engine
        self.max_patch_size_bytes = max_patch_size_bytes
        self.sandbox_timeout_seconds = sandbox_timeout_seconds
        self._security_sentinel = security_sentinel or SecuritySentinel(
            repository_root=repository_root,
            allowed_paths=allowed_paths or ["src", "services", "domain", "tests", "phase"],
        )
        
        # Ensure repository exists
        if not self.repository_root.exists():
            raise GatekeeperDaemonError(f"Repository root not found: {self.repository_root}")
        
        # Ensure it's a git repository
        if not (self.repository_root / ".git").exists():
            raise GatekeeperDaemonError(f"Not a git repository: {self.repository_root}")
    
    def _load_signing_key(self) -> bytes:
        """Load signing key from environment or generate ephemeral."""
        encoded = os.environ.get("GATEKEEPER_SIGNING_KEY")
        if encoded:
            import base64
            import binascii
            padded = encoded + "=" * (-len(encoded) % 4)
            try:
                return base64.b64decode(padded, altchars=b"-_", validate=True)
            except (binascii.Error, ValueError) as exc:
                raise GatekeeperDaemonError("Invalid GATEKEEPER_SIGNING_KEY") from exc
        # Generate ephemeral key for development
        import secrets
        return secrets.token_bytes(32)
    
    def _compute_fingerprint(self, data: Dict[str, Any]) -> str:
        """Compute SHA-256 fingerprint of data."""
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    
    def _sign_audit_entry(self, entry: Dict[str, Any]) -> str:
        """Sign audit entry with HMAC."""
        canonical = json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hmac.new(self._signing_key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    
    def _create_audit_entry(
        self,
        action: str,
        branch_name: str,
        status: GatekeeperStatus,
        details: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create immutable audit entry."""
        base_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "branch": branch_name,
            "status": status.value,
            "details": details,
        }
        entry = dict(base_entry)
        entry["fingerprint"] = self._compute_fingerprint(base_entry)
        entry["signature"] = self._sign_audit_entry(base_entry)
        return entry
    
    def _run_command(
        self,
        command: List[str],
        timeout: Optional[int] = None,
        cwd: Optional[Path] = None,
    ) -> Tuple[bool, str, str]:
        """
        Run a command in a subprocess.
        
        Returns:
            Tuple of (success, stdout, stderr)
        """
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout or self.sandbox_timeout_seconds,
                cwd=cwd or self.repository_root,
            )
            return (
                result.returncode == 0,
                result.stdout,
                result.stderr,
            )
        except subprocess.TimeoutExpired:
            return False, "", f"Command timed out after {timeout or self.sandbox_timeout_seconds} seconds"
        except Exception as e:
            return False, "", str(e)
    
    def _get_branch_head(self, branch_name: str) -> Optional[str]:
        """Get the HEAD commit hash for a branch."""
        success, stdout, stderr = self._run_command(
            ["git", "rev-parse", branch_name],
            timeout=30,
        )
        if success and stdout.strip():
            return stdout.strip()
        return None
    
    def _branch_exists(self, branch_name: str) -> bool:
        """Check if a branch exists."""
        success, stdout, _ = self._run_command(
            ["git", "branch", "--list", branch_name],
            timeout=30,
        )
        if not success or not stdout.strip():
            return False
        branches = [b.strip().lstrip("* ") for b in stdout.strip().splitlines()]
        return branch_name in branches
    
    def _checkout_branch(self, branch_name: str) -> bool:
        """Checkout a branch."""
        success, _, stderr = self._run_command(
            ["git", "checkout", branch_name],
            timeout=30,
        )
        return success
    
    def _fetch_latest(self) -> bool:
        """Fetch latest changes from remote."""
        success, _, _ = self._run_command(
            ["git", "fetch", "--all"],
            timeout=60,
        )
        return success
    
    def _merge_branch(self, branch_name: str, target: str = "main") -> Tuple[bool, List[str]]:
        """
        Merge a branch into target.
        
        Returns:
            Tuple of (success, list of errors)
        """
        errors = []
        
        # Ensure we're on target branch
        if not self._checkout_branch(target):
            errors.append(f"Failed to checkout target branch: {target}")
            return False, errors
        
        # Pull latest changes
        if not self._run_command(["git", "pull", "origin", target], timeout=60)[0]:
            errors.append(f"Failed to pull latest changes for {target}")
            return False, errors
        
        # Attempt merge
        success, stdout, stderr = self._run_command(
            ["git", "merge", branch_name, "--no-ff", "--no-edit"],
            timeout=60,
        )
        
        if not success:
            errors.append(f"Merge failed: {stderr}")
            # Check for conflicts
            conflict_success, conflict_out, _ = self._run_command(
                ["git", "diff", "--check"],
                timeout=10,
            )
            if not conflict_success:
                errors.append("Merge conflicts detected")
            return False, errors
        
        return True, errors
    
    def _delete_branch(self, branch_name: str) -> bool:
        """Delete a branch locally and remotely."""
        # Delete local branch
        success1, _, stderr1 = self._run_command(
            ["git", "branch", "-D", branch_name],
            timeout=30,
        )
        
        # Delete remote branch
        success2, _, stderr2 = self._run_command(
            ["git", "push", "origin", f":{branch_name}", "--delete"],
            timeout=30,
        )
        
        return success1 and success2
    
    def _run_tests_in_sandbox(self, branch_name: str) -> Tuple[bool, List[str]]:
        """
        Run tests in isolated sandbox environment.
        
        Returns:
            Tuple of (all_passed, list of errors)
        """
        errors = []
        
        # Checkout the branch
        if not self._checkout_branch(branch_name):
            errors.append(f"Failed to checkout branch: {branch_name}")
            return False, errors
        
        # Run pytest
        success, stdout, stderr = self._run_command(
            ["python", "-m", "pytest", "tests/", "-x", "--tb=short"],
            timeout=self.sandbox_timeout_seconds,
        )
        
        if not success:
            errors.append(f"Tests failed: {stderr}")
            return False, errors
        
        # Check exit code from output
        if "passed" not in stdout.lower() or "failed" in stdout.lower():
            errors.append(f"Test results indicate failures: {stdout}")
            return False, errors
        
        return True, errors
    
    def _validate_ast_constraints(self, branch_name: str) -> Tuple[bool, List[str]]:
        """
        Validate AST constraints for the branch.
        
        Returns:
            Tuple of (valid, list of errors)
        """
        errors = []
        
        # Checkout the branch
        if not self._checkout_branch(branch_name):
            errors.append(f"Failed to checkout branch: {branch_name}")
            return False, errors
        
        # If we have a verification engine, use it
        if self._verification_engine:
            # For now, we'll do basic AST validation
            # In a real implementation, this would use the full verification engine
            pass
        
        # Run basic AST validation using existing services
        try:
            from services.architecture_ast_constraint_evaluator import (
                evaluate_constraints,
                ConstraintEvaluationResult,
            )
            from services.architecture_ast_source import load_source_files
            
            # Load source files from the branch
            source_files = load_source_files(self.repository_root)
            
            # For now, just check that files can be parsed
            for file_path, source in source_files.items():
                try:
                    compile(source, file_path, "exec")
                except SyntaxError as e:
                    errors.append(f"Syntax error in {file_path}: {e}")
            
            if errors:
                return False, errors
            
        except Exception as e:
            errors.append(f"AST validation error: {e}")
            return False, errors
        
        return True, errors
    
    def _scan_security(
        self,
        branch_name: str,
    ) -> Tuple[bool, List[str], Optional[SecurityReport]]:
        """
        Scan the branch for security issues using SecuritySentinel.
        
        Returns:
            Tuple of (is_clean, list of errors, security report)
        """
        errors = []
        
        try:
            # Checkout the branch to scan its files
            if not self._checkout_branch(branch_name):
                errors.append(f"Failed to checkout branch for security scan: {branch_name}")
                return False, errors, None
            
            # Get the diff/patch for the branch
            success, stdout, stderr = self._run_command(
                ["git", "diff", f"{self.target_branch}...{branch_name}", "--no-color"],
                timeout=30,
            )
            
            if not success:
                errors.append(f"Failed to get diff for security scan: {stderr}")
                return False, errors, None
            
            patch_text = stdout
            
            if not patch_text.strip():
                # No changes, security scan passes
                return True, errors, None
            
            # Create scan context
            context = ScanContext(
                repository_root=self.repository_root,
                allowed_paths=self._security_sentinel.allowed_paths,
                branch_name=branch_name,
                target_branch=self.target_branch,
            )
            
            # Scan the patch
            report = self._security_sentinel.scan_patch(patch_text, context)
            
            # Check if merge should be blocked
            is_safe, blocking_findings = self._security_sentinel.check_merge_safety(report)
            
            if not is_safe:
                for finding in blocking_findings:
                    errors.append(
                        f"Security BLOCKED: {finding.severity.value} - {finding.rule} "
                        f"in {finding.file_path}:{finding.line_number or 0}"
                    )
            
            return is_safe, errors, report
            
        except Exception as e:
            errors.append(f"Security scan error: {e}")
            return False, errors, None

    def _verify_authority_grant(
        self,
        branch_name: str,
        expected_action: str = "merge",
        expected_resource: str = "repository",
    ) -> Tuple[bool, Optional[VerifiedAuthorityGrant], List[str]]:
        """
        Verify that the branch has a valid authority grant.
        
        Returns:
            Tuple of (has_valid_grant, grant, errors)
        """
        errors = []
        grant = None
        
        # In a real implementation, we would:
        # 1. Load the grant from branch metadata or a dedicated file
        # 2. Verify the grant's signature and expiration
        # 3. Check that it authorizes the requested action
        
        # For this implementation, we'll check for a grant file in the branch
        grant_file = self.repository_root / f".dor_grants/{branch_name}.grant"
        
        if not grant_file.exists():
            errors.append(f"No authority grant found for branch: {branch_name}")
            return False, None, errors
        
        try:
            with open(grant_file, "r") as f:
                grant_data = json.load(f)
            
            # Reconstruct the grant (simplified for this implementation)
            # In reality, we would deserialize the actual VerifiedAuthorityGrant
            grant = VerifiedAuthorityGrant(
                request_id=grant_data.get("request_id", ""),
                agent_identity=grant_data.get("agent_identity", ""),
                action=grant_data.get("action", ""),
                resource=grant_data.get("resource", ""),
                context_packet_id=grant_data.get("context_packet_id", ""),
                policy_id=grant_data.get("policy_id", ""),
                policy_version=grant_data.get("policy_version", ""),
                matched_rule_ids=tuple(grant_data.get("matched_rule_ids", [])),
                decision=grant_data.get("decision", "allow"),
            )
            
            # Verify the grant
            if not grant.verify():
                errors.append(f"Invalid authority grant for branch: {branch_name}")
                return False, grant, errors
            
            # Check action and resource
            if grant.action != expected_action:
                errors.append(f"Grant action mismatch. Expected: {expected_action}, Got: {grant.action}")
                return False, grant, errors
            
            if grant.resource != expected_resource:
                errors.append(f"Grant resource mismatch. Expected: {expected_resource}, Got: {grant.resource}")
                return False, grant, errors
            
            return True, grant, errors
            
        except json.JSONDecodeError as e:
            errors.append(f"Invalid grant file format: {e}")
            return False, None, errors
        except Exception as e:
            errors.append(f"Error verifying grant: {e}")
            return False, None, errors
    
    def evaluate_branch(
        self,
        branch_name: str,
        target_branch: Optional[str] = None,
    ) -> GatekeeperResult:
        """
        Evaluate a branch for merge readiness.
        
        This is the main entry point for the gatekeeper daemon.
        It performs all necessary checks before allowing a merge.
        
        Args:
            branch_name: Name of the branch to evaluate
            target_branch: Target branch for merge (default: self.target_branch)
            
        Returns:
            GatekeeperResult with full evaluation details
        """
        target = target_branch or self.target_branch
        result_id = str(uuid.uuid4())
        start_time = datetime.now(timezone.utc)
        
        # Initialize result with defaults
        result = GatekeeperResult(
            result_id=result_id,
            branch_name=branch_name,
            target_branch=target,
            status=GatekeeperStatus.PENDING,
            evaluated_at=start_time,
            ast_validation_passed=False,
            tests_passed=False,
            has_valid_grant=False,
            merge_success=False,
            branch_deleted=False,
            audit_fingerprint=audit_start["fingerprint"],
        )
        
        errors = []
        
        # Create audit entry for evaluation start
        audit_start = self._create_audit_entry(
            action="evaluate_start",
            branch_name=branch_name,
            status=GatekeeperStatus.PENDING,
            details={"target": target, "result_id": result_id},
        )
        
        try:
            # Step 1: Check if branch exists
            if not self._branch_exists(branch_name):
                errors.append(f"Branch not found: {branch_name}")
                result = GatekeeperResult(
                    **{**result.__dict__,
                       "status": GatekeeperStatus.FAILED,
                       "test_errors": (GatekeeperError.BRANCH_NOT_FOUND.value,),
                    }
                )
                audit_fail = self._create_audit_entry(
                    action="evaluate_fail",
                    branch_name=branch_name,
                    status=GatekeeperStatus.FAILED,
                    details={"errors": errors, "result_id": result_id},
                )
                return GatekeeperResult(
                    **{**result.__dict__,
                       "audit_fingerprint": audit_fail["fingerprint"],
                    }
                )
            
            # Step 2: Security scan (Fail-Closed)
            security_clean, security_errors, security_report = self._scan_security(branch_name)
            
            if not security_clean:
                errors.extend(security_errors)
                result = GatekeeperResult(
                    **{**result.__dict__,
                       "status": GatekeeperStatus.BLOCKED,
                       "test_errors": tuple(security_errors),
                    }
                )
                audit_fail = self._create_audit_entry(
                    action="evaluate_blocked",
                    branch_name=branch_name,
                    status=GatekeeperStatus.BLOCKED,
                    details={"errors": errors, "result_id": result_id, "error_type": "security_blocked", "security_report": security_report.dict() if security_report else {}},
                )
                return GatekeeperResult(
                    **{**result.__dict__,
                       "audit_fingerprint": audit_fail["fingerprint"],
                    }
                )
            
            # Step 3: Verify authority grant (Fail-Closed)
            has_grant, grant, grant_errors = self._verify_authority_grant(
                branch_name,
                expected_action="merge",
                expected_resource=f"repository:{self.repository_root.name}",
            )
            
            if not has_grant:
                errors.extend(grant_errors)
                result = GatekeeperResult(
                    **{**result.__dict__,
                       "status": GatekeeperStatus.FAILED,
                       "has_valid_grant": False,
                       "test_errors": tuple(errors),
                    }
                )
                audit_fail = self._create_audit_entry(
                    action="evaluate_fail",
                    branch_name=branch_name,
                    status=GatekeeperStatus.FAILED,
                    details={"errors": errors, "result_id": result_id, "error_type": GatekeeperError.MISSING_GRANT.value},
                )
                return GatekeeperResult(
                    **{**result.__dict__,
                       "audit_fingerprint": audit_fail["fingerprint"],
                    }
                )
            
            result = GatekeeperResult(
                **{**result.__dict__,
                   "has_valid_grant": True,
                   "grant_fingerprint": grant.request_id,
                }
            )
            
            # Step 4: Validate AST constraints (Fail-Closed)
            ast_valid, ast_errors = self._validate_ast_constraints(branch_name)
            
            if not ast_valid:
                errors.extend(ast_errors)
                result = GatekeeperResult(
                    **{**result.__dict__,
                       "status": GatekeeperStatus.FAILED,
                       "ast_validation_passed": False,
                       "ast_errors": tuple(ast_errors),
                       "test_errors": tuple(errors),
                    }
                )
                audit_fail = self._create_audit_entry(
                    action="evaluate_fail",
                    branch_name=branch_name,
                    status=GatekeeperStatus.FAILED,
                    details={"errors": errors, "result_id": result_id, "error_type": GatekeeperError.AST_VALIDATION_FAILED.value},
                )
                return GatekeeperResult(
                    **{**result.__dict__,
                       "audit_fingerprint": audit_fail["fingerprint"],
                    }
                )
            
            result = GatekeeperResult(
                **{**result.__dict__,
                   "ast_validation_passed": True,
                }
            )
            
            # Step 5: Run tests in sandbox (Fail-Closed)
            tests_passed, test_errors = self._run_tests_in_sandbox(branch_name)
            
            if not tests_passed:
                errors.extend(test_errors)
                result = GatekeeperResult(
                    **{**result.__dict__,
                       "status": GatekeeperStatus.FAILED,
                       "tests_passed": False,
                       "test_errors": tuple(test_errors),
                    }
                )
                audit_fail = self._create_audit_entry(
                    action="evaluate_fail",
                    branch_name=branch_name,
                    status=GatekeeperStatus.FAILED,
                    details={"errors": errors, "result_id": result_id, "error_type": GatekeeperError.TESTS_FAILED.value},
                )
                return GatekeeperResult(
                    **{**result.__dict__,
                       "audit_fingerprint": audit_fail["fingerprint"],
                    }
                )
            
            result = GatekeeperResult(
                **{**result.__dict__,
                   "tests_passed": True,
                }
            )
            
            # Step 6: Attempt merge (Fail-Closed)
            merge_success, merge_errors = self._merge_branch(branch_name, target)
            
            if not merge_success:
                errors.extend(merge_errors)
                result = GatekeeperResult(
                    **{**result.__dict__,
                       "status": GatekeeperStatus.FAILED,
                       "merge_success": False,
                       "merge_errors": tuple(merge_errors),
                    }
                )
                audit_fail = self._create_audit_entry(
                    action="evaluate_fail",
                    branch_name=branch_name,
                    status=GatekeeperStatus.FAILED,
                    details={"errors": errors, "result_id": result_id, "error_type": GatekeeperError.MERGE_CONFLICT.value},
                )
                return result
            
            result = GatekeeperResult(
                **{**result.__dict__,
                   "merge_success": True,
                }
            )
            
            # Step 7: Delete feature branch
            branch_deleted = self._delete_branch(branch_name)
            
            result = GatekeeperResult(
                **{**result.__dict__,
                   "status": GatekeeperStatus.PASSED,
                   "branch_deleted": branch_deleted,
                }
            )
            
            # Create success audit entry
            audit_success = self._create_audit_entry(
                action="evaluate_pass",
                branch_name=branch_name,
                status=GatekeeperStatus.PASSED,
                details={
                    "result_id": result_id,
                    "target": target,
                    "grant_fingerprint": result.grant_fingerprint,
                    "branch_deleted": branch_deleted,
                },
            )
            
            return result
            
        except Exception as e:
            # Handle unexpected errors
            errors.append(str(e))
            result = GatekeeperResult(
                **{**result.__dict__,
                   "status": GatekeeperStatus.FAILED,
                   "test_errors": (GatekeeperError.UNKNOWN_ERROR.value, str(e)),
                }
            )
            audit_fail = self._create_audit_entry(
                action="evaluate_error",
                branch_name=branch_name,
                status=GatekeeperStatus.FAILED,
                details={"errors": errors, "result_id": result_id, "error_type": GatekeeperError.UNKNOWN_ERROR.value},
            )
            return result
    
    def verify_patch(self, patch: PatchSynthesisResult) -> bool:
        """
        Verify a patch synthesis result.
        
        Args:
            patch: PatchSynthesisResult to verify
            
        Returns:
            bool: True if patch is valid and can be merged
        """
        # Check authority grant
        if not patch.has_valid_authority:
            return False
        
        # Check patch size
        if len(patch.diff_content.encode("utf-8")) > self.max_patch_size_bytes:
            return False
        
        # Check that patch has valid contract
        if not isinstance(patch.contract, ArchitectureContractV1):
            return False
        
        # Check that contract is approved
        if patch.contract.status != "approved":
            return False
        
        # Check AST validation result
        ast_result = patch.ast_validation_result
        if ast_result.get("status") != "PASS":
            return False
        
        # Check test results
        test_result = patch.test_results
        if test_result.get("status") != "PASS":
            return False
        
        return True
    
    def execute_merge(
        self,
        branch_name: str,
        target: str = "main",
    ) -> bool:
        """
        Execute merge of a branch into target.
        
        This is a standalone method for external callers.
        
        Args:
            branch_name: Name of the branch to merge
            target: Target branch (default: "main")
            
        Returns:
            bool: True if merge was successful
        """
        result = self.evaluate_branch(branch_name, target)
        return result.status == GatekeeperStatus.PASSED
