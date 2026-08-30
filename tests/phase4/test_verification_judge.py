"""Tests for the Phase 4 LLM-augmented verification judge."""
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
