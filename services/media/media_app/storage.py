"""Object-storage adapter (S3/MinIO) with a 'fake' backend for tests.

Presigned URLs let clients upload/download directly to storage, keeping large
payloads off the API tier (doc 06 §7). The only place that touches storage.
"""

from __future__ import annotations

import functools

from django.conf import settings


@functools.lru_cache(maxsize=2)
def _client(public: bool = False):
    """``public`` signs URLs for the address browsers use; the signature covers the host."""
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=(settings.S3_PUBLIC_ENDPOINT_URL if public else "")
        or settings.S3_ENDPOINT_URL,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        region_name=settings.S3_REGION,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def ensure_bucket() -> None:
    if settings.STORAGE_BACKEND != "s3":
        return
    client = _client()
    try:
        client.head_bucket(Bucket=settings.S3_BUCKET)
    except Exception:  # noqa: BLE001 - create on first use in dev
        client.create_bucket(Bucket=settings.S3_BUCKET)


def presign_put(storage_key: str, mime: str) -> str:
    if settings.STORAGE_BACKEND == "fake":
        return f"{settings.S3_PUBLIC_BASE}/{settings.S3_BUCKET}/{storage_key}?fake-upload=1"
    return _client(public=True).generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.S3_BUCKET, "Key": storage_key, "ContentType": mime},
        ExpiresIn=settings.SIGNED_URL_TTL,
    )


def presign_get(storage_key: str) -> str:
    if settings.STORAGE_BACKEND == "fake":
        return f"{settings.S3_PUBLIC_BASE}/{settings.S3_BUCKET}/{storage_key}?fake-download=1"
    return _client(public=True).generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.S3_BUCKET, "Key": storage_key},
        ExpiresIn=settings.SIGNED_URL_TTL,
    )
