from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from store_operator.auth.security import hash_password
from store_operator.models.identity import PlatformAdminGrant, User
from store_operator.models.prompt_management import PromptActivation, PromptTemplate

ORIGIN = {"Origin": "http://localhost:5173"}


class FakeRedis:
    def __init__(self):
        self.values: dict[str, int] = {}

    def eval(self, script, numkeys, *args):
        keys = args[:numkeys]
        counts = []
        for key in keys:
            self.values[key] = self.values.get(key, 0) + 1
            counts.append(self.values[key])
        return counts

    def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def expire(self, key, seconds):
        return True

    def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)
        return len(keys)


def test_platform_admin_can_create_publish_and_rollback_prompt_versions(
    identity_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    user = User(
        id=uuid4(),
        email_normalized="prompt-admin@example.com",
        password_hash=hash_password("test-password-123"),
        status="active",
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(
        PlatformAdminGrant(
            id=uuid4(),
            user_id=user.id,
            status="active",
            reason_code="prompt-test",
        )
    )
    db_session.flush()

    login = identity_client.post(
        "/api/v1/auth/login",
        json={"email": "prompt-admin@example.com", "password": "test-password-123"},
        headers=ORIGIN,
    )
    assert login.status_code == 200, login.text
    csrf = login.json()["csrf_token"]
    headers = {**ORIGIN, "X-CSRF-Token": csrf}

    created = identity_client.post(
        "/api/v1/admin/prompt-templates",
        headers=headers,
        json={
            "template_key": "store-social-post",
            "display_name": "Store social post",
            "industry_key": "retail",
            "task_type": "copy_only",
            "capability": "text",
        },
    )
    assert created.status_code == 201, created.text
    template_id = created.json()["id"]

    def create_version(changelog: str):
        return identity_client.post(
            f"/api/v1/admin/prompt-templates/{template_id}/versions",
            headers=headers,
            json={
                "system_prompt": "Generate accurate store marketing content.",
                "user_prompt_template": "Write for {{store_name}}.",
                "variables_schema_json": {
                    "type": "object",
                    "properties": {"store_name": {"type": "string"}},
                    "required": ["store_name"],
                },
                "output_schema_json": {"type": "object", "properties": {}},
                "schema_version": 1,
                "input_policy_json": {"confirmed_facts_only": True},
                "changelog": changelog,
            },
        )

    first = create_version("Initial version")
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]
    published = identity_client.post(
        f"/api/v1/admin/prompt-templates/{template_id}/versions/{first_id}/publish",
        headers={**headers, "Idempotency-Key": "prompt-publish-v1"},
        json={"reason": "Initial reviewed release"},
    )
    assert published.status_code == 200, published.text
    assert published.json()["action"] == "publish"

    second = create_version("Improve store tone")
    assert second.status_code == 201, second.text
    second_id = second.json()["id"]
    published_second = identity_client.post(
        f"/api/v1/admin/prompt-templates/{template_id}/versions/{second_id}/publish",
        headers={**headers, "Idempotency-Key": "prompt-publish-v2"},
        json={"reason": "Approved tone improvement"},
    )
    assert published_second.status_code == 200, published_second.text

    rollback = identity_client.post(
        f"/api/v1/admin/prompt-templates/{template_id}/rollback/{first_id}",
        headers={**headers, "Idempotency-Key": "prompt-rollback-v1"},
        json={"reason": "Restore the previously approved version"},
    )
    assert rollback.status_code == 200, rollback.text
    assert rollback.json()["action"] == "rollback"

    detail = identity_client.get(f"/api/v1/admin/prompt-templates/{template_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["current_published_version_id"] == first_id
    assert [item["version_no"] for item in detail.json()["versions"]] == [2, 1]
    assert [item["action"] for item in detail.json()["activations"]] == [
        "rollback",
        "publish",
        "publish",
    ]
    assert db_session.query(PromptTemplate).count() == 1
    assert db_session.query(PromptActivation).count() == 3
