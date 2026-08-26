"""
Security Sentinel Service

Fail-closed gatekeeper that scans all patches before merge.
Blocks insecure code including:
- Secrets (API keys, tokens, private keys, credentials)
- Known vulnerable dependencies
- Dangerous function calls
- Drift (files written outside allowed scope)

This service integrates with GatekeeperDaemon as an additional gate.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from services.gatekeeper_daemon import GatekeeperDaemon


class Severity(str, Enum):
    """Severity levels for security findings."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FindingType(str, Enum):
    """Types of security findings."""
    SECRET = "SECRET"
    VULNERABLE_DEPENDENCY = "VULNERABLE_DEPENDENCY"
    DANGEROUS_CALL = "DANGEROUS_CALL"
    DRIFT = "DRIFT"


@dataclass(frozen=True)
class SecurityFinding:
    """A single security finding from a scan."""
    severity: Severity
    finding_type: FindingType
    rule: str
    file_path: str
    line_number: Optional[int] = None
    line_content: Optional[str] = None
    message: Optional[str] = None
    
    def __post_init__(self) -> None:
        """Validate finding."""
        if not self.file_path:
            raise ValueError("file_path cannot be empty")
        if not self.rule:
            raise ValueError("rule cannot be empty")


@dataclass(frozen=True)
class SecurityReport:
    """
    Result from security scanning of a patch.
    
    Attributes:
        is_clean: True if no HIGH severity findings exist
        findings: List of all security findings
        secrets_found: List of secret-related findings
        vulnerable_dependencies: List of dependency-related findings
        dangerous_calls: List of dangerous call findings
        drift_findings: List of drift-related findings
    """
    is_clean: bool
    findings: Tuple[SecurityFinding, ...]
    secrets_found: Tuple[SecurityFinding, ...] = ()
    vulnerable_dependencies: Tuple[SecurityFinding, ...] = ()
    dangerous_calls: Tuple[SecurityFinding, ...] = ()
    drift_findings: Tuple[SecurityFinding, ...] = ()
    
    @classmethod
    def from_findings(cls, findings: List[SecurityFinding]) -> "SecurityReport":
        """Create a SecurityReport from a list of findings."""
        secrets = tuple(f for f in findings if f.finding_type == FindingType.SECRET)
        deps = tuple(f for f in findings if f.finding_type == FindingType.VULNERABLE_DEPENDENCY)
        calls = tuple(f for f in findings if f.finding_type == FindingType.DANGEROUS_CALL)
        drift = tuple(f for f in findings if f.finding_type == FindingType.DRIFT)
        
        # is_clean is True only if there are NO HIGH severity findings
        has_high = any(f.severity == Severity.HIGH or f.severity == Severity.CRITICAL 
                       for f in findings)
        
        return cls(
            is_clean=not has_high,
            findings=tuple(findings),
            secrets_found=secrets,
            vulnerable_dependencies=deps,
            dangerous_calls=calls,
            drift_findings=drift,
        )


@dataclass
class ScanContext:
    """
    Context for security scanning.
    
    Attributes:
        repository_root: Root path of the repository
        allowed_paths: List of allowed path prefixes for drift scanning
        branch_name: Name of the branch being scanned
        target_branch: Target branch for merge
        patch_files: List of files modified in the patch
    """
    repository_root: Path
    allowed_paths: List[str] = field(default_factory=list)
    branch_name: str = ""
    target_branch: str = "main"
    patch_files: List[str] = field(default_factory=list)
    
    def __post_init__(self) -> None:
        self.repository_root = Path(self.repository_root).resolve()


class SecuritySentinel:
    """
    Security Sentinel - Fail-closed gatekeeper for code security.
    
    Scans patches for:
    1. Secrets (API keys, tokens, private keys, AWS/Google credentials)
    2. Vulnerable dependencies (known vulnerable package versions)
    3. Dangerous function calls (subprocess, eval, exec, pickle.loads, socket)
    4. Drift (files written outside allowed scope)
    
    Integration:
    - Called by GatekeeperDaemon as an additional gate
    - Blocks merge on HIGH severity findings
    - Flags MEDIUM findings in audit
    """
    
    # Regex patterns for secret detection
    SECRET_PATTERNS: List[Tuple[str, str, Severity]] = [
        # API Keys
        (r'(?:api[_-]?key|apikey)[=:"]\s*["\']?([a-zA-Z0-9_\-]{32,})["\']?', 
         "API key detected", Severity.HIGH),
        (r'(?:api[_-]?secret|api_secret)[=:"]\s*["\']?([a-zA-Z0-9_\-]{32,})["\']?',
         "API secret detected", Severity.HIGH),
        # General API key pattern (32+ character alphanumeric)
        (r'["\']([a-zA-Z0-9_\-]{32,})["\']',
         "API key detected", Severity.HIGH),
        
        # Generic secrets
        (r'secret[=:"]\s*["\']?([a-zA-Z0-9_\-]{20,})["\']?',
         "Generic secret detected", Severity.HIGH),
        (r'password[=:"]\s*["\']?([^"\'\s]{8,})["\']?',
         "Password detected", Severity.HIGH),
        
        # AWS Credentials
        (r'(?:aws[_-]?access[_-]?key[_-]?id|AWS_ACCESS_KEY_ID)[=:"]\s*["\']?(AKIA[0-9A-Z]{16})["\']?',
         "AWS Access Key ID detected", Severity.CRITICAL),
        (r'(?:aws[_-]?secret[_-]?access[_-]?key|AWS_SECRET_ACCESS_KEY)[=:"]\s*["\']?([a-zA-Z0-9/+=]{40})["\']?',
         "AWS Secret Access Key detected", Severity.CRITICAL),
        (r'(?:aws[_-]?session[_-]?token|AWS_SESSION_TOKEN)[=:"]\s*["\']?([a-zA-Z0-9/+=]{300,})["\']?',
         "AWS Session Token detected", Severity.CRITICAL),
        # General AWS key patterns (catch keys even without variable names)
        (r'["\'](AKIA[0-9A-Z]{16})["\']',
         "AWS Access Key ID detected", Severity.CRITICAL),
        (r'["\']([a-zA-Z0-9/+=]{40})["\']',
         "AWS Secret Access Key detected", Severity.CRITICAL),
        
        # Google Cloud
        (r'(?:gcp[_-]?key|google[_-]?cloud[_-]?key|GCP_KEY)[=:"]\s*["\']?([a-zA-Z0-9_\-]{30,})["\']?',
         "GCP key detected", Severity.HIGH),
        (r'(?:google[_-]?api[_-]?key|GOOGLE_API_KEY)[=:"]\s*["\']?(AIza[0-9A-Za-z\-_]{35})["\']?',
         "Google API Key detected", Severity.HIGH),
        
        # GitHub Tokens
        (r'(?:github[_-]?token|GITHUB_TOKEN)[=:"]\s*["\']?(ghp_[a-zA-Z0-9]{36})["\']?',
         "GitHub Personal Access Token detected", Severity.CRITICAL),
        (r'(?:github[_-]?token|GITHUB_TOKEN)[=:"]\s*["\']?(gho_[a-zA-Z0-9]{36})["\']?',
         "GitHub OAuth Token detected", Severity.CRITICAL),
        (r'(?:github[_-]?token|GITHUB_TOKEN)[=:"]\s*["\']?(ghs_[a-zA-Z0-9]{36})["\']?',
         "GitHub Server-to-Server Token detected", Severity.CRITICAL),
        (r'(?:github[_-]?token|GITHUB_TOKEN)[=:"]\s*["\']?(ghr_[a-zA-Z0-9]{36})["\']?',
         "GitHub Refresh Token detected", Severity.CRITICAL),
        # General GitHub token patterns
        (r'["\'](ghp_[a-zA-Z0-9]{36})["\']',
         "GitHub Personal Access Token detected", Severity.CRITICAL),
        (r'["\'](gho_[a-zA-Z0-9]{36})["\']',
         "GitHub OAuth Token detected", Severity.CRITICAL),
        
        # Slack
        (r'(?:slack[_-]?token|SLACK_TOKEN)[=:"]\s*["\']?(xox[baprs]-[0-9a-zA-Z\-]{10,})["\']?',
         "Slack Token detected", Severity.HIGH),
        
        # Private Keys (PEM format)
        (r'-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----',
         "Private Key (PEM) detected", Severity.CRITICAL),
        (r'-----BEGIN\s+OPENSSH\s+PRIVATE\s+KEY-----',
         "OpenSSH Private Key detected", Severity.CRITICAL),
        (r'-----BEGIN\s+PGP\s+PRIVATE\s+KEY\s+BLOCK-----',
         "PGP Private Key detected", Severity.CRITICAL),
        
        # JWT Tokens (bearer tokens)
        (r'eyJ[a-zA-Z0-9\-_]+\.eyJ[a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+',
         "JWT Token detected", Severity.HIGH),
        
        # Generic token patterns
        (r'(?:bearer\s+)?[a-zA-Z0-9\-_]{20,}\.[a-zA-Z0-9\-_]{20,}\.[a-zA-Z0-9\-_]{20,}',
         "Bearer Token detected", Severity.HIGH),
        
        # Heroku API Key
        (r'(?:heroku[_-]?api[_-]?key|HEROKU_API_KEY)[=:"]\s*["\']?([a-f0-9\-]{36})["\']?',
         "Heroku API Key detected", Severity.HIGH),
        
        # Stripe Keys
        (r'(?:stripe[_-]?api[_-]?key|STRIPE_API_KEY)[=:"]\s*["\']?(sk_live_[0-9a-zA-Z]{24})["\']?',
         "Stripe Live API Key detected", Severity.CRITICAL),
        (r'(?:stripe[_-]?api[_-]?key|STRIPE_API_KEY)[=:"]\s*["\']?(sk_test_[0-9a-zA-Z]{24})["\']?',
         "Stripe Test API Key detected", Severity.HIGH),
        
        # Twilio
        (r'(?:twilio[_-]?api[_-]?key|TWILIO_API_KEY)[=:"]\s*["\']?(SK[a-f0-9]{32})["\']?',
         "Twilio API Key detected", Severity.HIGH),
        
        # SendGrid
        (r'(?:sendgrid[_-]?api[_-]?key|SENDGRID_API_KEY)[=:"]\s*["\']?(SG\.[a-zA-Z0-9_\-]{22}\.[a-zA-Z0-9_\-]{43})["\']?',
         "SendGrid API Key detected", Severity.HIGH),
        
        # Mailchimp
        (r'(?:mailchimp[_-]?api[_-]?key|MAILCHIMP_API_KEY)[=:"]\s*["\']?([a-f0-9]{32}\-[a-f0-9]{4}\-[a-f0-9]{4}\-[a-f0-9]{4}\-[a-f0-9]{12})["\']?',
         "Mailchimp API Key detected", Severity.HIGH),
    ]
    
    # Known vulnerable packages with version constraints
    # Format: (package_name, version_constraint, severity, vulnerability_id)
    VULNERABLE_DEPENDENCIES: List[Tuple[str, str, Severity, str]] = [
        # Log4j vulnerabilities
        ("log4j", "<=2.14.1", Severity.CRITICAL, "CVE-2021-44228"),
        ("log4j", "<=2.15.0", Severity.CRITICAL, "CVE-2021-45046"),
        ("log4j", "<=2.16.0", Severity.HIGH, "CVE-2021-45105"),
        
        # Requests library vulnerabilities
        ("requests", "<2.25.0", Severity.HIGH, "CVE-2021-22903"),
        ("requests", "<2.26.0", Severity.MEDIUM, "CVE-2021-35453"),
        
        # Django vulnerabilities
        ("django", "<3.2.12", Severity.HIGH, "CVE-2021-35042"),
        ("django", "<3.2.13", Severity.HIGH, "CVE-2021-37533"),
        ("django", "<4.0.4", Severity.HIGH, "CVE-2022-22818"),
        
        # Flask vulnerabilities
        ("flask", "<2.0.0", Severity.HIGH, "CVE-2021-23334"),
        ("flask", "<2.0.1", Severity.MEDIUM, "CVE-2021-23335"),
        
        # Jinja2 vulnerabilities
        ("jinja2", "<3.0.0", Severity.HIGH, "CVE-2021-20329"),
        ("jinja2", "<3.0.1", Severity.HIGH, "CVE-2019-10906"),
        
        # PyYAML vulnerabilities
        ("pyyaml", "<5.4", Severity.HIGH, "CVE-2020-14343"),
        ("pyyaml", "<5.4.1", Severity.MEDIUM, "CVE-2020-10208"),
        
        # urllib3 vulnerabilities
        ("urllib3", "<1.26.5", Severity.HIGH, "CVE-2021-28363"),
        ("urllib3", "<1.26.7", Severity.MEDIUM, "CVE-2021-33503"),
        
        # Pillow vulnerabilities
        ("pillow", "<8.3.0", Severity.HIGH, "CVE-2021-27921"),
        ("pillow", "<8.4.0", Severity.MEDIUM, "CVE-2021-34552"),
        
        # cryptography vulnerabilities
        ("cryptography", "<3.4.6", Severity.HIGH, "CVE-2020-36242"),
        ("cryptography", "<35.0.0", Severity.HIGH, "CVE-2021-41553"),
        
        # OpenSSL vulnerabilities (via pyOpenSSL)
        ("pyopenssl", "<22.0.0", Severity.HIGH, "CVE-2022-0778"),
        
        # SQLAlchemy vulnerabilities
        ("sqlalchemy", "<1.4.23", Severity.HIGH, "CVE-2021-36368"),
        ("sqlalchemy", "<1.4.31", Severity.MEDIUM, "CVE-2022-24874"),
        
        # Werkzeug vulnerabilities
        ("werkzeug", "<2.0.0", Severity.HIGH, "CVE-2021-23336"),
        ("werkzeug", "<2.0.2", Severity.MEDIUM, "CVE-2021-32928"),
        
        # PyJWT vulnerabilities
        ("pyjwt", "<2.0.0", Severity.HIGH, "CVE-2021-29452"),
        ("pyjwt", "<2.3.0", Severity.MEDIUM, "CVE-2022-29217"),
        
        # FastAPI vulnerabilities
        ("fastapi", "<0.68.0", Severity.MEDIUM, "CVE-2021-32681"),
        
        # aiohttp vulnerabilities
        ("aiohttp", "<3.8.0", Severity.HIGH, "CVE-2021-33503"),
        
        # boto3/botocore vulnerabilities
        ("boto3", "<1.20.0", Severity.MEDIUM, "CVE-2021-34273"),
        ("botocore", "<1.23.0", Severity.MEDIUM, "CVE-2021-34273"),
    ]
    
    # Dangerous function calls to detect
    DANGEROUS_CALLS: List[Tuple[str, str, Severity, str]] = [
        # Code execution
        ("eval", "builtins", Severity.CRITICAL, "eval() can execute arbitrary code"),
        ("exec", "builtins", Severity.CRITICAL, "exec() can execute arbitrary code"),
        ("compile", "builtins", Severity.HIGH, "compile() can be used to execute arbitrary code"),
        
        # Subprocess execution
        ("system", "os", Severity.HIGH, "os.system() can execute shell commands"),
        ("popen", "os", Severity.HIGH, "os.popen() can execute shell commands"),
        ("spawnl", "os", Severity.HIGH, "os.spawnl() can execute processes"),
        ("spawnle", "os", Severity.HIGH, "os.spawnle() can execute processes"),
        ("spawnlp", "os", Severity.HIGH, "os.spawnlp() can execute processes"),
        ("spawnlpe", "os", Severity.HIGH, "os.spawnlpe() can execute processes"),
        ("spawnv", "os", Severity.HIGH, "os.spawnv() can execute processes"),
        ("spawnve", "os", Severity.HIGH, "os.spawnve() can execute processes"),
        ("fdopen", "os", Severity.MEDIUM, "os.fdopen() can be used for file descriptor manipulation"),
        
        # subprocess module
        ("call", "subprocess", Severity.HIGH, "subprocess.call() can execute shell commands"),
        ("check_call", "subprocess", Severity.HIGH, "subprocess.check_call() can execute shell commands"),
        ("check_output", "subprocess", Severity.HIGH, "subprocess.check_output() can execute shell commands"),
        ("Popen", "subprocess", Severity.HIGH, "subprocess.Popen() can execute shell commands"),
        ("run", "subprocess", Severity.HIGH, "subprocess.run() can execute shell commands"),
        
        # Pickle deserialization (can lead to RCE)
        ("loads", "pickle", Severity.CRITICAL, "pickle.loads() can execute arbitrary code via deserialization"),
        ("load", "pickle", Severity.CRITICAL, "pickle.load() can execute arbitrary code via deserialization"),
        ("Unpickler", "pickle", Severity.CRITICAL, "pickle.Unpickler can execute arbitrary code"),
        
        # Shelve (uses pickle internally)
        ("open", "shelve", Severity.HIGH, "shelve.open() uses pickle and can be unsafe"),
        
        # Marshal (similar to pickle)
        ("loads", "marshal", Severity.HIGH, "marshal.loads() can execute arbitrary code"),
        ("load", "marshal", Severity.HIGH, "marshal.load() can execute arbitrary code"),
        
        # Socket operations (without proper validation)
        ("socket", "socket", Severity.MEDIUM, "socket.socket() can be used for network operations"),
        ("connect", "socket", Severity.MEDIUM, "socket.connect() can establish network connections"),
        ("bind", "socket", Severity.MEDIUM, "socket.bind() can create network listeners"),
        ("listen", "socket", Severity.MEDIUM, "socket.listen() can create network listeners"),
        ("accept", "socket", Severity.MEDIUM, "socket.accept() can accept network connections"),
        
        # File system operations
        ("remove", "os", Severity.MEDIUM, "os.remove() can delete files"),
        ("unlink", "os", Severity.MEDIUM, "os.unlink() can delete files"),
        ("rmdir", "os", Severity.MEDIUM, "os.rmdir() can remove directories"),
        ("system", "os", Severity.HIGH, "os.system() can execute arbitrary commands"),
        
        # Dangerous imports
        ("ctypes", "ctypes", Severity.HIGH, "ctypes can be used for arbitrary code execution"),
        ("ctypes.CDLL", "ctypes", Severity.HIGH, "ctypes.CDLL can load arbitrary libraries"),
        
        # __import__ function
        ("__import__", "builtins", Severity.HIGH, "__import__() can import arbitrary modules"),
        
        # Code object manipulation
        ("code", "types", Severity.HIGH, "types.CodeType can be used to create executable code objects"),
        ("FunctionType", "types", Severity.HIGH, "types.FunctionType can create functions from code objects"),
        
        # Attribute access manipulation
        ("__getattribute__", "builtins", Severity.MEDIUM, "__getattribute__ can bypass access controls"),
        ("__setattr__", "builtins", Severity.MEDIUM, "__setattr__ can modify object attributes"),
        ("__delattr__", "builtins", Severity.MEDIUM, "__delattr__ can delete object attributes"),
    ]
    
    def __init__(
        self,
        *,
        repository_root: Path | str = ".",
        allowed_paths: Optional[List[str]] = None,
        custom_secret_patterns: Optional[List[Tuple[str, str, Severity]]] = None,
        custom_vulnerable_deps: Optional[List[Tuple[str, str, Severity, str]]] = None,
        custom_dangerous_calls: Optional[List[Tuple[str, str, Severity, str]]] = None,
    ):
        """
        Initialize the Security Sentinel.
        
        Args:
            repository_root: Path to repository root
            allowed_paths: List of allowed path prefixes for drift scanning
            custom_secret_patterns: Additional secret patterns to detect
            custom_vulnerable_deps: Additional vulnerable dependencies to check
            custom_dangerous_calls: Additional dangerous calls to detect
        """
        self.repository_root = Path(repository_root).resolve()
        self.allowed_paths = allowed_paths or ["src", "services", "domain", "tests", "phase"]
        self.custom_secret_patterns = custom_secret_patterns or []
        self.custom_vulnerable_deps = custom_vulnerable_deps or []
        self.custom_dangerous_calls = custom_dangerous_calls or []
        
        # Combine default and custom patterns
        self._secret_patterns = self.SECRET_PATTERNS + self.custom_secret_patterns
        self._vulnerable_deps = self.VULNERABLE_DEPENDENCIES + self.custom_vulnerable_deps
        self._dangerous_calls = self.DANGEROUS_CALLS + self.custom_dangerous_calls
    
    def scan_patch(
        self,
        patch_text: str,
        context: Optional[ScanContext] = None,
    ) -> SecurityReport:
        """
        Scan a patch for security issues.
        
        This is the main entry point for security scanning.
        It performs all four types of scans:
        1. Secret scan
        2. Dependency scan
        3. Dangerous call scan
        4. Drift scan
        
        Args:
            patch_text: The patch content as a string (unified diff format)
            context: Optional scan context with repository info
            
        Returns:
            SecurityReport containing all findings
        """
        if context is None:
            context = ScanContext(
                repository_root=self.repository_root,
                allowed_paths=self.allowed_paths,
            )
        
        all_findings: List[SecurityFinding] = []
        
        # Step 1: Parse patch and extract file contents
        patch_files = self._parse_patch(patch_text)
        
        # Update context with patch files
        context = ScanContext(
            **{**context.__dict__, "patch_files": patch_files.keys()}
        )
        
        # Step 2: Secret scan
        secret_findings = self._scan_secrets(patch_files, context)
        all_findings.extend(secret_findings)
        
        # Step 3: Dependency scan
        dep_findings = self._scan_dependencies(patch_files, context)
        all_findings.extend(dep_findings)
        
        # Step 4: Dangerous call scan
        call_findings = self._scan_dangerous_calls(patch_files, context)
        all_findings.extend(call_findings)
        
        # Step 5: Drift scan
        drift_findings = self._scan_drift(patch_files, context)
        all_findings.extend(drift_findings)
        
        # Create report
        return SecurityReport.from_findings(all_findings)
    
    def _parse_patch(self, patch_text: str) -> Dict[str, str]:
        """
        Parse a unified diff patch and extract file contents.
        
        Args:
            patch_text: The patch content
            
        Returns:
            Dictionary mapping file paths to their new content
        """
        files: Dict[str, str] = {}
        
        # Split patch into hunks
        lines = patch_text.splitlines()
        current_file: Optional[str] = None
        current_content: List[str] = []
        in_hunk = False
        
        for line in lines:
            if line.startswith("diff --git"):
                # Save previous file
                if current_file and current_content:
                    files[current_file] = "\n".join(current_content)
                    current_content = []
                
                # Parse new file path
                parts = line.split()
                if len(parts) >= 4:
                    # Format: diff --git a/old_path b/new_path
                    new_path = parts[3].lstrip("b/")
                    current_file = new_path
            elif line.startswith("+++ ") and "dev/null" not in line:
                # This is the new file path
                current_file = line[4:].strip().lstrip('b/')
                current_content = []
                in_hunk = False
            elif line.startswith("--- ") and "dev/null" not in line:
                # Old file path - skip
                in_hunk = False
                continue
            elif line.startswith("@@"):
                # Hunk header - mark that we're in a hunk
                in_hunk = True
                continue
            elif line.startswith("-") and in_hunk:
                # Old line - skip
                continue
            elif line.startswith("+") and in_hunk and current_file:
                # New line - add to content (without the + prefix)
                current_content.append(line[1:])
            elif line.startswith(" ") and in_hunk and current_file:
                # Context line - add to content (without the space)
                current_content.append(line[1:])
            elif current_file and not in_hunk:
                # Lines between +++ and @@ (like old mode lines)
                current_content.append(line)
        
        # Save last file
        if current_file and current_content:
            files[current_file] = "\n".join(current_content)
        
        return files
    
    def _scan_secrets(
        self,
        files: Dict[str, str],
        context: ScanContext,
    ) -> List[SecurityFinding]:
        """
        Scan files for secrets using regex patterns.
        
        Args:
            files: Dictionary of file paths to content
            context: Scan context
            
        Returns:
            List of secret findings
        """
        findings: List[SecurityFinding] = []
        
        for file_path, content in files.items():
            for pattern, rule, severity in self._secret_patterns:
                matches = re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE)
                for match in matches:
                    # Get line number
                    line_number = content[:match.start()].count("\n") + 1
                    line_content = content.splitlines()[line_number - 1] if line_number <= len(content.splitlines()) else ""
                    
                    findings.append(SecurityFinding(
                        severity=severity,
                        finding_type=FindingType.SECRET,
                        rule=rule,
                        file_path=file_path,
                        line_number=line_number,
                        line_content=line_content.strip(),
                        message=f"Secret detected: {rule}",
                    ))
        
        return findings
    
    def _scan_dependencies(
        self,
        files: Dict[str, str],
        context: ScanContext,
    ) -> List[SecurityFinding]:
        """
        Scan files for vulnerable dependencies.
        
        Args:
            files: Dictionary of file paths to content
            context: Scan context
            
        Returns:
            List of dependency findings
        """
        findings: List[SecurityFinding] = []
        
        for file_path, content in files.items():
            if not file_path.endswith(("requirements.txt", "setup.py", "pyproject.toml", "Pipfile")):
                continue
            
            # Extract imports/dependencies from the file
            deps = self._extract_dependencies(file_path, content)
            
            for dep_name, dep_version in deps:
                for pkg_name, version_constraint, severity, vuln_id in self._vulnerable_deps:
                    if dep_name.lower() == pkg_name.lower():
                        if self._version_matches(dep_version, version_constraint):
                            findings.append(SecurityFinding(
                                severity=severity,
                                finding_type=FindingType.VULNERABLE_DEPENDENCY,
                                rule=f"{pkg_name} {version_constraint} ({vuln_id})",
                                file_path=file_path,
                                line_number=None,
                                line_content=f"{dep_name}=={dep_version}" if dep_version else dep_name,
                                message=f"Vulnerable dependency: {pkg_name} {dep_version or 'any'} is vulnerable to {vuln_id}",
                            ))
        
        return findings
    
    def _extract_dependencies(self, file_path: str, content: str) -> List[Tuple[str, Optional[str]]]:
        """
        Extract dependencies from a requirements file.
        
        Args:
            file_path: Path to the file
            content: File content
            
        Returns:
            List of (package_name, version) tuples
        """
        deps: List[Tuple[str, Optional[str]]] = []
        
        if file_path.endswith("requirements.txt"):
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                
                # Parse package name and version
                # Formats: package==1.0.0, package>=1.0.0, package, etc.
                match = re.match(r'^([a-zA-Z0-9_\-\.]+)\s*([>=<!=~]+\s*[a-zA-Z0-9_\-\.]*)?$', line)
                if match:
                    pkg_name = match.group(1)
                    version = match.group(2)
                    deps.append((pkg_name, version))
        
        elif file_path.endswith("setup.py"):
            # Parse install_requires from setup.py
            install_requires_match = re.search(
                r'install_requires\s*=\s*\[([^\]]+)\]',
                content,
                re.DOTALL,
            )
            if install_requires_match:
                requirements_str = install_requires_match.group(1)
                # Extract package specifications
                for match in re.finditer(
                    r'["\']([a-zA-Z0-9_\-\.]+)(?:\s*[>=<!=~]+\s*["\']?[a-zA-Z0-9_\-\.]*["\']?)?["\']',
                    requirements_str,
                ):
                    pkg_name = match.group(1)
                    # Try to extract version
                    version_match = re.search(
                        r'[>=<!=~]+\s*["\']?([a-zA-Z0-9_\-\.]+)["\']?',
                        match.group(0),
                    )
                    version = version_match.group(1) if version_match else None
                    deps.append((pkg_name, version))
        
        elif file_path.endswith("pyproject.toml"):
            # Parse dependencies from pyproject.toml
            deps_match = re.search(
                r'dependencies\s*=\s*\[([^\]]+)\]',
                content,
                re.DOTALL,
            )
            if deps_match:
                requirements_str = deps_match.group(1)
                for match in re.finditer(
                    r'["\']([a-zA-Z0-9_\-\.]+)(?:\s*[>=<!=~]+\s*["\']?[a-zA-Z0-9_\-\.]*["\']?)?["\']',
                    requirements_str,
                ):
                    pkg_name = match.group(1)
                    version_match = re.search(
                        r'[>=<!=~]+\s*["\']?([a-zA-Z0-9_\-\.]+)["\']?',
                        match.group(0),
                    )
                    version = version_match.group(1) if version_match else None
                    deps.append((pkg_name, version))
        
        return deps
    
    def _version_matches(self, version: Optional[str], constraint: str) -> bool:
        """
        Check if a version matches a constraint.
        
        Simple implementation for common constraint formats.
        
        Args:
            version: The version to check
            constraint: The constraint (e.g., "<=2.14.1", "<2.0.0")
            
        Returns:
            True if version matches constraint
        """
        if version is None:
            return True  # No version specified means any version
        
        # Remove any quotes or extra characters
        version = version.strip().strip("\"'")
        constraint = constraint.strip().strip("\"'")
        
        # Simple version comparison (for demonstration)
        # In a real implementation, use packaging.version or similar
        try:
            # Extract version numbers
            def extract_version(v: str) -> Tuple[int, ...]:
                # Remove non-numeric parts
                parts = re.findall(r'\d+', v)
                return tuple(int(p) for p in parts[:3])  # Major, minor, patch
            
            ver_parts = extract_version(version)
            constraint_parts = extract_version(constraint.lstrip("<>=!").lstrip("="))
            
            if not ver_parts or not constraint_parts:
                return True  # Can't parse, assume match
            
            # Compare based on constraint type
            if constraint.startswith("<="):
                return ver_parts <= constraint_parts
            elif constraint.startswith("<"):
                return ver_parts < constraint_parts
            elif constraint.startswith(">="):
                return ver_parts >= constraint_parts
            elif constraint.startswith(">"):
                return ver_parts > constraint_parts
            elif constraint.startswith("=="):
                return ver_parts == constraint_parts
            elif constraint.startswith("!="):
                return ver_parts != constraint_parts
            else:
                return True
        except Exception:
            return True  # Error in parsing, assume match for safety
    
    def _scan_dangerous_calls(
        self,
        files: Dict[str, str],
        context: ScanContext,
    ) -> List[SecurityFinding]:
        """
        Scan files for dangerous function calls using AST parsing.
        
        Args:
            files: Dictionary of file paths to content
            context: Scan context
            
        Returns:
            List of dangerous call findings
        """
        findings: List[SecurityFinding] = []
        
        for file_path, content in files.items():
            if not file_path.endswith(".py"):
                continue
            
            try:
                tree = ast.parse(content, filename=file_path)
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        # Check function name
                        func_name = self._get_call_name(node)
                        if func_name:
                            for call_name, module, severity, message in self._dangerous_calls:
                                if func_name == call_name and (module is None or self._is_from_module(node, module)):
                                    findings.append(SecurityFinding(
                                        severity=severity,
                                        finding_type=FindingType.DANGEROUS_CALL,
                                        rule=f"{module}.{call_name}()" if module else f"{call_name}()",
                                        file_path=file_path,
                                        line_number=node.lineno,
                                        line_content=content.splitlines()[node.lineno - 1] if node.lineno <= len(content.splitlines()) else "",
                                        message=message,
                                    ))
                    
                    # Check for dangerous imports
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            for call_name, module, severity, message in self._dangerous_calls:
                                if alias.name == module:
                                    findings.append(SecurityFinding(
                                        severity=severity,
                                        finding_type=FindingType.DANGEROUS_CALL,
                                        rule=f"import {module}",
                                        file_path=file_path,
                                        line_number=node.lineno,
                                        line_content=content.splitlines()[node.lineno - 1] if node.lineno <= len(content.splitlines()) else "",
                                        message=f"Dangerous import: {module}",
                                    ))
                    
                    if isinstance(node, ast.ImportFrom):
                        if node.module:
                            for call_name, module, severity, message in self._dangerous_calls:
                                if node.module == module:
                                    for alias in node.names:
                                        findings.append(SecurityFinding(
                                            severity=severity,
                                            finding_type=FindingType.DANGEROUS_CALL,
                                            rule=f"from {module} import {alias.name}",
                                            file_path=file_path,
                                            line_number=node.lineno,
                                            line_content=content.splitlines()[node.lineno - 1] if node.lineno <= len(content.splitlines()) else "",
                                            message=f"Dangerous import from {module}",
                                        ))
                        
            except SyntaxError:
                # Skip files with syntax errors
                continue
        
        return findings
    
    def _get_call_name(self, node: ast.Call) -> Optional[str]:
        """Get the name of a function being called."""
        if isinstance(node.func, ast.Name):
            return node.func.id
        elif isinstance(node.func, ast.Attribute):
            return node.func.attr
        return None
    
    def _is_from_module(self, node: ast.Call, module: str) -> bool:
        """Check if a call is from a specific module."""
        if isinstance(node.func, ast.Attribute):
            # Check if the attribute chain ends with the module
            current = node.func
            parts = []
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
                parts.reverse()
                # Check if module is in the import chain
                return module in parts or module == ".".join(parts)
        elif isinstance(node.func, ast.Name):
            # For builtins and other simple names, check if module is None or 'builtins'
            # builtins functions like eval, exec are always available
            return module is None or module == "builtins"
        return False
    
    def _scan_drift(
        self,
        files: Dict[str, str],
        context: ScanContext,
    ) -> List[SecurityFinding]:
        """
        Scan for drift - files written outside allowed scope.
        
        Args:
            files: Dictionary of file paths to content
            context: Scan context
            
        Returns:
            List of drift findings
        """
        findings: List[SecurityFinding] = []
        
        for file_path in files.keys():
            # Check if file is outside allowed paths
            is_allowed = False
            for allowed_prefix in context.allowed_paths:
                if file_path.startswith(allowed_prefix):
                    is_allowed = True
                    break
            
            if not is_allowed:
                # Check if it's a write operation (new file or modified)
                # In a real implementation, we'd check the patch diff
                findings.append(SecurityFinding(
                    severity=Severity.HIGH,
                    finding_type=FindingType.DRIFT,
                    rule="File outside allowed scope",
                    file_path=file_path,
                    line_number=None,
                    line_content="",
                    message=f"File {file_path} is outside allowed paths: {context.allowed_paths}",
                ))
        
        return findings
    
    def check_merge_safety(
        self,
        report: SecurityReport,
    ) -> Tuple[bool, List[SecurityFinding]]:
        """
        Check if a merge should be allowed based on security report.
        
        Args:
            report: Security report from scan
            
        Returns:
            Tuple of (is_safe, list of blocking findings)
        """
        if report.is_clean:
            return True, []
        
        # Get all HIGH and CRITICAL findings
        blocking_findings = [
            f for f in report.findings 
            if f.severity in (Severity.HIGH, Severity.CRITICAL)
        ]
        
        return len(blocking_findings) == 0, blocking_findings
    
    def get_audit_summary(self, report: SecurityReport) -> Dict[str, Any]:
        """
        Get an audit summary for a security report.
        
        Args:
            report: Security report
            
        Returns:
            Dictionary with audit summary
        """
        high_findings = [f for f in report.findings if f.severity == Severity.HIGH]
        medium_findings = [f for f in report.findings if f.severity == Severity.MEDIUM]
        low_findings = [f for f in report.findings if f.severity == Severity.LOW]
        critical_findings = [f for f in report.findings if f.severity == Severity.CRITICAL]
        
        return {
            "is_clean": report.is_clean,
            "total_findings": len(report.findings),
            "critical": len(critical_findings),
            "high": len(high_findings),
            "medium": len(medium_findings),
            "low": len(low_findings),
            "secrets": len(report.secrets_found),
            "vulnerable_dependencies": len(report.vulnerable_dependencies),
            "dangerous_calls": len(report.dangerous_calls),
            "drift": len(report.drift_findings),
            "blocking": not report.is_clean,
        }


# Global sentinel instance for convenience
_sentinel: Optional[SecuritySentinel] = None


def get_security_sentinel(
    repository_root: Path | str = ".",
    **kwargs,
) -> SecuritySentinel:
    """Get or create the global SecuritySentinel instance."""
    global _sentinel
    if _sentinel is None:
        _sentinel = SecuritySentinel(repository_root=repository_root, **kwargs)
    return _sentinel


def scan_patch(
    patch_text: str,
    context: Optional[ScanContext] = None,
    sentinel: Optional[SecuritySentinel] = None,
) -> SecurityReport:
    """
    Convenience function to scan a patch.
    
    Args:
        patch_text: The patch content
        context: Optional scan context
        sentinel: Optional sentinel instance (uses global if not provided)
        
    Returns:
        SecurityReport
    """
    if sentinel is None:
        sentinel = get_security_sentinel()
    return sentinel.scan_patch(patch_text, context)
