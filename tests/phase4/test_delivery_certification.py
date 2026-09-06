from __future__ import annotations

import hashlib
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from phase4.delivery_certificate import (
    DeliveryArtifactFile,
    DeliveryVerificationCandidate,
    canonical_digest,
)
from phase4.delivery_certification import (
    DELIVERY_CONTRACT_FINGERPRINT,
    DeliveryCandidateContractError,
    DeliveryCertificationResult,
    DeliveryCertificationUnavailableError,
    DeliveryCertificationVerifier,
    parse_delivery_verification_candidate,
)
from phase4.implementation_agent.patch_models import (
    PatchRecordStatus,
    ToolKind,
    TrustedToolSpec,
    WorkspaceFileState,
    toolchain_fingerprint,
)


def _digest(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


class _Adapter:
    def __init__(self, request, record) -> None:
        self._requests = {request.request_fingerprint: request}
        self._record = record

    def get_record(self, request_fingerprint: str):
        if request_fingerprint not in self._requests:
            raise KeyError(request_fingerprint)
        return self._record


class _PatchRuntime:
    def __init__(self, *, root: Path, tools, request, record) -> None:
        self.workspace_root = root
        self.tools = tools
        self._governed_adapter = _Adapter(request, record)


def _fixture(tmp_path: Path):
    file_path = tmp_path / "service.py"
    file_path.write_text("VALUE = 1\n", encoding="utf-8")
    file_bytes = file_path.read_bytes()
    file_state = WorkspaceFileState(
        path="service.py",
        exists=True,
        sha256=hashlib.sha256(file_bytes).hexdigest(),
        byte_count=len(file_bytes),
        mode=stat.S_IMODE(file_path.stat().st_mode),
    )
    tools = (
        TrustedToolSpec("lint", ToolKind.LINT, ("/bin/true",)),
        TrustedToolSpec("test", ToolKind.TEST, ("/bin/true",)),
        TrustedToolSpec("build", ToolKind.BUILD, ("/bin/true",)),
    )
    proposal_id = _digest("proposal")
    proposal_request_fingerprint = _digest("proposal-request")
    diff_sha256 = _digest("diff")
    baseline_fingerprint = _digest("baseline")
    apply_request_fingerprint = _digest("apply-request")
    artifact_id = canonical_digest(
        {
            "proposal_id": proposal_id,
            "diff_sha256": diff_sha256,
            "baseline_fingerprint": baseline_fingerprint,
            "files": [file_state.canonical()],
        }
    )
    evidence = tuple(
        SimpleNamespace(
            evidence_id=_digest(f"evidence-{kind}"),
            passed=True,
            kind=SimpleNamespace(value=kind),
            artifact_id=artifact_id,
        )
        for kind in ("lint", "test", "build")
    )
    record_id = _digest("record")
    proposal = SimpleNamespace(
        proposal_id=proposal_id,
        request_fingerprint=proposal_request_fingerprint,
        diff_sha256=diff_sha256,
    )
    request = SimpleNamespace(
        request_fingerprint=apply_request_fingerprint,
        organization_id="org-1",
        resource="owner/repo",
        proposal=proposal,
        baseline_fingerprint=baseline_fingerprint,
        toolchain_fingerprint=toolchain_fingerprint(tools),
    )
    artifact = SimpleNamespace(
        artifact_id=artifact_id,
        proposal_id=proposal_id,
        diff_sha256=diff_sha256,
        baseline_fingerprint=baseline_fingerprint,
        files=(file_state,),
    )
    record = SimpleNamespace(
        request_fingerprint=apply_request_fingerprint,
        proposal_id=proposal_id,
        baseline_fingerprint=baseline_fingerprint,
        record_id=record_id,
        status=PatchRecordStatus.SUCCEEDED,
        committed=True,
        rolled_back=False,
        error=None,
        artifact=artifact,
        evidence=evidence,
    )
    candidate = DeliveryVerificationCandidate(
        organization_id="org-1",
        repository="owner/repo",
        intent_id="intent-1",
        onboarding_content_fingerprint=_digest("onboarding"),
        audit_report_id=_digest("audit-report"),
        audit_request_fingerprint=_digest("audit-request"),
        audit_manifest_id=_digest("manifest"),
        audit_evidence_bundle_id=_digest("bundle"),
        audit_commit_sha="abc123",
        plan_id="plan-1",
        plan_request_fingerprint=_digest("plan-request"),
        proposal_id=proposal_id,
        proposal_request_fingerprint=proposal_request_fingerprint,
        apply_record_id=record_id,
        apply_request_fingerprint=apply_request_fingerprint,
        artifact_id=artifact_id,
        diff_sha256=diff_sha256,
        baseline_fingerprint=baseline_fingerprint,
        toolchain_fingerprint=toolchain_fingerprint(tools),
        files=(
            DeliveryArtifactFile(
                path=file_state.path,
                exists=file_state.exists,
                sha256=file_state.sha256,
                byte_count=file_state.byte_count,
                mode=file_state.mode,
            ),
        ),
        evidence_ids=tuple(item.evidence_id for item in evidence),
    )
    runtime = _PatchRuntime(
        root=tmp_path,
        tools=tools,
        request=request,
        record=record,
    )
    return candidate, runtime


def test_delivery_contract_passes_exact_server_owned_apply_and_workspace(tmp_path) -> None:
    candidate, runtime = _fixture(tmp_path)

    certificate = DeliveryCertificationVerifier().certify(
        candidate,
        patch_runtime=runtime,
        certified_by="admin",
    )

    assert certificate.result is DeliveryCertificationResult.PASS
    assert certificate.reason_codes == ("verified",)
    assert certificate.authoritative is True
    assert certificate.contract_fingerprint == DELIVERY_CONTRACT_FINGERPRINT
    assert canonical_digest(certificate.canonical(include_id=False)) == certificate.certificate_id


def test_delivery_contract_fails_closed_on_workspace_drift(tmp_path) -> None:
    candidate, runtime = _fixture(tmp_path)
    (tmp_path / "service.py").write_text("VALUE = 2\n", encoding="utf-8")

    certificate = DeliveryCertificationVerifier().certify(
        candidate,
        patch_runtime=runtime,
        certified_by="admin",
    )

    assert certificate.result is DeliveryCertificationResult.FAIL
    assert "workspace_drift" in certificate.reason_codes
    assert "verified" not in certificate.reason_codes


def test_delivery_contract_fails_closed_on_apply_record_mismatch(tmp_path) -> None:
    candidate, runtime = _fixture(tmp_path)
    runtime._governed_adapter._record.record_id = _digest("other-record")

    certificate = DeliveryCertificationVerifier().certify(
        candidate,
        patch_runtime=runtime,
        certified_by="admin",
    )

    assert certificate.result is DeliveryCertificationResult.FAIL
    assert "apply_record_mismatch" in certificate.reason_codes


def test_candidate_parser_rejects_content_id_tampering(tmp_path) -> None:
    candidate, _runtime = _fixture(tmp_path)
    payload = candidate.canonical()
    payload["audit_commit_sha"] = "different"

    with pytest.raises(DeliveryCandidateContractError):
        parse_delivery_verification_candidate(payload)


def test_certification_requires_server_owned_apply_provenance(tmp_path) -> None:
    candidate, runtime = _fixture(tmp_path)
    runtime._governed_adapter._requests.clear()

    with pytest.raises(DeliveryCertificationUnavailableError):
        DeliveryCertificationVerifier().certify(
            candidate,
            patch_runtime=runtime,
            certified_by="admin",
        )
