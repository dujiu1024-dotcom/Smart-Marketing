import hashlib
from typing import Any, cast

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]

from store_operator.config import settings


class ObjectStorageNotConfigured(RuntimeError):
    """The private object-storage backend is not configured."""


def _client() -> Any:
    if (
        not settings.object_storage_bucket
        or not settings.object_storage_access_key_id
        or not settings.object_storage_secret_access_key
    ):
        raise ObjectStorageNotConfigured("Private object storage is not configured")
    return boto3.client(
        "s3",
        endpoint_url=settings.object_storage_endpoint_url,
        region_name=settings.object_storage_region,
        aws_access_key_id=settings.object_storage_access_key_id,
        aws_secret_access_key=settings.object_storage_secret_access_key,
        config=Config(signature_version="s3v4"),
    )


def create_upload_url(
    *,
    object_key: str,
    mime_type: str,
    sha256: str,
    byte_size: int,
    expires_in: int | None = None,
) -> str:
    client = _client()
    return cast(
        str,
        client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.object_storage_bucket,
                "Key": object_key,
                "ContentType": mime_type,
                "ContentLength": byte_size,
                "IfNoneMatch": "*",
                "Metadata": {"sha256": sha256},
            },
            ExpiresIn=expires_in or settings.object_storage_upload_ttl_seconds,
            HttpMethod="PUT",
        ),
    )


def head_object(*, object_key: str) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        _client().head_object(
            Bucket=settings.object_storage_bucket,
            Key=object_key,
        ),
    )


def create_download_url(*, object_key: str, expires_in: int | None = None) -> str:
    return cast(
        str,
        _client().generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.object_storage_bucket, "Key": object_key},
            ExpiresIn=expires_in or settings.object_storage_download_ttl_seconds,
            HttpMethod="GET",
        ),
    )



def calculate_object_sha256(*, object_key: str) -> str:
    response = _client().get_object(
        Bucket=settings.object_storage_bucket,
        Key=object_key,
    )
    body = response["Body"]
    digest = hashlib.sha256()
    try:
        for chunk in body.iter_chunks(chunk_size=1024 * 1024):
            if chunk:
                digest.update(chunk)
    finally:
        body.close()
    return digest.hexdigest()


def read_object_bytes(*, object_key: str, max_bytes: int) -> tuple[bytes, str]:
    """Read a bounded private object for a server-side channel upload."""
    if not object_key.strip() or max_bytes < 1:
        raise ValueError("Object key and positive byte limit are required")
    response = _client().get_object(
        Bucket=settings.object_storage_bucket,
        Key=object_key,
    )
    body = response["Body"]
    try:
        content_length = response.get("ContentLength")
        if isinstance(content_length, int) and content_length > max_bytes:
            raise ValueError("Object exceeds the channel upload size limit")
        content = body.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise ValueError("Object exceeds the channel upload size limit")
    finally:
        body.close()
    content_type = response.get("ContentType")
    if not isinstance(content_type, str) or not content_type:
        raise ValueError("Object content type is missing")
    return content, content_type
