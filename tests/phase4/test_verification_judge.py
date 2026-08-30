"""Tests for the Phase 4 LLM-augmented verification judge."""
import json

import pytest

from phase4.contracts import (
    Evidence,
    KnowledgeRecord,
    VerificationMode,
    VerificationPolicy,
)
from phase4.verification import (
    DeterministicBaselineJudge,
    JudgeInputError,
    JudgeVerdict,
    LLMJudge,
    OpenAIJudgeProvider,
    VerificationEngine,
    VerificationResult,
)


def make_record(supports=True) -> KnowledgeRecord:
    return KnowledgeRecord(
        record_id="record-1",
        subject="subject-1",
        claim="claim-1",
        evidence=(
            Evidence(
                evidence_id="e1",
                source="source-1",
                content_digest="digest-1",
                supports=supports,
            ),
        ),
        author_agent_id="agent-1",
    )


class _FakeVerdictProvider:
    def __init__(self, payload):
        self._payload = payload
        self.calls = 0

    def judge(self, prompt: str) -> dict:
        self.calls += 1
        return dict(self._payload)


def test_baseline_judge_confirms_all_supporting_evidence():
    verdict = LLMJudge().judge_record(make_record(supports=True))
    assert isinstance(verdict, JudgeVerdict)
    assert verdict.verdict is True
    assert verdict.confidence == 1.0
    assert verdict.fingerprint


def test_baseline_judge_rejects_any_contradicting_evidence():
    verdict = LLMJudge().judge_record(make_record(supports=False))
    assert verdict.verdict is False
    assert verdict.confidence == 0.0


def test_baseline_judge_reports_ac_coverage():
    from phase4.verification.judge import DeterministicBaselineJudge

    judge = DeterministicBaselineJudge()

    full = judge.judge(
        json.dumps(
            {
                "bundle": {
                    "candidate_id": "r-ac",
                    "acceptance_criteria": ["AC-1", "AC-2"],
                    "evidence": [
                        {
                            "evidence_id": "e1",
                            "supports": True,
                            "acceptance_criterion": "AC-1",
                        },
                        {
                            "evidence_id": "e2",
                            "supports": True,
                            "acceptance_criterion": "AC-2",
                        },
                    ],
                }
            }
        )
    )
    assert full["verdict"] is True
    assert full["ac_coverage"] == 1.0

    partial = judge.judge(
        json.dumps(
            {
                "bundle": {
                    "candidate_id": "r-ac",
                    "acceptance_criteria": ["AC-1", "AC-2"],
                    "evidence": [
                        {
                            "evidence_id": "e1",
                            "supports": True,
                            "acceptance_criterion": "AC-1",
                        }
                    ],
                }
            }
        )
    )
    assert partial["verdict"] is True
    assert partial["ac_coverage"] == 0.5

    mixed = judge.judge(
        json.dumps(
            {
                "bundle": {
                    "candidate_id": "r-ac",
                    "acceptance_criteria": ["AC-1", "AC-2"],
                    "evidence": [
                        {
                            "evidence_id": "e1",
                            "supports": True,
                            "acceptance_criterion": "AC-1",
                        },
                        {
                            "evidence_id": "e2",
                            "supports": False,
                            "acceptance_criterion": "AC-2",
                        },
                    ],
                }
            }
        )
    )
    assert mixed["verdict"] is False
    assert mixed["ac_coverage"] == 0.5


def test_llm_judge_passes_ac_coverage_through_verdict():
    from phase4.contracts.models import Evidence

    record = KnowledgeRecord(
        record_id="r-ac-llm",
        subject="generated app",
        claim="all ACs met",
        evidence=[
            Evidence(
                evidence_id="e1",
                source="tests/test_a.py",
                content_digest="a",
                supports=True,
                acceptance_criterion="AC-1",
            ),
            Evidence(
                evidence_id="e2",
                source="tests/test_b.py",
                content_digest="b",
                supports=True,
                acceptance_criterion="AC-2",
            ),
        ],
        author_agent_id="agent-ac",
    )
    # Baseline provider accepts everything, so coverage tracks criteria count.
    verdict = LLMJudge().judge_record(record)
    assert verdict.verdict is True
    assert verdict.ac_coverage == 1.0


def test_fake_provider_payload_is_bounded_and_immutable():
    judge = LLMJudge(
        provider=_FakeVerdictProvider(
            {"candidate_id": "x", "verdict": False, "confidence": 2.0, "reasoning": "r"}
        )
    )
    verdict = judge.judge_record(make_record())
    assert verdict.verdict is False
    assert verdict.confidence == 1.0  # clamped to [0,1]
    assert verdict.candidate_id == "x"
    with pytest.raises((AttributeError, TypeError)):
        verdict.verdict = True


def test_judge_integrates_with_deterministic_engine():
    judge = LLMJudge()
    record = make_record(supports=True)
    verdict = judge.judge_record(record)
    engine = VerificationEngine()
    policy = VerificationPolicy(
        mode=VerificationMode.QUORUM, quorum_size=3, risk_level=2
    )
    result = engine.evaluate(policy, (verdict.verdict, verdict.verdict, verdict.verdict))
    assert result is VerificationResult.CONFIRMED


def test_baseline_judge_requires_json_bundle():
    with pytest.raises(JudgeInputError):
        DeterministicBaselineJudge().judge("not json")


def test_openai_provider_requires_key():
    with pytest.raises(ValueError):
        OpenAIJudgeProvider(api_key="")
