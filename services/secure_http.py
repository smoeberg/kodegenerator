"""Shared validation for outbound HTTP(S) requests."""
from __future__ import annotations

from urllib.parse import urlsplit


def validate_http_url(url: str) -> str:
    """Return a normalized URL only when its scheme is HTTP or HTTPS and it has a host."""
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("outbound URL must use http or https and include a host")
    return url
