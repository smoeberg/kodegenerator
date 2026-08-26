"""Architecture guards for the modular GitHub PR integration."""

from __future__ import annotations

import ast
from pathlib import Path

import services.github_pr_bot as facade

SERVICE_ROOT = Path(__file__).resolve().parents[2] / "services"
COMPONENTS = {
    "github_pr_api.py": 350,
    "github_pr_auth.py": 160,
    "github_pr_formatting.py": 200,
    "github_pr_webhooks.py": 475,
    "github_pr_workflow.py": 225,
}
PUBLIC_NAMES = {
    "AppAuthConfig",
    "AuthenticationError",
    "AuthMethod",
    "ChangelogEntry",
    "CommitInfo",
    "GitHubAPIError",
    "GitHubAuthenticator",
    "GitHubConfig",
    "GitHubPRBot",
    "GitHubPRBotError",
    "PatchInfo",
    "PRAction",
    "PRMetadata",
    "PRResult",
    "PRStatus",
    "RateLimitError",
    "TokenAuthConfig",
    "WebhookEventType",
    "WebhookParser",
    "WebhookPayload",
    "WebhookResponse",
    "WebhookVerificationError",
    "WebhookVerifier",
}


def _service_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("services.github_pr_")
    }


def test_public_facade_preserves_historical_imports() -> None:
    assert PUBLIC_NAMES <= set(facade.__all__)
    assert all(hasattr(facade, name) for name in PUBLIC_NAMES)


def test_facade_remains_a_small_composition_root() -> None:
    path = SERVICE_ROOT / "github_pr_bot.py"
    assert len(path.read_text(encoding="utf-8").splitlines()) <= 200

    tree = ast.parse(path.read_text(encoding="utf-8"))
    bot_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "GitHubPRBot"
    )
    methods = {
        node.name
        for node in bot_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert methods == {
        "__init__",
        "_load_signing_key",
        "_compute_fingerprint",
        "_sign_data",
    }


def test_components_stay_within_reviewable_line_budgets() -> None:
    for filename, limit in COMPONENTS.items():
        line_count = len(
            (SERVICE_ROOT / filename).read_text(encoding="utf-8").splitlines()
        )
        assert line_count <= limit, f"{filename} grew to {line_count} lines"


def test_components_depend_only_on_transport_neutral_contracts() -> None:
    allowed = {"services.github_pr_contracts"}
    for filename in COMPONENTS:
        assert _service_imports(SERVICE_ROOT / filename) <= allowed


def test_service_modules_do_not_import_fastapi() -> None:
    paths = [SERVICE_ROOT / "github_pr_bot.py"] + [
        SERVICE_ROOT / filename for filename in COMPONENTS
    ]
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert "from fastapi" not in source
        assert "import fastapi" not in source
