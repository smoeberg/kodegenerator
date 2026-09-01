"""Idempotently create the configured S3-compatible artifact bucket."""

from __future__ import annotations

import os

from services.runtime_configuration import validate_runtime_configuration


def _client(endpoint: str):
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is required for artifact bucket bootstrap") from exc
    return boto3.client("s3", endpoint_url=endpoint)


def main() -> None:
    validate_runtime_configuration(role="migrate")
    endpoint = os.environ["ARTIFACT_STORE_URL"]
    bucket = os.environ["ARTIFACT_BUCKET"]
    client = _client(endpoint)
    try:
        client.head_bucket(Bucket=bucket)
    except Exception as exc:
        response = getattr(exc, "response", {})
        code = str(response.get("Error", {}).get("Code", ""))
        if code not in {"404", "NoSuchBucket", "NotFound"}:
            raise
        client.create_bucket(Bucket=bucket)


if __name__ == "__main__":
    main()
