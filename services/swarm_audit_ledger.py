"""
Swarm Audit Ledger Service

Uforanderlig, kryptografisk verificerbar revisionslog over alle handlinger 
og patches i sværmen.

Implementerer en blockchain-lignende kæde hvor hver hændelse hashes 
sammen med previous_hash, payload_hash og signature for at sikre integritet.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
import uuid

if TYPE_CHECKING:
    from domain.task import Task
    from domain.task_execution import TaskExecutionReceipt


class SwarmEventType(Enum):
    """Typer af hændelser i swarm audit ledger."""
    TASK_ENQUEUED = auto()
    TASK_CLAIMED = auto()
    PATCH_PRODUCED = auto()
    SENTINEL_VERIFIED = auto()
    TASK_COMPLETED = auto()


@dataclass(frozen=True)
class SwarmEvent:
    """En uforanderlig hændelse i audit ledger."""
    event_id: str
    event_type: SwarmEventType
    timestamp: datetime
    project_id: str
    task_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    previous_hash: str = ""
    payload_hash: str = ""
    signature: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Konverter til dictionary for JSON serialisering."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.name,
            "timestamp": self.timestamp.isoformat(),
            "project_id": self.project_id,
            "task_id": self.task_id,
            "payload": self.payload,
            "previous_hash": self.previous_hash,
            "payload_hash": self.payload_hash,
            "signature": self.signature,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any], secret_key: Optional[str] = None) -> "SwarmEvent":
        """Opret SwarmEvent fra dictionary."""
        return cls(
            event_id=data["event_id"],
            event_type=SwarmEventType[data["event_type"]],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            project_id=data["project_id"],
            task_id=data.get("task_id"),
            payload=data.get("payload", {}),
            previous_hash=data.get("previous_hash", ""),
            payload_hash=data.get("payload_hash", ""),
            signature=data.get("signature", ""),
        )


@dataclass(frozen=True)
class ExecutionState:
    """Tilstand efter replay af hændelseskæde."""
    project_id: str
    current_tasks: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    completed_tasks: List[str] = field(default_factory=list)
    patches: List[Dict[str, Any]] = field(default_factory=list)
    verification_results: List[Dict[str, Any]] = field(default_factory=list)
    last_event_hash: str = ""
    is_consistent: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Konverter til dictionary."""
        return {
            "project_id": self.project_id,
            "current_tasks": self.current_tasks,
            "completed_tasks": self.completed_tasks,
            "patches": self.patches,
            "verification_results": self.verification_results,
            "last_event_hash": self.last_event_hash,
            "is_consistent": self.is_consistent,
        }


class SwarmAuditLedgerError(Exception):
    """Base exception for audit ledger errors."""
    pass


class IntegrityError(SwarmAuditLedgerError):
    """Raised when integrity verification fails."""
    pass


class SwarmAuditLedger:
    """
    Uforanderlig, kryptografisk verificerbar revisionslog.
    
    Hver hændelse hashes i en SHA-256 blockchain-lignende kæde med:
    - previous_hash: Hash af forrige hændelse
    - payload_hash: Hash af hændelsens payload
    - signature: HMAC signatur for autenticitet
    
    Hovedfunktioner:
    - record_event(): Tilføj ny hændelse til kæden
    - verify_integrity(): Verificer at ingen hændelser er blevet manipuleret
    - replay_project(): Genspil hele tilstanden fra hændelseskæden
    - export_jsonld(): Eksportér audit-log som JSON-LD
    """
    
    def __init__(
        self,
        *,
        secret_key: Optional[str] = None,
        initial_hash: str = "0" * 64,  # Genesis block
    ):
        """
        Initialiser audit ledger.
        
        Args:
            secret_key: Hemmelig nøgle til HMAC signaturer
            initial_hash: Initial hash (genesis block)
        """
        self._secret_key = secret_key or str(uuid.uuid4())
        self._initial_hash = initial_hash
        self._chain: List[SwarmEvent] = []
        self._event_index: Dict[str, SwarmEvent] = {}
        self._project_events: Dict[str, List[SwarmEvent]] = {}
    
    def _compute_payload_hash(self, payload: Dict[str, Any]) -> str:
        """Beregn SHA-256 hash af payload."""
        payload_str = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
    
    def _compute_event_hash(self, event: SwarmEvent) -> str:
        """Beregn hash af en hændelse."""
        event_data = {
            "event_id": event.event_id,
            "event_type": event.event_type.name,
            "timestamp": event.timestamp.isoformat(),
            "project_id": event.project_id,
            "task_id": event.task_id,
            "payload": event.payload,
            "previous_hash": event.previous_hash,
            "payload_hash": event.payload_hash,
        }
        event_str = json.dumps(event_data, sort_keys=True, default=str)
        return hashlib.sha256(event_str.encode("utf-8")).hexdigest()
    
    def _create_signature(self, data: str) -> str:
        """Opret HMAC signatur."""
        return hmac.new(
            self._secret_key.encode("utf-8"),
            data.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    
    def record_event(
        self,
        event_type: SwarmEventType,
        project_id: str,
        task_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> SwarmEvent:
        """
        Tilføj ny hændelse til kæden.
        
        Args:
            event_type: Type af hændelse
            project_id: Projekt ID
            task_id: Task ID (valgfrit)
            payload: Payload data (valgfrit)
            
        Returns:
            Den oprettede SwarmEvent
        """
        payload = payload or {}
        
        # Beregn payload hash
        payload_hash = self._compute_payload_hash(payload)
        
        # Beregn previous hash (hash af sidste hændelse i kæden)
        if self._chain:
            previous_hash = self._compute_event_hash(self._chain[-1])
        else:
            previous_hash = self._initial_hash
        
        # Opret hændelse
        event = SwarmEvent(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            project_id=project_id,
            task_id=task_id,
            payload=payload,
            previous_hash=previous_hash,
            payload_hash=payload_hash,
            signature="",  # Vil blive sat nedenfor
        )
        
        # Beregn signatur
        event_data_for_signing = {
            "event_id": event.event_id,
            "event_type": event.event_type.name,
            "timestamp": event.timestamp.isoformat(),
            "project_id": event.project_id,
            "task_id": event.task_id,
            "payload_hash": event.payload_hash,
            "previous_hash": event.previous_hash,
        }
        signature_data = json.dumps(event_data_for_signing, sort_keys=True, default=str)
        event = dataclasses.replace(event, signature=self._create_signature(signature_data))
        
        # Tilføj til kæden
        self._chain.append(event)
        self._event_index[event.event_id] = event
        
        # Indexer efter projekt
        if project_id not in self._project_events:
            self._project_events[project_id] = []
        self._project_events[project_id].append(event)
        
        return event
    
    def record_task_enqueued(
        self,
        project_id: str,
        task_id: str,
        task_data: Optional[Dict[str, Any]] = None,
    ) -> SwarmEvent:
        """Record TASK_ENQUEUED hændelse."""
        payload = task_data or {"task_id": task_id, "status": "enqueued"}
        return self.record_event(
            event_type=SwarmEventType.TASK_ENQUEUED,
            project_id=project_id,
            task_id=task_id,
            payload=payload,
        )
    
    def record_task_claimed(
        self,
        project_id: str,
        task_id: str,
        worker_id: str,
    ) -> SwarmEvent:
        """Record TASK_CLAIMED hændelse."""
        return self.record_event(
            event_type=SwarmEventType.TASK_CLAIMED,
            project_id=project_id,
            task_id=task_id,
            payload={"task_id": task_id, "worker_id": worker_id, "status": "claimed"},
        )
    
    def record_patch_produced(
        self,
        project_id: str,
        task_id: str,
        patch_data: Dict[str, Any],
    ) -> SwarmEvent:
        """Record PATCH_PRODUCED hændelse."""
        return self.record_event(
            event_type=SwarmEventType.PATCH_PRODUCED,
            project_id=project_id,
            task_id=task_id,
            payload={"task_id": task_id, "patch": patch_data, "status": "patch_produced"},
        )
    
    def record_sentinel_verified(
        self,
        project_id: str,
        task_id: str,
        verification_result: Dict[str, Any],
    ) -> SwarmEvent:
        """Record SENTINEL_VERIFIED hændelse."""
        return self.record_event(
            event_type=SwarmEventType.SENTINEL_VERIFIED,
            project_id=project_id,
            task_id=task_id,
            payload={"task_id": task_id, "verification": verification_result, "status": "verified"},
        )
    
    def record_task_completed(
        self,
        project_id: str,
        task_id: str,
        result: Optional[Dict[str, Any]] = None,
    ) -> SwarmEvent:
        """Record TASK_COMPLETED hændelse."""
        payload = result or {"task_id": task_id, "status": "completed"}
        return self.record_event(
            event_type=SwarmEventType.TASK_COMPLETED,
            project_id=project_id,
            task_id=task_id,
            payload=payload,
        )
    
    def verify_integrity(self) -> bool:
        """
        Verificer at ingen hændelser er blevet manipuleret.
        
        Returns:
            True hvis kæden er intakt, False hvis der er manipulation
        """
        if not self._chain:
            return True  # Tom kæde er intakt
        
        # Verificer hver hændelse i kæden
        for i, event in enumerate(self._chain):
            # Beregn forventet previous_hash
            if i == 0:
                expected_previous_hash = self._initial_hash
            else:
                expected_previous_hash = self._compute_event_hash(self._chain[i-1])
            
            if event.previous_hash != expected_previous_hash:
                return False
            
            # Beregn forventet payload_hash
            expected_payload_hash = self._compute_payload_hash(event.payload)
            if event.payload_hash != expected_payload_hash:
                return False
            
            # Verificer signatur
            event_data_for_verification = {
                "event_id": event.event_id,
                "event_type": event.event_type.name,
                "timestamp": event.timestamp.isoformat(),
                "project_id": event.project_id,
                "task_id": event.task_id,
                "payload_hash": event.payload_hash,
                "previous_hash": event.previous_hash,
            }
            signature_data = json.dumps(event_data_for_verification, sort_keys=True, default=str)
            expected_signature = self._create_signature(signature_data)
            
            if event.signature != expected_signature:
                return False
        
        return True
    
    def verify_integrity_detailed(self) -> Tuple[bool, List[str]]:
        """
        Verificer integritet med detaljerede fejlbeskeder.
        
        Returns:
            Tuple of (is_valid, list of errors)
        """
        errors = []
        
        if not self._chain:
            return True, []
        
        for i, event in enumerate(self._chain):
            # Check previous_hash
            if i == 0:
                expected_previous_hash = self._initial_hash
            else:
                expected_previous_hash = self._compute_event_hash(self._chain[i-1])
            
            if event.previous_hash != expected_previous_hash:
                errors.append(f"Event {event.event_id}: previous_hash mismatch at index {i}")
            
            # Check payload_hash
            expected_payload_hash = self._compute_payload_hash(event.payload)
            if event.payload_hash != expected_payload_hash:
                errors.append(f"Event {event.event_id}: payload_hash mismatch at index {i}")
            
            # Check signature
            event_data_for_verification = {
                "event_id": event.event_id,
                "event_type": event.event_type.name,
                "timestamp": event.timestamp.isoformat(),
                "project_id": event.project_id,
                "task_id": event.task_id,
                "payload_hash": event.payload_hash,
                "previous_hash": event.previous_hash,
            }
            signature_data = json.dumps(event_data_for_verification, sort_keys=True, default=str)
            expected_signature = self._create_signature(signature_data)
            
            if event.signature != expected_signature:
                errors.append(f"Event {event.event_id}: signature mismatch at index {i}")
        
        return len(errors) == 0, errors
    
    def replay_project(self, project_id: str) -> ExecutionState:
        """
        Genspil hele tilstanden deterministisk fra hændelseskæden.
        
        Args:
            project_id: Projekt ID at replay
            
        Returns:
            ExecutionState med den genspillede tilstand
        """
        if project_id not in self._project_events:
            raise SwarmAuditLedgerError(f"Project {project_id} not found in ledger")
        
        events = self._project_events[project_id]
        
        # Replay hændelser i rækkefølge
        current_tasks: Dict[str, Dict[str, Any]] = {}
        completed_tasks: List[str] = []
        patches: List[Dict[str, Any]] = []
        verification_results: List[Dict[str, Any]] = []
        
        for event in events:
            if event.event_type == SwarmEventType.TASK_ENQUEUED:
                # Tilføj task til current_tasks
                current_tasks[event.task_id or ""] = {
                    "task_id": event.task_id,
                    "status": "enqueued",
                    "timestamp": event.timestamp.isoformat(),
                    **event.payload,
                }
            
            elif event.event_type == SwarmEventType.TASK_CLAIMED:
                # Opdater task status
                task_id = event.task_id or ""
                if task_id in current_tasks:
                    current_tasks[task_id]["status"] = "claimed"
                    current_tasks[task_id]["worker_id"] = event.payload.get("worker_id")
                    current_tasks[task_id]["claimed_at"] = event.timestamp.isoformat()
            
            elif event.event_type == SwarmEventType.PATCH_PRODUCED:
                # Tilføj patch
                task_id = event.task_id or ""
                if task_id in current_tasks:
                    current_tasks[task_id]["status"] = "patch_produced"
                patches.append({
                    "task_id": task_id,
                    "patch": event.payload.get("patch"),
                    "timestamp": event.timestamp.isoformat(),
                })
            
            elif event.event_type == SwarmEventType.SENTINEL_VERIFIED:
                # Tilføj verification result
                task_id = event.task_id or ""
                if task_id in current_tasks:
                    current_tasks[task_id]["status"] = "verified"
                verification_results.append({
                    "task_id": task_id,
                    "verification": event.payload.get("verification"),
                    "timestamp": event.timestamp.isoformat(),
                })
            
            elif event.event_type == SwarmEventType.TASK_COMPLETED:
                # Flyt task til completed
                task_id = event.task_id or ""
                if task_id in current_tasks:
                    completed_tasks.append(task_id)
                    current_tasks[task_id]["status"] = "completed"
                    current_tasks[task_id]["completed_at"] = event.timestamp.isoformat()
                    current_tasks[task_id]["result"] = event.payload
        
        # Beregn last_event_hash
        if events:
            last_event_hash = self._compute_event_hash(events[-1])
        else:
            last_event_hash = self._initial_hash
        
        # Check konsistens
        is_consistent = self.verify_integrity()
        
        return ExecutionState(
            project_id=project_id,
            current_tasks=current_tasks,
            completed_tasks=completed_tasks,
            patches=patches,
            verification_results=verification_results,
            last_event_hash=last_event_hash,
            is_consistent=is_consistent,
        )
    
    def get_project_events(self, project_id: str) -> List[SwarmEvent]:
        """Hent alle hændelser for et projekt."""
        return self._project_events.get(project_id, [])
    
    def get_all_events(self) -> List[SwarmEvent]:
        """Hent alle hændelser."""
        return list(self._chain)
    
    def get_event(self, event_id: str) -> Optional[SwarmEvent]:
        """Hent specifik hændelse."""
        return self._event_index.get(event_id)
    
    def export_jsonld(self) -> Dict[str, Any]:
        """
        Eksportér audit-log som JSON-LD.
        
        Returns:
            JSON-LD struktur med alle hændelser
        """
        jsonld = {
            "@context": {
                "swarm": "https://schema.swarm.org/",
                "event": "swarm:SwarmEvent",
                "eventType": "swarm:eventType",
                "timestamp": "http://schema.org/dateTime",
                "projectId": "swarm:projectId",
                "taskId": "swarm:taskId",
                "previousHash": "swarm:previousHash",
                "payloadHash": "swarm:payloadHash",
                "signature": "swarm:signature",
            },
            "@type": "swarm:SwarmAuditLedger",
            "events": [event.to_dict() for event in self._chain],
            "chain_length": len(self._chain),
            "initial_hash": self._initial_hash,
            "is_valid": self.verify_integrity(),
        }
        
        return jsonld
    
    def export_json(self) -> str:
        """Eksportér audit-log som JSON string."""
        return json.dumps(self.export_jsonld(), indent=2, default=str)
    
    def import_from_jsonld(self, data: Dict[str, Any]) -> None:
        """
        Importer audit-log fra JSON-LD.
        
        Args:
            data: JSON-LD struktur
        """
        events = data.get("events", [])
        
        for event_data in events:
            event = SwarmEvent.from_dict(event_data)
            self._chain.append(event)
            self._event_index[event.event_id] = event
            
            if event.project_id not in self._project_events:
                self._project_events[event.project_id] = []
            self._project_events[event.project_id].append(event)
    
    def import_from_json(self, json_str: str) -> None:
        """Importer audit-log fra JSON string."""
        data = json.loads(json_str)
        self.import_from_jsonld(data)
    
    def clear(self) -> None:
        """Ryd ledger."""
        self._chain.clear()
        self._event_index.clear()
        self._project_events.clear()


# Import dataclasses for replace function
import dataclasses
