from __future__ import annotations

import json

import pytest
from botocore.exceptions import ClientError

from store_operator.channels.oauth_state import new_oauth_state
from store_operator.channels.secret_store import (
    AwsSecretsManagerStore,
    SecretStoreError,
    UnavailableSecretStore,
)


class FakeSecretsManager:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.next_arn = "arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:test"

    def create_secret(self, *, Name: str, SecretString: str) -> dict[str, str]:
        if Name in self.values:
            raise ClientError(
                {"Error": {"Code": "ResourceExistsException", "Message": "exists"}},
                "CreateSecret",
            )
        self.values[Name] = SecretString
        return {"ARN": self.next_arn}

    def put_secret_value(self, *, SecretId: str, SecretString: str) -> dict[str, str]:
        self.values[SecretId] = SecretString
        return {"ARN": self.next_arn}

    def get_secret_value(self, *, SecretId: str) -> dict[str, str]:
        return {"SecretString": self.values[SecretId]}


def test_oauth_state_is_high_entropy_and_only_hash_is_persisted() -> None:
    raw, digest = new_oauth_state()

    assert len(raw) >= 64
    assert len(digest) == 32
    assert raw.encode("utf-8") != digest
    assert new_oauth_state()[0] != raw


def test_unavailable_secret_store_fails_closed() -> None:
    store = UnavailableSecretStore()

    with pytest.raises(SecretStoreError):
        store.put_json("douyin/store/account", {"access_token": "never-persist-here"})
    with pytest.raises(SecretStoreError):
        store.get_json("secret-ref")


def test_aws_secret_store_creates_and_reads_json_without_exposing_payload() -> None:
    client = FakeSecretsManager()
    store = AwsSecretsManagerStore(region_name="ap-northeast-1", client=client)

    ref = store.put_json(
        "douyin/store/account",
        {"access_token": "access-secret", "refresh_token": "refresh-secret"},
    )

    assert ref == client.next_arn
    assert json.loads(client.values["douyin/store/account"]) == {
        "access_token": "access-secret",
        "refresh_token": "refresh-secret",
    }
    assert store.get_json(ref) == {
        "access_token": "access-secret",
        "refresh_token": "refresh-secret",
    }


def test_aws_secret_store_updates_existing_secret() -> None:
    client = FakeSecretsManager()
    client.values["douyin/store/account"] = "{}"
    store = AwsSecretsManagerStore(region_name="ap-northeast-1", client=client)

    ref = store.put_json("douyin/store/account", {"access_token": "rotated"})

    assert ref == client.next_arn
    assert store.get_json("douyin/store/account") == {"access_token": "rotated"}


def test_aws_secret_store_rejects_invalid_secret_payload() -> None:
    client = FakeSecretsManager()
    client.values["douyin/store/account"] = "[]"
    store = AwsSecretsManagerStore(region_name="ap-northeast-1", client=client)

    with pytest.raises(SecretStoreError):
        store.get_json("douyin/store/account")
