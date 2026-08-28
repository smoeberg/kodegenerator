"""Provider-backed executors for the software-factory pipeline.

AI stages require an explicitly configured LLM and validate every response
against a strict schema. Missing configuration fails closed.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Protocol

from generation.project_renderer import ProjectRenderer
from generation.project_spec import ArchitectureKind, ProjectDefinition
from generation.scaffold_engine import ScaffoldEngine, ScaffoldFile, ScaffoldPlan
from phase4.agent_registry import (
    AgentRegistry,
    AgentRole,
    AgentVersion,
    Capability,
)
from phase4.context_packet.models import ContextItem
from phase4.implementation_agent import ChangeBudget, ImplementationAgentRuntime
from phase4.verification.selector import VerifierSelector
from phase6.execution.process import BubblewrapProcessAdapter
from phase6.execution.sandbox import (
    ExecutionLimits,
    ExecutionOutcome,
    ExecutionSecurityContext,
    ExecutionSpec,
    SandboxRegistry,
)
from services.git_pr_publisher import GitPRPublisher
from services.github_pr_contracts import PatchInfo, PRMetadata, PRStatus


class PipelineExecutorConfigurationError(RuntimeError):
    pass


class TaskExecutor(Protocol):
    task_type: str

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class DeployService(Protocol):
    def deploy(
        self,
        repository: str,
        project_name: str,
        environment: str,
        target: str,
        release: str | None = None,
        workspace: str | None = None,
    ) -> dict[str, str]: ...


class DockerDeployService:
    """Build and push generated source as a Docker image."""

    def __init__(self, registry: str | None = None) -> None:
        self._registry = (
            (registry or os.getenv("DOR_PIPELINE_DOCKER_REGISTRY", ""))
            .strip()
            .rstrip("/")
        )

    @staticmethod
    def _safe_name(value: str) -> str:
        value = value.strip().lower()
        safe = "".join(
            char if char.isalnum() or char in "._-" else "-" for char in value
        )
        return safe.strip(".-") or "app"

    @staticmethod
    def _write_files(root: Path, files: list[Mapping[str, str]]) -> None:
        for item in files:
            path = str(item.get("path", ""))
            if (
                not path
                or PurePosixPath(path).is_absolute()
                or ".." in PurePosixPath(path).parts
            ):
                raise ValueError(f"invalid generated file path: {path!r}")
            destination = root.joinpath(*PurePosixPath(path).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(str(item.get("content", "")), encoding="utf-8")

        dockerfile = root / "Dockerfile"
        if not dockerfile.exists():
            raise ValueError("generated files must contain a Dockerfile")

    def deploy(
        self,
        files: list[Mapping[str, str]],
        project_name: str,
        environment: str,
        target: str,
    ) -> dict[str, str]:
        project = self._safe_name(project_name)
        env = self._safe_name(environment)
        repository = f"{self._registry}/{project}" if self._registry else project
        image_tag = f"{repository}:{env}"

        with tempfile.TemporaryDirectory(prefix="dor-deploy-") as temp_dir:
            root = Path(temp_dir)
            self._write_files(root, files)
            build = subprocess.run(
                ["docker", "build", "-t", image_tag, str(root)],
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
            )
            if build.returncode:
                raise RuntimeError(f"docker build failed: {build.stderr[-4000:]}")

            push = subprocess.run(
                ["docker", "push", image_tag],
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
            )
            if push.returncode:
                raise RuntimeError(f"docker push failed: {push.stderr[-4000:]}")

        deployed_at = datetime.now(timezone.utc).isoformat()
        base_url = os.getenv("DOR_PIPELINE_DEPLOY_URL", "").rstrip("/")
        if base_url:
            url = base_url.format(
                project_name=project,
                environment=env,
                target=target,
                image_tag=image_tag,
            )
        else:
            url = target

        return {
            "deployed_at": deployed_at,
            "image_tag": image_tag,
            "url": url,
        }


class GitDockerDeployBackend(DockerDeployService):
    """Checkout a governed Git release, build/push it, and deploy with Compose."""

    def __init__(self, runner: Any = subprocess.run) -> None:
        super().__init__()
        self._run = runner

    def _command(self, argv: list[str], *, cwd: Path, timeout: int = 900) -> str:
        result = self._run(
            argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
        )
        if result.returncode:
            raise RuntimeError(f"{' '.join(argv)} failed: {result.stderr[-4000:]}")
        return result.stdout.strip()

    def deploy(
        self,
        repository: str,
        project_name: str,
        environment: str,
        target: str,
        release: str | None = None,
        workspace: str | None = None,
    ) -> dict[str, str]:
        if not repository:
            raise ValueError("deploy requires a git repository")
        temporary = (
            tempfile.TemporaryDirectory(prefix="dor-deploy-")
            if workspace is None
            else None
        )
        root = Path(temporary.name if temporary else workspace).resolve()
        try:
            if (root / ".git").exists():
                self._command(
                    ["git", "fetch", "--tags", "--prune", "origin"],
                    cwd=root,
                    timeout=300,
                )
            else:
                root.parent.mkdir(parents=True, exist_ok=True)
                self._command(
                    ["git", "clone", repository, str(root)],
                    cwd=root.parent,
                    timeout=300,
                )
            ref = release or self._command(
                ["git", "describe", "--tags", "--abbrev=0"], cwd=root, timeout=300
            )
            self._command(["git", "checkout", "--force", ref], cwd=root, timeout=300)
            self._command(["git", "clean", "-fdx"], cwd=root, timeout=300)
            commit_sha = self._command(
                ["git", "rev-parse", "HEAD"], cwd=root, timeout=300
            )
            repository_name = (
                f"{self._registry}/{self._safe_name(project_name)}"
                if self._registry
                else self._safe_name(project_name)
            )
            image_tag = (
                f"{repository_name}:{self._safe_name(environment)}-{commit_sha[:12]}"
            )
            self._command(["docker", "build", "-t", image_tag, "."], cwd=root)
            self._command(["docker", "push", image_tag], cwd=root)
            compose = root / (
                target if target.endswith((".yml", ".yaml")) else "docker-compose.yml"
            )
            if not compose.exists():
                raise ValueError(f"compose file not found: {compose}")
            result = self._run(
                [
                    "docker",
                    "compose",
                    "-f",
                    str(compose),
                    "up",
                    "-d",
                    "--remove-orphans",
                ],
                cwd=root,
                env={**os.environ, "DOR_IMAGE_TAG": image_tag},
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
            )
            if result.returncode:
                raise RuntimeError(
                    f"docker compose deployment failed: {result.stderr[-4000:]}"
                )
            base_url = os.getenv("DOR_PIPELINE_DEPLOY_URL", "").rstrip("/")
            url = (
                base_url.format(
                    project_name=self._safe_name(project_name),
                    environment=self._safe_name(environment),
                    target=target,
                    image_tag=image_tag,
                )
                if base_url
                else target
            )
            return {
                "deployed_at": datetime.now(timezone.utc).isoformat(),
                "image_tag": image_tag,
                "url": url,
                "commit_sha": commit_sha,
            }
        finally:
            if temporary:
                temporary.cleanup()


class ArchitectureExecutor:
    """Create a verified deterministic scaffold plan with ``ScaffoldEngine``."""

    task_type = "generate_architecture"
    component = "generation/scaffold_engine"

    def __init__(self, backend: ScaffoldEngine | None = None) -> None:
        self._backend = backend or ScaffoldEngine()

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_name = str(
            payload.get("project_name") or payload.get("name") or "generated"
        )
        project = ProjectDefinition(
            name=raw_name.strip().lower().replace(" ", "-"),
            architecture=ArchitectureKind(
                payload.get("architecture_kind", "hexagonal")
            ),
            language=str(payload.get("language", "python")),
            api=str(payload.get("api", "fastapi")),
            database=str(payload.get("database", "postgresql")),
        )
        plan = self._backend.generate(project)
        if violations := plan.validate():
            raise ValueError(f"architecture scaffold verification failed: {violations}")
        return {
            "status": "success",
            "component": self.component,
            "architecture": {
                "project": project.model_dump(mode="json"),
                "files": [asdict(item) for item in plan.files],
                "architecture_contract": list(plan.architecture_contract),
                "fingerprint": plan.fingerprint,
            },
        }


class ContractsExecutor:
    """Render the verified scaffold plan through ``ProjectRenderer``."""

    task_type = "generate_contracts"
    component = "generation/project_renderer"

    def __init__(self, backend: ProjectRenderer | None = None) -> None:
        self._backend = backend or ProjectRenderer()

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        architecture = payload.get("architecture") or payload.get("context", {}).get(
            "architecture"
        )
        if not isinstance(architecture, dict):
            raise ValueError("contracts payload requires architecture output")
        project = ProjectDefinition.model_validate(architecture["project"])
        plan = ScaffoldPlan(
            project=project,
            files=tuple(ScaffoldFile(**item) for item in architecture["files"]),
            architecture_contract=tuple(architecture["architecture_contract"]),
        )
        rendered = self._backend.render(plan)
        return {
            "status": "success",
            "component": self.component,
            "contracts": {
                "files": [asdict(item) for item in rendered.files],
                "manifest": list(rendered.manifest),
                "fingerprint": rendered.fingerprint,
            },
        }


class CodeExecutor:
    """Produce a governed patch proposal with ``ImplementationAgentRuntime``."""

    task_type = "generate_code"
    component = "phase4/implementation_agent"

    def __init__(self, backend: ImplementationAgentRuntime | None = None) -> None:
        self._backend = backend

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        backend = self._backend
        if backend is None:
            from api.dependencies import get_implementation_agent_runtime

            backend = get_implementation_agent_runtime()
        context = payload.get("context", {})
        allowed_paths = tuple(
            payload.get("allowed_paths") or context.get("allowed_paths") or ()
        )
        if not allowed_paths:
            raise ValueError("code payload requires explicit allowed_paths")
        items = tuple(
            ContextItem(
                source="pipeline", key=str(key), value=value, provenance="workflow"
            )
            for key, value in sorted(context.items())
        )
        run = backend.run(
            organization_id=str(
                payload.get("organization_id") or context.get("organization_id")
            ),
            resource=str(payload.get("resource") or context.get("resource")),
            instruction=str(
                payload.get("instruction") or "Implement the approved contracts"
            ),
            allowed_paths=allowed_paths,
            context_items=items,
            budget=ChangeBudget(
                max_files=int(payload.get("max_files", len(allowed_paths))),
                max_changed_lines=int(payload.get("max_changed_lines", 1000)),
            ),
            idempotency_key=str(payload.get("task_id") or payload.get("workflow_id")),
        )
        return {
            "status": "success",
            "component": self.component,
            "code": {
                "proposal_id": run.proposal.proposal_id,
                "unified_diff": run.proposal.unified_diff,
            },
        }


class TestGeneratorExecutor:
    """Select independent test verifiers through ``VerifierSelector``."""

    task_type = "generate_tests"
    component = "phase4/verification"

    def __init__(self, backend: VerifierSelector | None = None) -> None:
        self._backend = backend or _default_verifier_selector()

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        selection = self._backend.select(
            claim_id=str(payload.get("claim_id") or payload.get("task_id")),
            policy_id=str(payload.get("verification_policy_id", "pipeline.tests.v1")),
            quorum_size=int(payload.get("quorum_size", 1)),
            capability=payload.get("verifier_capability"),
        )
        return {
            "status": "success",
            "component": self.component,
            "tests": asdict(selection),
        }


TestsExecutor = TestGeneratorExecutor


def _default_verifier_selector() -> VerifierSelector:
    """Build the process-local verifier registry used by the pipeline worker."""
    registry = AgentRegistry()
    version = AgentVersion(1, 0, 0)
    registry.register(
        agent_type="pipeline-test-verifier",
        instance_id="pipeline-default",
        version=version,
        role=AgentRole.VERIFIER,
        capabilities=(Capability.create("pipeline.tests", version),),
        actor="pipeline-runtime",
    )
    return VerifierSelector(registry)


class RunTestsExecutor:
    """Execute the test command through the Phase 6 ``SandboxRegistry``."""

    task_type = "run_tests"

    def __init__(self, backend: SandboxRegistry | None = None) -> None:
        self._backend = backend

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        root = Path(
            payload.get("workspace") or os.getenv("DOR_PIPELINE_WORKSPACE", ".")
        ).resolve()
        command = shlex.split(
            os.getenv("DOR_PIPELINE_TEST_COMMAND", "python -m pytest -q")
        )
        backend = self._backend
        if backend is None:
            executable = shutil.which(command[0])
            if executable is None:
                raise PipelineExecutorConfigurationError(
                    f"test executable is unavailable: {command[0]}"
                )
            command[0] = executable
            adapter = BubblewrapProcessAdapter(
                allowed_executables=(executable,),
            )
            backend = SandboxRegistry({adapter.adapter_id: adapter})
        spec = ExecutionSpec(
            execution_id=str(payload.get("task_id") or payload.get("workflow_id")),
            adapter_id=str(payload.get("sandbox_adapter_id", "bubblewrap-process")),
            argv=tuple(command),
            security=ExecutionSecurityContext(
                organization_id=str(payload.get("organization_id")),
                principal_id=str(payload.get("actor_id")),
                actor_id=str(payload.get("actor_id")),
                capabilities=("pipeline.run_tests",),
            ),
            limits=ExecutionLimits(wall_time_seconds=600, cpu_time_seconds=600),
            writable_paths=(str(root),),
            working_directory=str(root),
        )
        completed = backend.execute(spec)
        if completed.outcome is not ExecutionOutcome.SUCCEEDED:
            raise RuntimeError(completed.error or "pipeline test execution failed")
        return {
            "status": "success",
            "test_run": {
                "status": "passed",
                "component": "phase6",
                "output": completed.output,
            },
        }


class DeployExecutor(TaskExecutor):
    task_type = "deploy"

    def __init__(self, backend: DeployService | None = None):
        self._backend = backend or GitDockerDeployBackend()

    def execute(self, data: dict[str, Any]) -> dict[str, Any]:
        repository = data.get("repository") or data.get("repo_url")
        project_name = data.get("project_name")
        environment = data.get("environment")
        target = data.get("target")
        if not repository or not project_name or not environment or not target:
            raise ValueError(
                "deploy payload requires repository, project_name, "
                "environment and target"
            )

        deployment = self._backend.deploy(
            repository,
            project_name,
            environment,
            target,
            data.get("release"),
            data.get("workspace"),
        )
        return {
            "status": "success",
            "deployment": {
                "component": "services/docker",
                **deployment,
            },
        }


class ReleaseExecutor:
    task_type = "release"

    def __init__(self, backend: GitPRPublisher | None = None) -> None:
        self._backend = backend

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        backend = self._backend
        if backend is None:
            backend = GitPRPublisher(
                owner=os.environ["DOR_PIPELINE_GITHUB_OWNER"],
                repo=os.environ["DOR_PIPELINE_GITHUB_REPO"],
                token=os.environ["GITHUB_PERSONAL_ACCESS_TOKEN"],
                repo_root=Path(os.environ["DOR_PIPELINE_GIT_REPO_ROOT"]),
            )
        authority_grant = payload.get("authority_grant")
        if authority_grant is None:
            raise ValueError("release payload requires a verified authority_grant")
        patch = PatchInfo(**payload["patch"])
        metadata = PRMetadata(**payload["pr_metadata"])
        result = backend.publish_patch_as_pr(
            patch=patch,
            pr_metadata=metadata,
            wbs_summary=payload.get("wbs_summary"),
            test_results=payload.get("test_results"),
            authority_grant=authority_grant,
            push_remote=bool(payload.get("push_remote", True)),
        )
        if result.status is not PRStatus.CREATED:
            raise RuntimeError(
                "release PR publication failed: " + "; ".join(result.errors)
            )
        return {
            "status": "success",
            "release": {
                "component": "services/release",
                "workflow_id": payload.get("workflow_id"),
                "pr_number": result.pr_number,
                "pr_url": result.pr_url,
                "commit_hash": result.commit_hash,
            },
        }


def build_pipeline_executor_registry() -> dict[str, Any]:
    executors = [
        ArchitectureExecutor(),
        ContractsExecutor(),
        CodeExecutor(),
        TestGeneratorExecutor(),
        RunTestsExecutor(),
        DeployExecutor(),
        ReleaseExecutor(),
    ]
    return {executor.task_type: executor for executor in executors}
