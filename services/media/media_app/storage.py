"""Object-storage adapter (S3/MinIO), with test backends.

Presigned URLs let clients upload/download directly to storage, keeping large
payloads off the API tier (doc 06 §7). The only place that touches storage.

Backends (``TARA_STORAGE_BACKEND``):

- ``s3``: S3 or MinIO.
- ``fake``: no storage at all; uploads are not inspected (unit tests).
- ``memory``: an in-process dict that behaves like a bucket, so tests can run
  the real verify, copy and image-cleaning paths.
"""

from __future__ import annotations

import functools
import hashlib
from dataclasses import dataclass

from django.conf import settings


class ObjectChanged(Exception):
    """The object no longer has the ETag it was verified with."""


@dataclass(frozen=True)
class StoredObject:
    size: int
    etag: str
    head: bytes  # the first bytes, for signature checks


_memory: dict[str, tuple[bytes, str]] = {}


def _backend() -> str:
    return settings.STORAGE_BACKEND


def _memory_etag(content: bytes) -> str:
    return f'"{hashlib.md5(content, usedforsecurity=False).hexdigest()}"'


def memory_reset() -> None:
    _memory.clear()


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


def _error_code(exc: Exception) -> str:
    return str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))


def ensure_bucket() -> None:
    if _backend() != "s3":
        return
    client = _client()
    try:
        client.head_bucket(Bucket=settings.S3_BUCKET)
    except Exception:  # noqa: BLE001 - create on first use in dev
        client.create_bucket(Bucket=settings.S3_BUCKET)


def presign_put(storage_key: str, mime: str) -> str:
    if _backend() in ("fake", "memory"):
        return f"{settings.S3_PUBLIC_BASE}/{settings.S3_BUCKET}/{storage_key}?fake-upload=1"
    return _client(public=True).generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.S3_BUCKET, "Key": storage_key, "ContentType": mime},
        ExpiresIn=settings.SIGNED_URL_TTL,
    )


def presign_get(storage_key: str) -> str:
    if _backend() in ("fake", "memory"):
        return f"{settings.S3_PUBLIC_BASE}/{settings.S3_BUCKET}/{storage_key}?fake-download=1"
    return _client(public=True).generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.S3_BUCKET, "Key": storage_key},
        ExpiresIn=settings.SIGNED_URL_TTL,
    )


def stat(storage_key: str, head_bytes: int) -> StoredObject | None:
    """The stored object's real size and ETag (a HEAD), plus its first bytes.

    None if the object is missing. Raises ``ObjectChanged`` if it is replaced
    between the HEAD and the read. Other storage errors propagate.
    """
    if _backend() == "memory":
        if storage_key not in _memory:
            return None
        content, _ = _memory[storage_key]
        return StoredObject(len(content), _memory_etag(content), content[:head_bytes])
    from botocore.exceptions import ClientError

    client = _client()
    try:
        meta = client.head_object(Bucket=settings.S3_BUCKET, Key=storage_key)
    except ClientError as exc:
        if _error_code(exc) in ("404", "NoSuchKey", "NotFound"):
            return None
        raise
    size, etag = int(meta["ContentLength"]), meta["ETag"]
    if size == 0:
        return StoredObject(0, etag, b"")
    try:
        obj = client.get_object(
            Bucket=settings.S3_BUCKET,
            Key=storage_key,
            Range=f"bytes=0-{head_bytes - 1}",
            IfMatch=etag,
        )
    except ClientError as exc:
        if _error_code(exc) in ("412", "PreconditionFailed"):
            raise ObjectChanged(storage_key) from exc
        raise
    return StoredObject(size, etag, obj["Body"].read())


def copy(source_key: str, dest_key: str, *, if_match: str) -> str:
    """Copy only if the source still has ETag ``if_match``. Returns the new ETag."""
    if _backend() == "memory":
        if source_key not in _memory or _memory_etag(_memory[source_key][0]) != if_match:
            raise ObjectChanged(source_key)
        _memory[dest_key] = _memory[source_key]
        return if_match
    from botocore.exceptions import ClientError

    try:
        resp = _client().copy_object(
            Bucket=settings.S3_BUCKET,
            Key=dest_key,
            CopySource={"Bucket": settings.S3_BUCKET, "Key": source_key},
            CopySourceIfMatch=if_match,
        )
    except ClientError as exc:
        if _error_code(exc) in ("412", "PreconditionFailed", "404", "NoSuchKey"):
            raise ObjectChanged(source_key) from exc
        raise
    return resp["CopyObjectResult"]["ETag"]


def read(storage_key: str) -> bytes:
    if _backend() == "memory":
        return _memory[storage_key][0]
    return _client().get_object(Bucket=settings.S3_BUCKET, Key=storage_key)["Body"].read()


def write(storage_key: str, content: bytes, mime: str) -> str:
    """Store ``content`` and return its ETag."""
    if _backend() == "memory":
        _memory[storage_key] = (content, mime)
        return _memory_etag(content)
    resp = _client().put_object(
        Bucket=settings.S3_BUCKET, Key=storage_key, Body=content, ContentType=mime
    )
    return resp.get("ETag", "")


def delete(storage_key: str) -> None:
    if _backend() == "memory":
        _memory.pop(storage_key, None)
        return
    _client().delete_object(Bucket=settings.S3_BUCKET, Key=storage_key)
