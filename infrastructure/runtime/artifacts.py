"""S3-compatible immutable artifact storage port and implementation."""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from typing import BinaryIO, Protocol
from urllib.parse import urlparse


@dataclass(frozen=True)
class StoredArtifact:
    key: str
    sha256: str
    size: int
    content_type: str


class ArtifactStore(Protocol):
    def put(
        self,
        key: str,
        data: bytes | BinaryIO,
        *,
        content_type: str = "application/octet-stream",
    ) -> StoredArtifact: ...

    def get(self, key: str) -> bytes: ...


class S3ArtifactStore:
    """Small boto3-compatible adapter with content-address verification."""

    def __init__(self, endpoint_url: str, bucket: str, client=None):
        self.bucket = bucket
        self.endpoint_url = endpoint_url
        self._client = client
        if client is None:
            try:
                import boto3
            except ImportError as exc:  # pragma: no cover - dependency optional
                raise RuntimeError("boto3 is required for S3ArtifactStore") from exc
            self._client = boto3.client("s3", endpoint_url=endpoint_url)

    def put(
        self,
        key: str,
        data: bytes | BinaryIO,
        *,
        content_type: str = "application/octet-stream",
    ) -> StoredArtifact:
        raw = data if isinstance(data, bytes) else data.read()
        digest = hashlib.sha256(raw).hexdigest()
        self._client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=raw,
            ContentType=content_type,
            Metadata={"sha256": digest},
        )
        return StoredArtifact(key, digest, len(raw), content_type)

    def get(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self.bucket, Key=key)
        raw = response["Body"].read()
        expected = response.get("Metadata", {}).get("sha256")
        if expected and hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("Artifact integrity check failed")
        return raw
