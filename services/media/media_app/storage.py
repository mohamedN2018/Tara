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
import hmac
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

from django.conf import settings

logger = logging.getLogger("tara.media.storage")

# Browsers write to ``staging/...`` (see ``services.sign_upload``). Completion
# copies the verified object out and deletes it, but an abandoned upload, or a
# PUT replayed after completion, leaves one there: the bucket expires them.
STAGING_PREFIX = "staging/"
STAGING_RULE_ID = "tara-expire-staging"
STAGING_EXPIRY_DAYS = 1


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
    ensure_staging_expiry(client)


def ensure_staging_expiry(client) -> None:
    """Add (or keep) the bucket rule that deletes staging objects after a day.

    Other lifecycle rules on the bucket are kept. A failure is logged, not
    raised: the service works without it, staging objects just stay.
    """
    from botocore.exceptions import ClientError

    rule = {
        "ID": STAGING_RULE_ID,
        "Filter": {"Prefix": STAGING_PREFIX},
        "Status": "Enabled",
        "Expiration": {"Days": STAGING_EXPIRY_DAYS},
        "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": STAGING_EXPIRY_DAYS},
    }
    try:
        try:
            rules = client.get_bucket_lifecycle_configuration(Bucket=settings.S3_BUCKET)["Rules"]
        except ClientError as exc:
            if _error_code(exc) != "NoSuchLifecycleConfiguration":
                raise
            rules = []
        if rule in rules:
            return
        others = [r for r in rules if r.get("ID") != STAGING_RULE_ID]
        client.put_bucket_lifecycle_configuration(
            Bucket=settings.S3_BUCKET, LifecycleConfiguration={"Rules": [*others, rule]}
        )
    except Exception:  # noqa: BLE001 - see the docstring
        logger.warning("could not set the staging expiry rule", exc_info=True)


def presign_put(storage_key: str, mime: str) -> str:
    if _backend() in ("fake", "memory"):
        return f"{settings.S3_PUBLIC_BASE}/{settings.S3_BUCKET}/{storage_key}?fake-upload=1"
    return _client(public=True).generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.S3_BUCKET, "Key": storage_key, "ContentType": mime},
        ExpiresIn=settings.SIGNED_URL_TTL,
    )


def presign_get(storage_key: str, *, content_type: str = "", disposition: str = "") -> str:
    """A GET URL. ``content_type`` and ``disposition`` are signed into it and
    override the stored object's ``Content-Type`` and ``Content-Disposition``."""
    response = {}
    if content_type:
        response["ResponseContentType"] = content_type
    if disposition:
        response["ResponseContentDisposition"] = disposition
    if _backend() in ("fake", "memory"):
        query = urlencode(
            {
                "fake-download": 1,
                **({"response-content-type": content_type} if content_type else {}),
                **({"response-content-disposition": disposition} if disposition else {}),
            }
        )
        return f"{settings.S3_PUBLIC_BASE}/{settings.S3_BUCKET}/{storage_key}?{query}"
    return _client(public=True).generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.S3_BUCKET, "Key": storage_key, **response},
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


# ---- video pipeline (roadmap 5.2 / 5.3) -----------------------------------------


def download_to(storage_key: str, path: Path) -> None:
    """Stream an object to a local file (the transcoder's scratch dir)."""
    if _backend() == "memory":
        Path(path).write_bytes(_memory[storage_key][0])
        return
    _client().download_file(settings.S3_BUCKET, storage_key, str(path))


def upload_from(storage_key: str, path: Path, mime: str) -> None:
    """Stream a local file to an object (multipart for big files)."""
    if _backend() == "memory":
        _memory[storage_key] = (Path(path).read_bytes(), mime)
        return
    _client().upload_file(
        str(path), settings.S3_BUCKET, storage_key, ExtraArgs={"ContentType": mime}
    )


def delete_prefix(prefix: str) -> int:
    """Delete every object under ``prefix`` (which must end with ``/``)."""
    if not prefix.endswith("/"):
        raise ValueError("prefix must end with /")
    if _backend() == "memory":
        keys = [k for k in _memory if k.startswith(prefix)]
        for k in keys:
            _memory.pop(k, None)
        return len(keys)
    client = _client()
    deleted = 0
    for page in client.get_paginator("list_objects_v2").paginate(
        Bucket=settings.S3_BUCKET, Prefix=prefix
    ):
        keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if keys:
            client.delete_objects(Bucket=settings.S3_BUCKET, Delete={"Objects": keys})
            deleted += len(keys)
    return deleted


def memory_keys(prefix: str = "") -> list[str]:
    """Keys held by the memory backend (tests)."""
    return sorted(k for k in _memory if k.startswith(prefix))


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def presign_get_at(
    storage_key: str,
    *,
    signed_at: int,
    expires: int,
    content_type: str = "",
    cache_control: str = "",
) -> str:
    """A SigV4 presigned GET URL signed *as of* ``signed_at`` (epoch seconds).

    boto3 always signs with the current time, so two viewers in the same
    second get different URLs. HLS segment URLs are signed per time bucket
    instead (roadmap 5.3): everyone gets the same URL for a segment within a
    bucket, so browser and edge caches keep working, and the URL still expires.
    Same algorithm as boto3's ``generate_presigned_url`` for a path-style GET.
    ``cache_control`` is signed in as ``response-cache-control`` (the object is
    served with that ``Cache-Control``).
    """
    if _backend() in ("fake", "memory"):
        query = urlencode(
            {
                "fake-download": 1,
                "X-Amz-Date": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(signed_at)),
                "X-Amz-Expires": expires,
                **({"response-cache-control": cache_control} if cache_control else {}),
                **({"response-content-type": content_type} if content_type else {}),
            }
        )
        return f"{settings.S3_PUBLIC_BASE}/{settings.S3_BUCKET}/{storage_key}?{query}"
    endpoint = urlsplit(settings.S3_PUBLIC_ENDPOINT_URL or settings.S3_ENDPOINT_URL)
    host = endpoint.netloc
    uri = quote(f"{endpoint.path.rstrip('/')}/{settings.S3_BUCKET}/{storage_key}", safe="/-_.~")
    amz_date = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(signed_at))
    day = amz_date[:8]
    scope = f"{day}/{settings.S3_REGION}/s3/aws4_request"
    params = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": f"{settings.S3_ACCESS_KEY}/{scope}",
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(int(expires)),
        "X-Amz-SignedHeaders": "host",
    }
    if content_type:
        params["response-content-type"] = content_type
    if cache_control:
        params["response-cache-control"] = cache_control
    query = "&".join(
        f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in sorted(params.items())
    )
    canonical = "\n".join(["GET", uri, query, f"host:{host}\n", "host", "UNSIGNED-PAYLOAD"])
    to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()]
    )
    key = _hmac(("AWS4" + settings.S3_SECRET_KEY).encode(), day)
    for part in (settings.S3_REGION, "s3", "aws4_request"):
        key = _hmac(key, part)
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    return f"{endpoint.scheme}://{host}{uri}?{query}&X-Amz-Signature={signature}"


# ---- display URLs (Tara Intelligence 08 section 7.8, WP 4c.5-B3) ---------------------

# Every display URL stays valid at least this long after it is served (55 min), so
# a client that caches it for its ``urls_expire_at`` never holds a dead one.
DISPLAY_URL_MIN_VALID_SECONDS = 3300


def display_window(now: float | None = None) -> tuple[int, int, int]:
    """``(signed_at, expires, bucket)``: the start of the current bucket of
    ``MEDIA_DISPLAY_URL_BUCKET_SECONDS``, and a lifetime running the rest of the
    bucket plus ``DISPLAY_URL_MIN_VALID_SECONDS``. Every request in one bucket
    gets the same URL, so the browser cache hits across reloads."""
    bucket = max(60, int(settings.MEDIA_DISPLAY_URL_BUCKET_SECONDS))
    now = int(now if now is not None else time.time())
    return now - now % bucket, bucket + DISPLAY_URL_MIN_VALID_SECONDS, bucket


def presign_display(storage_key: str, *, content_type: str, now: float | None = None):
    """``(url, expires_at)``: a bucketed GET of something shown in place (an image,
    a thumbnail, a display size, a poster), served with ``Cache-Control: private,
    max-age=<bucket>``. ``expires_at`` is epoch seconds."""
    signed_at, expires, bucket = display_window(now)
    url = presign_get_at(
        storage_key,
        signed_at=signed_at,
        expires=expires,
        content_type=content_type,
        cache_control=f"private, max-age={bucket}",
    )
    return url, signed_at + expires
