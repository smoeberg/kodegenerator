"""
Approval Gate Service

Human-in-the-loop godkendelse for risikable operationer i sværmen.
Sikrer at ingen kritiske ændringer merges uden menneskelig accept.

Klassificerer ændringer:
- AUTO_APPROVED: docs, tests, små refactors
- NEEDS_APPROVAL: migrationer, security-ændringer, nye credentials, API-kontraktændringer
- BLOCKED: secrets, destruktive operationer
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum, auto
from typing import Any, Dict, List, Optional, TYPE_CHECKING
import uuid

if TYPE_CHECKING:
    from services.webhook_dispatcher import WebhookDispatcher


class ApprovalStatus(Enum):
    """Status for godkendelsesanmodning."""
    PENDING = auto()      # Afventer godkendelse
    APPROVED = auto()     # Godkendt
    DENIED = auto()       # Afvist
    EXPIRED = auto()      # Udløbet (TTL)


class ChangeClassification(Enum):
    """Klassificering af ændringer."""
    AUTO_APPROVED = auto()    # Automatisk godkendt
    NEEDS_APPROVAL = auto()  # Kræver menneskelig godkendelse
    BLOCKED = auto()         # Permanent blokeret


@dataclass(frozen=True)
class Change:
    """Repræsenterer en ændring der skal klassificeres."""
    change_id: str
    title: str
    description: str
    author: str
    files_changed: List[str]
    diff_summary: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def file_extensions(self) -> List[str]:
        """Hent filendelser for ændrede filer."""
        extensions = []
        for file_path in self.files_changed:
            if '.' in file_path:
                ext = file_path.rsplit('.', 1)[-1].lower()
                extensions.append(ext)
        return extensions
    
    @property
    def has_secrets(self) -> bool:
        """Check om ændringen indeholder secrets."""
        # More specific patterns that indicate actual secret values
        secret_patterns = [
            'password', 'passwd', 'api_key', 'apikey',
            'private_key', 'privatekey',
            'aws_access', 'aws_secret', 'gh_token', 'github_token',
            'secret_key', 'secretkey',
        ]
        content = (self.title + self.description + self.diff_summary).lower()
        for pattern in secret_patterns:
            if pattern in content:
                return True
        
        for file_path in self.files_changed:
            file_lower = file_path.lower()
            for pattern in secret_patterns:
                if pattern in file_lower:
                    return True
        
        return False
    
    @property
    def has_destructive_operations(self) -> bool:
        """Check om ændringen indeholder destruktive operationer."""
        destructive_patterns = [
            'drop table', 'drop database', 'delete from', 'truncate',
            'rm -rf', 'rm -r', 'chmod 777', 'chmod -r',
            'rmdir', 'unlink', 'shred', 'dd if=',
            ':(){ :|: & };:',  # fork bomb
        ]
        content = (self.title + self.description + self.diff_summary).lower()
        for pattern in destructive_patterns:
            if pattern in content:
                return True
        return False
    
    @property
    def is_api_contract_change(self) -> bool:
        """Check om ændringen påvirker API kontrakter."""
        api_files = [
            'openapi', 'swagger', 'api_spec', 'api_specs',
            'api.yaml', 'api.yml', 'api.json',
        ]
        api_patterns = [
            'routes.py', 'router.py', 'controller',
        ]
        
        for file_path in self.files_changed:
            file_lower = file_path.lower()
            # Check exact filename matches for api_files
            for pattern in api_files:
                if pattern == file_lower or file_lower.endswith(f'/{pattern}'):
                    return True
            # Check pattern matches for api_patterns
            for pattern in api_patterns:
                if pattern in file_lower:
                    return True
        
        # Also check content for API-related patterns
        content = (self.title + self.description + self.diff_summary).lower()
        api_content_patterns = [
            'api contract', 'api spec', 'openapi', 'swagger',
            'endpoint', 'route', 'rest api', 'graphql',
        ]
        for pattern in api_content_patterns:
            if pattern in content:
                return True
        
        return False
    
    @property
    def is_migration(self) -> bool:
        """Check om ændringen indeholder database migrationer."""
        migration_patterns = [
            'migration', 'migrations', 'alembic', 'flyway',
            'liquibase', 'schema_change', 'alter table',
            'add column', 'drop column', 'modify column',
        ]
        content = (self.title + self.description + self.diff_summary).lower()
        for pattern in migration_patterns:
            if pattern in content:
                return True
        
        for file_path in self.files_changed:
            file_lower = file_path.lower()
            if 'migration' in file_lower or 'alembic' in file_lower:
                return True
        return False
    
    @property
    def is_security_change(self) -> bool:
        """Check om ændringen påvirker sikkerhed."""
        security_patterns = [
            'auth', 'authentication', 'authorization', 'authz',
            'security', 'secure', 'permission', 'role',
            'jwt', 'oauth', 'saml', 'ldap', 'certificate',
            'cipher', 'encrypt', 'decrypt', 'hash',
            'firewall', 'waf', 'rate_limit', 'throttle',
        ]
        content = (self.title + self.description + self.diff_summary).lower()
        for pattern in security_patterns:
            if pattern in content:
                return True
        return False
    
    @property
    def is_new_credential(self) -> bool:
        """Check om ændringen tilføjer nye credentials."""
        credential_patterns = [
            'new user', 'create user', 'add user',
            'new service account', 'service_account',
            'new api key', 'generate token', 'create token',
            'new credential', 'add credential',
        ]
        content_lower = (self.title + self.description + self.diff_summary).lower()
        for pattern in credential_patterns:
            if pattern in content_lower:
                return True
        return False

    
    @property
    def is_doc_change(self) -> bool:
        """Check om ændringen kun påvirker dokumentation."""
        doc_extensions = ['md', 'rst', 'txt', 'adoc', 'asciidoc']
        for ext in self.file_extensions:
            if ext in doc_extensions:
                return True
        return False
    
    @property
    def is_test_change(self) -> bool:
        """Check om ændringen kun påvirker tests."""
        test_patterns = ['test_', '_test.', 'tests/', '.test.', 'spec_']
        for file_path in self.files_changed:
            file_lower = file_path.lower()
            for pattern in test_patterns:
                if pattern in file_lower:
                    return True
        return False
    
    @property
    def is_refactor(self) -> bool:
        """Check om ændringen er et refactor."""
        refactor_patterns = ['refactor', 'refactoring', 'cleanup', 'reorganize']
        content = (self.title + self.description).lower()
        for pattern in refactor_patterns:
            if pattern in content:
                return True
        return False


@dataclass(frozen=True)
class ApprovalRequest:
    """Godkendelsesanmodning."""
    request_id: str
    change: Change
    classification: ChangeClassification
    rationale: str
    risk_score: float  # 0.0 - 10.0, hvor 10.0 er højeste risiko
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc) + timedelta(hours=24))
    reviewer: Optional[str] = None
    review_comment: Optional[str] = None
    approved_at: Optional[datetime] = None
    denied_at: Optional[datetime] = None
    
    @property
    def is_expired(self) -> bool:
        """Check om anmodningen er udløbet."""
        return datetime.now(timezone.utc) > self.expires_at
    
    @property
    def ttl_remaining(self) -> timedelta:
        """Hent resterende TTL."""
        remaining = self.expires_at - datetime.now(timezone.utc)
        return remaining if remaining > timedelta(0) else timedelta(0)
    
    def to_dict(self) -> Dict[str, Any]:
        """Konverter til dictionary."""
        return {
            "request_id": self.request_id,
            "change_id": self.change.change_id,
            "classification": self.classification.name,
            "rationale": self.rationale,
            "risk_score": self.risk_score,
            "status": self.status.name,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "reviewer": self.reviewer,
            "review_comment": self.review_comment,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "denied_at": self.denied_at.isoformat() if self.denied_at else None,
        }


class ApprovalGateError(Exception):
    """Base exception for approval gate errors."""
    pass


class ApprovalGate:
    """
    Human-in-the-loop godkendelsesgate for risikable operationer.
    
    Klassificerer ændringer og håndterer godkendelsesflow.
    
    Hovedfunktioner:
    - classify_change(): Klassificer ændring (AUTO_APPROVED, NEEDS_APPROVAL, BLOCKED)
    - request_approval(): Opret godkendelsesanmodning
    - approve(): Godkend anmodning
    - deny(): Afvis anmodning
    - is_gate_open(): Check om gate er åben
    """
    
    def __init__(
        self,
        *,
        webhook_dispatcher: Optional["WebhookDispatcher"] = None,
        default_ttl_hours: int = 24,
        auto_approve_threshold: float = 2.0,  # Risiko score under dette = auto-godkendt
        block_threshold: float = 9.0,  # Risiko score over dette = blokeret
    ):
        """
        Initialiser ApprovalGate.
        
        Args:
            webhook_dispatcher: Webhook dispatcher for notifikationer
            default_ttl_hours: Standard TTL for anmodninger (timer)
            auto_approve_threshold: Risiko score under dette = auto-godkendt
            block_threshold: Risiko score over dette = blokeret
        """
        self._webhook_dispatcher = webhook_dispatcher
        self._default_ttl_hours = default_ttl_hours
        self._auto_approve_threshold = auto_approve_threshold
        self._block_threshold = block_threshold
        self._requests: Dict[str, ApprovalRequest] = {}
        self._change_classifications: Dict[str, ChangeClassification] = {}
        self._blocked_changes: Dict[str, str] = {}  # change_id -> reason
    
    def classify_change(self, change: Change) -> ChangeClassification:
        """
        Klassificer en ændring baseret på indhold og type.
        
        Args:
            change: Ændringen at klassificere
            
        Returns:
            ChangeClassification (AUTO_APPROVED, NEEDS_APPROVAL, BLOCKED)
        """
        # Check for BLOCKED conditions first
        if change.has_secrets:
            return ChangeClassification.BLOCKED
        
        if change.has_destructive_operations:
            return ChangeClassification.BLOCKED
        
        # Check for NEEDS_APPROVAL conditions
        if change.is_migration:
            return ChangeClassification.NEEDS_APPROVAL
        
        if change.is_security_change:
            return ChangeClassification.NEEDS_APPROVAL
        
        if change.is_new_credential:
            return ChangeClassification.NEEDS_APPROVAL
        
        if change.is_api_contract_change:
            return ChangeClassification.NEEDS_APPROVAL
        
        # Check for AUTO_APPROVED conditions
        if change.is_doc_change and not change.is_test_change:
            # Pure documentation changes
            return ChangeClassification.AUTO_APPROVED
        
        if change.is_test_change:
            # Test changes
            return ChangeClassification.AUTO_APPROVED
        
        if change.is_refactor:
            # Small refactors (assuming they're safe)
            return ChangeClassification.AUTO_APPROVED
        
        # Default: needs approval for safety
        return ChangeClassification.NEEDS_APPROVAL
    
    def calculate_risk_score(self, change: Change, classification: ChangeClassification) -> float:
        """
        Beregn risiko score for en ændring.
        
        Args:
            change: Ændringen
            classification: Klassificeringen
            
        Returns:
            Risiko score (0.0 - 10.0)
        """
        score = 0.0
        
        # Base score based on classification
        if classification == ChangeClassification.BLOCKED:
            score = 10.0
        elif classification == ChangeClassification.NEEDS_APPROVAL:
            score = 5.0
        else:  # AUTO_APPROVED
            score = 1.0
        
        # Adjust based on specific factors
        if change.has_secrets:
            score = min(score + 5.0, 10.0)
        
        if change.has_destructive_operations:
            score = min(score + 5.0, 10.0)
        
        if change.is_migration:
            score = min(score + 2.0, 10.0)
        
        if change.is_security_change:
            score = min(score + 2.0, 10.0)
        
        if change.is_new_credential:
            score = min(score + 3.0, 10.0)
        
        if change.is_api_contract_change:
            score = min(score + 2.5, 10.0)
        
        if change.is_doc_change:
            score = max(score - 1.0, 0.0)
        
        if change.is_test_change:
            score = max(score - 1.0, 0.0)
        
        # Number of files changed
        file_count = len(change.files_changed)
        if file_count > 10:
            score = min(score + (file_count - 10) * 0.1, 10.0)
        
        return round(score, 2)
    
    def generate_rationale(self, change: Change, classification: ChangeClassification) -> str:
        """
        Generer rationale for klassificeringen.
        
        Args:
            change: Ændringen
            classification: Klassificeringen
            
        Returns:
            Rationale tekst
        """
        reasons = []
        
        if classification == ChangeClassification.BLOCKED:
            reasons.append("BLOCKED: This change contains critical issues that cannot be merged.")
            if change.has_secrets:
                reasons.append("- Contains secret/credential information")
            if change.has_destructive_operations:
                reasons.append("- Contains destructive operations")
        
        elif classification == ChangeClassification.NEEDS_APPROVAL:
            reasons.append("NEEDS_APPROVAL: This change requires human review before merging.")
            if change.is_migration:
                reasons.append("- Contains database migrations")
            if change.is_security_change:
                reasons.append("- Affects security components")
            if change.is_new_credential:
                reasons.append("- Creates new credentials")
            if change.is_api_contract_change:
                reasons.append("- Modifies API contracts")
        
        else:  # AUTO_APPROVED
            reasons.append("AUTO_APPROVED: This change is safe to merge automatically.")
            if change.is_doc_change:
                reasons.append("- Documentation only changes")
            if change.is_test_change:
                reasons.append("- Test changes only")
            if change.is_refactor:
                reasons.append("- Minor refactoring")
        
        reasons.append(f"\nDiff Summary: {change.diff_summary[:200]}...")
        
        return "\n".join(reasons)
    
    def request_approval(
        self,
        change: Change,
        custom_ttl_hours: Optional[int] = None,
    ) -> ApprovalRequest:
        """
        Opret en godkendelsesanmodning.
        
        Args:
            change: Ændringen at anmode godkendelse for
            custom_ttl_hours: Custom TTL (timer), default bruger default_ttl_hours
            
        Returns:
            ApprovalRequest med anmodningsdetaljer
        """
        # Klassificer ændringen
        classification = self.classify_change(change)
        
        # Beregn risiko score
        risk_score = self.calculate_risk_score(change, classification)
        
        # Generer rationale
        rationale = self.generate_rationale(change, classification)
        
        # Beregn TTL
        ttl_hours = custom_ttl_hours or self._default_ttl_hours
        expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
        
        # Opret anmodning
        request = ApprovalRequest(
            request_id=str(uuid.uuid4()),
            change=change,
            classification=classification,
            rationale=rationale,
            risk_score=risk_score,
            status=ApprovalStatus.PENDING,
            expires_at=expires_at,
        )
        
        # Gem anmodning
        self._requests[request.request_id] = request
        self._change_classifications[change.change_id] = classification
        
        # Hvis BLOCKED, gem også i blocked list
        if classification == ChangeClassification.BLOCKED:
            self._blocked_changes[change.change_id] = rationale
        
        # Send notifikation via webhook
        if self._webhook_dispatcher:
            self._webhook_dispatcher.dispatch(
                event_type="approval_request_created",
                payload={
                    "request_id": request.request_id,
                    "change_id": change.change_id,
                    "classification": classification.name,
                    "risk_score": risk_score,
                    "status": "PENDING",
                },
            )
        
        return request
    
    def approve(
        self,
        request_id: str,
        reviewer: str,
        comment: Optional[str] = None,
    ) -> ApprovalRequest:
        """
        Godkend en godkendelsesanmodning.
        
        Args:
            request_id: ID for anmodningen at godkende
            reviewer: Navn på reviewer
            comment: Kommentar fra reviewer
            
        Returns:
            Opdateret ApprovalRequest
            
        Raises:
            ApprovalGateError: Hvis anmodning ikke findes eller allerede er behandlet
        """
        if request_id not in self._requests:
            raise ApprovalGateError(f"Approval request {request_id} not found")
        
        request = self._requests[request_id]
        
        if request.status != ApprovalStatus.PENDING:
            raise ApprovalGateError(
                f"Approval request {request_id} is already {request.status.name}"
            )
        
        if request.is_expired:
            raise ApprovalGateError(
                f"Approval request {request_id} has expired"
            )
        
        # Opdater anmodning
        request = ApprovalRequest(
            request_id=request.request_id,
            change=request.change,
            classification=request.classification,
            rationale=request.rationale,
            risk_score=request.risk_score,
            status=ApprovalStatus.APPROVED,
            created_at=request.created_at,
            expires_at=request.expires_at,
            reviewer=reviewer,
            review_comment=comment,
            approved_at=datetime.now(timezone.utc),
            denied_at=None,
        )
        
        # Gem opdateret anmodning
        self._requests[request_id] = request
        
        # Send notifikation via webhook
        if self._webhook_dispatcher:
            self._webhook_dispatcher.dispatch(
                event_type="approval_request_approved",
                payload={
                    "request_id": request.request_id,
                    "change_id": request.change.change_id,
                    "reviewer": reviewer,
                    "comment": comment,
                    "status": "APPROVED",
                },
            )
        
        return request
    
    def deny(
        self,
        request_id: str,
        reviewer: str,
        reason: str,
    ) -> ApprovalRequest:
        """
        Afvis en godkendelsesanmodning.
        
        Args:
            request_id: ID for anmodningen at afvise
            reviewer: Navn på reviewer
            reason: Årsag til afvisning
            
        Returns:
            Opdateret ApprovalRequest
            
        Raises:
            ApprovalGateError: Hvis anmodning ikke findes eller allerede er behandlet
        """
        if request_id not in self._requests:
            raise ApprovalGateError(f"Approval request {request_id} not found")
        
        request = self._requests[request_id]
        
        if request.status != ApprovalStatus.PENDING:
            raise ApprovalGateError(
                f"Approval request {request_id} is already {request.status.name}"
            )
        
        # Opdater anmodning
        request = ApprovalRequest(
            request_id=request.request_id,
            change=request.change,
            classification=request.classification,
            rationale=request.rationale,
            risk_score=request.risk_score,
            status=ApprovalStatus.DENIED,
            created_at=request.created_at,
            expires_at=request.expires_at,
            reviewer=reviewer,
            review_comment=reason,
            approved_at=None,
            denied_at=datetime.now(timezone.utc),
        )
        
        # Gem opdateret anmodning
        self._requests[request_id] = request
        
        # Tilføj til blocked list
        self._blocked_changes[request.change.change_id] = reason
        
        # Send notifikation via webhook
        if self._webhook_dispatcher:
            self._webhook_dispatcher.dispatch(
                event_type="approval_request_denied",
                payload={
                    "request_id": request.request_id,
                    "change_id": request.change.change_id,
                    "reviewer": reviewer,
                    "reason": reason,
                    "status": "DENIED",
                },
            )
        
        return request
    
    def is_gate_open(self, change: Change) -> bool:
        """
        Check om gate er åben for en ændring.
        
        Args:
            change: Ændringen at checke
            
        Returns:
            True hvis gate er åben (AUTO_APPROVED eller godkendt request)
            False hvis gate er lukket (NEEDS_APPROVAL, BLOCKED, eller afvist)
        """
        # Check if change is blocked
        if change.change_id in self._blocked_changes:
            return False
        
        # Check classification
        classification = self._change_classifications.get(change.change_id)
        if classification is None:
            classification = self.classify_change(change)
            self._change_classifications[change.change_id] = classification
        
        if classification == ChangeClassification.BLOCKED:
            return False
        
        if classification == ChangeClassification.AUTO_APPROVED:
            return True
        
        # For NEEDS_APPROVAL, check if there's an approved request
        if classification == ChangeClassification.NEEDS_APPROVAL:
            # Find any request for this change
            for request in self._requests.values():
                if request.change.change_id == change.change_id:
                    if request.status == ApprovalStatus.APPROVED:
                        return True
                    # If pending or denied, gate is closed
                    return False
        
        return False
    
    def check_and_request_approval(
        self,
        change: Change,
        custom_ttl_hours: Optional[int] = None,
    ) -> Tuple[bool, Optional[ApprovalRequest]]:
        """
        Check om gate er åben, og anmod om godkendelse hvis nødvendigt.
        
        Args:
            change: Ændringen at checke
            custom_ttl_hours: Custom TTL for anmodning
            
        Returns:
            Tuple of (is_open, approval_request)
            - is_open: True hvis gate er åben
            - approval_request: Anmodning hvis oprettet, None ellers
        """
        if self.is_gate_open(change):
            return True, None
        
        # Gate is closed, request approval
        request = self.request_approval(change, custom_ttl_hours)
        return False, request
    
    def get_request(self, request_id: str) -> Optional[ApprovalRequest]:
        """Hent en specifik anmodning."""
        return self._requests.get(request_id)
    
    def get_requests_for_change(self, change_id: str) -> List[ApprovalRequest]:
        """Hent alle anmodninger for en ændring."""
        return [
            req for req in self._requests.values()
            if req.change.change_id == change_id
        ]
    
    def get_pending_requests(self) -> List[ApprovalRequest]:
        """Hent alle afventende anmodninger."""
        return [
            req for req in self._requests.values()
            if req.status == ApprovalStatus.PENDING and not req.is_expired
        ]
    
    def get_expired_requests(self) -> List[ApprovalRequest]:
        """Hent alle udløbne anmodninger."""
        return [
            req for req in self._requests.values()
            if req.status == ApprovalStatus.PENDING and req.is_expired
        ]
    
    def cleanup_expired_requests(self) -> List[str]:
        """
        Ryd op i udløbne anmodninger ved at markere dem som EXPIRED.
        
        Returns:
            Liste af request_ids der blev markeret som udløbet
        """
        expired_ids = []
        
        for request_id, request in list(self._requests.items()):
            if request.status == ApprovalStatus.PENDING and request.is_expired:
                # Opdater til EXPIRED
                request = ApprovalRequest(
                    request_id=request.request_id,
                    change=request.change,
                    classification=request.classification,
                    rationale=request.rationale,
                    risk_score=request.risk_score,
                    status=ApprovalStatus.EXPIRED,
                    created_at=request.created_at,
                    expires_at=request.expires_at,
                    reviewer=None,
                    review_comment="Request expired - automatic deny",
                    approved_at=None,
                    denied_at=datetime.now(timezone.utc),
                )
                
                self._requests[request_id] = request
                self._blocked_changes[request.change.change_id] = "Request expired"
                expired_ids.append(request_id)
                
                # Send notifikation via webhook
                if self._webhook_dispatcher:
                    self._webhook_dispatcher.dispatch(
                        event_type="approval_request_expired",
                        payload={
                            "request_id": request.request_id,
                            "change_id": request.change.change_id,
                            "status": "EXPIRED",
                            "reason": "Request expired - automatic deny",
                        },
                    )
        
        return expired_ids
    
    def get_classification(self, change: Change) -> ChangeClassification:
        """Hent klassificering for en ændring."""
        return self._change_classifications.get(
            change.change_id,
            self.classify_change(change)
        )
    
    def get_blocked_changes(self) -> Dict[str, str]:
        """Hent alle blokerede ændringer med årsag."""
        return dict(self._blocked_changes)
    
    def clear(self) -> None:
        """Ryd alle anmodninger og klassificeringer."""
        self._requests.clear()
        self._change_classifications.clear()
        self._blocked_changes.clear()
