"""Pure changelog and Markdown formatting for GitHub pull requests."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.github_pr_contracts import ChangelogEntry, PatchInfo


class GitHubPRFormatter:
    """Create deterministic PR text without transport or webhook dependencies."""

    def generate_changelog(
        self,
        patch: PatchInfo,
        wbs_summary: dict[str, Any],
        test_results: dict[str, Any],
    ) -> ChangelogEntry:
        version = wbs_summary.get("version", f"v{patch.timestamp.strftime('%Y%m%d')}")
        changes: list[str] = []
        features: list[str] = []
        fixes: list[str] = []
        breaking_changes: list[str] = []

        for item in wbs_summary.get("items", []):
            item_type = item.get("type", "").lower()
            description = item.get("description", item.get("title", ""))
            if "breaking" in item_type or "major" in item_type:
                breaking_changes.append(description)
            elif "feature" in item_type or "new" in item_type:
                features.append(description)
            elif "fix" in item_type or "bug" in item_type:
                fixes.append(description)
            else:
                changes.append(description)

        summary = test_results.get("summary", {})
        if summary.get("passed", 0) > 0:
            changes.append(f"All {summary.get('total', 0)} tests passed")
        elif summary.get("failed", 0) > 0 and summary.get("warnings", []):
            changes.append(f"{summary.get('failed', 0)} tests failed")

        return ChangelogEntry(
            version=version,
            timestamp=datetime.now(timezone.utc),
            author=patch.author,
            changes=changes,
            breaking_changes=breaking_changes,
            fixes=fixes,
            features=features,
        )

    def format_pr_body(
        self,
        patch: PatchInfo,
        wbs_summary: dict[str, Any],
        test_results: dict[str, Any],
        changelog: ChangelogEntry,
    ) -> str:
        lines = [
            f"# {wbs_summary.get('title', 'Generated Pull Request')}",
            "",
            wbs_summary.get("description", ""),
            "",
            "## Patch Information",
            "",
            f"- **Patch ID:** `{patch.patch_id}`",
            f"- **Author:** {patch.author}",
            f"- **Timestamp:** {patch.timestamp.isoformat()}",
            (
                "- **Files Changed:** "
                f"{', '.join(patch.files_changed) if patch.files_changed else 'None'}"
            ),
            "",
            "## Changelog",
            "",
            changelog.to_markdown(),
            "",
            "## Test Results",
            "",
            self.format_test_results(test_results),
            "",
            "## Work Breakdown Structure",
            "",
            self.format_wbs_summary(wbs_summary),
        ]
        return "\n".join(lines)

    def format_test_results(self, test_results: dict[str, Any]) -> str:
        summary = test_results.get("summary", {})
        passed = summary.get("passed", 0)
        failed = summary.get("failed", 0)
        skipped = summary.get("skipped", 0)
        total = summary.get("total", passed + failed + skipped)
        lines = [
            f"- **Total:** {total}",
            f"- **Passed:** {passed}",
            f"- **Failed:** {failed}",
            f"- **Skipped:** {skipped}",
        ]
        if failed > 0:
            lines.extend(["", "**Failed Tests:**"])
            lines.extend(
                "  - "
                f"{test.get('name', 'Unknown')}: "
                f"{test.get('message', 'No message')}"
                for test in test_results.get("failures", [])
            )
        return "\n".join(lines)

    def format_wbs_summary(self, wbs_summary: dict[str, Any]) -> str:
        if "items" not in wbs_summary:
            return "_No WBS items found_"
        return "\n".join(
            f"- [{item.get('type', '')}] **{item.get('id', '')}**: "
            f"{item.get('description', item.get('title', ''))} "
            f"({item.get('status', '')})"
            for item in wbs_summary["items"]
        )

    def generate_status_comment(
        self,
        patch: PatchInfo,
        wbs_summary: dict[str, Any],
        test_results: dict[str, Any],
    ) -> str:
        del wbs_summary
        summary = test_results.get("summary", {})
        passed = summary.get("passed", 0)
        total = summary.get("total", 0)
        test_line = (
            f"All {total} tests passed"
            if passed == total and total > 0
            else f"{passed}/{total} tests passed"
        )
        return "\n".join(
            [
                "## Patch Successfully Converted to Pull Request",
                "",
                f"- **Patch ID:** `{patch.patch_id}`",
                f"- **Author:** {patch.author}",
                "",
                test_line,
                "",
                "Ready for review!",
            ]
        )


__all__ = ["GitHubPRFormatter"]
