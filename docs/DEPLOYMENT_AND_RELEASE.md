# Deployment and release operations

This guide describes the implemented Docker deployment and GitHub pull-request
publication boundaries. It is written for operators wiring the software-factory
pipeline into CI/CD.

## Responsibility boundary

| Component | Performs | Does not perform |
|---|---|---|
| `DeployExecutor` | Validates a deploy payload and delegates to `DockerDeployService` | Approve a release, run a container, or configure registry credentials |
| `DockerDeployService` | Materializes generated files, builds an image, and pushes it | Create registry accounts, deploy to Kubernetes, or expose secrets to the payload |
| `ReleaseExecutor` | Emits the terminal release artifact for an approved workflow | Create, approve, or merge a pull request |
| `GitPRPublisher` | Creates an isolated worktree, applies a verified patch, commits, pushes, creates a PR, and comments with status | Merge the PR or bypass branch protection and authority gates |

`ReleaseExecutor` and `GitPRPublisher` are deliberately separate. A caller must
publish the verified patch before it records the terminal release result.

## DeployExecutor

### Preconditions

- Docker CLI and daemon are available to the worker.
- The worker has authenticated to the target registry before execution, for
  example with `docker login` or a credential helper.
- Generated files contain a `Dockerfile`.
- The worker has `pipeline.deploy` authority through the canonical
  `TaskExecutionService` boundary.
- Secrets are injected into the worker environment or credential store. They
  must never be placed in the task payload, generated files, image build output,
  or pipeline state.

### Configuration

| Variable | Required | Purpose | Example |
|---|---:|---|---|
| `DOR_PIPELINE_DOCKER_REGISTRY` | Production | Registry/repository prefix; omitted for a local Docker repository name | `ghcr.io/acme` |
| `DOR_PIPELINE_DEPLOY_URL` | No | Result URL template. Available fields: `project_name`, `environment`, `target`, `image_tag` | `https://{project_name}-{environment}.example.com` |
| `DOR_PIPELINE_WORKSPACE` | Test stage only | Default workspace used by `RunTestsExecutor` | `/srv/dor/workspace` |
| `DOR_PIPELINE_TEST_COMMAND` | No | Test command executed before deployment | `python -m pytest -q` |

Registry-specific credentials are external to DOR:

- GHCR: `GITHUB_TOKEN` or a fine-grained token with package write permission.
- Docker Hub: `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`.
- Cloud registries: use their workload identity or short-lived credential helper.

Do not pass these values in `files`, `context`, task metadata, or PR bodies.

### Input and output

```python
from execution.pipeline_executors import DeployExecutor

result = DeployExecutor().execute(
    {
        "project_name": "orders-api",
        "environment": "staging",
        "target": "https://orders-staging.example.com",
        "files": [
            {"path": "Dockerfile", "content": "FROM python:3.12-slim\nCOPY . /app\n"},
            {"path": "app.py", "content": "print('ready')\n"},
        ],
    }
)
```

Successful result:

```json
{
  "status": "success",
  "deployment": {
    "component": "services/docker",
    "deployed_at": "2026-08-28T09:00:00+00:00",
    "image_tag": "ghcr.io/acme/orders-api:staging",
    "url": "https://orders-staging.example.com"
  }
}
```

### Workflow

1. `DeployExecutor` checks `files`, `project_name`, `environment`, and `target`.
2. `DockerDeployService` normalizes the project and environment for an image tag.
3. Files are written to a fresh temporary directory. Absolute paths and `..`
   traversal are rejected.
4. A supplied `Dockerfile` is required.
5. `docker build -t <image> <temporary-directory>` runs with a 15-minute timeout.
6. `docker push <image>` runs with a 15-minute timeout.
7. The temporary directory is removed and deployment metadata is returned.

The returned URL is metadata. The current backend pushes an image; it does not
start a workload. Use an injected `DeployService` implementation for Kubernetes,
ECS, Nomad, or another runtime.

### Troubleshooting

| Symptom | Likely cause | Resolution |
|---|---|---|
| `deploy payload requires ...` | Missing or empty required field | Validate the synthesized task payload before dispatch |
| `invalid generated file path` | Absolute or traversal path | Emit canonical relative POSIX paths only |
| `generated files must contain a Dockerfile` | Code-generation output is incomplete | Add a Dockerfile generation contract/gate |
| `docker: command not found` | Worker image lacks Docker CLI | Install the CLI or inject another `DeployService` |
| Cannot connect to daemon | Socket/daemon unavailable | Mount the intended socket securely or use a remote builder |
| `docker push failed: denied` | Missing login or package permission | Refresh the credential outside DOR and verify repository scope |
| Build timeout | Build exceeds 900 seconds | Optimize layers/build context or use an injected remote builder |
| Unexpected image name | Input was normalized | Use lowercase alphanumerics, `.`, `_`, and `-` in names |

## ReleaseExecutor and GitPRPublisher

### Credentials and Git prerequisites

`GitPRPublisher` currently accepts a token constructor argument. Read it from a
secret manager or `GITHUB_PERSONAL_ACCESS_TOKEN`; never hard-code it. The token
needs repository content write permission and pull-request write permission.
Branch-protection rules still apply.

The worker also needs:

- a clean local Git repository with the expected base branch;
- an `origin` remote that the Git credential helper can push to;
- a unique branch name; and
- a verified, unexpired `VerifiedAuthorityGrant` when authority is supplied.

API authentication and Git push authentication are distinct. Passing a token to
`GitPRPublisher` authenticates GitHub API calls; configure the Git credential
helper or authenticated remote separately for `git push`.

### Step-by-step release process

1. Complete code generation, tests, deployment, and the release approval gate.
2. Construct `PatchInfo` from the exact verified unified diff.
3. Construct `PRMetadata` with a unique head branch and explicit base branch.
4. Resolve a verified, non-expired authority grant for publication.
5. Call `GitPRPublisher.publish_patch_as_pr()`.
6. The publisher validates the patch and creates an isolated Git worktree.
7. It applies the patch, stages all changes, and creates an attributed commit.
8. With `push_remote=True`, it pushes the head branch to `origin`.
9. It creates the GitHub PR, applies configured metadata, and posts a status comment.
10. CI and human/automated review enforce branch protection. The publisher does
    not merge the PR.
11. After the approved release workflow is complete, call `ReleaseExecutor` to
    materialize the terminal release record.

### Publisher example

```python
import os
from pathlib import Path

from services.git_pr_publisher import GitPRPublisher
from services.github_pr_contracts import PatchInfo, PRMetadata

publisher = GitPRPublisher(
    owner="acme",
    repo="orders-api",
    token=os.environ["GITHUB_PERSONAL_ACCESS_TOKEN"],
    repo_root=Path("/srv/repos/orders-api"),
)

result = publisher.publish_patch_as_pr(
    patch=PatchInfo(
        patch_id="task-42",
        patch_content="--- a/README.md\n+++ b/README.md\n@@ -1 +1,2 @@\n # API\n+Ready\n",
        author="DOR Release Worker",
        summary="Prepare the verified staging release",
        files_changed=["README.md"],
    ),
    pr_metadata=PRMetadata(
        title="feat(release): prepare orders-api staging",
        description="Verified software-factory output",
        branch="dor/task-42-orders-staging",
        base_branch="main",
        labels=["release", "automated"],
        reviewers=["platform-team"],
        draft=False,
    ),
    wbs_summary={
        "title": "Orders API staging release",
        "version": "v1.4.0",
        "items": [
            {"id": "task-42", "type": "feature", "description": "Release staging image", "status": "done"}
        ],
    },
    test_results={"summary": {"total": 128, "passed": 128, "failed": 0, "skipped": 0}},
    authority_grant=verified_grant,
)
```

Release marker input/output:

```python
from execution.pipeline_executors import ReleaseExecutor

release = ReleaseExecutor().execute(
    {"workflow_id": "workflow-123", "pr_url": result.pr_url, "commit_hash": result.commit_hash}
)
```

Only `workflow_id` is currently materialized by `ReleaseExecutor`; retain the
`PRResult` in the caller's audit/evidence store.

### Expected pull-request format

The PR title is exactly `PRMetadata.title`. The generated body contains:

```markdown
# <WBS title or Generated Pull Request>

<WBS description>

## Patch Information
- Patch ID, author, timestamp, files changed

## Changelog
- Breaking changes, features, fixes, and other changes

## Test Results
- Total, passed, failed, skipped, and failure details

## Work Breakdown Structure
- Typed WBS items with ID, description, and status
```

The commit message contains the PR title, patch task ID, author, and patch
summary. A successful `PRResult` has status `created`, PR number/URL, commit
hash, changelog, and publication metadata.

### Release troubleshooting

| Symptom | Likely cause | Resolution |
|---|---|---|
| `Not a valid git repository` | `repo_root` is wrong | Point to a checkout containing `.git` |
| Worktree creation fails | Branch exists or base is missing | Fetch the base and use a unique head branch |
| Patch validation/application fails | Diff is empty, malformed, or stale | Regenerate against the exact base SHA |
| Authority error | Grant is unverified or expired | Obtain a new bounded grant; never bypass the check |
| `git push` authentication fails | Git remote lacks credentials | Configure a credential helper or authenticated remote |
| GitHub API 401/403 | Token expired or lacks permission | Rotate token and verify contents/PR scopes |
| PR is created but not merged | Expected behavior | Wait for required checks/reviews and use the governed merge process |
| `PRResult.status == failed` | Lifecycle exception was captured | Inspect `errors`; secrets are not intentionally included, but handle logs as sensitive |

## Operational use cases

- Push a generated service image to GHCR, then let Argo CD deploy the immutable tag.
- Publish an implementation-agent patch as a draft PR for human review.
- Use a fake/injected `DeployService` in tests without invoking Docker.
- Replace `DockerDeployService` with a Kubernetes backend while preserving the
  stable `DeployExecutor` payload/result contract.

