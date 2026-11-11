from typing import Any

import boto3
from botocore.config import Config

from store_operator.config import settings


class ObjectStorageNotConfigured(RuntimeError):
    """The private object-storage backend is not configured."""


def _client():
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
    expires_in: int | None = None,
) -> str:
    client = _client()
    return client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.object_storage_bucket,
            "Key": object_key,
            "ContentType": mime_type,
            "Metadata": {"sha256": sha256},
        },
        ExpiresIn=expires_in or settings.object_storage_upload_ttl_seconds,
        HttpMethod="PUT",
    )


def head_object(*, object_key: str) -> dict[str, Any]:
    return _client().head_object(
        Bucket=settings.object_storage_bucket,
        Key=object_key,
    )


def create_download_url(*, object_key: str, expires_in: int | None = None) -> str:
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.object_storage_bucket, "Key": object_key},
        ExpiresIn=expires_in or settings.object_storage_download_ttl_seconds,
        HttpMethod="GET",
    )
