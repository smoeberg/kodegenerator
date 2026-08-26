"""Repository Drift Detector for detecting human code changes and triggering agent realignment."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class DriftReport:
    has_drift: bool
    modified_files: List[str]
    latest_commit: str
    message: str


class RepositoryDriftDetector:
    """Detects out-of-band human code changes in the repository."""

    def __init__(self, repo_path: str = ".") -> None:
        self.repo_path = repo_path

    def get_current_head(self) -> str:
        """Get the latest git commit hash."""
        try:
            result = subprocess.run(
                ["git", "-C", self.repo_path, "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except Exception:
            return "unknown"

    def check_drift(self, last_known_commit: str) -> DriftReport:
        """Check if repository has changed since agent's last known checkpoint."""
        current_head = self.get_current_head()
        if current_head == "unknown" or current_head == last_known_commit:
            return DriftReport(
                has_drift=False,
                modified_files=[],
                latest_commit=current_head,
                message="No repository drift detected. Agent knowledge is synchronized."
            )

        # Get list of modified files between last known commit and current HEAD
        try:
            result = subprocess.run(
                ["git", "-C", self.repo_path, "diff", "--name-only", last_known_commit, current_head],
                capture_output=True,
                text=True,
                check=True
            )
            modified = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            return DriftReport(
                has_drift=True,
                modified_files=modified,
                latest_commit=current_head,
                message=f"Detected out-of-band modifications in {len(modified)} files! Realignment required."
            )
        except Exception as e:
            return DriftReport(
                has_drift=True,
                modified_files=[],
                latest_commit=current_head,
                message=f"Drift check failed to compare commits: {str(e)}"
            )
