"""Command-line interface for read-only governed repository audits."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TextIO

from .artifacts import ProjectAuditArtifactError, write_audit_artifacts
from .baseline import DORBaselineProjectAuditProvider
from .collector import EvidenceCollectionError
from .openai_provider import (
    OpenAIProjectAuditProvider,
    OpenAIProjectAuditProviderError,
)
from .repository import GitRepositoryError
from .runtime import ProjectAuditRuntime, ProjectAuditRuntimeError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dor-project-audit")
    subcommands = parser.add_subparsers(dest="command", required=True)
    audit = subcommands.add_parser(
        "audit",
        help="audit one exact checked-out Git revision without modifying it",
    )
    audit.add_argument("--repository-root", type=Path, default=Path.cwd())
    audit.add_argument(
        "--repository",
        default="repository:smoeberg/kodegenerator",
        help="authority resource identity for the repository",
    )
    audit.add_argument("--revision", default="HEAD")
    audit.add_argument(
        "--provider",
        choices=("baseline", "openai"),
        default="baseline",
    )
    audit.add_argument(
        "--model",
        help="OpenAI model; alternatively set DOR_PROJECT_AUDIT_MODEL",
    )
    audit.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/project-audit"),
    )
    audit.add_argument("--no-write", action="store_true")
    audit.add_argument("--max-files", type=int, default=5_000)
    audit.add_argument("--max-bytes", type=int, default=16 * 1024 * 1024)
    audit.add_argument(
        "--max-provider-input-bytes",
        type=int,
        default=2 * 1024 * 1024,
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    output = stdout or sys.stdout
    errors = stderr or sys.stderr
    environment = environ if environ is not None else os.environ
    args = build_parser().parse_args(argv)

    try:
        if args.provider == "baseline":
            provider = DORBaselineProjectAuditProvider()
        else:
            api_key = environment.get("OPENAI_API_KEY", "")
            if not api_key:
                raise ValueError(
                    "OPENAI_API_KEY must be configured for --provider openai"
                )
            model = args.model or environment.get("DOR_PROJECT_AUDIT_MODEL", "")
            if not model:
                raise ValueError(
                    "--model or DOR_PROJECT_AUDIT_MODEL is required for the OpenAI provider"
                )
            provider = OpenAIProjectAuditProvider(
                api_key=api_key,
                model=model,
                max_input_bytes=args.max_provider_input_bytes,
            )

        runtime = ProjectAuditRuntime(
            args.repository_root,
            max_files=args.max_files,
            max_bytes=args.max_bytes,
        )
        run = runtime.run(
            repository=args.repository,
            provider=provider,
            revision=args.revision,
        )
        paths = None
        if not args.no_write:
            output_dir = args.output_dir
            if not output_dir.is_absolute():
                output_dir = runtime.root / output_dir
            paths = write_audit_artifacts(run, output_dir)

        summary: dict[str, object] = {
            "authoritative": False,
            "commit_sha": run.report.request.evidence_bundle.commit_sha,
            "finding_count": len(run.report.findings),
            "provider_id": run.report.provider_id,
            "recommendation": run.report.recommendation.value,
            "report_id": run.report.report_id,
        }
        if paths is not None:
            summary["json_artifact"] = str(paths.json_path)
            summary["markdown_artifact"] = str(paths.markdown_path)
        output.write(json.dumps(summary, sort_keys=True) + "\n")
        return 0
    except (
        EvidenceCollectionError,
        GitRepositoryError,
        OpenAIProjectAuditProviderError,
        ProjectAuditArtifactError,
        ProjectAuditRuntimeError,
        ValueError,
    ) as exc:
        errors.write(f"project audit failed: {exc}\n")
        return 2
