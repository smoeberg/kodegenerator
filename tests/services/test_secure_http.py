"""Tests for outbound URL security validation."""
from __future__ import annotations

import pytest

from services.secure_http import validate_http_url


def test_accepts_https() -> None:
    assert validate_http_url("https://api.example.com/v1") == "https://api.example.com/v1"


def test_accepts_http_for_local_services() -> None:
    assert validate_http_url("http://localhost:11434") == "http://localhost:11434"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/file", "gopher://example.com", "localhost:8000", "https://"])
def test_rejects_non_http_or_missing_host(url: str) -> None:
    with pytest.raises(ValueError, match="must use http or https"):
        validate_http_url(url)
