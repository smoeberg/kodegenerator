# Pipeline Executors Documentation

Dette dokument beskriver arkitekturen, snitfladerne og konfigurationen for software-factory pipeline executors i `execution/pipeline_executors.py`, herunder **DeployExecutor** og **ReleaseExecutor**.

---

## 1. DeployExecutor (`deploy`)

`DeployExecutor` er ansvarlig for at udrulle kildekode og services til et målmiljø vha. Git og Docker.

### Funktionalitet:
- **Git-integration**:
  - Kloner eller checkout'er angivet repository (understøtter tag, release-version eller branch) i et isoleret arbejdsområde.
  - Henter commit SHA til entydig sporing og image-tagging.
- **Docker-integration**:
  - Bygger Docker-images (`docker build -t <tag> .`).
  - Pusher det taggede image til det konfigurerede container registry (`docker push <tag>`).
  - Udruller services via Docker Compose (`docker compose -f <target> up -d`) med dynamisk injicerede image-tags.
- **Fejlhåndtering & Rollback**:
  - Ved fejl rulles der automatisk tilbage til forrige version, hvis `DOR_PIPELINE_ROLLBACK_IMAGE` eller `DOR_PIPELINE_PREVIOUS_IMAGE_TAG` er defineret.

### Konfigurationsparametre (Payload):
```json
{
  "repository": "https://github.com/smoeberg/kodegenerator.git",
  "project_name": "kodegenerator",
  "environment": "staging",
  "target": "docker-compose.yml",
  "release": "v1.2.0",
  "workspace": "/sti/til/workspace"
}
```

---

## 2. ReleaseExecutor (`release`)

`ReleaseExecutor` automatiserer udgivelsesprocessen og Pull Request-oprettelse via `GitPRPublisher` mod GitHub.

### Funktionalitet:
- **Worktree-isolering & Patches**:
  - Modtager genererede kode-ændringer og patches (`PatchInfo`).
  - Etablerer ephemeral Git-worktrees til at validere og committe ændringer.
- **GitHub Pull Request & Metadata**:
  - Automatisk oprettelse af release-branches (f.eks. `release/v1.2.0`).
  - Opretter Pull Requests med specificerede labels, assignees, reviewers og changelog-beskrivelse.
- **Sikkerhed & Validering**:
  - Fail-closed validering på repo-koordinater og tokens (`GITHUB_TOKEN` / `GH_TOKEN`).

### Konfigurationsparametre (Payload):
```json
{
  "owner": "smoeberg",
  "repo": "kodegenerator",
  "token": "ghp_...",
  "version": "1.2.0",
  "title": "Release v1.2.0",
  "description": "Automatisk genereret release PR for version 1.2.0",
  "branch": "release/v1.2.0",
  "base_branch": "main",
  "labels": ["release", "automated"],
  "patch_content": "diff --git ...",
  "files_changed": ["services/core.py"]
}
```

---

## 3. Miljøvariable

| Variabel | Beskrivelse | Standardværdi |
|---|---|---|
| `GITHUB_TOKEN` | GitHub API / Clone Token | (Påkrævet for private repos / PRs) |
| `DOR_PIPELINE_DOCKER_REGISTRY` | Container Registry URL / Namespace | `ghcr.io/smoeberg` |
| `DOR_PIPELINE_ROLLBACK_IMAGE` | Image tag ved rollback | Ingen |
| `DOR_PIPELINE_DEPLOY_URL` | Formatstreng til URL endpoint | Ingen |
| `DOR_PIPELINE_MODEL` | LLM model for AI-stadier | Ingen |
