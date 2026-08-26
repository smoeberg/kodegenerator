"""Unit tests for adaptation tracker and anti-tunneling strategy fingerprinting."""
from phase4.adaptation.fingerprint import AdaptationTracker


def test_strategy_fingerprint_generation():
    tracker = AdaptationTracker()
    sig1 = tracker.compute_signature("Refactor auth", "ast_edit", "jwt_secret")
    sig2 = tracker.compute_signature("Refactor auth", "ast_edit", "jwt_secret")
    sig3 = tracker.compute_signature("Refactor auth", "sed_replace", "jwt_secret")

    assert sig1 == sig2
    assert sig1 != sig3


def test_tunneling_detection_and_pivot():
    tracker = AdaptationTracker(tunnel_threshold=2)
    sig = tracker.compute_signature("Migrate database", "raw_sql", "url=postgres")

    # Attempt 1 fails
    count1 = tracker.record_failure("task-300", sig, "Connection timeout")
    assert count1 == 1
    assert not tracker.is_tunneling(sig)
    assert "PROCEED" in tracker.get_pivot_recommendation(sig)

    # Attempt 2 fails (hits threshold)
    count2 = tracker.record_failure("task-300", sig, "Connection timeout again")
    assert count2 == 2
    assert tracker.is_tunneling(sig)
    recommendation = tracker.get_pivot_recommendation(sig)
    assert "TUNNELING_DETECTED" in recommendation
    assert "dialectical pivot" in recommendation
