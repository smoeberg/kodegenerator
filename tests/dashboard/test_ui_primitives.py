from dashboard.ui_primitives import count_label, format_timestamp, status_badge


def test_format_timestamp_normalizes_aware_iso_values_to_utc() -> None:
    assert format_timestamp("2026-09-05T13:42:17+02:00") == "2026-09-05 · 11:42 UTC"
    assert format_timestamp("2026-09-05T11:42:17Z") == "2026-09-05 · 11:42 UTC"


def test_format_timestamp_handles_missing_naive_and_unknown_values() -> None:
    assert format_timestamp(None) == "—"
    assert format_timestamp("2026-09-05T11:42:17") == "2026-09-05 · 11:42"
    assert format_timestamp("backend-specific-time") == "backend-specific-time"


def test_status_badges_are_consistent_and_preserve_unknown_backend_values() -> None:
    assert status_badge("approved") == "✅ APPROVED"
    assert status_badge("human_required") == "⚠️ HUMAN REQUIRED"
    assert status_badge("rejected", blocking=True) == "🛑 REJECTED · 🛑 BLOCKING"
    assert status_badge("custom_state") == "⚪ CUSTOM STATE"


def test_count_label_fails_safe() -> None:
    assert count_label(1, "event") == "1 event"
    assert count_label(2, "event") == "2 events"
    assert count_label("bad", "event") == "0 events"
