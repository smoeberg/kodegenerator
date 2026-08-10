from pathlib import Path


BASELINE = Path("docs/phase6/P6-01_SECURITY_BASELINE.md")


def test_p6_01_security_baseline_exists():
    assert BASELINE.is_file()


def test_p6_01_security_baseline_contains_required_sections():
    text = BASELINE.read_text(encoding="utf-8")

    required = (
        "## 2. Security objectives",
        "## 3. Trust boundaries",
        "## 4. Assets to protect",
        "## 5. Threat actors",
        "## 6. Primary threat scenarios",
        "## 7. Security invariants",
        "## 8. Existing code mapping",
        "## 9. Required controls by Phase 6 milestone",
        "## 10. Release gates",
        "## 13. Acceptance criteria for P6-01",
    )

    for section in required:
        assert section in text


def test_p6_01_baseline_has_release_blocking_security_invariants():
    text = BASELINE.read_text(encoding="utf-8")

    required_invariants = (
        "INV-01 — No ambient authority",
        "INV-02 — No self-escalation",
        "INV-03 — Organization scope is mandatory",
        "INV-04 — Authorization precedes mutation/execution",
        "INV-06 — Sandbox failure is containment",
        "INV-07 — Secrets are capabilities, not ambient data",
        "INV-09 — Security controls fail closed",
        "INV-10 — Supply-chain inputs are verifiable",
    )

    for invariant in required_invariants:
        assert invariant in text


def test_p6_01_baseline_requires_adversarial_testing():
    text = BASELINE.read_text(encoding="utf-8")

    for threat in (
        "cross-tenant access",
        "capability escalation",
        "sandbox filesystem escape",
        "sandbox network escape",
        "secret exfiltration",
        "recovery after timeout/crash/OOM",
    ):
        assert threat in text
