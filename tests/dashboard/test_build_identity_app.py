from pathlib import Path

from streamlit.testing.v1 import AppTest

from dashboard.build_identity import current_build_identity


APP_PATH = Path(__file__).resolve().parents[2] / "dashboard" / "app.py"


def test_login_sidebar_shows_build_and_revision(monkeypatch) -> None:
    monkeypatch.setenv("DOR_BUILD_REVISION", "abcdef1234567890")
    current_build_identity.cache_clear()

    at = AppTest.from_file(APP_PATH, default_timeout=5).run(timeout=5)

    captions = [caption.value for caption in at.sidebar.caption]
    assert any("DOR build `" in caption for caption in captions)
    assert any("revision `abcdef123456`" in caption for caption in captions)
    assert not at.exception

    current_build_identity.cache_clear()
