from app import status


def test_status() -> None:
    assert status() == {"status": "ok"}
