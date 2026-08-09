"""Operational tests for the Phase 4B Project Audit runtime and providers."""

from __future__ import annotations

import io
import json
import os
import subprocess
import urllib.request
from pathlib import Path

import pytest

from phase4.execution import ExecutionStatus
from phase4.outcome.models import OutcomeStatus
from phase4.project_audit import AuditRecommendation
from phase4.project_audit.artifacts import (
    audit_run_record,
    render_audit_json,
    render_audit_markdown,
    write_audit_artifacts,
)
from phase4.project_audit.baseline import DORBaselineProjectAuditProvider
from phase4.project_audit.cli import main as audit_main
from phase4.project_audit.openai_provider import (
    OPENAI_RESPONSES_URL,
    OpenAIProjectAuditInputLimitError,
    OpenAIProjectAuditProvider,
    OpenAIProjectAuditProviderError,
    OpenAIProjectAuditResponseError,
    _http_transport,
)
from phase4.project_audit.repository import (
    GitRepositoryDriftError,
    GitRepositoryManifestBuilder,
)
from phase4.project_audit.runtime import ProjectAuditRuntime


def _init_repository(root: Path, files: dict[str, str]) -> str:
    for path, content in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    subprocess.run(("git", "init", "-q", str(root)), check=True)
    subprocess.run(("git", "-C", str(root), "add", "--", *files), check=True)
    environment = {
        **os.environ,
        "GIT_AUTHOR_NAME": "DOR Test",
        "GIT_AUTHOR_EMAIL": "dor-test@example.invalid",
        "GIT_COMMITTER_NAME": "DOR Test",
        "GIT_COMMITTER_EMAIL": "dor-test@example.invalid",
    }
    subprocess.run(
        ("git", "-C", str(root), "commit", "-qm", "test revision"),
        check=True,
        env=environment,
    )
    return subprocess.run(
        ("git", "-C", str(root), "rev-parse", "HEAD"),
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def _dor_files() -> dict[str, str]:
    return {
        ".env.example": "DOR_JWT_SECRET_KEY=change-me\n",
        ".github/workflows/ci.yml": (
            "run: python -m compileall -q api domain runtime monitoring\n"
        ),
        "alembic/versions/006_merge_heads.py": "revision = '006_merge_heads'\n",
        "api/auth.py": 'SECRET_KEY = os.getenv("DOR_JWT_SECRET_KEY")\n',
        "api/main.py": "app = FastAPI()\n",
        "dashboard/app.py": (
            'ADMIN_PASSWORD = os.getenv("DOR_ADMIN_PASSWORD", "demo")\n'
            "def encrypt(plain_key):\n"
            "    try: return encrypt_real(plain_key)\n"
            "    except Exception: return plain_key\n"
        ),
        "docker-compose.yml": "environment:\n  - JWT_SECRET_KEY=change-me\n",
        "main.py": "async def main():\n    intent = Intent(goal='x')\n",
        "monitoring/tracer.py": "FastAPIInstrumentor.instrument_app(app)\n",
        "phase4/implementation_agent/models.py": "class PatchProposal: pass\n",
        "phase4/project_audit/adapter.py": "class Adapter: pass\n",
        "phase4/project_audit/models.py": "class Report: pass\n",
        "requirements.txt": "fastapi\nopentelemetry-api\n",
        "runtime/model_registry.py": "from domain.model import Model\n",
        "tests/phase4/test_implementation_agent.py": (
            "def test_contract(): assert True\n"
        ),
        "tests/phase4/test_project_audit.py": "def test_audit(): assert True\n",
    }


def _candidate_payload(candidate) -> dict[str, object]:
    return {
        "findings": [item.canonical() for item in candidate.findings],
        "maturity": [item.canonical() for item in candidate.maturity],
        "recommendation": candidate.recommendation.value,
    }


def test_git_manifest_is_bound_to_commit_and_excludes_untracked_files(tmp_path):
    commit_sha = _init_repository(
        tmp_path,
        {"README.md": "# audited\n", "src/app.py": "VALUE = 1\n"},
    )
    (tmp_path / "untracked.txt").write_text("outside revision", encoding="utf-8")

    manifest = GitRepositoryManifestBuilder(tmp_path).build(
        repository="repository:example/project"
    )

    assert manifest.commit_sha == commit_sha
    assert {entry.path for entry in manifest.entries} == {
        "README.md",
        "src/app.py",
    }
    assert manifest.complete is True


def test_git_manifest_rejects_tracked_worktree_drift(tmp_path):
    _init_repository(tmp_path, {"README.md": "committed\n"})
    (tmp_path / "README.md").write_text("changed\n", encoding="utf-8")

    with pytest.raises(GitRepositoryDriftError, match="does not match"):
        GitRepositoryManifestBuilder(tmp_path).build(
            repository="repository:example/project"
        )


def test_baseline_runtime_executes_ai1_through_ai5_and_writes_artifacts(tmp_path):
    commit_sha = _init_repository(tmp_path, _dor_files())

    run = ProjectAuditRuntime(tmp_path).run(
        repository="repository:smoeberg/kodegenerator",
        provider=DORBaselineProjectAuditProvider(),
    )

    assert run.report.request.evidence_bundle.commit_sha == commit_sha
    assert run.authority.allowed is True
    assert run.execution.status is ExecutionStatus.SUCCEEDED
    assert run.outcome.status is OutcomeStatus.SUCCEEDED
    assert run.report.recommendation is AuditRecommendation.REPLAN
    assert run.report.authoritative is False
    keys = {finding.key for finding in run.report.findings}
    assert {
        "dashboard-security-and-import-gap",
        "deployment-jwt-variable-drift",
        "implementation-agent-not-runtime-integrated",
        "project-audit-not-operational",
        "root-entrypoint-unbound-intent",
        "tracing-entrypoint-incomplete",
    } <= keys

    first_json = render_audit_json(run)
    assert first_json == render_audit_json(run)
    assert "P3-20 remains the PASS/FAIL gate" in render_audit_markdown(run)
    paths = write_audit_artifacts(run, tmp_path / "audit-output")
    assert paths.json_path.read_text(encoding="utf-8") == first_json
    assert paths.markdown_path.is_file()
    record = audit_run_record(run)
    assert record["governance"]["authority"]["decision"] == "allow"
    assert record["authoritative"] is False


def test_runtime_rejects_glob_authority_resources(tmp_path):
    _init_repository(tmp_path, _dor_files())

    with pytest.raises(ValueError, match="glob"):
        ProjectAuditRuntime(tmp_path).run(
            repository="repository:smoeberg/*",
            provider=DORBaselineProjectAuditProvider(),
        )


def test_baseline_closes_implementation_gap_only_for_complete_runtime_wiring(
    tmp_path,
):
    files = _dor_files()
    files.update(
        {
            "api/main.py": (
                "from api.endpoints import implementation_agent\n"
                "app.include_router(implementation_agent.router)\n"
            ),
            "api/endpoints/implementation_agent.py": "router = object()\n",
            "phase4/implementation_agent/runtime.py": (
                "class ImplementationAgentRuntime: pass\n"
            ),
        }
    )
    _init_repository(tmp_path, files)

    run = ProjectAuditRuntime(tmp_path).run(
        repository="repository:smoeberg/kodegenerator",
        provider=DORBaselineProjectAuditProvider(),
    )

    keys = {finding.key for finding in run.report.findings}
    assert "implementation-agent-not-runtime-integrated" not in keys


def test_openai_provider_uses_strict_responses_schema_without_leaking_key(tmp_path):
    _init_repository(tmp_path, _dor_files())
    baseline_run = ProjectAuditRuntime(tmp_path).run(
        repository="repository:smoeberg/kodegenerator",
        provider=DORBaselineProjectAuditProvider(),
    )
    expected = baseline_run.report.candidate
    captured: dict[str, object] = {}

    def transport(url, headers, body, timeout):
        captured.update(
            url=url,
            headers=dict(headers),
            body=body,
            timeout=timeout,
        )
        return {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(_candidate_payload(expected)),
                        }
                    ],
                }
            ],
        }

    provider = OpenAIProjectAuditProvider(
        api_key="secret-test-key",
        model="audit-model",
        transport=transport,
    )
    candidate = provider.audit_project(baseline_run.report.request)

    assert candidate == expected
    assert captured["url"] == OPENAI_RESPONSES_URL
    assert captured["headers"]["Authorization"] == "Bearer secret-test-key"
    assert b"secret-test-key" not in captured["body"]
    request_body = json.loads(captured["body"])
    assert request_body["store"] is False
    assert request_body["text"]["format"]["type"] == "json_schema"
    assert request_body["text"]["format"]["strict"] is True
    assert provider.provider_id == "openai.responses:audit-model"


@pytest.mark.parametrize(
    "url",
    (
        "http://api.openai.com/v1/responses",
        "https://attacker.example/v1/responses",
        "file:///tmp/responses.json",
    ),
)
def test_http_transport_rejects_non_allowlisted_endpoints_without_network(
    monkeypatch,
    url,
):
    called = False

    def urlopen(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("network transport must not be called")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    with pytest.raises(OpenAIProjectAuditProviderError, match="not allowed"):
        _http_transport(url, {}, b"{}", 1.0)
    assert called is False


def test_openai_provider_refuses_to_silently_truncate_complete_evidence(tmp_path):
    _init_repository(tmp_path, _dor_files())
    request = (
        ProjectAuditRuntime(tmp_path)
        .run(
            repository="repository:smoeberg/kodegenerator",
            provider=DORBaselineProjectAuditProvider(),
        )
        .report.request
    )
    called = False

    def transport(*_args):
        nonlocal called
        called = True
        return {}

    provider = OpenAIProjectAuditProvider(
        api_key="secret-test-key",
        model="audit-model",
        max_input_bytes=1,
        transport=transport,
    )

    with pytest.raises(OpenAIProjectAuditInputLimitError, match="no evidence was sent"):
        provider.audit_project(request)
    assert called is False


@pytest.mark.parametrize(
    ("response", "message"),
    (
        ({"status": "incomplete", "output": []}, "did not complete"),
        (
            {
                "status": "completed",
                "output": [
                    {"content": [{"type": "refusal", "refusal": "not available"}]}
                ],
            },
            "refused",
        ),
        (
            {
                "status": "completed",
                "output_text": '{"findings":[],"maturity":[],"unexpected":true}',
            },
            "strict schema",
        ),
    ),
)
def test_openai_provider_rejects_incomplete_refused_and_malformed_outputs(
    tmp_path,
    response,
    message,
):
    _init_repository(tmp_path, _dor_files())
    request = (
        ProjectAuditRuntime(tmp_path)
        .run(
            repository="repository:smoeberg/kodegenerator",
            provider=DORBaselineProjectAuditProvider(),
        )
        .report.request
    )
    provider = OpenAIProjectAuditProvider(
        api_key="secret-test-key",
        model="audit-model",
        transport=lambda *_args: response,
    )

    with pytest.raises(OpenAIProjectAuditResponseError, match=message):
        provider.audit_project(request)


def test_cli_writes_validated_baseline_report_and_openai_fails_closed(tmp_path):
    commit_sha = _init_repository(tmp_path, _dor_files())
    output = io.StringIO()
    errors = io.StringIO()

    exit_code = audit_main(
        (
            "audit",
            "--repository-root",
            str(tmp_path),
            "--output-dir",
            "audit-artifacts",
        ),
        environ={},
        stdout=output,
        stderr=errors,
    )

    assert exit_code == 0
    summary = json.loads(output.getvalue())
    assert summary["commit_sha"] == commit_sha
    assert summary["recommendation"] == "replan"
    assert Path(summary["json_artifact"]).is_file()
    assert errors.getvalue() == ""

    output = io.StringIO()
    errors = io.StringIO()
    exit_code = audit_main(
        (
            "audit",
            "--repository-root",
            str(tmp_path),
            "--provider",
            "openai",
            "--model",
            "audit-model",
            "--no-write",
        ),
        environ={},
        stdout=output,
        stderr=errors,
    )
    assert exit_code == 2
    assert "OPENAI_API_KEY must be configured" in errors.getvalue()
    assert output.getvalue() == ""
