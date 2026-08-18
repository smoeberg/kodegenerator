"""Formal, contract-bound exceptions for architecture verification.

Exceptions are part of the architecture contract content (and therefore its
fingerprint). Agents cannot invent ignores in source code; only human-approved
contract exceptions may suppress a specific rule for a scoped path, and only
while not expired.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from fnmatch import fnmatch
from typing import Any, Mapping

from domain.architecture_contract_v1 import ArchitectureContractV1Error, _require_nonempty_str


@dataclass(frozen=True)
class ExceptionV1:
    id: str
    rule_id: str
    path: str
    reason: str
    approved_by: str
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_nonempty_str("exception.id", self.id)
        _require_nonempty_str("exception.rule_id", self.rule_id)
        _require_nonempty_str("exception.path", self.path)
        _require_nonempty_str("exception.reason", self.reason)
        _require_nonempty_str("exception.approved_by", self.approved_by)
        if not self.id.startswith("EXC-"):
            raise ArchitectureContractV1Error(f"exception.id must start with EXC-: {self.id}")
        if "../" in self.path or self.path.startswith("/"):
            raise ArchitectureContractV1Error(
                f"exception.path must be repo-relative without traversal: {self.path}"
            )
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ArchitectureContractV1Error("exception.expires_at must be timezone-aware")

    def is_active(self, at: datetime | None = None) -> bool:
        if self.expires_at is None:
            return True
        when = at or datetime.now(timezone.utc)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return when <= self.expires_at

    def matches_path(self, path: str) -> bool:
        normalized = path.replace("\\", "/").lstrip("./")
        pattern = self.path
        if fnmatch(normalized, pattern):
            return True
        if pattern.endswith("/**"):
            prefix = pattern[:-3].rstrip("/")
            if normalized == prefix or normalized.startswith(prefix + "/"):
                return True
        prefix = pattern.rstrip("*").rstrip("/")
        if prefix and (normalized == prefix or normalized.startswith(prefix + "/")):
            return True
        return False

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "rule_id": self.rule_id,
            "path": self.path,
            "reason": self.reason,
            "approved_by": self.approved_by,
        }
        if self.expires_at is not None:
            data["expires_at"] = self.expires_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExceptionV1":
        expires_raw = data.get("expires_at")
        expires_at: datetime | None = None
        if expires_raw:
            expires_at = datetime.fromisoformat(str(expires_raw).replace("Z", "+00:00"))
        return cls(
            id=_require_nonempty_str("exception.id", data.get("id")),
            rule_id=_require_nonempty_str("exception.rule_id", data.get("rule_id")),
            path=_require_nonempty_str("exception.path", data.get("path")),
            reason=_require_nonempty_str("exception.reason", data.get("reason")),
            approved_by=_require_nonempty_str("exception.approved_by", data.get("approved_by")),
            expires_at=expires_at,
        )


def find_active_exception(
    exceptions: tuple[ExceptionV1, ...],
    *,
    rule_id: str,
    path: str | None,
    at: datetime | None = None,
) -> ExceptionV1 | None:
    """Return the first active exception matching rule_id and optional path."""
    for exc in exceptions:
        if exc.rule_id != rule_id:
            continue
        if not exc.is_active(at):
            continue
        if path is None or exc.matches_path(path):
            return exc
    return None
