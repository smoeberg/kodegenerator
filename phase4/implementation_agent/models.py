"""Immutable contracts for the Phase 4B governed implementation agent.

The implementation agent proposes a text patch. It does not write files,
execute commands, run tests, or issue an authority decision.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from phase4.authority.models import AuthorityRequest
from phase4.context_packet.models import ContextPacket
from phase4.execution.models import ExecutionRequest

IMPLEMENTATION_ACTION = "implementation.propose_patch"
_DIFF_HEADER = re.compile(r"^diff --git a/([^\s]+) b/([^\s]+)$")
_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?$")


class ImplementationContractError(ValueError):
    """Base error for invalid implementation-agent values."""


class InvalidPatchError(ImplementationContractError):
    """A proposed patch is malformed or exceeds the approved bounds."""


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_repository_path(path: str) -> str:
    if not isinstance(path, str) or not path.strip():
        raise ImplementationContractError("repository paths must be non-empty strings")
    if path != path.strip() or "\\" in path:
        raise ImplementationContractError(
            "repository paths must be canonical POSIX paths"
        )
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or path.startswith("/"):
        raise ImplementationContractError("repository paths must be relative")
    if not candidate.parts:
        raise ImplementationContractError("repository paths must identify a file")
    if any(part in {"", ".", ".."} for part in candidate.parts):
        raise ImplementationContractError(
            "repository paths cannot contain traversal segments"
        )
    if candidate.as_posix() != path:
        raise ImplementationContractError(
            "repository paths must be canonical POSIX paths"
        )
    return path


@dataclass(frozen=True)
class ChangeBudget:
    """Explicit upper bounds for one patch proposal."""

    max_files: int = 1
    max_changed_lines: int = 100

    def __post_init__(self) -> None:
        for name in ("max_files", "max_changed_lines"):
            value = getattr(self, name)
            if type(value) is not int:
                raise TypeError(f"{name} must be an integer")
            if value < 1:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True)
class ImplementationRequest:
    """Bounded request for a patch proposal from an implementation provider.

    ``authority_request`` constructs the exact AI-3 question for this request;
    it does not evaluate that question or grant authority.
    """

    agent_identity: str
    agent_role: str
    resource: str
    context_packet: ContextPacket
    instruction: str
    allowed_paths: tuple[str, ...]
    budget: ChangeBudget = field(default_factory=ChangeBudget)

    def __post_init__(self) -> None:
        for name in ("agent_identity", "agent_role", "resource", "instruction"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ImplementationContractError(f"{name} must be a non-empty string")
        if not isinstance(self.context_packet, ContextPacket):
            raise TypeError("context_packet must be a ContextPacket")
        if self.context_packet.agent_identity != self.agent_identity:
            raise ImplementationContractError(
                "context packet agent identity does not match the implementation request"
            )
        if self.context_packet.purpose != IMPLEMENTATION_ACTION:
            raise ImplementationContractError(
                f"context packet purpose must be {IMPLEMENTATION_ACTION!r}"
            )
        if not isinstance(self.budget, ChangeBudget):
            raise TypeError("budget must be a ChangeBudget")

        paths = tuple(_validate_repository_path(path) for path in self.allowed_paths)
        if not paths:
            raise ImplementationContractError("allowed_paths must not be empty")
        if len(paths) != len(set(paths)):
            raise ImplementationContractError("allowed_paths must be unique")
        paths = tuple(sorted(paths))
        if self.budget.max_files > len(paths):
            raise ImplementationContractError(
                "max_files cannot exceed the explicit allowed path count"
            )
        object.__setattr__(self, "allowed_paths", paths)

    @property
    def context_packet_id(self) -> str:
        return self.context_packet.packet_id

    @property
    def scope_fingerprint(self) -> str:
        return _canonical_digest(list(self.allowed_paths))

    @property
    def request_fingerprint(self) -> str:
        return _canonical_digest(
            {
                "action": IMPLEMENTATION_ACTION,
                "agent_identity": self.agent_identity,
                "agent_role": self.agent_role,
                "resource": self.resource,
                "context_packet_id": self.context_packet_id,
                "instruction": self.instruction,
                "allowed_paths": list(self.allowed_paths),
                "budget": {
                    "max_files": self.budget.max_files,
                    "max_changed_lines": self.budget.max_changed_lines,
                },
            }
        )

    def authority_context(self) -> Mapping[str, str]:
        """Return immutable request facts for AI-3 policy matching."""
        return {
            "scope_fingerprint": self.scope_fingerprint,
            "max_files": str(self.budget.max_files),
            "max_changed_lines": str(self.budget.max_changed_lines),
        }

    def authority_request(self) -> AuthorityRequest:
        """Build the exact AI-3 question, including execution-bound parameters."""
        return AuthorityRequest.create(
            agent_identity=self.agent_identity,
            agent_role=self.agent_role,
            action=IMPLEMENTATION_ACTION,
            resource=self.resource,
            context_packet_id=self.context_packet_id,
            context=self.authority_context(),
            parameters=self.execution_parameters(),
        )

    def execution_parameters(self) -> Mapping[str, str]:
        return {
            "implementation_request_fingerprint": self.request_fingerprint,
        }

    def execution_request(
        self, *, idempotency_key: str | None = None
    ) -> ExecutionRequest:
        """Build the AI-4 work item bound to the exact AI-3 question."""
        authority_request = self.authority_request()
        return ExecutionRequest.create(
            request_id=authority_request.request_id,
            agent_identity=self.agent_identity,
            action=IMPLEMENTATION_ACTION,
            resource=self.resource,
            context_packet_id=self.context_packet_id,
            parameters=self.execution_parameters(),
            idempotency_key=idempotency_key,
        )


@dataclass(frozen=True)
class PatchCandidate:
    """Untrusted provider response before DOR validates it as a proposal."""

    unified_diff: str

    def __post_init__(self) -> None:
        if not isinstance(self.unified_diff, str) or not self.unified_diff.strip():
            raise InvalidPatchError("provider returned an empty patch")


@dataclass(frozen=True)
class PatchProposal:
    """Content-addressed, scope-checked patch artifact.

    This value is a proposal only. It exposes no method that can apply the diff.
    """

    request: ImplementationRequest
    provider_id: str
    unified_diff: str
    proposal_id: str = field(init=False)
    diff_sha256: str = field(init=False)
    touched_paths: tuple[str, ...] = field(init=False)
    changed_lines: int = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.request, ImplementationRequest):
            raise TypeError("request must be an ImplementationRequest")
        if not isinstance(self.provider_id, str) or not self.provider_id.strip():
            raise ImplementationContractError("provider_id must be a non-empty string")
        if not isinstance(self.unified_diff, str) or not self.unified_diff.strip():
            raise InvalidPatchError("patch must be non-empty")

        touched_paths, changed_lines = _inspect_unified_diff(self.unified_diff)
        outside_scope = tuple(
            path for path in touched_paths if path not in self.request.allowed_paths
        )
        if outside_scope:
            raise InvalidPatchError(
                "patch touches paths outside the approved scope: "
                + ", ".join(outside_scope)
            )
        if len(touched_paths) > self.request.budget.max_files:
            raise InvalidPatchError("patch exceeds the approved file budget")
        if changed_lines > self.request.budget.max_changed_lines:
            raise InvalidPatchError("patch exceeds the approved changed-line budget")

        diff_sha256 = _sha256_text(self.unified_diff)
        proposal_id = _canonical_digest(
            {
                "request_fingerprint": self.request.request_fingerprint,
                "provider_id": self.provider_id,
                "diff_sha256": diff_sha256,
                "touched_paths": list(touched_paths),
                "changed_lines": changed_lines,
            }
        )
        object.__setattr__(self, "proposal_id", proposal_id)
        object.__setattr__(self, "diff_sha256", diff_sha256)
        object.__setattr__(self, "touched_paths", touched_paths)
        object.__setattr__(self, "changed_lines", changed_lines)

    @property
    def request_fingerprint(self) -> str:
        return self.request.request_fingerprint


def _inspect_unified_diff(unified_diff: str) -> tuple[tuple[str, ...], int]:
    """Parse the deliberately narrow text-patch subset accepted by Phase 4B-1."""
    if "GIT binary patch" in unified_diff or "Binary files " in unified_diff:
        raise InvalidPatchError("binary patches are not supported")

    lines = unified_diff.splitlines()
    touched: list[str] = []
    changed_lines = 0
    current_path: str | None = None
    old_header: str | None = None
    new_header: str | None = None
    saw_hunk = False
    section_changed_lines = 0
    in_hunk = False
    expected_old_lines = 0
    expected_new_lines = 0
    seen_old_lines = 0
    seen_new_lines = 0

    def finish_hunk() -> None:
        nonlocal in_hunk
        if not in_hunk:
            return
        if seen_old_lines != expected_old_lines or seen_new_lines != expected_new_lines:
            raise InvalidPatchError("diff hunk line counts do not match its header")
        in_hunk = False

    def finish_section() -> None:
        nonlocal current_path, old_header, new_header, saw_hunk, section_changed_lines
        if current_path is None:
            return
        finish_hunk()
        if old_header is None or new_header is None or not saw_hunk:
            raise InvalidPatchError(
                "each diff section requires file headers and a hunk"
            )
        expected_old = f"a/{current_path}"
        expected_new = f"b/{current_path}"
        if old_header not in {expected_old, "/dev/null"}:
            raise InvalidPatchError("old-file header does not match the diff path")
        if new_header not in {expected_new, "/dev/null"}:
            raise InvalidPatchError("new-file header does not match the diff path")
        if old_header == "/dev/null" and new_header == "/dev/null":
            raise InvalidPatchError(
                "a diff cannot create and delete the same null file"
            )
        if section_changed_lines < 1:
            raise InvalidPatchError("each diff section must contain a changed line")

    for line in lines:
        match = _DIFF_HEADER.match(line)
        if match:
            finish_section()
            old_path, new_path = match.groups()
            if old_path != new_path:
                raise InvalidPatchError(
                    "renames are outside the Phase 4B-1 patch contract"
                )
            try:
                current_path = _validate_repository_path(old_path)
            except ImplementationContractError as exc:
                raise InvalidPatchError(str(exc)) from exc
            if current_path in touched:
                raise InvalidPatchError(
                    "a patch cannot contain duplicate file sections"
                )
            touched.append(current_path)
            old_header = None
            new_header = None
            saw_hunk = False
            section_changed_lines = 0
            in_hunk = False
            continue

        if current_path is None:
            raise InvalidPatchError("patch must start with a git unified-diff header")
        if not in_hunk and line.startswith("--- "):
            if old_header is not None or saw_hunk:
                raise InvalidPatchError("duplicate or misplaced old-file header")
            old_header = line[4:]
            continue
        if not in_hunk and line.startswith("+++ "):
            if old_header is None or new_header is not None or saw_hunk:
                raise InvalidPatchError("duplicate or misplaced new-file header")
            new_header = line[4:]
            continue
        if line.startswith("@@"):
            if old_header is None or new_header is None:
                raise InvalidPatchError("diff hunk appears before file headers")
            finish_hunk()
            hunk_match = _HUNK_HEADER.match(line)
            if hunk_match is None:
                raise InvalidPatchError("malformed diff hunk header")
            _, old_count, _, new_count = hunk_match.groups()
            expected_old_lines = int(old_count) if old_count is not None else 1
            expected_new_lines = int(new_count) if new_count is not None else 1
            seen_old_lines = 0
            seen_new_lines = 0
            saw_hunk = True
            in_hunk = True
            continue
        if in_hunk:
            if line.startswith("+"):
                changed_lines += 1
                section_changed_lines += 1
                seen_new_lines += 1
                continue
            if line.startswith("-"):
                changed_lines += 1
                section_changed_lines += 1
                seen_old_lines += 1
                continue
            if line.startswith(" "):
                seen_old_lines += 1
                seen_new_lines += 1
                continue
            if line == "\\ No newline at end of file":
                continue
            raise InvalidPatchError("malformed line inside diff hunk")
        if line.startswith(
            ("index ", "new file mode ", "deleted file mode ", "old mode ", "new mode ")
        ):
            continue
        raise InvalidPatchError("unsupported metadata in diff section")

    finish_section()
    if not touched:
        raise InvalidPatchError("patch contains no file sections")
    return tuple(sorted(touched)), changed_lines
