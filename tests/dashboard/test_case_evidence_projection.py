from dashboard.case_evidence_projection import EvidenceStatus, build_case_evidence


def _project(**extra):
    payload = {"project_id": "p1", "name": "Demo", "status": "active"}
    payload.update(extra)
    return payload


def _execution(state: str):
    return {"workflow_id": "w1", "project_id": "p1", "current_state": state}


def _by_id(evidence, item_id: str):
    return next(item for item in evidence.process_items if item.id == item_id)


def test_early_case_exposes_pending_process_basis_without_verified_evidence():
    evidence = build_case_evidence(_project(), _execution("requirements_draft"))

    assert all(item.status is EvidenceStatus.PENDING for item in evidence.process_items)
    assert evidence.verified_items == ()
    assert all(item.authoritative is False for item in evidence.process_items)


def test_tests_passed_produces_human_process_milestones_but_not_completion_proof():
    evidence = build_case_evidence(_project(), _execution("tests_passed"))

    assert _by_id(evidence, "requirements").label == "Krav godkendt"
    assert _by_id(evidence, "solution").status is EvidenceStatus.COMPLETED
    assert _by_id(evidence, "implementation").label == "Implementering gennemført"
    assert _by_id(evidence, "verification").label == "Automatiske kontroller bestået"
    assert _by_id(evidence, "verification").status is EvidenceStatus.COMPLETED
    assert _by_id(evidence, "delivery").status is EvidenceStatus.PENDING
    assert evidence.verified_items == ()


def test_failed_tests_are_explicitly_failed_not_completed():
    evidence = build_case_evidence(_project(), _execution("tests_failed"))

    verification = _by_id(evidence, "verification")
    assert verification.status is EvidenceStatus.FAILED
    assert verification.label == "Automatiske kontroller"
    assert "fandt fejl" in verification.detail
    assert verification.authoritative is False


def test_released_pipeline_is_still_not_presented_as_authoritative_completion_proof():
    evidence = build_case_evidence(_project(), _execution("released"))

    assert _by_id(evidence, "delivery").status is EvidenceStatus.COMPLETED
    assert evidence.verified_items == ()


def test_completed_project_with_completion_record_exposes_verified_delivery():
    evidence = build_case_evidence(
        _project(
            status="completed",
            completion_record_id="a" * 64,
            completed_by="alice",
            completed_at="2026-09-09T11:00:00+00:00",
        ),
        _execution("released"),
    )

    assert len(evidence.verified_items) == 1
    verified = evidence.verified_items[0]
    assert verified.label == "Levering verificeret"
    assert verified.status is EvidenceStatus.VERIFIED
    assert verified.authoritative is True
    assert "immutable afslutningsbevis" in verified.detail
    assert "a" * 64 not in verified.detail


def test_archived_completed_project_keeps_verified_delivery_evidence():
    evidence = build_case_evidence(
        _project(
            status="archived",
            archived_from_status="completed",
            completion_record_id="b" * 64,
        ),
        _execution("released"),
    )

    assert evidence.verified_items[0].label == "Levering verificeret"


def test_completion_record_is_not_trusted_on_incompatible_project_state():
    evidence = build_case_evidence(
        _project(status="active", completion_record_id="c" * 64),
        _execution("released"),
    )

    assert evidence.verified_items == ()


def test_no_execution_does_not_invent_process_progress():
    evidence = build_case_evidence(_project(status="created"), None)

    assert all(item.status is EvidenceStatus.PENDING for item in evidence.process_items)
    assert evidence.verified_items == ()
