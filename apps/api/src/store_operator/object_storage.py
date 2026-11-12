import hashlib
from typing import Any, cast

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]

from store_operator.config import settings


class ObjectStorageNotConfigured(RuntimeError):
    """The private object-storage backend is not configured."""


def _build_client(endpoint_url: str | None) -> Any:
    if (
        not settings.object_storage_bucket
        or not settings.object_storage_access_key_id
        or not settings.object_storage_secret_access_key
    ):
        raise ObjectStorageNotConfigured("Private object storage is not configured")
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=settings.object_storage_region,
        aws_access_key_id=settings.object_storage_access_key_id,
        aws_secret_access_key=settings.object_storage_secret_access_key,
        config=Config(signature_version="s3v4"),
    )


def _client() -> Any:
    return _build_client(settings.object_storage_endpoint_url)


def _presign_client() -> Any:
    return _build_client(
        settings.object_storage_public_endpoint_url or settings.object_storage_endpoint_url
    )


def create_upload_url(
    *,
    object_key: str,
    mime_type: str,
    sha256: str,
    byte_size: int,
    expires_in: int | None = None,
) -> str:
    client = _presign_client()
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


def delete_object(*, object_key: str) -> None:
    """Delete a private object; S3 delete_object is idempotent for missing keys."""
    _client().delete_object(
        Bucket=settings.object_storage_bucket,
        Key=object_key,
    )


def create_download_url(*, object_key: str, expires_in: int | None = None) -> str:
    return cast(
        str,
        _presign_client().generate_presigned_url(
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



def download_object_bytes(*, object_key: str, max_bytes: int) -> bytes:
    if not object_key.strip() or max_bytes <= 0:
        raise ValueError("A valid object key and positive size limit are required")
    client = _client()
    metadata = client.head_object(
        Bucket=settings.object_storage_bucket,
        Key=object_key,
    )
    content_length = metadata.get("ContentLength")
    if not isinstance(content_length, int) or content_length <= 0:
        raise ValueError("Stored media metadata is invalid")
    if content_length > max_bytes:
        raise ValueError("Stored media exceeds the channel upload size limit")
    response = client.get_object(
        Bucket=settings.object_storage_bucket,
        Key=object_key,
    )
    body = response["Body"]
    try:
        content = body.read(max_bytes + 1)
    finally:
        body.close()
    if not isinstance(content, bytes) or not content or len(content) > max_bytes:
        raise ValueError("Stored media could not be read within the configured size limit")
    return content
