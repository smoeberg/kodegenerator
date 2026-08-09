"""Deterministic JSON and Markdown artifacts for validated audit runs."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .runtime import ProjectAuditRun


class ProjectAuditArtifactError(RuntimeError):
    """Validated audit artifacts could not be persisted safely."""


@dataclass(frozen=True)
class ProjectAuditArtifactPaths:
    json_path: Path
    markdown_path: Path


def audit_run_record(run: ProjectAuditRun) -> dict[str, object]:
    report = run.report
    return {
        "schema_version": "dor.project-audit.run.v1",
        "repository": report.request.resource,
        "commit_sha": report.request.evidence_bundle.commit_sha,
        "manifest_id": report.request.evidence_bundle.manifest.manifest_id,
        "evidence_bundle_id": report.request.evidence_bundle.bundle_id,
        "request_fingerprint": report.request_fingerprint,
        "report_id": report.report_id,
        "provider_id": report.provider_id,
        "authoritative": report.authoritative,
        "recommendation": report.recommendation.value,
        "objectives": list(report.request.objectives),
        "target_maturity": report.request.target_maturity.value,
        "governance": {
            "agent_identity": run.agent_identity,
            "authority": {
                "decision": run.authority.decision.value,
                "policy_id": run.authority.policy_id,
                "policy_version": run.authority.policy_version,
                "matched_rule_ids": list(run.authority.matched_rule_ids),
            },
            "execution": {
                "execution_id": run.execution.execution_id,
                "status": run.execution.status.value,
                "adapter_id": run.execution.adapter_id,
            },
            "outcome": {
                "outcome_id": run.outcome.outcome_id,
                "status": run.outcome.status.value,
                "provenance_id": run.outcome.provenance_id,
            },
        },
        "findings": [
            {
                "finding_id": finding.finding_id,
                **finding.candidate.canonical(),
            }
            for finding in report.findings
        ],
        "maturity": [item.canonical() for item in report.candidate.maturity],
    }


def render_audit_json(run: ProjectAuditRun) -> str:
    return (
        json.dumps(
            audit_run_record(run),
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )


def render_audit_markdown(run: ProjectAuditRun) -> str:
    report = run.report
    lines = [
        "# DOR Project Audit",
        "",
        f"- Repository: `{report.request.resource}`",
        f"- Commit: `{report.request.evidence_bundle.commit_sha}`",
        f"- Report: `{report.report_id}`",
        f"- Provider: `{report.provider_id}`",
        f"- Recommendation: **{report.recommendation.value.upper()}**",
        "- Authority: advisory only; P3-20 remains the PASS/FAIL gate",
        "",
        "## Maturity",
        "",
        "| Level | Status | Rationale |",
        "|---|---|---|",
    ]
    for item in report.candidate.maturity:
        lines.append(
            f"| `{item.level.value}` | **{item.status.value}** | "
            f"{_markdown_cell(item.rationale)} |"
        )

    lines.extend(("", "## Findings", ""))
    for finding in report.findings:
        candidate = finding.candidate
        lines.extend(
            (
                f"### {candidate.title}",
                "",
                f"- Key: `{candidate.key}`",
                f"- Classification: `{candidate.classification.value}`",
                f"- Severity: `{candidate.severity.value}`",
                f"- Finding ID: `{finding.finding_id}`",
                "",
                candidate.summary,
                "",
                f"Rationale: {candidate.rationale}",
                "",
                "Evidence:",
                "",
            )
        )
        for assertion in candidate.evidence:
            expected = (
                f" = `{assertion.expected}`" if assertion.expected is not None else ""
            )
            lines.append(
                f"- `{assertion.path}` — `{assertion.predicate.value}`{expected}"
            )
        if candidate.consequences:
            lines.extend(("", "Consequences:", ""))
            lines.extend(f"- {item}" for item in candidate.consequences)
        lines.append("")

    lines.extend(
        (
            "## Governance provenance",
            "",
            f"- Agent identity: `{run.agent_identity}`",
            f"- AI-3 decision: `{run.authority.decision.value}` via `{run.authority.policy_id}`",
            f"- AI-4 execution: `{run.execution.execution_id}` ({run.execution.status.value})",
            f"- AI-5 outcome: `{run.outcome.outcome_id}` ({run.outcome.status.value})",
            "",
        )
    )
    return "\n".join(lines)


def write_audit_artifacts(
    run: ProjectAuditRun,
    output_dir: Path,
) -> ProjectAuditArtifactPaths:
    if not isinstance(output_dir, Path):
        raise TypeError("output_dir must be a pathlib.Path")
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        resolved = output_dir.resolve()
        if not resolved.is_dir():
            raise ProjectAuditArtifactError("output path must be a directory")
        stem = run.report.report_id
        json_path = resolved / f"{stem}.json"
        markdown_path = resolved / f"{stem}.md"
        _atomic_write(json_path, render_audit_json(run))
        _atomic_write(markdown_path, render_audit_markdown(run))
    except OSError as exc:
        raise ProjectAuditArtifactError("could not write audit artifacts") from exc
    return ProjectAuditArtifactPaths(json_path, markdown_path)


def _atomic_write(path: Path, content: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
