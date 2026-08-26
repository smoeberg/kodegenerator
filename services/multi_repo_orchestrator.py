"""Cross-repository planning and merge gating for the DOR swarm."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
import sqlite3
from threading import RLock
from typing import Any, Optional, Protocol


@dataclass(frozen=True)
class RepoConfig:
    repo_name: str
    remote_url: str
    base_branch: str = "main"
    capabilities: tuple[str, ...] = ()
    approval_required: bool = True


@dataclass(frozen=True)
class CrossRepoDependency:
    upstream_repo: str
    downstream_repo: str
    upstream_task_id: str
    downstream_task_id: str


@dataclass
class RepoWork:
    repo_name: str
    task_id: str
    branch_name: Optional[str] = None
    completed: bool = False
    sentinel_approved: bool = False
    gate_open: bool = True
    merged: bool = False


@dataclass
class CrossRepoPlan:
    project_id: str
    repos: dict[str, RepoWork]
    dependencies: list[CrossRepoDependency] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "repos": {k: vars(v).copy() for k, v in self.repos.items()},
            "dependencies": [vars(d).copy() for d in self.dependencies],
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CrossRepoPlan":
        return cls(
            project_id=data["project_id"],
            repos={k: RepoWork(**v) for k, v in data["repos"].items()},
            dependencies=[CrossRepoDependency(**d) for d in data.get("dependencies", [])],
            created_at=datetime.fromisoformat(data["created_at"]),
        )


class PlanStateBackend(Protocol):
    def save_plan(self, plan: CrossRepoPlan) -> None: ...
    def load_plan(self, project_id: str) -> Optional[CrossRepoPlan]: ...


class SQLitePlanStateBackend:
    """Small additive persistence backend suitable beside SQLiteTaskQueue."""
    def __init__(self, path: str = ":memory:") -> None:
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS multi_repo_plans (project_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        self._db.commit()
        self._lock = RLock()

    def save_plan(self, plan: CrossRepoPlan) -> None:
        import json
        payload = json.dumps(plan.to_dict(), sort_keys=True)
        with self._lock:
            self._db.execute("INSERT INTO multi_repo_plans(project_id,payload) VALUES(?,?) ON CONFLICT(project_id) DO UPDATE SET payload=excluded.payload", (plan.project_id, payload))
            self._db.commit()

    def load_plan(self, project_id: str) -> Optional[CrossRepoPlan]:
        import json
        with self._lock:
            row = self._db.execute("SELECT payload FROM multi_repo_plans WHERE project_id=?", (project_id,)).fetchone()
        return CrossRepoPlan.from_dict(json.loads(row[0])) if row else None


class MultiRepoOrchestrator:
    def __init__(self, backend: Optional[PlanStateBackend] = None) -> None:
        self._repos: dict[str, RepoConfig] = {}
        self._plans: dict[str, CrossRepoPlan] = {}
        self._backend = backend
        self._lock = RLock()

    def register_repo(self, repo_name: str, config: dict[str, Any] | RepoConfig) -> RepoConfig:
        cfg = config if isinstance(config, RepoConfig) else RepoConfig(
            repo_name=repo_name, remote_url=config["remote_url"], base_branch=config.get("base_branch", "main"),
            capabilities=tuple(config.get("capabilities", ())), approval_required=config.get("approval_required", True))
        with self._lock: self._repos[repo_name] = cfg
        return cfg

    def plan_cross_repo(self, project: dict[str, Any]) -> CrossRepoPlan:
        project_id = str(project["project_id"])
        repos_input = project.get("repos", [])
        works: dict[str, RepoWork] = {}
        for item in repos_input:
            repo = item["repo_name"]
            if repo not in self._repos: raise ValueError(f"unregistered repository: {repo}")
            works[repo] = RepoWork(repo, str(item["task_id"]))
        deps: list[CrossRepoDependency] = []
        for edge in project.get("dependencies", []):
            deps.append(CrossRepoDependency(edge["upstream_repo"], edge["downstream_repo"], str(edge["upstream_task_id"]), str(edge["downstream_task_id"])))
        plan = CrossRepoPlan(project_id, works, deps)
        with self._lock:
            self._plans[project_id] = plan
            if self._backend: self._backend.save_plan(plan)
        return plan

    def create_repo_branch(self, repo: str, task_id: str) -> str:
        if repo not in self._repos: raise ValueError(f"unregistered repository: {repo}")
        safe_repo = re.sub(r"[^a-zA-Z0-9._-]+", "-", repo).strip("-")
        safe_task = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(task_id)).strip("-")
        branch = f"swarm/{safe_repo}/{safe_task}"
        with self._lock:
            for plan in self._plans.values():
                work = plan.repos.get(repo)
                if work and work.task_id == str(task_id):
                    work.branch_name = branch
                    if self._backend: self._backend.save_plan(plan)
        return branch

    def set_repo_state(self, project_id: str, repo: str, *, completed: Optional[bool] = None, sentinel_approved: Optional[bool] = None, gate_open: Optional[bool] = None, merged: Optional[bool] = None) -> CrossRepoPlan:
        plan = self._get_plan(project_id); work = plan.repos[repo]
        for name, value in (("completed", completed), ("sentinel_approved", sentinel_approved), ("gate_open", gate_open), ("merged", merged)):
            if value is not None: setattr(work, name, value)
        if self._backend: self._backend.save_plan(plan)
        return plan

    def merge_ready(self, project_id: str) -> list[str]:
        plan = self._get_plan(project_id)
        ready: list[str] = []
        for repo, work in plan.repos.items():
            if work.merged or not work.completed or not work.gate_open: continue
            if self._repos[repo].approval_required and not work.sentinel_approved: continue
            blocked = any(d.downstream_repo == repo and not plan.repos[d.upstream_repo].merged for d in plan.dependencies)
            if not blocked: ready.append(repo)
        return ready

    def load_plan(self, project_id: str) -> Optional[CrossRepoPlan]:
        if self._backend:
            plan = self._backend.load_plan(project_id)
            if plan: self._plans[project_id] = plan
            return plan
        return self._plans.get(project_id)

    def _get_plan(self, project_id: str) -> CrossRepoPlan:
        plan = self.load_plan(project_id)
        if plan is None: raise KeyError(project_id)
        return plan
