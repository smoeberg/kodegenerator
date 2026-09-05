import pytest

from dashboard.cockpit_view_model import gate_rework_payload, normalize_gates


def test_rejected_blocking_gate_can_rework_only_when_backend_allows() -> None:
    gates = normalize_gates(
        [
            {
                "id": "gate_architecture_approval",
                "name": "Architecture Approval",
                "resolved": True,
                "decision": "rejected",
                "blocking": True,
                "round": 1,
                "retry_allowed": True,
                "rework_supported": True,
                "rework_allowed": True,
                "rework_active": False,
                "rework_task_id": None,
                "rework_task_type": "generate_architecture",
            }
        ]
    )

    gate = gates[0]
    assert gate["status"] == "rejected"
    assert gate["can_retry"] is True
    assert gate["rework_supported"] is True
    assert gate["can_rework"] is True
    assert gate["rework_active"] is False
    assert gate["rework_task_id"] is None
    assert gate["rework_task_type"] == "generate_architecture"


def test_active_rework_disables_retry_and_second_rework_locally() -> None:
    gate = normalize_gates(
        [
            {
                "id": "gate_architecture_approval",
                "resolved": True,
                "decision": "rejected",
                "blocking": True,
                "round": 1,
                "retry_allowed": True,
                "rework_supported": True,
                "rework_allowed": True,
                "rework_active": True,
                "rework_task_id": "task-rework-1",
                "rework_task_type": "generate_architecture",
            }
        ]
    )[0]

    assert gate["can_retry"] is False
    assert gate["can_rework"] is False
    assert gate["rework_active"] is True
    assert gate["rework_task_id"] == "task-rework-1"


def test_missing_or_malformed_rework_authority_fails_closed() -> None:
    missing = normalize_gates(
        [
            {
                "id": "gate_architecture_approval",
                "resolved": True,
                "decision": "rejected",
                "blocking": True,
                "retry_allowed": True,
                "rework_supported": True,
            }
        ]
    )[0]
    malformed = normalize_gates(
        [
            {
                "id": "gate_architecture_approval",
                "resolved": True,
                "decision": "rejected",
                "blocking": True,
                "retry_allowed": True,
                "rework_supported": True,
                "rework_allowed": "yes",
                "rework_active": "false",
            }
        ]
    )[0]

    assert missing["can_rework"] is False
    assert malformed["can_rework"] is False
    assert malformed["rework_active"] is False


def test_gate_rework_payload_matches_api_contract() -> None:
    assert gate_rework_payload(
        " gate_architecture_approval ", "  Revise trust boundary.  "
    ) == {
        "gate_id": "gate_architecture_approval",
        "reason": "Revise trust boundary.",
    }


@pytest.mark.parametrize(
    ("gate_id", "reason", "match"),
    [
        ("", "reason", "gate_id is required"),
        ("gate", "   ", "reason is required"),
        ("gate", "x" * 2001, "reason must be at most 2000 characters"),
    ],
)
def test_gate_rework_payload_rejects_invalid_input(
    gate_id: str, reason: str, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        gate_rework_payload(gate_id, reason)
