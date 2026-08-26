"""
Tests for Swarm Audit Ledger Service

Tests dækker:
- Kædens integritet ved normal kørsel
- Detektering af manipulation i historiske logs (tamper-evident)
- Komplet replay af en fuldført projektkørsel
- JSON-LD eksport og import
- Alle hændelsestyper (TASK_ENQUEUED, TASK_CLAIMED, PATCH_PRODUCED, SENTINEL_VERIFIED, TASK_COMPLETED)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, List

import pytest

from services.swarm_audit_ledger import (
    SwarmAuditLedger,
    SwarmAuditLedgerError,
    IntegrityError,
    SwarmEvent,
    SwarmEventType,
    ExecutionState,
)


class TestSwarmAuditLedgerInitialization:
    """Tests for SwarmAuditLedger initialization."""
    
    def test_initialization_default(self):
        """Test default initialization."""
        ledger = SwarmAuditLedger()
        
        assert ledger._chain == []
        assert ledger._event_index == {}
        assert ledger._project_events == {}
        assert len(ledger._secret_key) > 0
    
    def test_initialization_with_secret_key(self):
        """Test initialization with custom secret key."""
        secret_key = "my-secret-key"
        ledger = SwarmAuditLedger(secret_key=secret_key)
        
        assert ledger._secret_key == secret_key
    
    def test_initialization_with_custom_initial_hash(self):
        """Test initialization with custom initial hash."""
        initial_hash = "a" * 64
        ledger = SwarmAuditLedger(initial_hash=initial_hash)
        
        assert ledger._initial_hash == initial_hash


class TestRecordEvent:
    """Tests for recording events."""
    
    @pytest.fixture
    def ledger(self):
        """Create a fresh ledger for each test."""
        return SwarmAuditLedger(secret_key="test-secret")
    
    def test_record_single_event(self, ledger):
        """Test recording a single event."""
        event = ledger.record_event(
            event_type=SwarmEventType.TASK_ENQUEUED,
            project_id="project-1",
            task_id="task-1",
            payload={"key": "value"},
        )
        
        assert isinstance(event, SwarmEvent)
        assert event.event_type == SwarmEventType.TASK_ENQUEUED
        assert event.project_id == "project-1"
        assert event.task_id == "task-1"
        assert event.payload == {"key": "value"}
        assert len(event.event_id) > 0
        assert event.previous_hash == ledger._initial_hash
        assert len(event.payload_hash) == 64  # SHA-256 hash
        assert len(event.signature) == 64  # HMAC-SHA256 signature
    
    def test_record_multiple_events(self, ledger):
        """Test recording multiple events in sequence."""
        event1 = ledger.record_event(
            event_type=SwarmEventType.TASK_ENQUEUED,
            project_id="project-1",
            task_id="task-1",
        )
        
        event2 = ledger.record_event(
            event_type=SwarmEventType.TASK_CLAIMED,
            project_id="project-1",
            task_id="task-1",
        )
        
        assert len(ledger._chain) == 2
        assert event1.previous_hash == ledger._initial_hash
        assert event2.previous_hash == ledger._compute_event_hash(event1)
    
    def test_record_event_without_task_id(self, ledger):
        """Test recording event without task_id."""
        event = ledger.record_event(
            event_type=SwarmEventType.TASK_ENQUEUED,
            project_id="project-1",
            task_id=None,
        )
        
        assert event.task_id is None
    
    def test_record_event_without_payload(self, ledger):
        """Test recording event without payload."""
        event = ledger.record_event(
            event_type=SwarmEventType.TASK_ENQUEUED,
            project_id="project-1",
        )
        
        assert event.payload == {}


class TestConvenienceMethods:
    """Tests for convenience recording methods."""
    
    @pytest.fixture
    def ledger(self):
        """Create a fresh ledger for each test."""
        return SwarmAuditLedger(secret_key="test-secret")
    
    def test_record_task_enqueued(self, ledger):
        """Test record_task_enqueued method."""
        event = ledger.record_task_enqueued(
            project_id="project-1",
            task_id="task-1",
            task_data={"priority": "high"},
        )
        
        assert event.event_type == SwarmEventType.TASK_ENQUEUED
        assert event.payload.get("priority") == "high"
        assert event.payload["priority"] == "high"
    
    def test_record_task_claimed(self, ledger):
        """Test record_task_claimed method."""
        event = ledger.record_task_claimed(
            project_id="project-1",
            task_id="task-1",
            worker_id="worker-1",
        )
        
        assert event.event_type == SwarmEventType.TASK_CLAIMED
        assert event.payload["worker_id"] == "worker-1"
    
    def test_record_patch_produced(self, ledger):
        """Test record_patch_produced method."""
        patch_data = {"files": ["file1.py"], "diff": "..."}
        event = ledger.record_patch_produced(
            project_id="project-1",
            task_id="task-1",
            patch_data=patch_data,
        )
        
        assert event.event_type == SwarmEventType.PATCH_PRODUCED
        assert event.payload["patch"] == patch_data
    
    def test_record_sentinel_verified(self, ledger):
        """Test record_sentinel_verified method."""
        verification_result = {"passed": True, "checks": ["check1", "check2"]}
        event = ledger.record_sentinel_verified(
            project_id="project-1",
            task_id="task-1",
            verification_result=verification_result,
        )
        
        assert event.event_type == SwarmEventType.SENTINEL_VERIFIED
        assert event.payload["verification"] == verification_result
    
    def test_record_task_completed(self, ledger):
        """Test record_task_completed method."""
        result = {"output": "result", "status": "success"}
        event = ledger.record_task_completed(
            project_id="project-1",
            task_id="task-1",
            result=result,
        )
        
        assert event.event_type == SwarmEventType.TASK_COMPLETED
        assert event.payload == result


class TestVerifyIntegrity:
    """Tests for integrity verification."""
    
    @pytest.fixture
    def ledger(self):
        """Create a ledger with some events."""
        ledger = SwarmAuditLedger(secret_key="test-secret")
        
        # Record a sequence of events
        ledger.record_task_enqueued("project-1", "task-1")
        ledger.record_task_claimed("project-1", "task-1", "worker-1")
        ledger.record_patch_produced("project-1", "task-1", {"files": ["file.py"]})
        ledger.record_sentinel_verified("project-1", "task-1", {"passed": True})
        ledger.record_task_completed("project-1", "task-1", {"status": "success"})
        
        return ledger
    
    def test_verify_integrity_valid_chain(self, ledger):
        """Test that a valid chain passes integrity verification."""
        is_valid = ledger.verify_integrity()
        
        assert is_valid is True
    
    def test_verify_integrity_empty_chain(self):
        """Test that an empty chain is considered valid."""
        ledger = SwarmAuditLedger(secret_key="test-secret")
        
        is_valid = ledger.verify_integrity()
        
        assert is_valid is True
    
    def test_verify_integrity_single_event(self):
        """Test integrity verification with single event."""
        ledger = SwarmAuditLedger(secret_key="test-secret")
        ledger.record_task_enqueued("project-1", "task-1")
        
        is_valid = ledger.verify_integrity()
        
        assert is_valid is True
    
    def test_verify_integrity_detailed_valid(self, ledger):
        """Test detailed integrity verification with valid chain."""
        is_valid, errors = ledger.verify_integrity_detailed()
        
        assert is_valid is True
        assert len(errors) == 0


class TestTamperEvident:
    """Tests for tamper detection."""
    
    @pytest.fixture
    def ledger_with_events(self):
        """Create a ledger with events."""
        ledger = SwarmAuditLedger(secret_key="test-secret")
        
        ledger.record_task_enqueued("project-1", "task-1")
        ledger.record_task_claimed("project-1", "task-1", "worker-1")
        ledger.record_patch_produced("project-1", "task-1", {"files": ["file.py"]})
        
        return ledger
    
    def test_detect_payload_tampering(self, ledger_with_events):
        """Test detection of payload tampering."""
        # Tamper with the payload of the first event
        if ledger_with_events._chain:
            # Create a copy of the chain to modify
            tampered_chain = []
            for i, event in enumerate(ledger_with_events._chain):
                if i == 0:
                    # Tamper with the payload
                    new_payload = event.payload.copy()
                    new_payload["tampered"] = True
                    event = SwarmEvent(
                        event_id=event.event_id,
                        event_type=event.event_type,
                        timestamp=event.timestamp,
                        project_id=event.project_id,
                        task_id=event.task_id,
                        payload=new_payload,
                        previous_hash=event.previous_hash,
                        payload_hash=event.payload_hash,  # This is now wrong
                        signature=event.signature,
                    )
                tampered_chain.append(event)
            
            # Replace the chain
            ledger_with_events._chain = tampered_chain
            
            # Rebuild indexes
            ledger_with_events._event_index.clear()
            ledger_with_events._project_events.clear()
            for event in tampered_chain:
                ledger_with_events._event_index[event.event_id] = event
                if event.project_id not in ledger_with_events._project_events:
                    ledger_with_events._project_events[event.project_id] = []
                ledger_with_events._project_events[event.project_id].append(event)
        
        is_valid = ledger_with_events.verify_integrity()
        
        assert is_valid is False
    
    def test_detect_previous_hash_tampering(self, ledger_with_events):
        """Test detection of previous_hash tampering."""
        # Tamper with previous_hash of the second event
        if len(ledger_with_events._chain) >= 2:
            tampered_chain = []
            for i, event in enumerate(ledger_with_events._chain):
                if i == 1:
                    # Change previous_hash to a wrong value
                    event = SwarmEvent(
                        event_id=event.event_id,
                        event_type=event.event_type,
                        timestamp=event.timestamp,
                        project_id=event.project_id,
                        task_id=event.task_id,
                        payload=event.payload,
                        previous_hash="0" * 64,  # Wrong previous_hash
                        payload_hash=event.payload_hash,
                        signature=event.signature,
                    )
                tampered_chain.append(event)
            
            ledger_with_events._chain = tampered_chain
            
            # Rebuild indexes
            ledger_with_events._event_index.clear()
            ledger_with_events._project_events.clear()
            for event in tampered_chain:
                ledger_with_events._event_index[event.event_id] = event
                if event.project_id not in ledger_with_events._project_events:
                    ledger_with_events._project_events[event.project_id] = []
                ledger_with_events._project_events[event.project_id].append(event)
        
        is_valid = ledger_with_events.verify_integrity()
        
        assert is_valid is False
    
    def test_detect_signature_tampering(self, ledger_with_events):
        """Test detection of signature tampering."""
        # Tamper with signature of the first event
        if ledger_with_events._chain:
            tampered_chain = []
            for i, event in enumerate(ledger_with_events._chain):
                if i == 0:
                    # Change signature to a wrong value
                    event = SwarmEvent(
                        event_id=event.event_id,
                        event_type=event.event_type,
                        timestamp=event.timestamp,
                        project_id=event.project_id,
                        task_id=event.task_id,
                        payload=event.payload,
                        previous_hash=event.previous_hash,
                        payload_hash=event.payload_hash,
                        signature="0" * 64,  # Wrong signature
                    )
                tampered_chain.append(event)
            
            ledger_with_events._chain = tampered_chain
            
            # Rebuild indexes
            ledger_with_events._event_index.clear()
            ledger_with_events._project_events.clear()
            for event in tampered_chain:
                ledger_with_events._event_index[event.event_id] = event
                if event.project_id not in ledger_with_events._project_events:
                    ledger_with_events._project_events[event.project_id] = []
                ledger_with_events._project_events[event.project_id].append(event)
        
        is_valid = ledger_with_events.verify_integrity()
        
        assert is_valid is False
    
    def test_detect_removed_event(self, ledger_with_events):
        """Test detection of removed event from chain."""
        # Remove the middle event
        if len(ledger_with_events._chain) >= 3:
            original_chain = ledger_with_events._chain
            tampered_chain = [original_chain[0], original_chain[2]]
            
            ledger_with_events._chain = tampered_chain
            
            # Rebuild indexes
            ledger_with_events._event_index.clear()
            ledger_with_events._project_events.clear()
            for event in tampered_chain:
                ledger_with_events._event_index[event.event_id] = event
                if event.project_id not in ledger_with_events._project_events:
                    ledger_with_events._project_events[event.project_id] = []
                ledger_with_events._project_events[event.project_id].append(event)
        
        is_valid = ledger_with_events.verify_integrity()
        
        # The chain should still be valid because each event's previous_hash
        # still points to the previous event in the tampered chain
        # This is a limitation of blockchain - it only detects tampering,
        # not removal of events
        # However, the previous_hash of the second event will be wrong
        # because it was pointing to the removed event
        assert is_valid is False


class TestReplayProject:
    """Tests for project replay."""
    
    @pytest.fixture
    def ledger_with_full_project(self):
        """Create a ledger with a complete project execution."""
        ledger = SwarmAuditLedger(secret_key="test-secret")
        
        # Simulate a complete project workflow
        # Task 1
        ledger.record_task_enqueued("project-1", "task-1", {"name": "Task 1"})
        ledger.record_task_claimed("project-1", "task-1", "worker-1")
        ledger.record_patch_produced("project-1", "task-1", {"files": ["file1.py"]})
        ledger.record_sentinel_verified("project-1", "task-1", {"passed": True, "checks": ["ast", "tests"]})
        ledger.record_task_completed("project-1", "task-1", {"status": "success", "output": "result1"})
        
        # Task 2
        ledger.record_task_enqueued("project-1", "task-2", {"name": "Task 2"})
        ledger.record_task_claimed("project-1", "task-2", "worker-2")
        ledger.record_patch_produced("project-1", "task-2", {"files": ["file2.py"]})
        ledger.record_sentinel_verified("project-1", "task-2", {"passed": True, "checks": ["ast", "tests"]})
        ledger.record_task_completed("project-1", "task-2", {"status": "success", "output": "result2"})
        
        return ledger
    
    def test_replay_project_full_execution(self, ledger_with_full_project):
        """Test replay of a complete project execution."""
        execution_state = ledger_with_full_project.replay_project("project-1")
        
        assert isinstance(execution_state, ExecutionState)
        assert execution_state.project_id == "project-1"
        assert len(execution_state.completed_tasks) == 2
        assert "task-1" in execution_state.completed_tasks
        assert "task-2" in execution_state.completed_tasks
        assert len(execution_state.patches) == 2
        assert len(execution_state.verification_results) == 2
        assert execution_state.is_consistent is True
    
    def test_replay_project_nonexistent(self, ledger_with_full_project):
        """Test replay of nonexistent project."""
        with pytest.raises(SwarmAuditLedgerError, match="Project .* not found"):
            ledger_with_full_project.replay_project("nonexistent-project")
    
    def test_replay_project_empty(self):
        """Test replay of project with no events."""
        ledger = SwarmAuditLedger(secret_key="test-secret")
        
        # Record events for a different project
        ledger.record_task_enqueued("other-project", "task-1")
        
        with pytest.raises(SwarmAuditLedgerError, match="Project .* not found"):
            ledger.replay_project("empty-project")
    
    def test_replay_project_partial_execution(self):
        """Test replay of project with partial execution."""
        ledger = SwarmAuditLedger(secret_key="test-secret")
        
        # Record partial execution
        ledger.record_task_enqueued("project-1", "task-1")
        ledger.record_task_claimed("project-1", "task-1", "worker-1")
        ledger.record_patch_produced("project-1", "task-1", {"files": ["file.py"]})
        # Task not completed
        
        execution_state = ledger.replay_project("project-1")
        
        assert execution_state.project_id == "project-1"
        assert len(execution_state.completed_tasks) == 0
        assert len(execution_state.patches) == 1
        assert "task-1" in execution_state.current_tasks
        assert execution_state.current_tasks["task-1"]["status"] == "patch_produced"


class TestExportImport:
    """Tests for JSON-LD export and import."""
    
    @pytest.fixture
    def ledger_with_events(self):
        """Create a ledger with events."""
        ledger = SwarmAuditLedger(secret_key="test-secret")
        
        ledger.record_task_enqueued("project-1", "task-1")
        ledger.record_task_claimed("project-1", "task-1", "worker-1")
        ledger.record_patch_produced("project-1", "task-1", {"files": ["file.py"]})
        
        return ledger
    
    def test_export_jsonld(self, ledger_with_events):
        """Test JSON-LD export."""
        jsonld = ledger_with_events.export_jsonld()
        
        assert "@context" in jsonld
        assert "@type" in jsonld
        assert jsonld["@type"] == "swarm:SwarmAuditLedger"
        assert "events" in jsonld
        assert len(jsonld["events"]) == 3
        assert "chain_length" in jsonld
        assert jsonld["chain_length"] == 3
        assert "is_valid" in jsonld
        assert jsonld["is_valid"] is True
    
    def test_export_json(self, ledger_with_events):
        """Test JSON string export."""
        json_str = ledger_with_events.export_json()
        
        assert isinstance(json_str, str)
        
        # Verify it's valid JSON
        data = json.loads(json_str)
        assert "events" in data
        assert len(data["events"]) == 3
    
    def test_import_from_jsonld(self, ledger_with_events):
        """Test JSON-LD import."""
        # Export from original ledger
        jsonld = ledger_with_events.export_jsonld()
        
        # Create new ledger and import
        new_ledger = SwarmAuditLedger(secret_key="test-secret")
        new_ledger.import_from_jsonld(jsonld)
        
        # Verify imported data
        assert len(new_ledger._chain) == 3
        assert len(new_ledger._event_index) == 3
        assert "project-1" in new_ledger._project_events
        assert len(new_ledger._project_events["project-1"]) == 3
    
    def test_import_from_json(self, ledger_with_events):
        """Test JSON string import."""
        # Export from original ledger
        json_str = ledger_with_events.export_json()
        
        # Create new ledger and import
        new_ledger = SwarmAuditLedger(secret_key="test-secret")
        new_ledger.import_from_json(json_str)
        
        # Verify imported data
        assert len(new_ledger._chain) == 3
    
    def test_roundtrip_export_import(self, ledger_with_events):
        """Test that export and import preserves data."""
        # Export
        json_str = ledger_with_events.export_json()
        
        # Import into new ledger
        new_ledger = SwarmAuditLedger(secret_key="test-secret")
        new_ledger.import_from_json(json_str)
        
        # Verify chain length
        assert len(new_ledger._chain) == len(ledger_with_events._chain)
        
        # Verify events match
        for i, (original, imported) in enumerate(zip(
            ledger_with_events._chain,
            new_ledger._chain
        )):
            assert original.event_id == imported.event_id
            assert original.event_type == imported.event_type
            assert original.project_id == imported.project_id
            assert original.task_id == imported.task_id


class TestGetters:
    """Tests for getter methods."""
    
    @pytest.fixture
    def ledger(self):
        """Create a ledger with events."""
        ledger = SwarmAuditLedger(secret_key="test-secret")
        
        ledger.record_task_enqueued("project-1", "task-1")
        ledger.record_task_claimed("project-1", "task-1", "worker-1")
        ledger.record_task_enqueued("project-2", "task-2")
        
        return ledger
    
    def test_get_project_events(self, ledger):
        """Test getting events for a project."""
        events = ledger.get_project_events("project-1")
        
        assert len(events) == 2
        assert all(e.project_id == "project-1" for e in events)
    
    def test_get_project_events_nonexistent(self, ledger):
        """Test getting events for nonexistent project."""
        events = ledger.get_project_events("nonexistent")
        
        assert events == []
    
    def test_get_all_events(self, ledger):
        """Test getting all events."""
        all_events = ledger.get_all_events()
        
        assert len(all_events) == 3
    
    def test_get_event(self, ledger):
        """Test getting specific event."""
        event_id = ledger._chain[0].event_id
        event = ledger.get_event(event_id)
        
        assert event is not None
        assert event.event_id == event_id
    
    def test_get_event_nonexistent(self, ledger):
        """Test getting nonexistent event."""
        event = ledger.get_event("nonexistent-event-id")
        
        assert event is None


class TestClear:
    """Tests for clear method."""
    
    def test_clear(self):
        """Test clearing the ledger."""
        ledger = SwarmAuditLedger(secret_key="test-secret")
        
        ledger.record_task_enqueued("project-1", "task-1")
        ledger.record_task_claimed("project-1", "task-1", "worker-1")
        
        assert len(ledger._chain) == 2
        
        ledger.clear()
        
        assert len(ledger._chain) == 0
        assert len(ledger._event_index) == 0
        assert len(ledger._project_events) == 0


class TestSwarmEvent:
    """Tests for SwarmEvent dataclass."""
    
    def test_to_dict(self):
        """Test SwarmEvent to_dict method."""
        event = SwarmEvent(
            event_id="test-event-id",
            event_type=SwarmEventType.TASK_ENQUEUED,
            timestamp=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            project_id="project-1",
            task_id="task-1",
            payload={"key": "value"},
            previous_hash="0" * 64,
            payload_hash="a" * 64,
            signature="b" * 64,
        )
        
        data = event.to_dict()
        
        assert data["event_id"] == "test-event-id"
        assert data["event_type"] == "TASK_ENQUEUED"
        assert data["project_id"] == "project-1"
        assert data["task_id"] == "task-1"
        assert data["payload"] == {"key": "value"}
        assert data["previous_hash"] == "0" * 64
    
    def test_from_dict(self):
        """Test SwarmEvent from_dict method."""
        data = {
            "event_id": "test-event-id",
            "event_type": "TASK_ENQUEUED",
            "timestamp": "2024-01-01T00:00:00+00:00",
            "project_id": "project-1",
            "task_id": "task-1",
            "payload": {"key": "value"},
            "previous_hash": "0" * 64,
            "payload_hash": "a" * 64,
            "signature": "b" * 64,
        }
        
        event = SwarmEvent.from_dict(data)
        
        assert event.event_id == "test-event-id"
        assert event.event_type == SwarmEventType.TASK_ENQUEUED
        assert event.project_id == "project-1"
        assert event.task_id == "task-1"


class TestExecutionState:
    """Tests for ExecutionState dataclass."""
    
    def test_to_dict(self):
        """Test ExecutionState to_dict method."""
        state = ExecutionState(
            project_id="project-1",
            current_tasks={"task-1": {"status": "enqueued"}},
            completed_tasks=["task-2"],
            patches=[{"task_id": "task-1", "files": ["file.py"]}],
            verification_results=[{"task_id": "task-1", "passed": True}],
            last_event_hash="abc123",
            is_consistent=True,
        )
        
        data = state.to_dict()
        
        assert data["project_id"] == "project-1"
        assert data["current_tasks"] == {"task-1": {"status": "enqueued"}}
        assert data["completed_tasks"] == ["task-2"]
        assert data["is_consistent"] is True
