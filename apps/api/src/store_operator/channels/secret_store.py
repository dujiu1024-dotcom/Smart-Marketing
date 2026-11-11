from __future__ import annotations

import json
from typing import Any, Protocol

import boto3  # type: ignore[import-untyped]
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]


class SecretStoreError(RuntimeError):
    """Raised when a credential cannot be safely stored or retrieved."""


class SecretStore(Protocol):
    def put_json(self, secret_name: str, value: dict[str, str]) -> str: ...

    def get_json(self, secret_ref: str) -> dict[str, str]: ...


class UnavailableSecretStore:
    """Fail-closed implementation used until a deployment configures a secret backend."""

    def put_json(self, secret_name: str, value: dict[str, str]) -> str:
        raise SecretStoreError("Secret storage is not configured")

    def get_json(self, secret_ref: str) -> dict[str, str]:
        raise SecretStoreError("Secret storage is not configured")


class AwsSecretsManagerStore:
    """Store OAuth credentials in AWS Secrets Manager, never in application tables."""

    def __init__(self, *, region_name: str, client: Any | None = None) -> None:
        if not region_name.strip():
            raise ValueError("A Secrets Manager region is required")
        self._client: Any = client or boto3.client("secretsmanager", region_name=region_name)

    def put_json(self, secret_name: str, value: dict[str, str]) -> str:
        if not secret_name.strip() or not value:
            raise ValueError("Secret name and value are required")
        serialized = json.dumps(value, sort_keys=True, separators=(",", ":"))
        try:
            response = self._client.create_secret(Name=secret_name, SecretString=serialized)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code != "ResourceExistsException":
                raise SecretStoreError("Secret could not be stored") from exc
            try:
                response = self._client.put_secret_value(
                    SecretId=secret_name, SecretString=serialized
                )
            except (BotoCoreError, ClientError) as update_exc:
                raise SecretStoreError("Secret could not be updated") from update_exc
        except BotoCoreError as exc:
            raise SecretStoreError("Secret could not be stored") from exc
        arn = response.get("ARN")
        if not isinstance(arn, str) or not arn:
            raise SecretStoreError("Secret backend did not return a reference")
        return arn

    def get_json(self, secret_ref: str) -> dict[str, str]:
        if not secret_ref.strip():
            raise ValueError("Secret reference is required")
        try:
            response = self._client.get_secret_value(SecretId=secret_ref)  # type: ignore[attr-defined]
            raw = response.get("SecretString")
            if not isinstance(raw, str):
                raise SecretStoreError("Secret backend returned an unsupported payload")
            value = json.loads(raw)
        except (BotoCoreError, ClientError) as exc:
            raise SecretStoreError("Secret could not be retrieved") from exc
        except (TypeError, ValueError) as exc:
            raise SecretStoreError("Secret payload is invalid") from exc
        if not isinstance(value, dict) or not all(
            isinstance(key, str) and isinstance(item, str) for key, item in value.items()
        ):
            raise SecretStoreError("Secret payload has an invalid schema")
        return value
