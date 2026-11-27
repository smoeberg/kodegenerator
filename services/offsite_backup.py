"""Backup outside GitHub (completion plan, decision 38).

Uploads a milestone's release backup (verified git bundle, milestone state,
release evidence) to S3-compatible object storage; for the first run that
is UpCloud Object Storage. Endpoint, bucket and keys come from the
environment of the host. Every object is uploaded with its SHA-256 and read
back to check it arrived intact; objects are never overwritten.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class OffsiteBackupError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class OffsiteBackup:
    client: Any
    bucket: str
    prefix: str = "dor"

    @classmethod
    def from_environment(cls) -> OffsiteBackup | None:
        """``DOR_BACKUP_S3_ENDPOINT``, ``_BUCKET``, ``_ACCESS_KEY``, ``_SECRET_KEY``:
        all or none (one missing fails closed)."""
        names = ("ENDPOINT", "BUCKET", "ACCESS_KEY", "SECRET_KEY")
        values = {n: os.getenv(f"DOR_BACKUP_S3_{n}", "").strip() for n in names}
        if not any(values.values()):
            return None
        missing = [f"DOR_BACKUP_S3_{n}" for n, v in values.items() if not v]
        if missing:
            raise OffsiteBackupError(
                f"offsite backup is partly configured; missing {missing}"
            )
        import boto3

        client = boto3.client(
            "s3",
            endpoint_url=values["ENDPOINT"],
            aws_access_key_id=values["ACCESS_KEY"],
            aws_secret_access_key=values["SECRET_KEY"],
        )
        return cls(client, values["BUCKET"])

    def _exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise OffsiteBackupError(f"cannot check {key}: {exc}") from exc
        return True

    def upload(self, milestone_id: str, files: Sequence[Path]) -> list[dict[str, str]]:
        uploaded = []
        for path in files:
            key = f"{self.prefix}/{milestone_id}/{path.name}"
            digest = _sha256(path)
            if self._exists(key):
                raise OffsiteBackupError(
                    f"{key} already exists; backups are never overwritten"
                )
            with path.open("rb") as body:
                self.client.put_object(
                    Bucket=self.bucket, Key=key, Body=body, Metadata={"sha256": digest}
                )
            stored = self.client.head_object(Bucket=self.bucket, Key=key)
            if (stored.get("Metadata") or {}).get("sha256") != digest or int(
                stored.get("ContentLength", -1)
            ) != path.stat().st_size:
                raise OffsiteBackupError(f"{key} did not arrive intact")
            uploaded.append({"key": key, "sha256": digest})
        return uploaded
