from __future__ import annotations

from typing import Protocol

from store_operator.channels.secret_store import SecretStore, SecretStoreError


class ProviderSecretResolver(Protocol):
    def resolve_api_key(self, secret_ref: str) -> str: ...


class SecretStoreProviderResolver:
    """Resolve provider credentials from the existing external SecretStore."""

    def __init__(self, store: SecretStore, *, key_name: str = "api_key") -> None:
        if not key_name.strip():
            raise ValueError("Secret key name is required")
        self._store = store
        self._key_name = key_name

    def resolve_api_key(self, secret_ref: str) -> str:
        if not secret_ref.strip():
            raise ValueError("A provider Secret reference is required")
        try:
            payload = self._store.get_json(secret_ref)
        except SecretStoreError:
            raise
        except Exception as exc:
            raise SecretStoreError("Provider credential could not be retrieved") from exc
        value = payload.get(self._key_name)
        if not isinstance(value, str) or not value.strip():
            raise SecretStoreError("Provider Secret does not contain the required credential")
        return value


class EnvironmentSecretResolver:
    """Resolve env://NAME references for deployments injecting secrets at runtime."""

    def __init__(self, environ: dict[str, str] | None = None) -> None:
        import os

        self._environ = environ if environ is not None else os.environ

    def resolve_api_key(self, secret_ref: str) -> str:
        import re

        match = re.fullmatch(r"env://([A-Z][A-Z0-9_]*)", secret_ref)
        if match is None:
            raise SecretStoreError("Provider Secret reference must use env://NAME")
        value = self._environ.get(match.group(1))
        if not value or not value.strip():
            raise SecretStoreError("Referenced provider Secret is not configured")
        return value
