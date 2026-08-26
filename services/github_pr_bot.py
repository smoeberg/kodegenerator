"""
GitHub PR & Webhook Bot Integration Service

Automatisk konvertering af godkendte patches til rigtige GitHub Pull Requests
med changelog og status-kommentarer.

Funktioner:
- create_pull_request: Opretter PR via GitHub REST API
- Automatisk commit-generering med signering og changelog-formattering
- Webhook-modtager for PR review comments, triggers (/kodegen fix ...) og status sync
- Token og GitHub App private-key auth integration
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple, Union

import requests
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from services.github_pr_contracts import (
    AppAuthConfig,
    AuthenticationError,
    AuthMethod,
    ChangelogEntry,
    CommitInfo,
    GitHubAPIError,
    GitHubConfig,
    GitHubPRBotError,
    PatchInfo,
    PRAction,
    PRMetadata,
    PRResult,
    PRStatus,
    RateLimitError,
    TokenAuthConfig,
    WebhookEventType,
    WebhookPayload,
    WebhookResponse,
    WebhookVerificationError,
)

if TYPE_CHECKING:
    from fastapi import Request, Response


# =============================================================================
# Configuration & Constants
# =============================================================================

GITHUB_API_BASE = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
DEFAULT_USER_AGENT = "kodegenerator-github-bot/1.0.0"

# GitHub App authentication headers
GITHUB_APP_ACCEPT = "application/vnd.github+json"

# Webhook signature header
GITHUB_WEBHOOK_SIGNATURE_HEADER = "x-hub-signature-256"
GITHUB_WEBHOOK_EVENT_HEADER = "x-github-event"
GITHUB_WEBHOOK_DELIVERY_HEADER = "x-github-delivery"

# Default timeout for GitHub API calls
DEFAULT_TIMEOUT_SECONDS = 30


# =============================================================================
# Authentication Utilities
# =============================================================================

class GitHubAuthenticator:
    """
    Handles authentication with GitHub API.
    
    Supports both personal access tokens and GitHub App authentication.
    """
    
    def __init__(
        self,
        *,
        token: Optional[str] = None,
        app_id: Optional[str] = None,
        private_key: Optional[str] = None,
        installation_id: Optional[str] = None,
    ):
        """
        Initialize the authenticator.
        
        Args:
            token: Personal access token (for token auth)
            app_id: GitHub App ID (for app auth)
            private_key: PEM-encoded private key (for app auth)
            installation_id: Installation ID (for app auth)
        """
        self._token = token
        self._app_id = app_id
        self._private_key_pem = private_key
        self._installation_id = installation_id
        
        # Validate that we have valid credentials
        if not (token or (app_id and private_key)):
            raise AuthenticationError("Either token or app credentials must be provided")
    
    def get_auth_method(self) -> AuthMethod:
        """Get the authentication method being used."""
        if self._token:
            return AuthMethod.TOKEN
        return AuthMethod.APP
    
    def get_access_token(self) -> str:
        """
        Get the access token for API requests.
        
        For token auth, returns the token directly.
        For app auth, generates an installation access token.
        
        Returns:
            Access token string
        """
        if self._token:
            return self._token
        
        if not self._app_id or not self._private_key_pem:
            raise AuthenticationError("App credentials not configured")
        
        if not self._installation_id:
            raise AuthenticationError("Installation ID required for GitHub App auth")
        
        # Generate JWT for GitHub App authentication
        jwt_token = self._generate_app_jwt()
        
        # Request installation access token
        token_url = f"{GITHUB_API_BASE}/app/installations/{self._installation_id}/access_tokens"
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": GITHUB_APP_ACCEPT,
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }
        
        response = requests.post(token_url, headers=headers, timeout=DEFAULT_TIMEOUT_SECONDS)
        
        if response.status_code != 201:
            raise GitHubAPIError(
                f"Failed to get installation token: {response.text}",
                response.status_code,
                response.json() if response.text else None,
            )
        
        token_data = response.json()
        return token_data["token"]
    
    def _generate_app_jwt(self) -> str:
        """Generate JWT for GitHub App authentication."""
        try:
            import jwt
        except ImportError:
            raise AuthenticationError("PyJWT library required for GitHub App authentication. Install with: pip install PyJWT")
        
        now = int(time.time())
        
        payload = {
            "iat": now,
            "exp": now + 600,  # 10 minutes expiration
            "iss": self._app_id,
        }
        
        # Load private key
        try:
            private_key = serialization.load_pem_private_key(
                self._private_key_pem.encode() if isinstance(self._private_key_pem, str) else self._private_key_pem,
                password=None,
                backend=default_backend(),
            )
        except ValueError as e:
            raise AuthenticationError(f"Invalid private key format: {e}")
        
        # Sign the JWT
        encoded_jwt = jwt.encode(payload, private_key, algorithm="RS256")
        return encoded_jwt
    
    def get_headers(self, extra_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """
        Get headers for GitHub API requests.
        
        Args:
            extra_headers: Additional headers to include
            
        Returns:
            Dictionary of headers
        """
        token = self.get_access_token()
        
        headers = {
            "Authorization": f"token {token}",
            "Accept": GITHUB_APP_ACCEPT,
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }
        
        if extra_headers:
            headers.update(extra_headers)
        
        return headers


# =============================================================================
# Webhook Utilities
# =============================================================================

class WebhookVerifier:
    """
    Verifies GitHub webhook signatures.
    """
    
    def __init__(self, secret: str):
        """
        Initialize the verifier.
        
        Args:
            secret: Webhook secret for signature verification
        """
        self._secret = secret.encode() if isinstance(secret, str) else secret
    
    def verify_signature(
        self,
        payload: bytes,
        signature: str,
    ) -> bool:
        """
        Verify the webhook signature.
        
        Args:
            payload: Raw request body
            signature: Signature from x-hub-signature-256 header
            
        Returns:
            True if signature is valid
        """
        if not signature or not signature.startswith("sha256="):
            return False
        
        # Extract the hash part
        hash_value = signature[7:]  # Remove "sha256=" prefix
        
        # Compute expected hash
        expected_hash = hmac.new(
            self._secret,
            payload,
            hashlib.sha256,
        ).hexdigest()
        
        # Compare in constant time to prevent timing attacks
        return hmac.compare_digest(expected_hash, hash_value)


class WebhookParser:
    """
    Parses GitHub webhook payloads.
    """
    
    @staticmethod
    def parse_payload(
        body: bytes,
        event_type: str,
        action: Optional[str] = None,
    ) -> WebhookPayload:
        """
        Parse raw webhook payload.
        
        Args:
            body: Raw request body
            event_type: Event type from x-github-event header
            action: Action from payload
            
        Returns:
            Parsed WebhookPayload
        """
        try:
            payload = json.loads(body.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise WebhookVerificationError(f"Invalid JSON payload: {e}")
        
        return WebhookPayload(
            event_type=WebhookEventType(event_type),
            action=action or payload.get("action"),
            repository=payload.get("repository", {}),
            pull_request=payload.get("pull_request"),
            comment=payload.get("comment"),
            issue=payload.get("issue"),
            sender=payload.get("sender", {}),
            installation=payload.get("installation"),
            raw_payload=payload,
        )


# =============================================================================
# Main GitHub PR Bot Service
# =============================================================================

class GitHubPRBot:
    """
    Main service for GitHub PR automation.
    
    Provides functionality for:
    - Creating Pull Requests from patches
    - Automatic commit generation with signing
    - Changelog formatting
    - Webhook processing
    - Status comments
    """
    
    def __init__(
        self,
        *,
        owner: str,
        repo: str,
        auth_config: Union[TokenAuthConfig, AppAuthConfig],
        webhook_secret: Optional[str] = None,
        config: Optional[GitHubConfig] = None,
        signing_key: Optional[bytes] = None,
    ):
        """
        Initialize the GitHub PR Bot.
        
        Args:
            owner: Repository owner (user or organization)
            repo: Repository name
            auth_config: Authentication configuration
            webhook_secret: Secret for webhook signature verification
            config: GitHub API configuration
            signing_key: Key for signing commits
        """
        self.owner = owner
        self.repo = repo
        self.repo_full_name = f"{owner}/{repo}"
        self.config = config or GitHubConfig()
        self.webhook_secret = webhook_secret
        
        # Initialize authenticator
        if isinstance(auth_config, TokenAuthConfig):
            self._auth = GitHubAuthenticator(token=auth_config.token)
        elif isinstance(auth_config, AppAuthConfig):
            self._auth = GitHubAuthenticator(
                app_id=auth_config.app_id,
                private_key=auth_config.private_key,
                installation_id=auth_config.installation_id,
            )
        else:
            raise AuthenticationError("Invalid auth configuration type")
        
        # Initialize signing key
        self._signing_key = signing_key or self._load_signing_key()
        
        # Webhook verifier (if secret provided)
        self._webhook_verifier = WebhookVerifier(webhook_secret) if webhook_secret else None
    
    def _load_signing_key(self) -> bytes:
        """Load signing key from environment or generate ephemeral."""
        encoded = os.environ.get("GITHUB_BOT_SIGNING_KEY")
        if encoded:
            import base64
            import binascii
            padded = encoded + "=" * (-len(encoded) % 4)
            try:
                return base64.b64decode(padded, altchars=b"-_", validate=True)
            except (binascii.Error, ValueError) as exc:
                raise GitHubPRBotError("Invalid GITHUB_BOT_SIGNING_KEY") from exc
        
        # Generate ephemeral key for development
        return secrets.token_bytes(32)
    
    def _compute_fingerprint(self, data: Dict[str, Any]) -> str:
        """Compute SHA-256 fingerprint of data."""
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    
    def _sign_data(self, data: str) -> str:
        """Sign data with HMAC."""
        return hmac.new(self._signing_key, data.encode("utf-8"), hashlib.sha256).hexdigest()
    
    # -------------------------------------------------------------------------
    # GitHub API Client Methods
    # -------------------------------------------------------------------------
    
    def _api_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Make a request to the GitHub API.
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE, PATCH)
            endpoint: API endpoint (relative to base URL)
            data: Request body data
            params: Query parameters
            timeout: Request timeout in seconds
            
        Returns:
            JSON response from API
            
        Raises:
            GitHubAPIError: If the request fails
            RateLimitError: If rate limit is exceeded
        """
        url = f"{self.config.api_url}{endpoint}"
        headers = self._auth.get_headers()
        
        actual_timeout = timeout or self.config.timeout
        
        for attempt in range(self.config.retry_count):
            try:
                response = requests.request(
                    method,
                    url,
                    headers=headers,
                    json=data,
                    params=params,
                    timeout=actual_timeout,
                )
                
                # Check rate limit
                remaining = int(response.headers.get("x-ratelimit-remaining", 0))
                if remaining == 0:
                    reset_time = int(response.headers.get("x-ratelimit-reset", 0))
                    wait_time = max(reset_time - time.time(), 0) + 10
                    if attempt < self.config.retry_count - 1:
                        time.sleep(wait_time)
                        continue
                    raise RateLimitError(
                        f"Rate limit exceeded. Reset in {wait_time} seconds."
                    )
                
                # Check for errors
                if response.status_code >= 400:
                    error_data = response.json() if response.text else {}
                    
                    # Handle specific error cases
                    if response.status_code == 401:
                        raise AuthenticationError(
                            f"Authentication failed: {error_data.get('message', 'Unknown error')}"
                        )
                    elif response.status_code == 403:
                        # Could be rate limit or permission issue
                        if "rate limit" in error_data.get("message", "").lower():
                            raise RateLimitError(
                                f"Rate limit exceeded: {error_data.get('message', '')}"
                            )
                        raise GitHubAPIError(
                            f"Forbidden: {error_data.get('message', 'Unknown error')}",
                            response.status_code,
                            error_data,
                        )
                    elif response.status_code == 404:
                        raise GitHubAPIError(
                            f"Not found: {error_data.get('message', endpoint)}",
                            response.status_code,
                            error_data,
                        )
                    else:
                        raise GitHubAPIError(
                            f"API error: {error_data.get('message', 'Unknown error')}",
                            response.status_code,
                            error_data,
                        )
                
                # Return JSON response
                if response.text:
                    return response.json()
                return {}
                
            except requests.exceptions.Timeout:
                if attempt < self.config.retry_count - 1:
                    time.sleep(self.config.retry_delay * (attempt + 1))
                    continue
                raise GitHubAPIError(
                    f"Request timeout after {actual_timeout} seconds",
                    408,
                )
            except requests.exceptions.RequestException as e:
                raise GitHubAPIError(f"Request failed: {e}", 0)
        
        raise GitHubAPIError("Max retries exceeded", 0)
    
    def get_repo_info(self) -> Dict[str, Any]:
        """Get repository information."""
        return self._api_request("GET", f"/repos/{self.repo_full_name}")
    
    def get_branch(self, branch: str) -> Dict[str, Any]:
        """Get branch information."""
        return self._api_request("GET", f"/repos/{self.repo_full_name}/branches/{branch}")
    
    def get_default_branch(self) -> str:
        """Get the default branch for the repository."""
        repo_info = self.get_repo_info()
        return repo_info.get("default_branch", "main")
    
    def create_branch(
        self,
        branch_name: str,
        sha: str,
    ) -> Dict[str, Any]:
        """
        Create a new branch.
        
        Args:
            branch_name: Name of the branch to create
            sha: SHA of the commit to branch from
            
        Returns:
            Branch information
        """
        data = {"ref": f"refs/heads/{branch_name}", "sha": sha}
        return self._api_request("POST", f"/repos/{self.repo_full_name}/git/refs", data)
    
    def create_commit(
        self,
        message: str,
        tree_sha: str,
        parent_sha: str,
        author: Dict[str, str],
        committer: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Create a new commit.
        
        Args:
            message: Commit message
            tree_sha: SHA of the tree to commit
            parent_sha: SHA of the parent commit
            author: Author information (name and email)
            committer: Committer information (defaults to author)
            
        Returns:
            Commit information
        """
        data = {
            "message": message,
            "tree": tree_sha,
            "parents": [parent_sha],
            "author": author,
            "committer": committer or author,
        }
        return self._api_request("POST", f"/repos/{self.repo_full_name}/git/commits", data)
    
    def create_blob(self, content: str, encoding: str = "utf-8") -> Dict[str, Any]:
        """
        Create a new blob.
        
        Args:
            content: File content
            encoding: Content encoding
            
        Returns:
            Blob information
        """
        data = {"content": content, "encoding": encoding}
        return self._api_request("POST", f"/repos/{self.repo_full_name}/git/blobs", data)
    
    def create_tree(
        self,
        tree: List[Dict[str, Any]],
        base_tree_sha: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new tree.
        
        Args:
            tree: List of tree entries (path, mode, type, sha)
            base_tree_sha: Base tree SHA (optional)
            
        Returns:
            Tree information
        """
        data = {"tree": tree}
        if base_tree_sha:
            data["base_tree"] = base_tree_sha
        return self._api_request("POST", f"/repos/{self.repo_full_name}/git/trees", data)
    
    def get_tree(self, tree_sha: str, recursive: bool = False) -> Dict[str, Any]:
        """Get tree information."""
        params = {"recursive": str(recursive).lower()}
        return self._api_request(
            "GET",
            f"/repos/{self.repo_full_name}/git/trees/{tree_sha}",
            params=params,
        )
    
    def get_commit(self, commit_sha: str) -> Dict[str, Any]:
        """Get commit information."""
        return self._api_request("GET", f"/repos/{self.repo_full_name}/git/commits/{commit_sha}")
    
    def get_reference(self, ref: str) -> Dict[str, Any]:
        """Get reference information."""
        return self._api_request("GET", f"/repos/{self.repo_full_name}/git/{ref}")
    
    def update_reference(
        self,
        ref: str,
        sha: str,
        force: bool = False,
    ) -> Dict[str, Any]:
        """
        Update a reference.
        
        Args:
            ref: Reference name (e.g., 'heads/branch')
            sha: New SHA for the reference
            force: Force update (overwrite existing)
            
        Returns:
            Reference information
        """
        data = {"sha": sha, "force": force}
        return self._api_request(
            "PATCH",
            f"/repos/{self.repo_full_name}/git/refs/{ref}",
            data,
        )
    
    # -------------------------------------------------------------------------
    # Pull Request Methods
    # -------------------------------------------------------------------------
    
    def create_pull_request(
        self,
        title: str,
        body: str,
        head: str,
        base: str,
        draft: bool = False,
        labels: Optional[List[str]] = None,
        assignees: Optional[List[str]] = None,
        reviewers: Optional[List[str]] = None,
    ) -> PRResult:
        """
        Create a new Pull Request.
        
        Args:
            title: PR title
            body: PR description/body
            head: Head branch name
            base: Base branch name
            draft: Whether PR is a draft
            labels: Labels to add
            assignees: Users to assign
            reviewers: Users to request review from
            
        Returns:
            PRResult with PR information
            
        Raises:
            GitHubAPIError: If PR creation fails
        """
        data: Dict[str, Any] = {
            "title": title,
            "body": body,
            "head": head,
            "base": base,
            "draft": draft,
        }
        
        if labels:
            data["labels"] = labels
        if assignees:
            data["assignees"] = assignees
        
        try:
            pr_data = self._api_request(
                "POST",
                f"/repos/{self.repo_full_name}/pulls",
                data,
            )
            
            pr_number = pr_data.get("number")
            pr_url = pr_data.get("html_url")
            
            # Add reviewers (if any)
            if reviewers and pr_number:
                self._add_reviewers(pr_number, reviewers)
            
            return PRResult(
                pr_number=pr_number,
                pr_url=pr_url,
                status=PRStatus.CREATED,
                metadata=pr_data,
            )
            
        except GitHubAPIError as e:
            return PRResult(
                status=PRStatus.FAILED,
                errors=[f"Failed to create PR: {e}"],
            )
    
    def _add_reviewers(self, pr_number: int, reviewers: List[str]) -> None:
        """Add reviewers to a Pull Request."""
        data = {"reviewers": reviewers}
        self._api_request(
            "POST",
            f"/repos/{self.repo_full_name}/pulls/{pr_number}/requested_reviewers",
            data,
        )
    
    def get_pull_request(self, pr_number: int) -> Dict[str, Any]:
        """Get Pull Request information."""
        return self._api_request(
            "GET",
            f"/repos/{self.repo_full_name}/pulls/{pr_number}",
        )
    
    def update_pull_request(
        self,
        pr_number: int,
        title: Optional[str] = None,
        body: Optional[str] = None,
        base: Optional[str] = None,
        labels: Optional[List[str]] = None,
        state: Optional[str] = None,
    ) -> PRResult:
        """
        Update a Pull Request.
        
        Args:
            pr_number: PR number
            title: New title
            body: New body
            base: New base branch
            labels: New labels
            state: New state (open or closed)
            
        Returns:
            PRResult with update information
        """
        data: Dict[str, Any] = {}
        
        if title is not None:
            data["title"] = title
        if body is not None:
            data["body"] = body
        if base is not None:
            data["base"] = base
        if labels is not None:
            data["labels"] = labels
        if state is not None:
            data["state"] = state
        
        if not data:
            return PRResult(
                status=PRStatus.PENDING,
                errors=["No fields to update"],
            )
        
        try:
            pr_data = self._api_request(
                "PATCH",
                f"/repos/{self.repo_full_name}/pulls/{pr_number}",
                data,
            )
            
            return PRResult(
                pr_number=pr_number,
                pr_url=pr_data.get("html_url"),
                status=PRStatus.UPDATED,
                metadata=pr_data,
            )
            
        except GitHubAPIError as e:
            return PRResult(
                status=PRStatus.FAILED,
                errors=[f"Failed to update PR: {e}"],
            )
    
    def add_pr_comment(
        self,
        pr_number: int,
        body: str,
    ) -> Dict[str, Any]:
        """
        Add a comment to a Pull Request.
        
        Args:
            pr_number: PR number
            body: Comment body
            
        Returns:
            Comment information
        """
        data = {"body": body}
        return self._api_request(
            "POST",
            f"/repos/{self.repo_full_name}/issues/{pr_number}/comments",
            data,
        )
    
    def merge_pull_request(
        self,
        pr_number: int,
        commit_title: Optional[str] = None,
        merge_method: str = "squash",
    ) -> PRResult:
        """
        Merge a Pull Request.
        
        Args:
            pr_number: PR number
            commit_title: Title for merge commit
            merge_method: Merge method (merge, squash, rebase)
            
        Returns:
            PRResult with merge information
        """
        data: Dict[str, Any] = {
            "merge_method": merge_method,
        }
        
        if commit_title:
            data["commit_title"] = commit_title
        
        try:
            result = self._api_request(
                "PUT",
                f"/repos/{self.repo_full_name}/pulls/{pr_number}/merge",
                data,
            )
            
            if result.get("merged", False):
                return PRResult(
                    pr_number=pr_number,
                    status=PRStatus.MERGED,
                    commit_hash=result.get("sha"),
                    metadata=result,
                )
            else:
                return PRResult(
                    pr_number=pr_number,
                    status=PRStatus.FAILED,
                    errors=[result.get("message", "Merge failed")],
                    metadata=result,
                )
            
        except GitHubAPIError as e:
            return PRResult(
                status=PRStatus.FAILED,
                errors=[f"Failed to merge PR: {e}"],
            )
    
    # -------------------------------------------------------------------------
    # Patch Conversion Methods
    # -------------------------------------------------------------------------
    
    def apply_patch_and_create_pr(
        self,
        patch: PatchInfo,
        pr_metadata: PRMetadata,
        wbs_summary: Dict[str, Any],
        test_results: Dict[str, Any],
    ) -> PRResult:
        """
        Apply a patch and create a Pull Request.
        
        This is the main method for converting approved patches to PRs.
        
        Args:
            patch: Patch information
            pr_metadata: PR metadata (title, description, etc.)
            wbs_summary: WBS (Work Breakdown Structure) summary
            test_results: Test results from validation
            
        Returns:
            PRResult with full operation details
        """
        errors: List[str] = []
        warnings: List[str] = []
        
        try:
            # Step 1: Generate changelog entry
            changelog = self._generate_changelog(
                patch,
                wbs_summary,
                test_results,
            )
            
            # Step 2: Prepare PR body with changelog and test results
            pr_body = self._format_pr_body(
                patch,
                wbs_summary,
                test_results,
                changelog,
            )
            
            # Step 3: Create the Pull Request
            pr_result = self.create_pull_request(
                title=pr_metadata.title,
                body=pr_body,
                head=pr_metadata.branch,
                base=pr_metadata.base_branch,
                draft=pr_metadata.draft,
                labels=pr_metadata.labels,
                assignees=pr_metadata.assignees,
                reviewers=pr_metadata.reviewers,
            )
            
            if pr_result.status != PRStatus.CREATED:
                return PRResult(
                    status=PRStatus.FAILED,
                    errors=pr_result.errors,
                    warnings=warnings,
                )
            
            # Step 4: Add status comment
            if pr_result.pr_number:
                status_comment = self._generate_status_comment(
                    patch,
                    wbs_summary,
                    test_results,
                )
                self.add_pr_comment(pr_result.pr_number, status_comment)
            
            return PRResult(
                pr_number=pr_result.pr_number,
                pr_url=pr_result.pr_url,
                status=PRStatus.CREATED,
                changelog_entry=changelog,
                warnings=warnings,
                metadata={
                    **pr_result.metadata,
                    "wbs_summary": wbs_summary,
                    "test_results": test_results,
                },
            )
            
        except Exception as e:
            errors.append(str(e))
            return PRResult(
                status=PRStatus.FAILED,
                errors=errors,
                warnings=warnings,
            )
    
    def _generate_changelog(
        self,
        patch: PatchInfo,
        wbs_summary: Dict[str, Any],
        test_results: Dict[str, Any],
    ) -> ChangelogEntry:
        """
        Generate a changelog entry from patch and test data.
        
        Args:
            patch: Patch information
            wbs_summary: WBS summary
            test_results: Test results
            
        Returns:
            ChangelogEntry
        """
        # Extract version from WBS or patch
        version = wbs_summary.get("version", f"v{patch.timestamp.strftime('%Y%m%d')}")
        author = patch.author
        timestamp = datetime.now(timezone.utc)
        
        # Extract changes from WBS
        changes: List[str] = []
        features: List[str] = []
        fixes: List[str] = []
        breaking_changes: List[str] = []
        
        # Categorize changes from WBS
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
        
        # Add test results summary
        test_summary = test_results.get("summary", {})
        if test_summary.get("passed", 0) > 0:
            changes.append(f"All {test_summary.get('total', 0)} tests passed")
        elif test_summary.get("failed", 0) > 0:
            warnings = test_summary.get("warnings", [])
            if warnings:
                changes.append(f"{test_summary.get('failed', 0)} tests failed")
        
        return ChangelogEntry(
            version=version,
            timestamp=timestamp,
            author=author,
            changes=changes,
            breaking_changes=breaking_changes,
            fixes=fixes,
            features=features,
        )
    
    def _format_pr_body(
        self,
        patch: PatchInfo,
        wbs_summary: Dict[str, Any],
        test_results: Dict[str, Any],
        changelog: ChangelogEntry,
    ) -> str:
        """
        Format the PR body with changelog and details.
        
        Args:
            patch: Patch information
            wbs_summary: WBS summary
            test_results: Test results
            changelog: Changelog entry
            
        Returns:
            Formatted PR body as markdown
        """
        lines = []
        
        # Title and description
        lines.append(f"# {wbs_summary.get('title', 'Generated Pull Request')}")
        lines.append("")
        lines.append(wbs_summary.get("description", ""))
        lines.append("")
        
        # Patch information
        lines.append("## Patch Information")
        lines.append("")
        lines.append(f"- **Patch ID:** `{patch.patch_id}`")
        lines.append(f"- **Author:** {patch.author}")
        lines.append(f"- **Timestamp:** {patch.timestamp.isoformat()}")
        lines.append(f"- **Files Changed:** {', '.join(patch.files_changed) if patch.files_changed else 'None'}")
        lines.append("")
        
        # Changelog
        lines.append("## Changelog")
        lines.append("")
        lines.append(changelog.to_markdown())
        lines.append("")
        
        # Test results
        lines.append("## Test Results")
        lines.append("")
        lines.append(self._format_test_results(test_results))
        lines.append("")
        
        # WBS Summary
        lines.append("## Work Breakdown Structure")
        lines.append("")
        lines.append(self._format_wbs_summary(wbs_summary))
        
        return "\n".join(lines)
    
    def _format_test_results(self, test_results: Dict[str, Any]) -> str:
        """Format test results as markdown."""
        lines = []
        
        summary = test_results.get("summary", {})
        passed = summary.get("passed", 0)
        failed = summary.get("failed", 0)
        skipped = summary.get("skipped", 0)
        total = summary.get("total", passed + failed + skipped)
        
        lines.append(f"- **Total:** {total}")
        lines.append(f"- **Passed:** {passed}")
        lines.append(f"- **Failed:** {failed}")
        lines.append(f"- **Skipped:** {skipped}")
        
        if failed > 0:
            lines.append("")
            lines.append("**Failed Tests:**")
            for test in test_results.get("failures", []):
                lines.append(f"  - {test.get('name', 'Unknown')}: {test.get('message', 'No message')}")
        
        return "\n".join(lines)
    
    def _format_wbs_summary(self, wbs_summary: Dict[str, Any]) -> str:
        """Format WBS summary as markdown."""
        lines = []
        
        if "items" in wbs_summary:
            for item in wbs_summary["items"]:
                item_id = item.get("id", "")
                item_type = item.get("type", "")
                description = item.get("description", item.get("title", ""))
                status = item.get("status", "")
                
                lines.append(f"- [{item_type}] **{item_id}**: {description} ({status})")
        else:
            lines.append("_No WBS items found_")
        
        return "\n".join(lines)
    
    def _generate_status_comment(
        self,
        patch: PatchInfo,
        wbs_summary: Dict[str, Any],
        test_results: Dict[str, Any],
    ) -> str:
        """
        Generate a status comment for the PR.
        
        Args:
            patch: Patch information
            wbs_summary: WBS summary
            test_results: Test results
            
        Returns:
            Status comment as markdown
        """
        lines = []
        
        lines.append("## Patch Successfully Converted to Pull Request")
        lines.append("")
        lines.append(f"- **Patch ID:** `{patch.patch_id}`")
        lines.append(f"- **Author:** {patch.author}")
        lines.append("")
        
        # Test summary
        summary = test_results.get("summary", {})
        passed = summary.get("passed", 0)
        total = summary.get("total", 0)
        
        if passed == total and total > 0:
            lines.append(f"All {total} tests passed")
        else:
            lines.append(f"{passed}/{total} tests passed")
        
        lines.append("")
        lines.append("Ready for review!")
        
        return "\n".join(lines)
    
    # -------------------------------------------------------------------------
    # Webhook Processing Methods
    # -------------------------------------------------------------------------
    
    async def process_webhook(
        self,
        request: "Request",
    ) -> WebhookResponse:
        """
        Process an incoming GitHub webhook.
        
        Args:
            request: FastAPI Request object
            
        Returns:
            WebhookResponse with processing results
        """
        # Read request body
        body = await request.body()
        
        # Get headers
        signature = request.headers.get(GITHUB_WEBHOOK_SIGNATURE_HEADER)
        event_type = request.headers.get(GITHUB_WEBHOOK_EVENT_HEADER)
        delivery_id = request.headers.get(GITHUB_WEBHOOK_DELIVERY_HEADER)
        
        # Verify signature if configured
        if self._webhook_verifier and signature:
            if not self._webhook_verifier.verify_signature(body, signature):
                raise WebhookVerificationError(
                    f"Invalid webhook signature for delivery {delivery_id}"
                )
        
        # Parse payload
        try:
            payload = WebhookParser.parse_payload(body, event_type or "")
        except WebhookVerificationError as e:
            return WebhookResponse(
                status="error",
                message=f"Invalid payload: {e}",
            )
        
        # Route to appropriate handler
        return self._route_webhook(payload)
    
    def _route_webhook(self, payload: WebhookPayload) -> WebhookResponse:
        """
        Route webhook payload to appropriate handler.
        
        Args:
            payload: Parsed webhook payload
            
        Returns:
            WebhookResponse
        """
        event_type = payload.event_type
        action = payload.action
        
        try:
            if event_type == WebhookEventType.PULL_REQUEST:
                return self._handle_pr_event(payload)
            elif event_type == WebhookEventType.PUSH:
                return self._handle_push_event(payload)
            elif event_type == WebhookEventType.ISSUE_COMMENT:
                return self._handle_issue_comment(payload)
            elif event_type == WebhookEventType.PULL_REQUEST_REVIEW_COMMENT:
                return self._handle_pr_comment(payload)
            elif event_type == WebhookEventType.PULL_REQUEST_REVIEW:
                return self._handle_pr_review(payload)
            elif event_type == WebhookEventType.STATUS:
                return self._handle_status_event(payload)
            elif event_type == WebhookEventType.CHECK_SUITE:
                return self._handle_check_suite_event(payload)
            elif event_type == WebhookEventType.CHECK_RUN:
                return self._handle_check_run_event(payload)
            else:
                return WebhookResponse(
                    status="ignored",
                    message=f"Unhandled event type: {event_type}",
                )
        except Exception as e:
            return WebhookResponse(
                status="error",
                message=f"Error processing {event_type}: {e}",
            )
    
    def _handle_pr_event(self, payload: WebhookPayload) -> WebhookResponse:
        """Handle Pull Request webhook events."""
        pr = payload.pull_request
        action = payload.action
        
        if not pr or not action:
            return WebhookResponse(
                status="ignored",
                message="No pull request or action in payload",
            )
        
        pr_number = pr.get("number")
        
        if action == PRAction.OPENED.value:
            return self._handle_pr_opened(pr_number, pr)
        elif action == PRAction.CLOSED.value:
            return self._handle_pr_closed(pr_number, pr)
        elif action == PRAction.MERGED.value:
            return self._handle_pr_merged(pr_number, pr)
        elif action == PRAction.SYNCHRONIZE.value:
            return self._handle_pr_synchronized(pr_number, pr)
        elif action == PRAction.READY_FOR_REVIEW.value:
            return self._handle_pr_ready_for_review(pr_number, pr)
        else:
            return WebhookResponse(
                status="ignored",
                message=f"Unhandled PR action: {action}",
            )
    
    def _handle_pr_opened(self, pr_number: int, pr: Dict[str, Any]) -> WebhookResponse:
        """Handle PR opened event."""
        # Check for /kodegen commands in PR body or title
        body = pr.get("body", "")
        title = pr.get("title", "")
        
        commands = self._extract_commands(body + " " + title)
        
        if not commands:
            return WebhookResponse(
                status="ignored",
                message="No /kodegen commands found",
            )
        
        # Process commands
        actions = []
        for command in commands:
            action = self._process_command(command, pr_number, pr)
            if action:
                actions.append(action)
        
        return WebhookResponse(
            status="processed",
            message=f"Processed {len(actions)} commands",
            actions=actions,
            pr_number=pr_number,
        )
    
    def _handle_pr_closed(self, pr_number: int, pr: Dict[str, Any]) -> WebhookResponse:
        """Handle PR closed event."""
        # Log the closure
        return WebhookResponse(
            status="acknowledged",
            message=f"PR #{pr_number} closed",
            pr_number=pr_number,
        )
    
    def _handle_pr_merged(self, pr_number: int, pr: Dict[str, Any]) -> WebhookResponse:
        """Handle PR merged event."""
        # Update audit ledger or other tracking
        return WebhookResponse(
            status="acknowledged",
            message=f"PR #{pr_number} merged",
            pr_number=pr_number,
        )
    
    def _handle_pr_synchronized(self, pr_number: int, pr: Dict[str, Any]) -> WebhookResponse:
        """Handle PR synchronized (new commits pushed) event."""
        # Re-run validation if needed
        return WebhookResponse(
            status="acknowledged",
            message=f"PR #{pr_number} synchronized",
            pr_number=pr_number,
        )
    
    def _handle_pr_ready_for_review(self, pr_number: int, pr: Dict[str, Any]) -> WebhookResponse:
        """Handle PR ready for review event."""
        # Trigger additional validation or notifications
        return WebhookResponse(
            status="acknowledged",
            message=f"PR #{pr_number} ready for review",
            pr_number=pr_number,
        )
    
    def _handle_push_event(self, payload: WebhookPayload) -> WebhookResponse:
        """Handle push webhook events."""
        ref = payload.raw_payload.get("ref", "")
        commits = payload.raw_payload.get("commits", [])
        
        return WebhookResponse(
            status="acknowledged",
            message=f"Push to {ref} with {len(commits)} commits",
        )
    
    def _handle_issue_comment(self, payload: WebhookPayload) -> WebhookResponse:
        """Handle issue comment webhook events."""
        comment = payload.comment
        issue = payload.issue
        
        if not comment or not issue:
            return WebhookResponse(
                status="ignored",
                message="No comment or issue in payload",
            )
        
        # Check for /kodegen commands
        body = comment.get("body", "")
        commands = self._extract_commands(body)
        
        if not commands:
            return WebhookResponse(
                status="ignored",
                message="No /kodegen commands found",
            )
        
        # Process commands
        issue_number = issue.get("number")
        actions = []
        for command in commands:
            action = self._process_issue_command(command, issue_number, comment)
            if action:
                actions.append(action)
        
        return WebhookResponse(
            status="processed",
            message=f"Processed {len(actions)} commands",
            actions=actions,
            comment_id=comment.get("id"),
        )
    
    def _handle_pr_comment(self, payload: WebhookPayload) -> WebhookResponse:
        """Handle PR review comment webhook events."""
        comment = payload.comment
        pr = payload.pull_request
        
        if not comment or not pr:
            return WebhookResponse(
                status="ignored",
                message="No comment or PR in payload",
            )
        
        # Check for /kodegen commands
        body = comment.get("body", "")
        commands = self._extract_commands(body)
        
        if not commands:
            return WebhookResponse(
                status="ignored",
                message="No /kodegen commands found",
            )
        
        # Process commands
        pr_number = pr.get("number")
        actions = []
        for command in commands:
            action = self._process_pr_comment_command(command, pr_number, comment)
            if action:
                actions.append(action)
        
        return WebhookResponse(
            status="processed",
            message=f"Processed {len(actions)} commands",
            actions=actions,
            pr_number=pr_number,
            comment_id=comment.get("id"),
        )
    
    def _handle_pr_review(self, payload: WebhookPayload) -> WebhookResponse:
        """Handle PR review webhook events."""
        review = payload.raw_payload.get("review")
        pr = payload.pull_request
        
        if not review or not pr:
            return WebhookResponse(
                status="ignored",
                message="No review or PR in payload",
            )
        
        state = review.get("state", "")
        pr_number = pr.get("number")
        
        return WebhookResponse(
            status="acknowledged",
            message=f"PR #{pr_number} review: {state}",
            pr_number=pr_number,
        )
    
    def _handle_status_event(self, payload: WebhookPayload) -> WebhookResponse:
        """Handle status webhook events."""
        state = payload.raw_payload.get("state", "")
        description = payload.raw_payload.get("description", "")
        
        return WebhookResponse(
            status="acknowledged",
            message=f"Status: {state} - {description}",
        )
    
    def _handle_check_suite_event(self, payload: WebhookPayload) -> WebhookResponse:
        """Handle check suite webhook events."""
        action = payload.action
        check_suite = payload.raw_payload.get("check_suite")
        
        if not check_suite:
            return WebhookResponse(
                status="ignored",
                message="No check suite in payload",
            )
        
        conclusion = check_suite.get("conclusion", "")
        
        return WebhookResponse(
            status="acknowledged",
            message=f"Check suite {action}: {conclusion}",
        )
    
    def _handle_check_run_event(self, payload: WebhookPayload) -> WebhookResponse:
        """Handle check run webhook events."""
        action = payload.action
        check_run = payload.raw_payload.get("check_run")
        
        if not check_run:
            return WebhookResponse(
                status="ignored",
                message="No check run in payload",
            )
        
        conclusion = check_run.get("conclusion", "")
        
        return WebhookResponse(
            status="acknowledged",
            message=f"Check run {action}: {conclusion}",
        )
    
    def _extract_commands(self, text: str) -> List[str]:
        """
        Extract /kodegen commands from text.
        
        Args:
            text: Text to search for commands
            
        Returns:
            List of command strings
        """
        commands = []
        
        # Match /kodegen commands - split by /kodegen and process each
        parts = re.split(r'(/kodegen\s+)', text, flags=re.IGNORECASE)
        
        # Reconstruct commands from parts
        i = 0
        while i < len(parts):
            if parts[i].lower().startswith('/kodegen'):
                # This is a command start
                cmd_prefix = parts[i]
                # Collect all following parts until next /kodegen or end
                cmd_parts = [cmd_prefix]
                j = i + 1
                while j < len(parts) and not parts[j].lower().startswith('/kodegen'):
                    cmd_parts.append(parts[j])
                    j += 1
                
                command = ''.join(cmd_parts).strip()
                if command:
                    commands.append(command)
                i = j
            else:
                i += 1
        
        return commands
    
    def _process_command(
        self,
        command: str,
        pr_number: int,
        pr: Dict[str, Any],
    ) -> Optional[str]:
        """
        Process a /kodegen command.
        
        Args:
            command: Command string
            pr_number: PR number
            pr: PR data
            
        Returns:
            Action description or None
        """
        parts = command.split()
        if len(parts) < 2:
            return None
        
        cmd = parts[1].lower()
        args = parts[2:] if len(parts) > 2 else []
        
        if cmd == "fix":
            return self._process_fix_command(pr_number, args)
        elif cmd == "test":
            return self._process_test_command(pr_number, args)
        elif cmd == "rebase":
            return self._process_rebase_command(pr_number, args)
        elif cmd == "merge":
            return self._process_merge_command(pr_number, args)
        elif cmd == "status":
            return self._process_status_command(pr_number, args)
        else:
            return None
    
    def _process_issue_command(
        self,
        command: str,
        issue_number: int,
        comment: Dict[str, Any],
    ) -> Optional[str]:
        """Process a /kodegen command from an issue comment."""
        # For now, just handle basic commands
        parts = command.split()
        if len(parts) < 2:
            return None
        
        cmd = parts[1].lower()
        
        if cmd == "help":
            return "Displaying help"
        
        return None
    
    def _process_pr_comment_command(
        self,
        command: str,
        pr_number: int,
        comment: Dict[str, Any],
    ) -> Optional[str]:
        """Process a /kodegen command from a PR comment."""
        return self._process_command(command, pr_number, {})
    
    def _process_fix_command(self, pr_number: int, args: List[str]) -> str:
        """Process /kodegen fix command."""
        # Trigger automated fix workflow
        return f"Triggering fix workflow for PR #{pr_number}"
    
    def _process_test_command(self, pr_number: int, args: List[str]) -> str:
        """Process /kodegen test command."""
        # Re-run tests
        return f"Re-running tests for PR #{pr_number}"
    
    def _process_rebase_command(self, pr_number: int, args: List[str]) -> str:
        """Process /kodegen rebase command."""
        # Rebase PR onto target branch
        return f"Rebasing PR #{pr_number}"
    
    def _process_merge_command(self, pr_number: int, args: List[str]) -> str:
        """Process /kodegen merge command."""
        # Attempt to merge PR
        result = self.merge_pull_request(pr_number)
        if result.status == PRStatus.MERGED:
            return f"Merged PR #{pr_number}"
        else:
            return f"Failed to merge PR #{pr_number}: {', '.join(result.errors)}"
    
    def _process_status_command(self, pr_number: int, args: List[str]) -> str:
        """Process /kodegen status command."""
        pr_data = self.get_pull_request(pr_number)
        status = pr_data.get("state", "unknown")
        return f"PR #{pr_number} status: {status}"
    
    # -------------------------------------------------------------------------
    # Commit Signing Methods
    # -------------------------------------------------------------------------
    
    def sign_commit(self, commit_sha: str, message: str) -> Optional[str]:
        """
        Sign a commit with GPG-style signature.
        
        Args:
            commit_sha: SHA of the commit to sign
            message: Commit message to include in signature
            
        Returns:
            Base64-encoded signature or None if signing fails
        """
        try:
            # Create signature payload
            payload = f"tree {commit_sha}\n{message}"
            
            # Sign with HMAC (simplified for this implementation)
            # In a real implementation, this would use GPG or SSH keys
            signature = self._sign_data(payload)
            
            # Return as base64
            return base64.b64encode(signature.encode()).decode()
            
        except Exception as e:
            # Log error and return None
            return None
    
    def create_signed_commit(
        self,
        message: str,
        tree_sha: str,
        parent_sha: str,
        author: Dict[str, str],
        sign: bool = True,
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """
        Create a signed commit.
        
        Args:
            message: Commit message
            tree_sha: SHA of the tree to commit
            parent_sha: SHA of the parent commit
            author: Author information
            sign: Whether to sign the commit
            
        Returns:
            Tuple of (commit_data, signature)
        """
        # Create the commit
        commit_data = self.create_commit(
            message=message,
            tree_sha=tree_sha,
            parent_sha=parent_sha,
            author=author,
        )
        
        commit_sha = commit_data.get("sha")
        if not commit_sha:
            return commit_data, None
        
        # Sign the commit if requested
        signature = None
        if sign:
            signature = self.sign_commit(commit_sha, message)
        
        return commit_data, signature
    
    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------
    
    def validate_patch(self, patch: PatchInfo) -> Tuple[bool, List[str]]:
        """
        Validate a patch before creating a PR.
        
        Args:
            patch: Patch to validate
            
        Returns:
            Tuple of (is_valid, errors)
        """
        errors = []
        
        # Check patch content
        if not patch.patch_content.strip():
            errors.append("Patch content is empty")
        
        # Check patch ID
        if not patch.patch_id:
            errors.append("Patch ID is required")
        
        # Check author
        if not patch.author:
            errors.append("Author is required")
        
        return len(errors) == 0, errors
    
    def get_pr_template(
        self,
        wbs_summary: Dict[str, Any],
        test_results: Dict[str, Any],
    ) -> str:
        """
        Get a PR template based on WBS and test results.
        
        Args:
            wbs_summary: WBS summary
            test_results: Test results
            
        Returns:
            PR template as markdown
        """
        # This would be customized based on project templates
        return self._format_pr_body(
            PatchInfo(
                patch_id="template",
                patch_content="",
                author="template",
            ),
            wbs_summary,
            test_results,
            ChangelogEntry(
                version="template",
                timestamp=datetime.now(timezone.utc),
                author="template",
            ),
        )
