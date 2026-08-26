"""
Tests for Security Sentinel service.

Tests cover:
- Secret detection (positive and negative)
- Vulnerable dependency detection
- Dangerous call detection
- Drift detection
"""

from __future__ import annotations

import pytest
from pathlib import Path

from services.security_sentinel import (
    SecuritySentinel,
    SecurityReport,
    SecurityFinding,
    ScanContext,
    Severity,
    FindingType,
    scan_patch,
)


class TestSecurityFinding:
    """Tests for SecurityFinding dataclass."""
    
    def test_creating_finding(self):
        """Test creating a basic finding."""
        finding = SecurityFinding(
            severity=Severity.HIGH,
            finding_type=FindingType.SECRET,
            rule="API key detected",
            file_path="test.py",
            line_number=10,
            line_content="api_key = 'secret123'",
            message="Secret detected",
        )
        
        assert finding.severity == Severity.HIGH
        assert finding.finding_type == FindingType.SECRET
        assert finding.rule == "API key detected"
        assert finding.file_path == "test.py"
        assert finding.line_number == 10
        assert finding.message == "Secret detected"
    
    def test_finding_requires_file_path(self):
        """Test that file_path cannot be empty."""
        with pytest.raises(ValueError, match="file_path cannot be empty"):
            SecurityFinding(
                severity=Severity.HIGH,
                finding_type=FindingType.SECRET,
                rule="test",
                file_path="",
            )
    
    def test_finding_requires_rule(self):
        """Test that rule cannot be empty."""
        with pytest.raises(ValueError, match="rule cannot be empty"):
            SecurityFinding(
                severity=Severity.HIGH,
                finding_type=FindingType.SECRET,
                rule="",
                file_path="test.py",
            )


class TestSecurityReport:
    """Tests for SecurityReport dataclass."""
    
    def test_empty_report_is_clean(self):
        """Test that an empty report is clean."""
        report = SecurityReport.from_findings([])
        assert report.is_clean is True
        assert len(report.findings) == 0
    
    def test_report_with_low_finding_is_clean(self):
        """Test that a report with only LOW findings is clean."""
        finding = SecurityFinding(
            severity=Severity.LOW,
            finding_type=FindingType.SECRET,
            rule="test",
            file_path="test.py",
        )
        report = SecurityReport.from_findings([finding])
        assert report.is_clean is True
    
    def test_report_with_medium_finding_is_clean(self):
        """Test that a report with only MEDIUM findings is clean."""
        finding = SecurityFinding(
            severity=Severity.MEDIUM,
            finding_type=FindingType.SECRET,
            rule="test",
            file_path="test.py",
        )
        report = SecurityReport.from_findings([finding])
        assert report.is_clean is True
    
    def test_report_with_high_finding_is_not_clean(self):
        """Test that a report with HIGH findings is not clean."""
        finding = SecurityFinding(
            severity=Severity.HIGH,
            finding_type=FindingType.SECRET,
            rule="test",
            file_path="test.py",
        )
        report = SecurityReport.from_findings([finding])
        assert report.is_clean is False
    
    def test_report_with_critical_finding_is_not_clean(self):
        """Test that a report with CRITICAL findings is not clean."""
        finding = SecurityFinding(
            severity=Severity.CRITICAL,
            finding_type=FindingType.SECRET,
            rule="test",
            file_path="test.py",
        )
        report = SecurityReport.from_findings([finding])
        assert report.is_clean is False
    
    def test_report_categorizes_findings(self):
        """Test that report categorizes findings correctly."""
        findings = [
            SecurityFinding(
                severity=Severity.HIGH,
                finding_type=FindingType.SECRET,
                rule="secret",
                file_path="test.py",
            ),
            SecurityFinding(
                severity=Severity.MEDIUM,
                finding_type=FindingType.VULNERABLE_DEPENDENCY,
                rule="vulnerable",
                file_path="requirements.txt",
            ),
            SecurityFinding(
                severity=Severity.CRITICAL,
                finding_type=FindingType.DANGEROUS_CALL,
                rule="eval",
                file_path="test.py",
            ),
            SecurityFinding(
                severity=Severity.HIGH,
                finding_type=FindingType.DRIFT,
                rule="drift",
                file_path="unexpected.txt",
            ),
        ]
        
        report = SecurityReport.from_findings(findings)
        
        assert len(report.secrets_found) == 1
        assert len(report.vulnerable_dependencies) == 1
        assert len(report.dangerous_calls) == 1
        assert len(report.drift_findings) == 1


class TestSecretScan:
    """Tests for secret scanning."""
    
    def test_detects_aws_access_key(self):
        """Test detection of AWS access key."""
        sentinel = SecuritySentinel(allowed_paths=["."])
        
        patch_text = """diff --git a/test.py b/test.py
index 1234567..abcdefg 100644
--- a/test.py
+++ b/test.py
@@ -1,3 +1,4 @@
 test = "test"
+aws_key = "AKIAIOSFODNN7EXAMPLE"
"""
        
        report = sentinel.scan_patch(patch_text)
        
        assert report.is_clean is False
        assert any(f.finding_type == FindingType.SECRET for f in report.findings)
        assert any("AWS" in f.rule for f in report.findings)
    
    def test_detects_github_token(self):
        """Test detection of GitHub token."""
        sentinel = SecuritySentinel(allowed_paths=["."])
        
        patch_text = """diff --git a/test.py b/test.py
index 1234567..abcdefg 100644
--- a/test.py
+++ b/test.py
@@ -1,3 +1,4 @@
 test = "test"
+GITHUB_TOKEN = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"
"""
        
        report = sentinel.scan_patch(patch_text)
        
        assert report.is_clean is False
        assert any(f.finding_type == FindingType.SECRET for f in report.findings)
        assert any("GitHub" in f.rule for f in report.findings)
    
    def test_detects_private_key_pem(self):
        """Test detection of PEM private key."""
        sentinel = SecuritySentinel(allowed_paths=["."])
        
        patch_text = """diff --git a/key.pem b/key.pem
index 1234567..abcdefg 100644
--- a/key.pem
+++ b/key.pem
@@ -1,3 +1,4 @@
 test = "test"
+-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC7...
-----END PRIVATE KEY-----
"""
        
        report = sentinel.scan_patch(patch_text)
        
        assert report.is_clean is False
        assert any(f.finding_type == FindingType.SECRET for f in report.findings)
        assert any("Private Key" in f.rule for f in report.findings)
    
    def test_detects_api_key(self):
        """Test detection of generic API key."""
        sentinel = SecuritySentinel(allowed_paths=["."])
        
        patch_text = """diff --git a/config.py b/config.py
index 1234567..abcdefg 100644
--- a/config.py
+++ b/config.py
@@ -1,3 +1,4 @@
 test = "test"
+API_KEY = "abcdef1234567890abcdef1234567890abcdef12"
"""
        
        report = sentinel.scan_patch(patch_text)
        
        assert report.is_clean is False
        assert any(f.finding_type == FindingType.SECRET for f in report.findings)
        assert any("API key" in f.rule for f in report.findings)
    
    def test_no_secrets_clean(self):
        """Test that code without secrets passes."""
        sentinel = SecuritySentinel(allowed_paths=["."])
        
        patch_text = """diff --git a/test.py b/test.py
index 1234567..abcdefg 100644
--- a/test.py
+++ b/test.py
@@ -1,3 +1,4 @@
 test = "test"
+def hello():
+    return "world"
"""
        
        report = sentinel.scan_patch(patch_text)
        
        # No secret findings
        assert not any(f.finding_type == FindingType.SECRET for f in report.findings)
    
    def test_detects_jwt_token(self):
        """Test detection of JWT token."""
        sentinel = SecuritySentinel(allowed_paths=["."])
        
        patch_text = """diff --git a/test.py b/test.py
index 1234567..abcdefg 100644
--- a/test.py
+++ b/test.py
@@ -1,3 +1,4 @@
 test = "test"
+token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
"""
        
        report = sentinel.scan_patch(patch_text)
        
        assert report.is_clean is False
        assert any(f.finding_type == FindingType.SECRET for f in report.findings)
        assert any("JWT" in f.rule for f in report.findings)


class TestDependencyScan:
    """Tests for vulnerable dependency scanning."""
    
    def test_detects_vulnerable_requests(self):
        """Test detection of vulnerable requests library."""
        sentinel = SecuritySentinel(allowed_paths=["."])
        
        patch_text = """diff --git a/requirements.txt b/requirements.txt
index 1234567..abcdefg 100644
--- a/requirements.txt
+++ b/requirements.txt
@@ -1,3 +1,4 @@
 flask==2.0.0
+requests==2.24.0
"""
        
        report = sentinel.scan_patch(patch_text)
        
        assert not report.is_clean
        assert any(f.finding_type == FindingType.VULNERABLE_DEPENDENCY for f in report.findings)
        assert any("requests" in f.rule for f in report.findings)
    
    def test_detects_vulnerable_django(self):
        """Test detection of vulnerable Django version."""
        sentinel = SecuritySentinel(allowed_paths=["."])
        
        patch_text = """diff --git a/requirements.txt b/requirements.txt
index 1234567..abcdefg 100644
--- a/requirements.txt
+++ b/requirements.txt
@@ -1,3 +1,4 @@
 flask==2.0.0
+django==3.2.10
"""
        
        report = sentinel.scan_patch(patch_text)
        
        assert not report.is_clean
        assert any(f.finding_type == FindingType.VULNERABLE_DEPENDENCY for f in report.findings)
        assert any("django" in f.rule for f in report.findings)
    
    def test_safe_dependencies_clean(self):
        """Test that safe dependencies pass."""
        sentinel = SecuritySentinel(allowed_paths=["."])
        
        patch_text = """diff --git a/requirements.txt b/requirements.txt
index 1234567..abcdefg 100644
--- a/requirements.txt
+++ b/requirements.txt
@@ -1,3 +1,4 @@
 flask==2.0.0
+requests==2.28.0
"""
        
        report = sentinel.scan_patch(patch_text)
        
        # No vulnerable dependency findings for safe version
        assert not any(
            f.finding_type == FindingType.VULNERABLE_DEPENDENCY and "requests" in f.rule
            for f in report.findings
        )


class TestDangerousCallScan:
    """Tests for dangerous call scanning."""
    
    def test_detects_eval(self):
        """Test detection of eval() call."""
        sentinel = SecuritySentinel(allowed_paths=["."])
        
        patch_text = """diff --git a/test.py b/test.py
index 1234567..abcdefg 100644
--- a/test.py
+++ b/test.py
@@ -1,3 +1,4 @@
 test = "test"
+result = eval(user_input)
"""
        
        report = sentinel.scan_patch(patch_text)
        
        assert report.is_clean is False
        assert any(f.finding_type == FindingType.DANGEROUS_CALL for f in report.findings)
        assert any("eval" in f.rule for f in report.findings)
    
    def test_detects_exec(self):
        """Test detection of exec() call."""
        sentinel = SecuritySentinel(allowed_paths=["."])
        
        patch_text = """diff --git a/test.py b/test.py
index 1234567..abcdefg 100644
--- a/test.py
+++ b/test.py
@@ -1,3 +1,4 @@
 test = "test"
+exec(user_input)
"""
        
        report = sentinel.scan_patch(patch_text)
        
        assert report.is_clean is False
        assert any(f.finding_type == FindingType.DANGEROUS_CALL for f in report.findings)
        assert any("exec" in f.rule for f in report.findings)
    
    def test_detects_subprocess_call(self):
        """Test detection of subprocess.call()."""
        sentinel = SecuritySentinel(allowed_paths=["."])
        
        patch_text = """diff --git a/test.py b/test.py
index 1234567..abcdefg 100644
--- a/test.py
+++ b/test.py
@@ -1,3 +1,4 @@
 test = "test"
+import subprocess
+subprocess.call("rm -rf /", shell=True)
"""
        
        report = sentinel.scan_patch(patch_text)
        
        assert report.is_clean is False
        assert any(f.finding_type == FindingType.DANGEROUS_CALL for f in report.findings)
        assert any("subprocess" in f.rule for f in report.findings)
    
    def test_detects_os_system(self):
        """Test detection of os.system() call."""
        sentinel = SecuritySentinel(allowed_paths=["."])
        
        patch_text = """diff --git a/test.py b/test.py
index 1234567..abcdefg 100644
--- a/test.py
+++ b/test.py
@@ -1,3 +1,4 @@
 test = "test"
+import os
+os.system("rm -rf /")
"""
        
        report = sentinel.scan_patch(patch_text)
        
        assert report.is_clean is False
        assert any(f.finding_type == FindingType.DANGEROUS_CALL for f in report.findings)
        assert any("os.system" in f.rule or "system" in f.rule for f in report.findings)
    
    def test_detects_pickle_loads(self):
        """Test detection of pickle.loads()."""
        sentinel = SecuritySentinel(allowed_paths=["."])
        
        patch_text = """diff --git a/test.py b/test.py
index 1234567..abcdefg 100644
--- a/test.py
+++ b/test.py
@@ -1,3 +1,4 @@
 test = "test"
+import pickle
+data = pickle.loads(untrusted_data)
"""
        
        report = sentinel.scan_patch(patch_text)
        
        assert report.is_clean is False
        assert any(f.finding_type == FindingType.DANGEROUS_CALL for f in report.findings)
        assert any("pickle.loads" in f.rule or "pickle" in f.rule for f in report.findings)
    
    def test_detects_socket_usage(self):
        """Test detection of socket usage."""
        sentinel = SecuritySentinel(allowed_paths=["."])
        
        patch_text = """diff --git a/test.py b/test.py
index 1234567..abcdefg 100644
--- a/test.py
+++ b/test.py
@@ -1,3 +1,4 @@
 test = "test"
+import socket
+s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
"""
        
        report = sentinel.scan_patch(patch_text)
        
        assert report.is_clean is False
        assert any(f.finding_type == FindingType.DANGEROUS_CALL for f in report.findings)
        assert any("socket" in f.rule for f in report.findings)
    
    def test_safe_code_clean(self):
        """Test that safe code passes."""
        sentinel = SecuritySentinel(allowed_paths=["."])
        
        patch_text = """diff --git a/test.py b/test.py
index 1234567..abcdefg 100644
--- a/test.py
+++ b/test.py
@@ -1,3 +1,4 @@
 test = "test"
+def add(a, b):
+    return a + b
"""
        
        report = sentinel.scan_patch(patch_text)
        
        # No dangerous call findings
        assert not any(f.finding_type == FindingType.DANGEROUS_CALL for f in report.findings)


class TestDriftScan:
    """Tests for drift scanning."""
    
    def test_detects_file_outside_scope(self):
        """Test detection of file outside allowed scope."""
        sentinel = SecuritySentinel(
            allowed_paths=["src", "services", "tests"]
        )
        
        patch_text = """diff --git a/secret.txt b/secret.txt
index 1234567..abcdefg 100644
--- a/secret.txt
+++ b/secret.txt
@@ -1,3 +1,4 @@
 test = "test"
+secret = "value"
"""
        
        report = sentinel.scan_patch(patch_text)
        
        assert report.is_clean is False
        assert any(f.finding_type == FindingType.DRIFT for f in report.findings)
    
    def test_allows_file_in_scope(self):
        """Test that files in allowed scope pass."""
        sentinel = SecuritySentinel(
            allowed_paths=["src", "services", "tests"]
        )
        
        patch_text = """diff --git a/src/module.py b/src/module.py
index 1234567..abcdefg 100644
--- a/src/module.py
+++ b/src/module.py
@@ -1,3 +1,4 @@
 test = "test"
+def hello():
+    return "world"
"""
        
        report = sentinel.scan_patch(patch_text)
        
        # No drift findings
        assert not any(f.finding_type == FindingType.DRIFT for f in report.findings)


class TestIntegration:
    """Integration tests for SecuritySentinel."""
    
    def test_full_scan_with_multiple_issues(self):
        """Test a patch with multiple types of issues."""
        sentinel = SecuritySentinel(
            allowed_paths=["src", "services"]
        )
        
        patch_text = """diff --git a/src/test.py b/src/test.py
index 1234567..abcdefg 100644
--- a/src/test.py
+++ b/src/test.py
@@ -1,3 +1,4 @@
 test = "test"
+API_KEY = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"
+import os
+os.system("rm -rf /")
diff --git a/secret.txt b/secret.txt
index 1234567..abcdefg 100644
--- a/secret.txt
+++ b/secret.txt
@@ -1,3 +1,4 @@
 test = "test"
+secret = "value"
diff --git a/requirements.txt b/requirements.txt
index 1234567..abcdefg 100644
--- a/requirements.txt
+++ b/requirements.txt
@@ -1,3 +1,4 @@
 flask==2.0.0
+requests==2.24.0
"""
        
        report = sentinel.scan_patch(patch_text)
        
        # Should have findings of all types
        assert len(report.findings) >= 4
        assert any(f.finding_type == FindingType.SECRET for f in report.findings)
        assert any(f.finding_type == FindingType.DANGEROUS_CALL for f in report.findings)
        assert any(f.finding_type == FindingType.DRIFT for f in report.findings)
        assert any(f.finding_type == FindingType.VULNERABLE_DEPENDENCY for f in report.findings)
        
        # Should not be clean due to HIGH/CRITICAL findings
        assert report.is_clean is False
    
    def test_clean_patch_passes(self):
        """Test that a clean patch passes all checks."""
        sentinel = SecuritySentinel(
            allowed_paths=["src", "services", "tests"]
        )
        
        patch_text = """diff --git a/src/test.py b/src/test.py
index 1234567..abcdefg 100644
--- a/src/test.py
+++ b/src/test.py
@@ -1,3 +1,4 @@
 test = "test"
+def add(a, b):
+    return a + b
"""
        
        report = sentinel.scan_patch(patch_text)
        
        assert report.is_clean is True
        assert len(report.findings) == 0
    
    def test_check_merge_safety(self):
        """Test merge safety check."""
        sentinel = SecuritySentinel(allowed_paths=["."])
        
        # Create a report with HIGH severity finding
        finding = SecurityFinding(
            severity=Severity.HIGH,
            finding_type=FindingType.SECRET,
            rule="test",
            file_path="test.py",
        )
        report = SecurityReport.from_findings([finding])
        
        is_safe, blocking = sentinel.check_merge_safety(report)
        
        assert is_safe is False
        assert len(blocking) == 1
        assert blocking[0].severity == Severity.HIGH
    
    def test_check_merge_safety_with_medium_only(self):
        """Test that MEDIUM findings don't block merge."""
        sentinel = SecuritySentinel(allowed_paths=["."])
        
        finding = SecurityFinding(
            severity=Severity.MEDIUM,
            finding_type=FindingType.VULNERABLE_DEPENDENCY,
            rule="test",
            file_path="test.py",
        )
        report = SecurityReport.from_findings([finding])
        
        is_safe, blocking = sentinel.check_merge_safety(report)
        
        assert is_safe is True
        assert len(blocking) == 0
    
    def test_get_audit_summary(self):
        """Test audit summary generation."""
        sentinel = SecuritySentinel(allowed_paths=["."])
        
        findings = [
            SecurityFinding(
                severity=Severity.CRITICAL,
                finding_type=FindingType.SECRET,
                rule="secret",
                file_path="test.py",
            ),
            SecurityFinding(
                severity=Severity.HIGH,
                finding_type=FindingType.DANGEROUS_CALL,
                rule="eval",
                file_path="test.py",
            ),
            SecurityFinding(
                severity=Severity.MEDIUM,
                finding_type=FindingType.VULNERABLE_DEPENDENCY,
                rule="requests",
                file_path="requirements.txt",
            ),
            SecurityFinding(
                severity=Severity.LOW,
                finding_type=FindingType.SECRET,
                rule="test",
                file_path="test.py",
            ),
        ]
        
        report = SecurityReport.from_findings(findings)
        summary = sentinel.get_audit_summary(report)
        
        assert summary["is_clean"] is False
        assert summary["total_findings"] == 4
        assert summary["critical"] == 1
        assert summary["high"] == 1
        assert summary["medium"] == 1
        assert summary["low"] == 1
        assert summary["blocking"] is True


class TestScanPatchFunction:
    """Tests for the scan_patch convenience function."""
    
    def test_scan_patch_function(self):
        """Test the scan_patch convenience function."""
        patch_text = """diff --git a/test.py b/test.py
index 1234567..abcdefg 100644
--- a/test.py
+++ b/test.py
@@ -1,3 +1,4 @@
 test = "test"
+API_KEY = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"
"""
        
        report = scan_patch(patch_text)
        
        assert report.is_clean is False
        assert any(f.finding_type == FindingType.SECRET for f in report.findings)


class TestScanContext:
    """Tests for ScanContext."""
    
    def test_scan_context_defaults(self):
        """Test ScanContext with defaults."""
        context = ScanContext(repository_root="/tmp/test")
        
        assert context.repository_root == Path("/tmp/test")
        assert context.allowed_paths == []
        assert context.branch_name == ""
        assert context.target_branch == "main"
        assert context.patch_files == []
    
    def test_scan_context_with_values(self):
        """Test ScanContext with custom values."""
        context = ScanContext(
            repository_root="/tmp/test",
            allowed_paths=["src", "tests"],
            branch_name="feat/test",
            target_branch="main",
            patch_files=["test.py", "config.py"],
        )
        
        assert context.repository_root == Path("/tmp/test")
        assert context.allowed_paths == ["src", "tests"]
        assert context.branch_name == "feat/test"
        assert context.target_branch == "main"
        assert context.patch_files == ["test.py", "config.py"]
