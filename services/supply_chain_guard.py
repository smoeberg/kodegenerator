"""Static supply-chain and secret scanning for merge gates."""
from __future__ import annotations

import ast
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class ScanFinding:
    kind: str
    line: int
    pattern: str
    evidence: str


@dataclass
class ScanReport:
    findings: list[ScanFinding] = field(default_factory=list)
    scanned_lines: int = 0

    @property
    def safe(self) -> bool:
        return not self.findings

    @property
    def clean(self) -> bool:
        return self.safe


@dataclass(frozen=True)
class DependencyFinding:
    package: str
    declared: str
    cve: str
    fixed: str
    reason: str


@dataclass
class AuditReport:
    findings: list[DependencyFinding] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)

    @property
    def safe(self) -> bool:
        return not self.findings


@dataclass
class SbomDocument:
    components: list[dict[str, str]]
    format: str = "CycloneDX-lite"
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {"format": self.format, "version": self.version, "components": self.components}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]


class SupplyChainGuard:
    """Merge gate for secrets, vulnerable declarations, and service imports."""

    STATIC_CVES: Mapping[str, tuple[str, str, str]] = {
        "requests": ("2.31.0", "CVE-2024-35195", "2.32.0"),
        "urllib3": ("2.2.1", "CVE-2024-37891", "2.2.2"),
        "cryptography": ("42.0.4", "CVE-2024-26130", "42.0.5"),
        "setuptools": ("70.0.0", "CVE-2024-6345", "70.0.0"),
    }

    _SECRET_PATTERNS = (
        ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
        ("aws_secret_key", re.compile(r"(?i)(?:aws_secret_access_key|aws_secret_key)\s*[:=]\s*[A-Za-z0-9/+=]{32,}")),
        ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
        ("github_token", re.compile(r"\bghp_[A-Za-z0-9]{20,}\b")),
        ("github_oauth", re.compile(r"\bgho_[A-Za-z0-9]{20,}\b")),
        ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
        ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
        ("dotenv_secret", re.compile(r"(?i)^\s*\+?\s*(?:[A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD))\s*=\s*[^\s#][^#]*$")),
    )
    _DOTENV_LINE = re.compile(r"^\s*\+?\s*[A-Z][A-Z0-9_]*\s*=\s*[^\s#][^#]*$")
    _VERSION_RE = re.compile(r"(?P<op>===|==|>=|<=|~=|>|<)?\s*(?P<version>\d+(?:\.\d+){0,3}(?:[a-zA-Z0-9.-]*)?)")

    def __init__(self, project_root: str | Path = ".", *, cve_database: Mapping[str, tuple[str, str, str]] | None = None) -> None:
        self.project_root = Path(project_root).resolve()
        self.cve_database = dict(cve_database or self.STATIC_CVES)

    def scan_patch(self, patch: str) -> ScanReport:
        findings: list[ScanFinding] = []
        lines = patch.splitlines()
        current_file = ""
        for number, line in enumerate(lines, 1):
            if line.startswith("+++ b/"):
                current_file = line[6:]
                continue
            if not line.startswith("+") or line.startswith("+++"):
                continue
            content = line[1:]
            for kind, pattern in self._SECRET_PATTERNS:
                match = pattern.search(content)
                if match:
                    evidence = self._redact(content, match.start(), match.end())
                    findings.append(ScanFinding(kind, number, pattern.pattern, evidence))
            if Path(current_file).name.startswith(".env"):
                match = self._DOTENV_LINE.search(content)
                if match and not any(f.line == number and f.kind == "dotenv_file" for f in findings):
                    start, end = match.span()
                    findings.append(ScanFinding("dotenv_file", number, self._DOTENV_LINE.pattern, self._redact(content, start, end)))
        return ScanReport(findings=findings, scanned_lines=len(lines))

    @staticmethod
    def _redact(value: str, start: int, end: int) -> str:
        return value[:start] + "[REDACTED]" + value[end:]

    def audit_dependencies(self, manifest: str | Path | Mapping[str, Any]) -> AuditReport:
        declarations = self._parse_manifest(manifest)
        findings: list[DependencyFinding] = []
        for package, declared in declarations.items():
            key = package.lower().replace("_", "-")
            cve = self.cve_database.get(key)
            if not cve:
                continue
            vulnerable, cve_id, fixed = cve
            version = self._extract_version(declared)
            if version and self._version_lte(version, vulnerable):
                findings.append(DependencyFinding(package, declared, cve_id, fixed, f"versions at or below {vulnerable} are vulnerable"))
        return AuditReport(findings=findings, checked=sorted(declarations))

    def _parse_manifest(self, manifest: str | Path | Mapping[str, Any]) -> dict[str, str]:
        if isinstance(manifest, Mapping):
            if "dependencies" in manifest or "devDependencies" in manifest:
                result: dict[str, str] = {}
                for section in ("dependencies", "devDependencies"):
                    result.update({str(k): str(v) for k, v in manifest.get(section, {}).items()})
                return result
            return {str(k): str(v) for k, v in manifest.items()}
        value = str(manifest)
        path = Path(value)
        if "\n" in value or "\r" in value:
            return self._parse_requirements_text(value)
        try:
            if path.exists():
                text = path.read_text(encoding="utf-8")
            else:
                text = value
        except OSError:
            text = value
        if path.name == "package.json" or text.lstrip().startswith("{"):
            try:
                return self._parse_manifest(json.loads(text))
            except json.JSONDecodeError:
                pass
        return self._parse_requirements_text(text)

    @staticmethod
    def _parse_requirements_text(text: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            match = re.match(r"^([A-Za-z0-9_.-]+)\s*(.*)$", line)
            if match:
                result[match.group(1)] = match.group(2).strip()
        return result

    @classmethod
    def _extract_version(cls, declaration: str) -> str | None:
        match = cls._VERSION_RE.search(declaration)
        return match.group("version") if match else None

    @staticmethod
    def _version_lt(left: str, right: str) -> bool:
        def parts(value: str) -> tuple[int, ...]:
            nums = re.findall(r"\d+", value)
            return tuple(int(x) for x in nums[:4]) + (0,) * (4 - min(4, len(nums)))
        return parts(left) < parts(right)

    @staticmethod
    def _version_lte(left: str, right: str) -> bool:
        return SupplyChainGuard._version_lt(left, right) or left == right

    def generate_sbom(self) -> SbomDocument:
        used: set[str] = set()
        services_dir = self.project_root / "services"
        if services_dir.exists():
            for path in sorted(services_dir.glob("*.py")):
                try:
                    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                except (OSError, SyntaxError):
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        used.update(alias.name.split(".")[0] for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                        used.add(node.module.split(".")[0])
        stdlib = {"abc", "argparse", "ast", "asyncio", "base64", "collections", "contextlib", "copy", "csv", "dataclasses", "datetime", "enum", "functools", "hashlib", "hmac", "io", "itertools", "json", "logging", "math", "os", "pathlib", "re", "secrets", "shutil", "signal", "sqlite3", "statistics", "string", "subprocess", "sys", "tempfile", "threading", "time", "traceback", "typing", "uuid", "warnings", "weakref"}
        components = [{"name": name, "type": "library", "source": "services-import"} for name in sorted(used - stdlib)]
        return SbomDocument(components=components)

    def verify(self, project_id: str | Path) -> bool:
        root = Path(project_id)
        if not root.is_absolute():
            root = self.project_root / root
        guard = SupplyChainGuard(root, cve_database=self.cve_database)
        try:
            patch = subprocess.run(["git", "-C", str(root), "diff", "--cached", "--diff-filter=ACMRT"], capture_output=True, text=True, check=False).stdout
            if not patch:
                patch = subprocess.run(["git", "-C", str(root), "diff", "--diff-filter=ACMRT"], capture_output=True, text=True, check=False).stdout
        except OSError:
            patch = ""
        scan = guard.scan_patch(patch)
        manifest_reports = []
        for name in ("requirements.txt", "package.json"):
            path = root / name
            if path.exists():
                manifest_reports.append(guard.audit_dependencies(path))
        audit_safe = all(report.safe for report in manifest_reports)
        return scan.safe and audit_safe and bool(guard.generate_sbom().components or not (root / "services").exists())
