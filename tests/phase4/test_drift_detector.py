"""Tests for RepositoryDriftDetector."""
import pytest
from phase4.adaptation.drift_detector import RepositoryDriftDetector


def test_drift_detector_same_commit():
    detector = RepositoryDriftDetector()
    head = detector.get_current_head()
    if head == "unknown":
        pytest.skip("Not a git repository or git not available")
    
    report = detector.check_drift(head)
    assert not report.has_drift
    assert report.latest_commit == head


def test_drift_detector_with_fake_old_commit():
    detector = RepositoryDriftDetector()
    head = detector.get_current_head()
    if head == "unknown":
        pytest.skip("Not a git repository")
    
    # Using an invalid or older hash should trigger fallback or diff
    report = detector.check_drift("4b29772") # an older commit in log
    assert isinstance(report.has_drift, bool)
    assert report.latest_commit == head
