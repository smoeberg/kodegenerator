"""GitHub Authentication & Repository Health Checker."""
from __future__ import annotations

import os
import subprocess
from typing import Dict, Any


class GitHubHealthChecker:
    """Verifies GitHub connectivity, remote configuration, and token permissions."""

    @staticmethod
    def check_health(repo_path: str = ".") -> Dict[str, Any]:
        result = {
            "is_healthy": True,
            "remote_url": "unknown",
            "token_present": False,
            "auth_status": "OK",
            "details": "GitHub integration operational."
        }

        # 1. Check Git remote
        try:
            remote_proc = subprocess.run(
                ["git", "-C", repo_path, "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                check=False
            )
            if remote_proc.returncode == 0:
                result["remote_url"] = remote_proc.stdout.strip()
            else:
                result["is_healthy"] = False
                result["auth_status"] = "NO_REMOTE"
                result["details"] = "Ingen git origin remote fundet."
                return result
        except Exception as e:
            result["is_healthy"] = False
            result["auth_status"] = "GIT_ERROR"
            result["details"] = f"Fejl ved tjek af git remote: {str(e)}"
            return result

        # 2. Check Token in Environment
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            result["token_present"] = True
            # Simulate token validity check (in production, check expiration date or test API)
            if len(token) < 10:
                result["is_healthy"] = False
                result["auth_status"] = "INVALID_TOKEN"
                result["details"] = "GITHUB_TOKEN virker ugyldig (for kort)."
        else:
            # Check if ssh or credential helper works without explicit env token
            # For robustness, we warn if no token is found but allow local git
            result["token_present"] = False
            result["details"] = "Ingen GITHUB_TOKEN fundet i miljøvariabler. Bruger standard system-kredentialer."

        # 3. Test connection (dry run ls-remote if remote exists)
        if result["is_healthy"] and result["remote_url"] != "unknown":
            try:
                test_proc = subprocess.run(
                    ["git", "-C", repo_path, "ls-remote", "--exit-code", "HEAD"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False
                )
                if test_proc.returncode != 0:
                    result["is_healthy"] = False
                    result["auth_status"] = "AUTH_FAILED_OR_EXPIRED"
                    result["details"] = "GitHub afviste adgang (403/401 eller udløbet token). Push/Pull vil fejle."
            except subprocess.TimeoutExpired:
                result["is_healthy"] = False
                result["auth_status"] = "TIMEOUT"
                result["details"] = "Forbindelse til GitHub timed out."
            except Exception:
                pass  # Ignore offline test failures gracefully

        return result
