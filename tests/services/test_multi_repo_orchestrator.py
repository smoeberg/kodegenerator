from services.multi_repo_orchestrator import MultiRepoOrchestrator, SQLitePlanStateBackend


def configured(backend=None):
    o = MultiRepoOrchestrator(backend)
    o.register_repo("repo-a", {"remote_url": "https://github.com/acme/a", "base_branch": "main", "capabilities": ["domain"], "approval_required": True})
    o.register_repo("repo-b", {"remote_url": "https://github.com/acme/b", "base_branch": "main", "capabilities": ["api"], "approval_required": True})
    return o


def test_cross_repo_plan_preserves_dependency_order():
    o = configured()
    p = o.plan_cross_repo({"project_id": "p1", "repos": [{"repo_name": "repo-a", "task_id": "A1"}, {"repo_name": "repo-b", "task_id": "B1"}], "dependencies": [{"upstream_repo": "repo-a", "downstream_repo": "repo-b", "upstream_task_id": "A1", "downstream_task_id": "B1"}]})
    assert p.dependencies[0].upstream_repo == "repo-a"
    assert p.dependencies[0].downstream_repo == "repo-b"


def test_downstream_not_merge_ready_until_upstream_merged():
    o = configured()
    o.plan_cross_repo({"project_id": "p2", "repos": [{"repo_name": "repo-a", "task_id": "A1"}, {"repo_name": "repo-b", "task_id": "B1"}], "dependencies": [{"upstream_repo": "repo-a", "downstream_repo": "repo-b", "upstream_task_id": "A1", "downstream_task_id": "B1"}]})
    o.set_repo_state("p2", "repo-a", completed=True, sentinel_approved=True)
    o.set_repo_state("p2", "repo-b", completed=True, sentinel_approved=True)
    assert o.merge_ready("p2") == ["repo-a"]
    o.set_repo_state("p2", "repo-a", merged=True)
    assert o.merge_ready("p2") == ["repo-b"]


def test_branch_names_are_unique_per_task_and_repo():
    o = configured()
    o.plan_cross_repo({"project_id": "p3", "repos": [{"repo_name": "repo-a", "task_id": "same"}, {"repo_name": "repo-b", "task_id": "same"}]})
    a = o.create_repo_branch("repo-a", "same")
    b = o.create_repo_branch("repo-b", "same")
    assert a != b
    assert a == "swarm/repo-a/same"
    assert b == "swarm/repo-b/same"


def test_plan_persists_and_restores_after_restart():
    backend = SQLitePlanStateBackend(":memory:")
    o1 = configured(backend)
    o1.plan_cross_repo({"project_id": "p4", "repos": [{"repo_name": "repo-a", "task_id": "A1"}, {"repo_name": "repo-b", "task_id": "B1"}], "dependencies": [{"upstream_repo": "repo-a", "downstream_repo": "repo-b", "upstream_task_id": "A1", "downstream_task_id": "B1"}]})
    o1.create_repo_branch("repo-a", "A1")
    o2 = configured(backend)
    restored = o2.load_plan("p4")
    assert restored is not None
    assert restored.project_id == "p4"
    assert restored.repos["repo-a"].branch_name == "swarm/repo-a/A1"
    assert restored.dependencies[0].downstream_repo == "repo-b"
